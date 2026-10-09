


from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.deal import Deal, StageHistoryEntry
from aura.core.domain.enums import DealStage, Role, TransactionClass
from aura.core.domain.errors import Conflict
from aura.core.policy.rbac_policy import Capability, require
from aura.core.services.deal_profile import CURRENT_PROFILE_VERSION, validate_profile
from aura.core.ports.repositories import (AuditRepository, DealRepository,
                                          StageHistoryRepository, UserRepository,
                                          WallRepository)


def create_deal(
    external_id: str,
    name: str,
    transaction_class: TransactionClass,
    owner: str,
    owner_role: Role,
    deals: DealRepository,
    history: StageHistoryRepository,
    audit: AuditRepository,
    walls: WallRepository,
    users: UserRepository | None = None,
    profile: dict | None = None,
    profile_schema_version: int | None = None,
) -> Deal:
    """Open a deal at ORIGINATED, record the first history row, and put the deal behind
    its own wall with the creator as the first member. Active compliance users join the
    wall too: they manage walls, and they could not reach a wall they are not on."""
    require(owner_role, Capability.CREATE_DEAL, "create deals")
    profile = dict(profile or {})
    profile_schema_version = profile_schema_version or CURRENT_PROFILE_VERSION
    validate_profile(transaction_class, profile_schema_version, profile)
    if deals.get_by_external_id(external_id) is not None:
        raise Conflict(f"Deal {external_id} already exists")
    now = utcnow()

    deal = deals.add(Deal(id=None, external_id=external_id, name=name,
                          stage=DealStage.ORIGINATED, transaction_class=transaction_class,
                          owner=owner, outcome=None, opened_at=now, profile=profile,
                          profile_schema_version=profile_schema_version))
    walls.create(deal.id, f"{external_id} wall", owner)
    history.append(StageHistoryEntry(id=None, deal_id=deal.id, from_stage=None,
                                     to_stage=DealStage.ORIGINATED, entered_at=now,
                                     actor=owner, reason_code=None, is_regression=False))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor=owner,
                            action="deal_created", created_at=now,
                            payload={"external_id": external_id,
                                     "transaction_class": transaction_class.value}))
    for username in (users.usernames_with_role(Role.COMPLIANCE) if users else []):
        if username != owner and walls.add_member(deal.id, username):
            audit.append(AuditEntry(id=None, job_id=None, deal_id=deal.id, actor="system",
                                    action="wall_member_added", created_at=now,
                                    payload={"username": username,
                                             "reason": "compliance oversight"}))
    return deal
