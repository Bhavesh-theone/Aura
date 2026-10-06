"""Migrations 0006-0009: roles, document versions, guard-evaluation links, extractions and
templates. Data is carried across and every step goes back down."""
import json
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from aura.config import BACKEND_DIR


def _cfg(path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _cols(c, table):
    return [r[1] for r in c.execute(f"PRAGMA table_info({table})")]


def _tables(c):
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _deal(c, ext="D-1", owner="bhavesh", stage="ORIGINATED"):
    c.execute("INSERT INTO deals (external_id, name, stage, owner, transaction_class, "
              "opened_at) VALUES (?, 'Deal', ?, ?, 'DEBT', '2026-10-06 12:00:00.000000')",
              (ext, stage, owner))
    return c.execute("SELECT id FROM deals WHERE external_id = ?", (ext,)).fetchone()[0]


def test_roles_become_dealmaker_and_analyst_and_users_gain_active(tmp_path):
    db, cfg = tmp_path / "r.db", _cfg(tmp_path / "r.db")
    command.upgrade(cfg, "0005")
    with sqlite3.connect(db) as c:
        c.executemany("INSERT INTO users (username, password_hash, role) VALUES (?, 'h', ?)",
                      [("bhavesh", "admin"), ("boss", "admin"), ("asha", "member"),
                       ("ravi", "member")])
    command.upgrade(cfg, "0006")
    with sqlite3.connect(db) as c:
        assert dict(c.execute("SELECT username, role FROM users")) == {
            "bhavesh": "dealmaker", "boss": "admin", "asha": "analyst", "ravi": "analyst"}
        assert {r[0] for r in c.execute("SELECT active FROM users")} == {1}
        for role in ("compliance", "dealmaker", "analyst", "admin"):
            c.execute("INSERT INTO users (username, password_hash, role) VALUES (?, 'h', ?)",
                      (f"new-{role}", role))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO users (username, password_hash, role) VALUES ('m', 'h', "
                      "'member')")
    command.downgrade(cfg, "0005")
    with sqlite3.connect(db) as c:
        assert dict(c.execute("SELECT username, role FROM users WHERE username IN "
                              "('bhavesh', 'boss', 'asha', 'new-compliance')")) == {
            "bhavesh": "admin", "boss": "admin", "asha": "member", "new-compliance": "member"}
        assert "active" not in _cols(c, "users")
    command.upgrade(cfg, "head")


def test_documents_get_version_rows_and_an_executed_flag(tmp_path):
    db, cfg = tmp_path / "d.db", _cfg(tmp_path / "d.db")
    command.upgrade(cfg, "0006")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('bhavesh', 'h', "
                  "'dealmaker')")
        deal = _deal(c)
        for name, version in (("a.pdf", 1), ("a.pdf", 2), ("b.pdf", 1)):
            c.execute("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
                      "version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
                      "class_confirmed) VALUES (?, 'nda', ?, ?, 10, ?, 0, 2, 'bhavesh', "
                      "'2026-10-06 12:00:00.000000', 1)", (deal, name, f"sha-{name}-{version}",
                                                           version))
        c.execute("INSERT INTO doc_access_log (document_id, accessed_by, action) VALUES "
                  "(1, 'bhavesh', 'download')")
    command.upgrade(cfg, "0007")
    with sqlite3.connect(db) as c:
        assert "current_version" in _cols(c, "document")
        assert "version" not in _cols(c, "document")
        assert c.execute("SELECT id, current_version, is_executed FROM document "
                         "ORDER BY id").fetchall() == [(1, 1, 0), (2, 2, 0), (3, 1, 0)]
        assert c.execute("SELECT document_id, version, sha256, byte_size, uploaded_by FROM "
                         "doc_version ORDER BY document_id").fetchall() == [
            (1, 1, "sha-a.pdf-1", 10, "bhavesh"), (2, 2, "sha-a.pdf-2", 10, "bhavesh"),
            (3, 1, "sha-b.pdf-1", 10, "bhavesh")]
        assert c.execute("SELECT COUNT(*) FROM doc_access_log").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO doc_version VALUES (1, 1, 'x', 1, 'u', '2026')")
    command.downgrade(cfg, "0006")
    with sqlite3.connect(db) as c:
        assert "doc_version" not in _tables(c)
        assert [r[0] for r in c.execute("SELECT version FROM document ORDER BY id")] == [1, 2, 1]
        assert "is_executed" not in _cols(c, "document")
    command.upgrade(cfg, "head")


def test_evaluations_are_linked_to_their_history_row_and_deals_get_flags(tmp_path):
    db, cfg = tmp_path / "e.db", _cfg(tmp_path / "e.db")
    command.upgrade(cfg, "0007")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('bhavesh', 'h', "
                  "'dealmaker')")
        deal = _deal(c, stage="MANDATED")
        c.execute("INSERT INTO stage_guard (from_stage, to_stage, guard_name, sql_text, "
                  "severity, active, description) VALUES ('QUALIFIED', 'MANDATED', 'g', "
                  "'select 1', 'blocking', 1, '')")
        c.execute("INSERT INTO stage_guard (from_stage, to_stage, guard_name, sql_text, "
                  "severity, active, description) VALUES ('MANDATED', 'PREPARED', 'h', "
                  "'select 1', 'blocking', 1, '')")
        for to, frm, at in (("QUALIFIED", "ORIGINATED", "2026-10-06 10:00:00.000000"),
                            ("MANDATED", "QUALIFIED", "2026-10-06 12:00:00.000000")):
            c.execute("INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, "
                      "entered_at, actor, is_regression) VALUES (?, ?, ?, ?, 'u', 0)",
                      (deal, frm, to, at))
        # a failed attempt, then the passing one that let the move through, then an
        # evaluation for a move that never happened
        for guard, result, at in ((1, 0, "2026-10-06 11:00:00.000000"),
                                  (1, 1, "2026-10-06 11:59:59.000000"),
                                  (2, 1, "2026-10-06 13:00:00.000000")):
            c.execute("INSERT INTO stage_guard_evaluation (deal_id, guard_id, attempted_at, "
                      "result, detail, actor) VALUES (?, ?, ?, ?, '{}', 'u')",
                      (deal, guard, at, result))
    command.upgrade(cfg, "0008")
    with sqlite3.connect(db) as c:
        links = c.execute("SELECT id, result, history_id FROM stage_guard_evaluation "
                          "ORDER BY id").fetchall()
        assert links == [(1, 0, None), (2, 1, 2), (3, 1, None)]
        assert c.execute("SELECT regulatory_flags FROM deals").fetchone()[0] == "[]"
        assert "deal_signoff" in _tables(c)
        c.execute("INSERT INTO deal_signoff (deal_id, signed_by, note, signed_at) VALUES "
                  "(?, 'priya', '', '2026-10-06')", (deal,))
    command.downgrade(cfg, "0007")
    with sqlite3.connect(db) as c:
        assert "deal_signoff" not in _tables(c)
        assert "regulatory_flags" not in _cols(c, "deals")
        assert "history_id" not in _cols(c, "stage_guard_evaluation")
        assert c.execute("SELECT COUNT(*) FROM stage_guard_evaluation").fetchone()[0] == 3
    command.upgrade(cfg, "head")


def test_checklist_items_are_grouped_under_templates_and_identifiers_get_checks(tmp_path):
    db, cfg = tmp_path / "t.db", _cfg(tmp_path / "t.db")
    command.upgrade(cfg, "0008")
    with sqlite3.connect(db) as c:
        for cls, prompt in ((None, "p1"), (None, "p2"), ("DEBT", "p3"), ("ALLIANCE", "p4")):
            c.execute("INSERT INTO checklist_item_template (transaction_class, category, "
                      "prompt, default_severity) VALUES (?, 'c', ?, 'standard')", (cls, prompt))
        c.execute("INSERT INTO party (party_type, display_name, created_at) VALUES "
                  "('company', 'x', '2026-10-06')")
        c.execute("INSERT INTO party_identifier (party_id, scheme, value) VALUES "
                  "(1, 'PAN', 'ABCDE1234F')")
    command.upgrade(cfg, "0009")
    with sqlite3.connect(db) as c:
        templates = c.execute("SELECT transaction_class, layer, version FROM "
                              "checklist_template ORDER BY id").fetchall()
        assert templates == [(None, "base", 1), ("DEBT", "subclass", 1),
                             ("ALLIANCE", "subclass", 1)]
        grouped = c.execute("SELECT i.prompt, t.layer, t.transaction_class FROM "
                            "checklist_item_template i JOIN checklist_template t ON "
                            "t.id = i.template_id ORDER BY i.id").fetchall()
        assert grouped == [("p1", "base", None), ("p2", "base", None),
                           ("p3", "subclass", "DEBT"), ("p4", "subclass", "ALLIANCE")]
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO party_identifier (party_id, scheme, value) VALUES "
                      "(1, 'PAN', 'bad')")
        for table in ("extraction", "finding"):
            assert table in _tables(c)
    with sqlite3.connect(db) as c:
        c.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO checklist_item_template (template_id, category, prompt, "
                      "default_severity) VALUES (99, 'c', 'p', 'standard')")
    command.downgrade(cfg, "0008")
    with sqlite3.connect(db) as c:
        assert not {"extraction", "finding", "checklist_template"} & _tables(c)
        assert "template_id" not in _cols(c, "checklist_item_template")
        assert c.execute("SELECT COUNT(*) FROM checklist_item_template").fetchone()[0] == 4
        c.execute("INSERT INTO party_identifier (party_id, scheme, value) VALUES (1, 'PAN', "
                  "'bad')")  # the CHECK went with the downgrade
        # upgrading again refuses a database holding a malformed identifier
        c.commit()
    with pytest.raises(Exception, match="malformed identifier"):
        command.upgrade(cfg, "head")
    with sqlite3.connect(db) as c:
        assert "extraction" not in _tables(c)  # refused before anything changed
    with sqlite3.connect(db) as c:
        c.execute("DELETE FROM party_identifier WHERE value = 'bad'")
    command.upgrade(cfg, "head")


def test_a_real_looking_database_goes_all_the_way_up_down_and_up(tmp_path):
    db, cfg = tmp_path / "full.db", _cfg(tmp_path / "full.db")
    command.upgrade(cfg, "0005")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('bhavesh', 'h', "
                  "'admin')")
        deal = _deal(c)
        c.execute("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
                  "version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
                  "class_confirmed) VALUES (?, 'nda', 'a.pdf', 'x', 1, 1, 0, 2, 'bhavesh', "
                  "'2026-10-06 12:00:00.000000', 0)", (deal,))
    command.upgrade(cfg, "head")
    command.check(cfg)
    command.downgrade(cfg, "0005")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT role FROM users").fetchone()[0] == "admin"
        assert c.execute("SELECT version FROM document").fetchone()[0] == 1
    command.upgrade(cfg, "head")
    command.check(cfg)