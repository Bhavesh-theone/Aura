"""Migration 0010: mandates move to the SOSPE §6.2 shape, data carried both ways."""
import json
import sqlite3

import pytest
from alembic import command

from tests.integration.test_migrations_m4 import _cfg, _cols, _deal

T3_OLD = ("SELECT EXISTS(SELECT 1 FROM mandate m JOIN mandate_criteria c ON c.mandate_id = "
          "m.id WHERE m.deal_id = :deal_id AND c.kind = 'hard')")


def test_mandates_take_the_sospe_shape_and_come_back(tmp_path):
    db, cfg = tmp_path / "m.db", _cfg(tmp_path / "m.db")
    command.upgrade(cfg, "0009")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('bhavesh', 'h', "
                  "'dealmaker')")
        debt, mna = _deal(c, "D-1"), _deal(c, "D-2")
        c.execute("UPDATE deals SET transaction_class = 'MNA' WHERE id = ?", (mna,))
        for deal in (debt, mna):
            c.execute("INSERT INTO mandate (deal_id, title, notes, created_at) VALUES "
                      "(?, 'M', '', '2026-10-06 12:00:00.000000')", (deal,))
        c.executemany("INSERT INTO mandate_criteria (mandate_id, kind, attribute, value, "
                      "weight) VALUES (?, ?, ?, ?, ?)",
                      [(1, "hard", "ticket_min", "100", None),
                       (1, "soft", "sector", "infra", 5.0),
                       (2, "preference", "region", "south", 0.25)])
        c.execute("INSERT INTO stage_guard (from_stage, to_stage, guard_name, sql_text, "
                  "severity, override_role, active, description) VALUES ('MANDATED', "
                  "'PREPARED', 'T3_hard_criterion', ?, 'blocking', 'dealmaker', 1, '')",
                  (T3_OLD,))
    command.upgrade(cfg, "0010")
    with sqlite3.connect(db) as c:
        assert dict(c.execute("SELECT deal_id, side FROM mandate")) == {debt: "raise",
                                                                         mna: "sell"}
        assert {r[0] for r in c.execute("SELECT status FROM mandate")} == {"active"}
        rows = c.execute("SELECT criterion_key, operator, value, hardness, weight FROM "
                         "mandate_criteria ORDER BY id").fetchall()
        assert [(k, o, json.loads(v), h, w) for k, o, v, h, w in rows] == [
            ("ticket_min", "eq", "100", "hard", None),
            ("sector", "eq", "infra", "soft", 1.0),        # weight clamped into 0..1
            ("region", "eq", "south", "preference", 0.25)]
        sql = c.execute("SELECT sql_text FROM stage_guard").fetchone()[0]
        assert "c.hardness = 'hard'" in sql and "c.kind" not in sql
        assert c.execute(sql.replace(":deal_id", str(debt))).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):  # soft needs a weight
            c.execute("INSERT INTO mandate_criteria (mandate_id, criterion_key, operator, "
                      "value, hardness) VALUES (1, 'k', 'eq', '\"v\"', 'soft')")
        with pytest.raises(sqlite3.IntegrityError):  # weight 0..1
            c.execute("INSERT INTO mandate_criteria (mandate_id, criterion_key, operator, "
                      "value, hardness, weight) VALUES (1, 'k', 'eq', '1', 'hard', 2)")
        with pytest.raises(sqlite3.IntegrityError):  # unknown operator
            c.execute("INSERT INTO mandate_criteria (mandate_id, criterion_key, operator, "
                      "value, hardness) VALUES (1, 'k', 'approx', '1', 'hard')")
        with pytest.raises(sqlite3.IntegrityError):  # unknown side
            c.execute("UPDATE mandate SET side = 'lend' WHERE id = 1")
        c.execute("INSERT INTO mandate_criteria (mandate_id, criterion_key, operator, value, "
                  "hardness) VALUES (1, 'size', 'between', '[1, 2]', 'hard')")
    command.downgrade(cfg, "0009")
    with sqlite3.connect(db) as c:
        assert "side" not in _cols(c, "mandate") and "status" not in _cols(c, "mandate")
        assert c.execute("SELECT kind, attribute, value, weight FROM mandate_criteria "
                         "ORDER BY id").fetchall() == [
            ("hard", "ticket_min", "100", None), ("soft", "sector", "infra", 1.0),
            ("preference", "region", "south", 0.25), ("hard", "size", "[1, 2]", None)]
        assert c.execute("SELECT sql_text FROM stage_guard").fetchone()[0] == T3_OLD
    command.upgrade(cfg, "head")
