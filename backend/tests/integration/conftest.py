import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aura.api.deps import get_anchor_path, get_store, get_uow
from aura.api.main import app
from aura.data.engine import Base, make_engine
from aura.data.filestore import LocalFileStore
from aura.data.seed import seed_reference
from aura.data.uow import SqlUnitOfWork

PASSWORDS = {"bhavesh": "admin123", "asha": "analyst123", "priya": "compliance123",
             "admin": "admin123"}


class Api:
    """Thin test client wrapper that keeps per-user bearer tokens."""

    def __init__(self, client: TestClient, session: Session, store):
        self.client, self.session, self.store = client, session, store
        self._tokens: dict[str, dict] = {}

    def as_user(self, username: str) -> dict:
        if username not in self._tokens:
            r = self.client.post("/api/auth/login",
                                 json={"username": username, "password": PASSWORDS[username]})
            self._tokens[username] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return self._tokens[username]

    def call(self, method: str, url: str, user: str = "bhavesh", **kw):
        return self.client.request(method, url, headers=self.as_user(user), **kw)

    def add_member(self, deal_id: int, username: str, by: str = "priya"):
        """Compliance manages walls; new deals put the compliance users on the wall."""
        r = self.call("POST", f"/api/deals/{deal_id}/members", user=by,
                      json={"username": username})
        assert r.status_code == 201, r.text


def _override_uow(session: Session):
    """The app's per-request unit of work, over the test's shared in-memory session."""
    def override():
        with SqlUnitOfWork(session).transaction() as uow:
            yield uow
    return override


@pytest.fixture()
def api(tmp_path, monkeypatch):
    # Cheap bcrypt cost: the tests hash two passwords per fixture and verify on every login.
    real_gensalt = bcrypt.gensalt
    monkeypatch.setattr(bcrypt, "gensalt", lambda *a, **k: real_gensalt(rounds=4))
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    seed_reference(session)
    store = LocalFileStore(tmp_path / "docs")
    app.dependency_overrides[get_uow] = _override_uow(session)
    app.dependency_overrides[get_store] = lambda: store
    anchor = tmp_path / "audit_anchor.json"
    app.dependency_overrides[get_anchor_path] = lambda: anchor
    # The worker re-reads document text when a segment runs: from this test's store.
    from aura.worker import runner
    monkeypatch.setattr(runner, "store_factory", lambda: store)
    from aura.api import rate_limit
    rate_limit.reset()
    yield Api(TestClient(app), session, store)
    app.dependency_overrides.clear()
    session.close()
