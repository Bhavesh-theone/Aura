"""Reads for the deal export that no other repository offers (aura.core.ports.ExportReader):
a deal's guard evaluations and the confirmed intake it was created from. Built for a viewer,
so walls apply twice: row-level security on the session and the `walled` filter here."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from aura.core.domain.enums import GuardSeverity
from aura.core.domain.guard import GuardEvaluation
from aura.core.domain.intake import Intake
from aura.data.models.tables import DealIntakeRow, StageGuardEvaluationRow, StageGuardRow
from aura.data.repositories.sql_intake import _intake
from aura.data.walls import Viewer, bind_viewer, walled


class SqlExportReader:
    def __init__(self, session: Session, viewer: Viewer):
        self.s, self.viewer = session, bind_viewer(session, viewer)

    def guard_evaluations(self, deal_id: int) -> list[GuardEvaluation]:
        stmt = walled(select(StageGuardEvaluationRow, StageGuardRow)
                      .join(StageGuardRow, StageGuardRow.id == StageGuardEvaluationRow.guard_id)
                      .where(StageGuardEvaluationRow.deal_id == deal_id),
                      self.viewer, StageGuardEvaluationRow.deal_id)
        rows = self.s.execute(stmt.order_by(StageGuardEvaluationRow.attempted_at,
                                            StageGuardEvaluationRow.id)).all()
        return [GuardEvaluation(
            id=e.id, deal_id=e.deal_id, guard_id=e.guard_id, guard_name=g.guard_name,
            severity=GuardSeverity(g.severity), attempted_at=e.attempted_at, result=e.result,
            detail=e.detail or {}, actor=e.actor, overridden_by=e.overridden_by,
            override_justification=e.override_justification, description=g.description or "",
            override_role=g.override_role, history_id=e.history_id) for e, g in rows]

    def confirmed_intake(self, deal_id: int) -> Intake | None:
        stmt = walled(select(DealIntakeRow).where(DealIntakeRow.confirmed_deal_id == deal_id,
                                                  DealIntakeRow.status == "confirmed"),
                      self.viewer, DealIntakeRow.confirmed_deal_id)
        row = self.s.scalars(stmt.order_by(DealIntakeRow.id.desc())).first()
        return _intake(row) if row else None
