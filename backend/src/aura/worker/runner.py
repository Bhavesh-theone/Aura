import logging
import threading
import time

from sqlalchemy.orm import Session

from aura.config import get_settings
from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.services.notifying_audit import NotifyingAudit
from aura.core.services.handoffs import escalate_overdue
from aura.core.services.run_segment import run_segment
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import (SqlAuditRepository, SqlHandoffRepository,
                                        SqlJobRepository, SqlSegmentRepository,
                                        SqlTaskRepository)
from aura.data.repositories.sql_deals import SqlDocumentRepository, SqlExtractionRepository
from aura.data.run_sink import SqlAgentRunSink
from aura.data.uow import SqlUnitOfWork
from aura.data.verify_audit import default_anchor_path, refresh_anchor
from aura.data.walls import SYSTEM

POLL_SECONDS = 2.0
ANCHOR_REFRESH_SECONDS = 60.0
logger = logging.getLogger(__name__)


def run_once(session: Session, orchestrator: Orchestrator, events: EventPublisher,
             materiality_cap_inr: int | None = None) -> bool:
    """Claim and run one queued segment. Returns True if work was done.

    The worker acts for the system, so its repositories are unscoped (SYSTEM): it carries
    out decisions that were already made behind the walls.
    """
    segments = SqlSegmentRepository(session)
    claimed = segments.claim_next_queued()
    if claimed is None:
        return False

    uow = SqlUnitOfWork(session)
    events = uow.defer(events)
    cap = materiality_cap_inr if materiality_cap_inr is not None \
        else get_settings().materiality_cap_inr
    try:
        run_segment(
            segment_id=claimed.id,
            orchestrator=orchestrator,
            jobs=SqlJobRepository(session, SYSTEM),
            segments=segments,
            tasks=SqlTaskRepository(session, SYSTEM),
            handoffs=SqlHandoffRepository(session, SYSTEM),
            audit=NotifyingAudit(SqlAuditRepository(session, SYSTEM), events),
            events=events,
            runs=SqlAgentRunSink(session),
            uow=uow,
            materiality_cap_inr=cap,
            extractions=SqlExtractionRepository(session, SYSTEM),
            documents=SqlDocumentRepository(session, SYSTEM),
        )
    except Exception:
        uow.rollback()
        raise
    return True


def sweep_escalations(session: Session, events: EventPublisher) -> int:
    """Escalate open handoffs whose auto_escalate_at has passed."""
    uow = SqlUnitOfWork(session)
    try:
        deferred = uow.defer(events)
        count = escalate_overdue(SqlHandoffRepository(session, SYSTEM),
                                 NotifyingAudit(SqlAuditRepository(session, SYSTEM), deferred),
                                 deferred)
        uow.commit()
    except Exception:
        uow.rollback()
        raise
    return count


def refresh_audit_anchor() -> None:
    """Keep the anchor close to the audit head, so tail deletion is caught soon after."""
    with SessionLocal() as session:
        result = refresh_anchor(session, default_anchor_path())
    if not result.ok:
        logger.error("AUDIT VERIFICATION FAILED: %s", result.message)


def _loop(orchestrator: Orchestrator, events: EventPublisher, stop: threading.Event) -> None:
    last_anchor = time.monotonic()
    while not stop.is_set():
        did_work = False
        with SessionLocal() as session:
            try:
                sweep_escalations(session, events)
                did_work = run_once(session, orchestrator, events)
            except Exception:
                logger.exception("worker iteration failed")
        if time.monotonic() - last_anchor >= ANCHOR_REFRESH_SECONDS:
            last_anchor = time.monotonic()
            try:
                refresh_audit_anchor()
            except Exception:
                logger.exception("audit anchor refresh failed")
        if not did_work:
            stop.wait(POLL_SECONDS)


def start_worker(orchestrator: Orchestrator, events: EventPublisher) -> threading.Event:
    """Start the segment loop in a daemon thread. Returns its stop event."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(orchestrator, events, stop), daemon=True).start()
    return stop
