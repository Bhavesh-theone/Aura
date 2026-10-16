from aura.core.domain.enums import Role
from aura.core.domain.user import User
from aura.core.services.authenticate import authenticate


class FakeUserRepo:
    def __init__(self, user: User | None):
        self.user = user

    def get_by_username(self, username: str) -> User | None:
        return self.user if self.user and self.user.username == username else None

    def get(self, user_id: int) -> User | None:
        return self.user


def always_true(plain: str, hashed: str) -> bool:
    return True


def always_false(plain: str, hashed: str) -> bool:
    return False


def test_authenticate_returns_user_on_valid_password():
    user = User(id=1, username="bhavesh", password_hash="x", role=Role.ADMIN)
    assert authenticate("bhavesh", "pw", FakeUserRepo(user), always_true) == user


def test_authenticate_returns_none_on_bad_password():
    user = User(id=1, username="bhavesh", password_hash="x", role=Role.ADMIN)
    assert authenticate("bhavesh", "pw", FakeUserRepo(user), always_false) is None


def test_authenticate_returns_none_for_unknown_user():
    assert authenticate("nobody", "pw", FakeUserRepo(None), always_true) is None


def test_authenticate_refuses_an_inactive_user_even_with_the_right_password():
    user = User(id=1, username="asha", password_hash="x", role=Role.ANALYST, active=False)
    assert authenticate("asha", "pw", FakeUserRepo(user), always_true) is None
    user.active = True
    assert authenticate("asha", "pw", FakeUserRepo(user), always_true) == user
