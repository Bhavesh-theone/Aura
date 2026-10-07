import pytest

from aura.core.domain.enums import HandoffTrigger, Role
from aura.core.domain.errors import Forbidden
from aura.core.policy.rbac_policy import (Capability, can, can_resolve_handoff,
                                          check_transition_actor, require,
                                          require_resolve_handoff)

C = Capability


def test_every_role_has_a_distinct_set_of_powers():
    holders = {cap: {r for r in Role if can(r, cap)} for cap in Capability}
    assert holders[C.TRANSITION_DEAL] == {Role.DEALMAKER}
    assert holders[C.OVERRIDE_OWN_GUARDS] == {Role.COMPLIANCE}
    assert holders[C.MANAGE_WALL] == {Role.COMPLIANCE}
    assert holders[C.SIGN_OFF] == {Role.COMPLIANCE}
    assert holders[C.MANAGE_USERS] == {Role.ADMIN}
    assert holders[C.EDIT_REGULATORY_FLAGS] == {Role.DEALMAKER, Role.COMPLIANCE}
    assert holders[C.VERIFY_EXTRACTION] == {Role.DEALMAKER, Role.ANALYST}
    assert holders[C.EDIT_DEAL_DATA] == {Role.DEALMAKER, Role.ANALYST}
    assert holders[C.SUBMIT_JOB] == {Role.DEALMAKER, Role.ANALYST}


def test_admin_has_no_deal_powers():
    deal_powers = set(Capability) - {C.MANAGE_USERS, C.MANAGE_AUTONOMY}
    assert not any(can(Role.ADMIN, cap) for cap in deal_powers)


def test_require_raises_forbidden_with_the_role_named():
    require(Role.DEALMAKER, C.TRANSITION_DEAL)
    with pytest.raises(Forbidden, match="analyst"):
        require(Role.ANALYST, C.TRANSITION_DEAL, "move a deal")


@pytest.mark.parametrize("trigger", [t for t in HandoffTrigger
                                     if t is not HandoffTrigger.POLICY_REQUIRED])
def test_compliance_resolves_only_policy_required_handoffs(trigger):
    assert can_resolve_handoff(Role.DEALMAKER, trigger)
    assert not can_resolve_handoff(Role.COMPLIANCE, trigger)
    with pytest.raises(Forbidden):
        require_resolve_handoff(Role.COMPLIANCE, trigger)


def test_transition_actor_rule():
    check_transition_actor(Role.DEALMAKER, "", [])
    check_transition_actor(Role.DEALMAKER, "", ["compliance"])  # guards then block it
    check_transition_actor(Role.COMPLIANCE, "why", ["compliance", "compliance"])
    for role, why, failing in [(Role.COMPLIANCE, "", ["compliance"]),
                               (Role.COMPLIANCE, "why", []),
                               (Role.COMPLIANCE, "why", ["compliance", "dealmaker"]),
                               (Role.COMPLIANCE, "why", ["compliance", None]),
                               (Role.ANALYST, "why", ["analyst"]),
                               (Role.ADMIN, "why", ["admin"])]:
        with pytest.raises(Forbidden, match=role.value):
            check_transition_actor(role, why, failing)


def test_policy_required_handoffs_go_to_dealmaker_or_compliance_only():
    t = HandoffTrigger.POLICY_REQUIRED
    assert [r for r in Role if can_resolve_handoff(r, t)] == [Role.DEALMAKER, Role.COMPLIANCE]