


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import Role
from aura.core.domain.errors import Conflict, NotFound
from aura.core.domain.wall import WallMember
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import (AuditRepository, DealRepository, UserRepository,
                                          WallRepository)


def list_members(deal_id: int, deals: DealRepository, walls: WallRepository) -> list[WallMember]:
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    return walls.members(deal_id)


def add_member(deal_id: int, username: str, actor: str, actor_role: Role,
               deals: DealRepository, walls: WallRepository, users: UserRepository,
               audit: AuditRepository) -> None:
    """Compliance manages walls, and the acting user must already see the deal."""
    require(actor_role, Capability.MANAGE_WALL, "change a deal's wall")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    if users.get_by_username(username) is None:
        raise NotFound("User not found")
    if not walls.add_member(deal_id, username):
        raise Conflict(f"{username} is already on this deal's wall")
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="wall_member_added", created_at=utcnow(),
                            payload={"username": username}))


def remove_member(deal_id: int, username: str, actor: str, actor_role: Role,
                  deals: DealRepository, walls: WallRepository,
                  audit: AuditRepository) -> None:
    require(actor_role, Capability.MANAGE_WALL, "change a deal's wall")
    if deals.get(deal_id) is None:
        raise NotFound("Deal not found")
    if not walls.remove_member(deal_id, username):
        raise NotFound(f"{username} is not on this deal's wall")
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal_id, actor=actor,
                            action="wall_member_removed",
                            created_at=utcnow(),
                            payload={"username": username}))
