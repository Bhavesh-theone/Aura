"""aura.data.migrate_sqlite: an SQLite-era database copied into PostgreSQL keeps every id,
its JSON, booleans and timestamps, and an audit chain that still verifies byte for byte."""
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, get_settings
from aura.core.domain.audit import GENESIS_HASH, AuditEntry, compute_row_hash
from aura.data import migrate_sqlite
from tests.integration.pgtest import owner_url

T0 = datetime(2026, 10, 6, 12, 0, 0, 123456, tzinfo=timezone.utc)


def _sqlite_ts(dt: datetime) -> str:
    """How SQLAlchemy stored a DateTime on SQLite: naive UTC wall clock, microseconds."""
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _build_sqlite(path) -> list[str]:
    """A small SQLite-era database (the columns the old schema had), with a valid chain."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR,
            role VARCHAR, active BOOLEAN, created_at DATETIME);
        CREATE TABLE deals (id INTEGER PRIMARY KEY, external_id VARCHAR, name VARCHAR,
            stage VARCHAR, transaction_class VARCHAR, owner VARCHAR, outcome VARCHAR,
            opened_at DATETIME, closed_at DATETIME, regulatory_flags JSON, created_at DATETIME);
        CREATE TABLE wall (id INTEGER PRIMARY KEY, deal_id INTEGER, name VARCHAR,
            created_at DATETIME);
        CREATE TABLE wall_member (id INTEGER PRIMARY KEY, wall_id INTEGER, user_id INTEGER,
            added_at DATETIME, removed_at DATETIME);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, status VARCHAR, inputs JSON, result JSON,
            deal_id INTEGER, created_at DATETIME, created_by VARCHAR, trace_id VARCHAR,
            span_id VARCHAR);
        CREATE TABLE task (id INTEGER PRIMARY KEY, deal_id INTEGER, job_id INTEGER,
            task_type VARCHAR, assignment_mode VARCHAR, status VARCHAR, materiality_inr BIGINT,
            created_at DATETIME);
        CREATE TABLE audit_entries (id INTEGER PRIMARY KEY, job_id INTEGER, actor VARCHAR,
            action VARCHAR, payload JSON, created_at DATETIME, deal_id INTEGER,
            prev_hash VARCHAR, row_hash VARCHAR);
        CREATE TABLE legacy_scratch (id INTEGER PRIMARY KEY);
    """)
    c.execute("INSERT INTO users VALUES (3, 'bhavesh', 'h', 'dealmaker', 1, ?)",
              (_sqlite_ts(T0),))
    c.execute("INSERT INTO users VALUES (7, 'asha', 'h', 'analyst', 0, ?)", (_sqlite_ts(T0),))
    c.execute("INSERT INTO deals VALUES (11, 'D-011', 'Kept id', 'ORIGINATED', 'DEBT', "
              "'bhavesh', NULL, ?, NULL, '[\"FEMA\"]', ?)", (_sqlite_ts(T0), _sqlite_ts(T0)))
    c.execute("INSERT INTO wall VALUES (5, 11, 'D-011 wall', ?)", (_sqlite_ts(T0),))
    c.execute("INSERT INTO wall_member VALUES (9, 5, 3, ?, NULL)", (_sqlite_ts(T0),))
    c.execute("INSERT INTO jobs VALUES (4, 'complete', '{\"brief\": \"x\", \"n\": 0.1}', "
              "'null', 11, ?, 'bhavesh', NULL, NULL)", (_sqlite_ts(T0),))
    c.execute("INSERT INTO task VALUES (2, 11, 4, 'draft_email', 'human_required', 'done', "
              "50000001, ?)", (_sqlite_ts(T0),))
    prev, payloads = GENESIS_HASH, []
    for i, payload in enumerate([{"external_id": "D-011", "b": 1, "a": [1.5, None, True]},
                                 {"nested": {"z": "ünïcode ₹", "y": 1e-05}, "i": 2},
                                 {}]):
        created = T0 + timedelta(seconds=i, microseconds=7)
        entry = AuditEntry(id=None, job_id=4 if i else None, actor="bhavesh",
                           action=f"act{i}", payload=payload, created_at=created, deal_id=11)
        row_hash = compute_row_hash(prev, entry)
        c.execute("INSERT INTO audit_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                  (20 + i, entry.job_id, "bhavesh", entry.action, json.dumps(payload),
                   _sqlite_ts(created), 11, prev, row_hash))
        payloads.append(row_hash)
        prev = row_hash
    c.commit()
    c.close()
    return payloads


