from aura.core.domain.enums import Role
from aura.core.policy.rbac_policy import Capability, can


def test_admin_can_decide_approvals():
    assert can(Role.ADMIN, Capability.DECIDE_APPROVAL) is True


def test_member_cannot_decide_approvals():
    assert can(Role.MEMBER, Capability.DECIDE_APPROVAL) is False


def test_member_can_submit_jobs():
    assert can(Role.MEMBER, Capability.SUBMIT_JOB) is True


def test_member_cannot_manage_users():
    assert can(Role.MEMBER, Capability.MANAGE_USERS) is False
