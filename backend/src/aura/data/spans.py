"""The tracer's only exporter: finished spans go into the local trace_span table.

flush_spans runs after a unit of work commits (SqlUnitOfWork.commit), on the same session, in
its own short transaction. A failure (say, an old database with no trace_span table) is
logged and the spans are dropped; tracing never breaks the work it describes."""
import logging

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from aura.core.tracing import tracer
from aura.data.models.tables import TraceSpanRow
from aura.data.walls import SYSTEM_VIEWER

logger = logging.getLogger(__name__)


def flush_spans(session: Session) -> int:
    spans = tracer.drain()
    if not spans:
        return 0
    rows = [dict(trace_id=s.trace_id, span_id=s.span_id, parent_span_id=s.parent_span_id,
                 name=s.name[:64], start_time=s.start, end_time=s.end,
                 attributes=s.attributes, status=s.status, deal_id=s.deal_id)
            for s in spans if s.trace_id and s.span_id]
    if not rows:
        return 0
    try:
        # The tracer is process-wide, so this batch can hold spans of deals the session's
        # viewer is not on: the exporter writes them as the system (this transaction only).
        session.execute(text("SELECT set_config('aura.viewer', :v, true)"),
                        {"v": SYSTEM_VIEWER})
        session.execute(insert(TraceSpanRow), rows)
        session.commit()
    except Exception:
        session.rollback()
        logger.warning("could not write %d trace span(s); dropped", len(spans), exc_info=True)
        return 0
    return len(spans)
