import threading

from sqlalchemy.orm import Session

from aura.core.ports.events import EventPublisher
from aura.core.ports.orchestrator import Orchestrator
from aura.core.services.run_segment import run_segment
from aura.data.engine import SessionLocal
from aura.data.repositories.sql import (SqlApprovalRepository, SqlAuditRepository,
                                        SqlJobRepository, SqlSegmentRepository)

POLL_SECONDS = 2.0


def run_once(session: Session, orchestrator: Orchestrator, events: EventPublisher) -> bool:
    """Claim and run one queued segment. Returns True if work was done."""
    segments = SqlSegmentRepository(session)
    claimed = segments.claim_next_queued()
    if claimed is None:
        return False

    run_segment(
        segment_id=claimed.id,
        orchestrator=orchestrator,
        jobs=SqlJobRepository(session),
        segments=segments,
        approvals=SqlApprovalRepository(session),
        audit=SqlAuditRepository(session),
        events=events,
    )
    return True


def _loop(orchestrator: Orchestrator, events: EventPublisher, stop: threading.Event) -> None:
    while not stop.is_set():
        with SessionLocal() as session:
            try:
                did_work = run_once(session, orchestrator, events)
            except Exception:
                did_work = False
        if not did_work:
            stop.wait(POLL_SECONDS)


def start_worker(orchestrator: Orchestrator, events: EventPublisher) -> threading.Event:
    """Start the segment loop in a daemon thread. Returns its stop event."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(orchestrator, events, stop), daemon=True).start()
    return stop
