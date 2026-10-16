"""Evaluation runs, capability autonomy, deal notes and trace spans (migration 0012).

Eval runs and autonomy are deal-less configuration and read the same for everyone. Notes and
spans belong to a deal and are wall-filtered for the viewer (spans with no deal stay visible,
like the other deal-less rows)."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.core.domain.harness import (CapabilityAutonomy, DealNote, EvalCaseResult, EvalRun,
                                      TraceSpanRecord)
from aura.data.models.tables import (CapabilityAutonomyRow, DealNoteRow, EvalCaseResultRow,
                                     EvalRunRow, TraceSpanRow)
from aura.data.walls import Viewer, bind_viewer, walled


def _case(row: EvalCaseResultRow) -> EvalCaseResult:
    return EvalCaseResult(id=row.id, eval_run_id=row.eval_run_id, case_id=row.case_id,
                          passed=row.passed, score=row.score, confidence=row.confidence,
                          expected=row.expected or {}, actual=row.actual or {},
                          detail=row.detail or {}, agent_run_id=row.agent_run_id,
                          latency_ms=row.latency_ms or 0, error=row.error)


def _run(row: EvalRunRow, cases: list[EvalCaseResult] | None = None) -> EvalRun:
    return EvalRun(id=row.id, capability=row.capability, orchestrator=row.orchestrator,
                   model_id=row.model_id, golden_sha256=row.golden_sha256,
                   n_cases=row.n_cases, score=row.score, threshold=row.threshold,
                   passed=row.passed, metrics=row.metrics or {}, started_at=row.started_at,
                   completed_at=row.completed_at, created_by=row.created_by,
                   cases=cases or [])


class SqlEvalRepository:
    def __init__(self, session: Session):
        self.s = session

    def add_run(self, run: EvalRun) -> EvalRun:
        row = EvalRunRow(capability=run.capability, orchestrator=run.orchestrator,
                         model_id=run.model_id, golden_sha256=run.golden_sha256,
                         n_cases=run.n_cases, score=run.score, threshold=run.threshold,
                         passed=run.passed, metrics=run.metrics, started_at=run.started_at,
                         completed_at=run.completed_at, created_by=run.created_by)
        self.s.add(row)
        self.s.flush()
        for c in run.cases:
            self.s.add(EvalCaseResultRow(
                eval_run_id=row.id, case_id=c.case_id, passed=c.passed, score=c.score,
                confidence=c.confidence, expected=c.expected, actual=c.actual,
                detail=c.detail, agent_run_id=c.agent_run_id, latency_ms=c.latency_ms,
                error=c.error))
        self.s.flush()
        return self.get_run(row.id)

    def get_run(self, run_id: int) -> EvalRun | None:
        row = self.s.get(EvalRunRow, run_id)
        if row is None:
            return None
        cases = self.s.scalars(select(EvalCaseResultRow)
                               .where(EvalCaseResultRow.eval_run_id == run_id)
                               .order_by(EvalCaseResultRow.id)).all()
        return _run(row, [_case(c) for c in cases])

    def list_runs(self, capability: str | None = None, limit: int = 50) -> list[EvalRun]:
        stmt = select(EvalRunRow)
        if capability:
            stmt = stmt.where(EvalRunRow.capability == capability)
        rows = self.s.scalars(stmt.order_by(EvalRunRow.id.desc()).limit(limit)).all()
        return [_run(r) for r in rows]

    def latest(self, capability: str, include_stub: bool = False) -> EvalRun | None:
        stmt = select(EvalRunRow).where(EvalRunRow.capability == capability)
        if not include_stub:
            stmt = stmt.where(EvalRunRow.orchestrator != "stub")
        # A run over part of the golden set (--limit / --cases) is a spot check: it is kept
        # and shown, but it is not evidence for promotion or demotion.
        rows = self.s.scalars(stmt.order_by(EvalRunRow.completed_at.desc(),
                                            EvalRunRow.id.desc()))
        row = next((r for r in rows if not (r.metrics or {}).get("partial")), None)
        return _run(row) if row else None


class SqlAutonomyRepository:
    def __init__(self, session: Session):
        self.s = session

    @staticmethod
    def _to_domain(row: CapabilityAutonomyRow) -> CapabilityAutonomy:
        return CapabilityAutonomy(capability=row.capability, level=row.level,
                                  pinned_model=row.pinned_model, demoted_at=row.demoted_at,
                                  reason=row.reason, updated_by=row.updated_by,
                                  updated_at=row.updated_at)

    def get(self, capability: str) -> CapabilityAutonomy:
        row = self.s.get(CapabilityAutonomyRow, capability)
        return self._to_domain(row) if row else CapabilityAutonomy(capability=capability)

    def save(self, state: CapabilityAutonomy) -> CapabilityAutonomy:
        row = self.s.get(CapabilityAutonomyRow, state.capability)
        if row is None:
            row = CapabilityAutonomyRow(capability=state.capability)
            self.s.add(row)
        row.level, row.pinned_model = state.level, state.pinned_model
        row.demoted_at, row.reason = state.demoted_at, state.reason
        row.updated_by, row.updated_at = state.updated_by, state.updated_at
        self.s.flush()
        return self._to_domain(row)

    def list_all(self) -> list[CapabilityAutonomy]:
        return [self._to_domain(r) for r in self.s.scalars(
            select(CapabilityAutonomyRow).order_by(CapabilityAutonomyRow.capability))]


class SqlNoteRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    @staticmethod
    def _to_domain(row: DealNoteRow) -> DealNote:
        return DealNote(id=row.id, deal_id=row.deal_id, body=row.body, author=row.author,
                        source=row.source, created_at=row.created_at, job_id=row.job_id)

    def add(self, note: DealNote) -> DealNote:
        row = DealNoteRow(deal_id=note.deal_id, body=note.body, author=note.author,
                          source=note.source, job_id=note.job_id, created_at=note.created_at)
        self.s.add(row)
        self.s.flush()
        return self._to_domain(row)

    def list_for_deal(self, deal_id: int) -> list[DealNote]:
        stmt = walled(select(DealNoteRow).where(DealNoteRow.deal_id == deal_id), self.viewer,
                      DealNoteRow.deal_id)
        return [self._to_domain(r) for r in self.s.scalars(stmt.order_by(DealNoteRow.id))]


class SqlTraceRepository:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def list_trace(self, trace_id: str) -> list[TraceSpanRecord]:
        stmt = walled(select(TraceSpanRow).where(TraceSpanRow.trace_id == trace_id),
                      self.viewer, TraceSpanRow.deal_id, include_unattached=True)
        rows = self.s.scalars(stmt.order_by(TraceSpanRow.start_time, TraceSpanRow.id)).all()
        return [TraceSpanRecord(trace_id=r.trace_id, span_id=r.span_id,
                                parent_span_id=r.parent_span_id, name=r.name,
                                start=r.start_time, end=r.end_time,
                                attributes=r.attributes or {}, status=r.status,
                                deal_id=r.deal_id) for r in rows]
