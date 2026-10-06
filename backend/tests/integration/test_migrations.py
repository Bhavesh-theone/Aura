import json
import sqlite3

from alembic import command
from alembic.config import Config

from aura.config import BACKEND_DIR
from aura.core.domain.audit import GENESIS_HASH
from aura.data.engine import Base
import aura.data.models.tables  # noqa: F401


def _cfg(path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _tables(path) -> set[str]:
    with sqlite3.connect(path) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_legacy_database_upgrades_and_downgrades(tmp_path):
    db = tmp_path / "legacy.db"
    cfg = _cfg(db)
    command.upgrade(cfg, "0001")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('u', 'h', 'admin')")
        c.execute("INSERT INTO deals (external_id, name, stage, owner) "
                  "VALUES ('D-1', 'Legacy', 'NDA signed', 'u')")
        for i in range(2):
            c.execute("INSERT INTO audit_entries (actor, action, payload, created_at) "
                      "VALUES ('u', ?, ?, '2026-10-06 12:00:00.000000')",
                      (f"act{i}", json.dumps({"i": i})))

    command.upgrade(cfg, "head")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT stage, transaction_class, outcome FROM deals").fetchone() == \
            ("ORIGINATED", "DEBT", None)
        assert c.execute("SELECT COUNT(*) FROM deal_stage_history").fetchone()[0] == 1
        rows = c.execute("SELECT prev_hash, row_hash FROM audit_entries ORDER BY id").fetchall()
        assert rows[0][0] == GENESIS_HASH and rows[1][0] == rows[0][1]
    # the migrated schema has the same tables as create_all
    assert Base.metadata.tables.keys() <= _tables(db)

    command.downgrade(cfg, "0001")
    after = _tables(db)
    assert "deal_stage_history" not in after and "stage_guard" not in after
    with sqlite3.connect(db) as c:
        assert [r[1] for r in c.execute("PRAGMA table_info(deals)")] == \
            ["id", "external_id", "name", "stage", "owner", "created_at"]
        assert c.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 1
        assert not c.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall()

    command.upgrade(cfg, "head")  # and back up again
