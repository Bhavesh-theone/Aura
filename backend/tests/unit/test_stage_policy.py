import pytest

from aura.core.domain.enums import DealStage as S
from aura.core.domain.errors import InvalidTransition, RuleViolation
from aura.core.policy.stage_policy import allowed_next, check_transition


def test_forward_moves_one_stage_only():
    assert check_transition(S.ORIGINATED, S.QUALIFIED, None) is False
    with pytest.raises(InvalidTransition):
        check_transition(S.ORIGINATED, S.MATCHED, None)


def test_regression_needs_reason_code():
    with pytest.raises(RuleViolation):
        check_transition(S.DILIGENCE, S.NEGOTIATION, None)
    assert check_transition(S.DILIGENCE, S.NEGOTIATION, "terms_reopened") is True


@pytest.mark.parametrize("a,b", [(S.DILIGENCE, S.NEGOTIATION), (S.DOCUMENTATION, S.NEGOTIATION),
                                 (S.CONDITIONS_PRECEDENT, S.DOCUMENTATION),
                                 (S.MATCHED, S.MARKETED), (S.BID_AUCTION, S.MARKETED)])
def test_permitted_regressions(a, b):
    assert check_transition(a, b, "x") is True


def test_other_backward_moves_rejected():
    with pytest.raises(InvalidTransition):
        check_transition(S.NEGOTIATION, S.MATCHED, "x")


def test_any_non_terminal_can_exit_with_reason():
    for stage in (S.ORIGINATED, S.NEGOTIATION, S.CONDITIONS_PRECEDENT):
        assert check_transition(stage, S.WITHDRAWN, "client_pulled") is False
        with pytest.raises(RuleViolation):
            check_transition(stage, S.ABORTED, "")


def test_terminal_stages_have_no_moves():
    for stage in (S.CLOSED, S.LAPSED, S.WITHDRAWN, S.REJECTED, S.ABORTED):
        assert allowed_next(stage) == []
    with pytest.raises(InvalidTransition):
        check_transition(S.CLOSED, S.NEGOTIATION, "x")


def test_allowed_next_lists_forward_regression_and_exits():
    nxt = allowed_next(S.DILIGENCE)
    assert S.DOCUMENTATION in nxt and S.NEGOTIATION in nxt and S.LAPSED in nxt
    assert S.MATCHED not in nxt