@pytest.fixture()
def target():
    name = f"{make_url(get_settings().migration_database_url).database}_import"
    admin = create_engine(owner_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    yield owner_url(name)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()
    (BACKEND_DIR / "data" / f"audit_anchor.{name}.json").unlink(missing_ok=True)


def test_round_trip_keeps_ids_types_and_the_audit_chain(tmp_path, target):
    src = tmp_path / "old.db"
    hashes = _build_sqlite(src)
    anchor = tmp_path / "old.db.audit_anchor.json"
    anchor.write_text(json.dumps({"head_id": 22, "head_hash": hashes[-1]}))
    before = src.read_bytes()
    log: list[str] = []

    counts = migrate_sqlite.migrate(src, target, anchor_from=anchor, out=log.append)

    assert src.read_bytes() == before  # the SQLite file is the untouched backup
    assert counts["deals"] == (1, 1) and counts["audit_entries"] == (3, 3)
    assert counts["party"] == (0, 0)
    assert any("legacy_scratch" in line for line in log)  # reported, not copied
    assert any("3 entries hash identically" in line for line in log)
    eng = create_engine(target)
    with eng.connect() as c:
        # (seed_reference then adds the reference users the old file lacked: ids 8, 9)
        assert c.execute(text("SELECT id, active FROM users WHERE id < 8 ORDER BY id")).all() == \
            [(3, True), (7, False)]
        deal = c.execute(text("SELECT id, regulatory_flags, profile, opened_at FROM deals")).one()
        assert deal[:3] == (11, ["FEMA"], {})
        assert deal[3] == T0
        assert c.execute(text("SELECT inputs, result FROM jobs")).one() == \
            ({"brief": "x", "n": 0.1}, None)
        assert c.scalar(text("SELECT materiality_inr FROM task")) == 50000001
        rows = c.execute(text("SELECT id, prev_hash, row_hash, payload FROM audit_entries "
                              "ORDER BY id")).all()
        assert [r.id for r in rows] == [20, 21, 22]
        assert [r.row_hash for r in rows] == hashes  # stored hashes copied as they were
        assert rows[1].payload == {"nested": {"z": "ünïcode ₹", "y": 1e-05}, "i": 2}
        # Identity sequences moved past the copied ids.
        new_id = c.execute(text("INSERT INTO deals (external_id, name, stage, "
                                "transaction_class, owner, opened_at) VALUES ('D-NEW', 'n', "
                                "'ORIGINATED', 'DEBT', 'bhavesh', now()) RETURNING id")).scalar()
        assert new_id == 12
        c.rollback()
    with Session(eng) as s:
        assert migrate_sqlite.verify_copied_chain(s) == (3, None)
    eng.dispose()
    copied = migrate_sqlite.target_anchor(target)
    assert json.loads(copied.read_text())["head_hash"] == hashes[-1]


def test_a_non_empty_target_is_refused_unless_forced(tmp_path, target):
    src = tmp_path / "old.db"
    _build_sqlite(src)
    migrate_sqlite.migrate(src, target, out=lambda _: None)
    with pytest.raises(SystemExit, match="not empty"):
        migrate_sqlite.migrate(src, target, out=lambda _: None)
    counts = migrate_sqlite.migrate(src, target, force=True, out=lambda _: None)
    assert counts["audit_entries"] == (3, 3)


def test_a_tampered_chain_is_refused_and_nothing_is_copied(tmp_path, target):
    src = tmp_path / "old.db"
    _build_sqlite(src)
    c = sqlite3.connect(src)
    c.execute("UPDATE audit_entries SET actor = 'mallory' WHERE id = 21")
    c.commit()
    c.close()
    with pytest.raises(SystemExit, match="entry id 21"):
        migrate_sqlite.migrate(src, target, out=lambda _: None)
    eng = create_engine(target)
    with eng.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM audit_entries")) == 0
        assert conn.scalar(text("SELECT count(*) FROM deals")) == 0
    eng.dispose()


@pytest.mark.skipif(not (BACKEND_DIR / "aura.db").exists(), reason="no local aura.db")
def test_the_real_local_database_copies_and_verifies(tmp_path, target):
    """A copy of the developer's own backend/aura.db (never the file itself)."""
    src = tmp_path / "aura_copy.db"
    shutil.copyfile(BACKEND_DIR / "aura.db", src)
    counts = migrate_sqlite.migrate(src, target, out=lambda _: None)
    assert all(a == b for a, b in counts.values())
    eng = create_engine(target)
    with Session(eng) as s:
        n, broken = migrate_sqlite.verify_copied_chain(s)
    eng.dispose()
    assert broken is None and n == counts["audit_entries"][0]
