from dataclasses import dataclass

from aura.core.domain.enums import Role


@dataclass
class User:
    id: int | None
    username: str
    password_hash: str
    role: Role
    active: bool = True
