"""Where agent_run rows are written."""
from sqlalchemy.orm import Session

from aura.core.domain.agent_run import AgentRun
from aura.core.ports.orchestrator import AgentRunLogError
from aura.data.repositories.sql import SqlAgentRunRepository
from aura.data.walls import SYSTEM


class SqlAgentRunSink:
    """Writes each run and commits it at once, on the session it was given.

    The worker hands it its own session at a point where nothing else is pending (the
    segment's RUNNING mark has just been committed), so committing here is safe, and a run
    that was paid for stays on record even if the segment later fails.
    """

    def __init__(self, session: Session):
        self.s = session

    def record(self, run: AgentRun) -> AgentRun:
        try:
            saved = SqlAgentRunRepository(self.s, SYSTEM).add(run)
            self.s.commit()
            return saved
        except Exception as exc:
            self.s.rollback()
            raise AgentRunLogError(f"could not write agent_run: {exc}") from exc
