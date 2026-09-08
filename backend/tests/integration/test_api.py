import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from aura.api.deps import get_session
from aura.api.main import app
from aura.api.security import hash_password
from aura.data.engine import Base, make_engine
from aura.data.models.tables import UserRow


@pytest.fixture()
def client():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(UserRow(username="bhavesh", password_hash=hash_password("admin123"),
                        role="admin"))
    session.commit()

    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token(client):
    r = client.post("/api/auth/login", json={"username": "bhavesh", "password": "admin123"})
    assert r.status_code == 200
    return r.json()["access_token"]


def test_login_rejects_bad_password(client):
    r = client.post("/api/auth/login", json={"username": "bhavesh", "password": "wrong"})
    assert r.status_code == 401


def test_submit_job_returns_202_and_creates_job(client):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    r = client.post("/api/jobs", json={"inputs": {"brief": "draft intro"}, "deal_id": None},
                    headers=headers)
    assert r.status_code == 202
    assert r.json()["status"] == "pending"

    listed = client.get("/api/jobs", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_jobs_require_auth(client):
    assert client.get("/api/jobs").status_code == 401


def test_approvals_list_is_empty_initially(client):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    r = client.get("/api/approvals", headers=headers)
    assert r.status_code == 200
    assert r.json() == []
