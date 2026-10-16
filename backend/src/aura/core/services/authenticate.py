from typing import Callable

from aura.core.domain.user import User
from aura.core.ports.repositories import UserRepository


def authenticate(
    username: str,
    password: str,
    users: UserRepository,
    verify: Callable[[str, str], bool],
) -> User | None:
    """Return the user when credentials are valid and the account is active, else None.
    No framework imports."""
    user = users.get_by_username(username)
    if user is None or not user.active:
        return None
    if not verify(password, user.password_hash):
        return None
    return user
