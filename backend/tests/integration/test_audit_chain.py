from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from aura.core.domain.audit import GENESIS_HASH, AuditEntry
from aura.data.engine import Base, make_engine
from aura.data.repositories.sql import SqlAuditRepository
from aura.data.verify_audit import verify_chain
from aura.data.walls import SYSTEM


@pytest.fixture()
def session():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _append(repo, n):
    for i in range(n):
        repo.append(AuditEntry(id=None, job_id=None, actor="u", action=f"a{i}",
                               payload={"i": i, "nested": {"b": 1, "a": 2}},
                               created_at=datetime.now(timezone.utc)))


def test_chain_links_from_genesis_and_verifies(session):
    repo = SqlAuditRepository(session, SYSTEM)
    assert verify_chain(session) is None  # empty chain is fine
    _append(repo, 3)
    rows = session.execute(text("SELECT id, prev_hash, row_hash FROM audit_entries "
                                "ORDER BY id")).all()
    assert rows[0][1] == GENESIS_HASH
    assert rows[1][1] == rows[0][2] and rows[2][1] == rows[1][2]
    assert verify_chain(session) is None


def test_audit_rows_are_append_only(session):
    _append(SqlAuditRepository(session, SYSTEM), 1)
    session.commit()  # repositories only flush; the rollbacks below must not undo the row
    for sql in ("UPDATE audit_entries SET actor = 'x'", "DELETE FROM audit_entries"):
        with pytest.raises(Exception, match="append-only"):
            session.execute(text(sql))
        session.rollback()


def test_verify_detects_tampering_at_the_edited_row(session):
    _append(SqlAuditRepository(session, SYSTEM), 4)
    session.execute(text("DROP TRIGGER trg_audit_entries_no_update"))
    session.execute(text("UPDATE audit_entries SET actor = 'mallory' WHERE id = 2"))
    session.commit()
    assert verify_chain(session) == 2


def test_verify_detects_deleted_row(session):
    _append(SqlAuditRepository(session, SYSTEM), 4)
    session.execute(text("DROP TRIGGER trg_audit_entries_no_delete"))
    session.execute(text("DELETE FROM audit_entries WHERE id = 2"))
    session.commit()
    assert verify_chain(session) == 3
