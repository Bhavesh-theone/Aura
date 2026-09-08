from enum import Enum

from aura.core.domain.enums import Role


class Capability(str, Enum):
    SUBMIT_JOB = "submit_job"
    DECIDE_APPROVAL = "decide_approval"
    VIEW_ACTIVITY = "view_activity"
    MANAGE_USERS = "manage_users"


_GRANTS: dict[Role, frozenset[Capability]] = {
    Role.ADMIN: frozenset(Capability),
    Role.MEMBER: frozenset({Capability.SUBMIT_JOB, Capability.VIEW_ACTIVITY}),
}


def can(role: Role, capability: Capability) -> bool:
    return capability in _GRANTS.get(role, frozenset())
