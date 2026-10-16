from datetime import datetime, timezone

import pytest

from aura.core.domain.deal import Deal
from aura.core.domain.diligence import ChecklistItemTemplate
from aura.core.domain.enums import DealStage as S
from aura.core.domain.enums import (DiligenceSeverity, GuardSeverity, Outcome, Role,
                                    TransactionClass)
from aura.core.domain.errors import Forbidden, GuardBlocked, InvalidTransition, RuleViolation
from aura.core.domain.guard import StageGuard
from aura.core.services.transition_deal import preview_guards, transition_deal
from tests.unit.fakes import (FakeAuditRepo, FakeDealRepo, FakeDiligenceRepo, FakeGuardRepo,
                              FakeHistoryRepo)


def _guard(name, frm, to, severity=GuardSeverity.BLOCKING, override_role="compliance"):
    return StageGuard(id=abs(hash(name)) % 1000, from_stage=frm, to_stage=to,
                      transaction_class=None, guard_name=name, sql_text="",
                      severity=severity, override_role=override_role)


def _world(stage=S.QUALIFIED, guards=(), outcomes=None, templates=()):
    deals = FakeDealRepo()
    deal = deals.add(Deal(id=None, external_id="D-1", name="x", stage=stage,
                          transaction_class=TransactionClass.DEBT, owner="u", outcome=None,
                          opened_at=datetime.now(timezone.utc)))
    return deal, dict(deals=deals, history=FakeHistoryRepo(),
                      guards=FakeGuardRepo(guards, outcomes), audit=FakeAuditRepo(),
                      diligence=FakeDiligenceRepo(templates))


def _go(deal, w, to, role=Role.DEALMAKER, reason=None, justification=None):
    return transition_deal(deal.id, to, "u", role, reason, justification, **w)


def test_passing_guards_advance_and_write_history_and_audit():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED)])
    result = _go(deal, w, S.MANDATED)
    assert result.deal.stage is S.MANDATED
    assert [e.result for e in w["guards"].recorded] == [True]
    assert w["history"].entries[0].to_stage is S.MANDATED
    assert w["audit"].entries[0].action == "deal_transition"


def test_blocking_failure_blocks_but_still_records_evaluation():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED)], outcomes={"g": False})
    with pytest.raises(GuardBlocked) as exc:
        _go(deal, w, S.MANDATED)
    assert len(exc.value.evaluations) == 1 and len(w["guards"].recorded) == 1
    assert deal.stage is S.QUALIFIED and w["history"].entries == []


def test_warning_failure_does_not_block():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED, GuardSeverity.WARNING)],
                     outcomes={"g": False})
    assert _go(deal, w, S.MANDATED).deal.stage is S.MANDATED


def test_override_needs_matching_role_and_justification():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED, override_role="dealmaker")],
                     outcomes={"g": False})
    with pytest.raises(GuardBlocked):
        _go(deal, w, S.MANDATED, justification="   ")  # right role, no justification
    result = _go(deal, w, S.MANDATED, justification="client signed offline")
    ev = result.evaluations[0]
    assert ev.overridden_by == "u" and ev.override_justification == "client signed offline"
    assert ev.override_role == "dealmaker"


@pytest.mark.parametrize("role", [Role.ANALYST, Role.COMPLIANCE, Role.ADMIN])
def test_only_a_dealmaker_may_make_an_ordinary_move(role):
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED)])
    with pytest.raises(Forbidden):
        _go(deal, w, S.MANDATED, role=role)
    with pytest.raises(Forbidden):  # nothing failed, so there is nothing to override
        _go(deal, w, S.MANDATED, role=role, justification="because")
    assert deal.stage is S.QUALIFIED and w["guards"].recorded == []
    with pytest.raises(Forbidden):
        _go(deal, w, S.WITHDRAWN, role=role, reason="x")  # exits too


def test_compliance_may_move_a_deal_only_by_overriding_its_own_guards():
    deal, w = _world(guards=[_guard("own", S.QUALIFIED, S.MANDATED)], outcomes={"own": False})
    with pytest.raises(Forbidden):  # an override needs a justification
        _go(deal, w, S.MANDATED, role=Role.COMPLIANCE)
    assert w["guards"].recorded == []
    result = _go(deal, w, S.MANDATED, role=Role.COMPLIANCE,
                 justification="Regulator confirmed by letter; blocker is moot")
    assert result.deal.stage is S.MANDATED
    ev = result.evaluations[0]
    assert ev.overridden_by == "u" and ev.override_role == "compliance"
    assert w["audit"].entries[-1].payload["overridden"] == ["own"]


def test_compliance_cannot_override_when_any_failing_guard_names_another_role():
    deal, w = _world(guards=[_guard("own", S.QUALIFIED, S.MANDATED),
                             _guard("theirs", S.QUALIFIED, S.MANDATED,
                                    override_role="dealmaker")],
                     outcomes={"own": False, "theirs": False})
    with pytest.raises(Forbidden, match="compliance"):
        _go(deal, w, S.MANDATED, role=Role.COMPLIANCE, justification="please")
    assert deal.stage is S.QUALIFIED and w["guards"].recorded == []


def test_a_dealmaker_cannot_override_a_compliance_guard():
    deal, w = _world(guards=[_guard("own", S.QUALIFIED, S.MANDATED)], outcomes={"own": False})
    with pytest.raises(GuardBlocked):
        _go(deal, w, S.MANDATED, justification="I am sure")


def test_evaluations_are_linked_to_the_history_row_on_success():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED)])
    _go(deal, w, S.MANDATED)
    assert w["guards"].attached == [([1], w["history"].entries[0].id)]


def test_invalid_jump_and_missing_reason_are_rejected():
    deal, w = _world(stage=S.ORIGINATED)
    with pytest.raises(InvalidTransition):
        _go(deal, w, S.MATCHED)
    with pytest.raises(RuleViolation):
        _go(deal, w, S.LAPSED)


def test_terminal_sets_outcome_and_closed_at():
    deal, w = _world(stage=S.NEGOTIATION)
    result = _go(deal, w, S.WITHDRAWN, reason="client_pulled")
    assert result.deal.outcome is Outcome.WITHDRAWN and result.deal.closed_at is not None


def test_entering_diligence_instantiates_checklist_once():
    tpl = [ChecklistItemTemplate(1, None, "c", "p1", DiligenceSeverity.BLOCKER),
           ChecklistItemTemplate(2, TransactionClass.ALLIANCE, "c", "p2",
                                 DiligenceSeverity.STANDARD)]
    deal, w = _world(stage=S.NEGOTIATION, templates=tpl)
    _go(deal, w, S.DILIGENCE)
    assert [i.prompt for i in w["diligence"].items] == ["p1"]
    _go(deal, w, S.NEGOTIATION, reason="reopened")
    _go(deal, w, S.DILIGENCE)
    assert len(w["diligence"].items) == 1


def test_preview_writes_nothing():
    deal, w = _world(guards=[_guard("g", S.QUALIFIED, S.MANDATED)], outcomes={"g": False})
    evs = preview_guards(deal.id, S.MANDATED, w["deals"], w["guards"])
    assert [e.result for e in evs] == [False]
    assert w["guards"].recorded == [] and w["audit"].entries == []
