"""Migration 0011_harness_reliability: claim and retry columns, dead_letter, agent_run
segment_id and the idempotency_key table, carried up and back down."""
import sqlite3

import pytest
from alembic import command

from tests.integration.test_migrations_m4 import _cfg, _cols, _tables


def test_harness_reliability_columns_come_and_go(tmp_path):
    db, cfg = tmp_path / "h.db", _cfg(tmp_path / "h.db")
    command.upgrade(cfg, "0010")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO jobs (status, inputs, created_at) VALUES ('pending', '{}', "
                  "'2026-10-06 12:00:00.000000')")
        c.execute("INSERT INTO segments (job_id, seq, status, context_in) VALUES "
                  "(1, 1, 'queued', '{}')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE segments SET status = 'dead_letter'")

    command.upgrade(cfg, "0011_harness_reliability")
    with sqlite3.connect(db) as c:
        assert {"claimed_by", "claimed_at", "attempts", "not_before", "last_error"} <= \
            set(_cols(c, "segments"))
        assert "segment_id" in _cols(c, "agent_run")
        assert "idempotency_key" in _tables(c)
        assert c.execute("SELECT status, attempts FROM segments").fetchone() == ("queued", 0)
        c.execute("UPDATE segments SET status = 'dead_letter', attempts = 3, "
                  "last_error = 'refused'")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE segments SET status = 'lost'")
        c.execute("INSERT INTO idempotency_key (key, username, request_hash, job_id, "
                  "created_at) VALUES ('k', 'asha', 'h', 1, '2026-10-06 12:00:00.000000')")
        with pytest.raises(sqlite3.IntegrityError):  # one per key and user
            c.execute("INSERT INTO idempotency_key (key, username, request_hash, job_id, "
                      "created_at) VALUES ('k', 'asha', 'h2', 1, "
                      "'2026-10-06 12:00:00.000000')")

    command.downgrade(cfg, "0010")
    with sqlite3.connect(db) as c:
        assert "attempts" not in _cols(c, "segments")
        assert "segment_id" not in _cols(c, "agent_run")
        assert "idempotency_key" not in _tables(c)
        assert c.execute("SELECT status FROM segments").fetchone() == ("failed",)
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE segments SET status = 'dead_letter'")
    command.upgrade(cfg, "head")
