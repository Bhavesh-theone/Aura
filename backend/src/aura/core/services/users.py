"""User management: admin only. Admins have no deal powers; this is all they manage."""
import re


from typing import Callable

from aura.core.clock import utcnow
from aura.core.domain.audit import AuditEntry
from aura.core.domain.enums import Role
from aura.core.domain.errors import Conflict, NotFound, RuleViolation
from aura.core.domain.user import User
from aura.core.policy.rbac_policy import Capability, require
from aura.core.ports.repositories import AuditRepository, UserRepository

MIN_PASSWORD_CHARS = 8
_USERNAME = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def list_users(actor_role: Role, users: UserRepository) -> list[User]:
    require(actor_role, Capability.MANAGE_USERS, "manage users")
    return users.list_all()


def create_user(username: str, password: str, role: Role, actor: str, actor_role: Role,
                users: UserRepository, audit: AuditRepository,
                hash_password: Callable[[str], str]) -> User:
    require(actor_role, Capability.MANAGE_USERS, "manage users")
    if not _USERNAME.match(username):
        raise RuleViolation("username must be 1-64 letters, digits, '.', '_' or '-'")
    if len(password) < MIN_PASSWORD_CHARS:
        raise RuleViolation(f"password must be at least {MIN_PASSWORD_CHARS} characters")
    if users.get_by_username(username) is not None:
        raise Conflict(f"User {username} already exists")
    user = users.add(User(id=None, username=username, password_hash=hash_password(password),
                          role=role, active=True))
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor,
                            action="user_created", created_at=utcnow(),
                            payload={"user_id": user.id, "username": username,
                                     "role": role.value}))
    return user


def update_user(user_id: int, role: Role | None, active: bool | None, actor: str,
                actor_role: Role, users: UserRepository, audit: AuditRepository) -> User:
    require(actor_role, Capability.MANAGE_USERS, "manage users")
    user = users.get(user_id)
    if user is None:
        raise NotFound("User not found")
    new_role = role if role is not None else user.role
    new_active = active if active is not None else user.active
    leaves_admin = user.role is Role.ADMIN and user.active and (
        new_role is not Role.ADMIN or not new_active)
    if leaves_admin and not any(u.role is Role.ADMIN and u.active and u.id != user.id
                                for u in users.list_all()):
        raise Conflict("The last active admin cannot be demoted or deactivated")
    changes = {}
    if new_role is not user.role:
        changes["role"] = {"from": user.role.value, "to": new_role.value}
    if new_active != user.active:
        changes["active"] = {"from": user.active, "to": new_active}
    user.role, user.active = new_role, new_active
    saved = users.update(user)
    audit.append(AuditEntry(id=None, job_id=None, deal_id=None, actor=actor,
                            action="user_updated", created_at=utcnow(),
                            payload={"user_id": saved.id, "username": saved.username,
                                     "changes": changes}))
    return saved
