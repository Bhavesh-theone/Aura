"""Migrations 0003-0005: data is carried across, and every step goes back down cleanly."""
import json
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from aura.config import BACKEND_DIR
from aura.core.policy.handoff_policy import validate_bot_to_human


def _cfg(path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path.as_posix()}")
    return cfg


def _tables(db) -> set[str]:
    with sqlite3.connect(db) as c:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _deal(c, ext="D-1", owner="u"):
    c.execute("INSERT INTO deals (external_id, name, stage, owner, transaction_class, opened_at)"
              " VALUES (?, 'Deal', 'ORIGINATED', ?, 'DEBT', '2026-10-06 12:00:00.000000')",
              (ext, owner))
    return c.execute("SELECT id FROM deals WHERE external_id = ?", (ext,)).fetchone()[0]


def test_guard_descriptions_and_enum_alignment(tmp_path):
    db, cfg = tmp_path / "a.db", _cfg(tmp_path / "a.db")
    command.upgrade(cfg, "0002")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('u', 'h', 'admin')")
        deal = _deal(c)
        c.execute("INSERT INTO stage_guard (from_stage, to_stage, guard_name, sql_text, "
                  "severity, active) VALUES ('QUALIFIED', 'MANDATED', 'T2_engagement_letter', "
                  "'select 1', 'blocking', 1)")
        for i, cls in enumerate(["financial_statements", "sha", "loan_agreement", "teaser",
                                 "dd_report", "cp_evidence", "other", "term_sheet", "nda"]):
            c.execute("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
                      "version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
                      "class_confirmed) VALUES (?, ?, ?, 'x', 1, 1, 0, 2, 'u', "
                      "'2026-10-06', 1)", (deal, cls, f"f{i}"))
        for t in ("institution", "company", "fund"):
            c.execute("INSERT INTO party (party_type, display_name, created_at) VALUES "
                      "(?, ?, '2026-10-06')", (t, t))

    command.upgrade(cfg, "0003")
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT description FROM stage_guard").fetchone()[0] == \
            "A signed engagement letter is on file"
        rows = c.execute("SELECT filename, doc_class, class_confirmed FROM document "
                         "ORDER BY id").fetchall()
        assert rows == [("f0", "financial_statement", 1), ("f1", "shpa", 0),
                        ("f2", "charge_document", 1), ("f3", "financial_statement", 0),
                        ("f4", "financial_statement", 0), ("f5", "board_resolution", 0),
                        ("f6", "financial_statement", 0), ("f7", "term_sheet", 1),
                        ("f8", "nda", 1)]
        assert [r[0] for r in c.execute("SELECT party_type FROM party ORDER BY id")] == \
            ["company", "company", "fund"]
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
                      "version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
                      "class_confirmed) VALUES (?, 'teaser', 'x', 'x', 1, 1, 0, 2, 'u', "
                      "'2026-10-06', 0)", (deal,))
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO party (party_type, display_name, created_at) VALUES "
                      "('institution', 'x', '2026-10-06')")
        for ok in ("cap_table", "moa_aoa", "land_title"):
            c.execute("INSERT INTO document (deal_id, doc_class, filename, sha256, byte_size, "
                      "version, contains_upsi, sensitivity, uploaded_by, uploaded_at, "
                      "class_confirmed) VALUES (?, ?, 'x', 'x', 1, 1, 0, 2, 'u', "
                      "'2026-10-06', 0)", (deal, ok))
        for ok in ("trust", "huf", "sole_prop", "government_body", "foreign_entity",
                   "partnership"):
            c.execute("INSERT INTO party (party_type, display_name, created_at) VALUES "
                      "(?, 'x', '2026-10-06')", (ok,))

    command.downgrade(cfg, "0002")
    with sqlite3.connect(db) as c:
        classes = {r[0] for r in c.execute("SELECT doc_class FROM document")}
        assert classes <= {"financial_statements", "shpa", "loan_agreement", "board_resolution",
                           "term_sheet", "nda", "other"}
        assert "description" not in [r[1] for r in c.execute("PRAGMA table_info(stage_guard)")]
        assert {r[0] for r in c.execute("SELECT party_type FROM party")} <= {
            "company", "llp", "fund", "individual", "institution"}
    command.upgrade(cfg, "head")


def test_approvals_become_handoffs_and_come_back(tmp_path):
    db, cfg = tmp_path / "b.db", _cfg(tmp_path / "b.db")
    command.upgrade(cfg, "0003")
    action = {"tool": "send_email", "category": "outbound", "arguments": {"body": "hi"},
              "summary": "Send intro email"}
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES ('u', 'h', 'admin')")
        deal = _deal(c)
        c.execute("INSERT INTO jobs (status, inputs, deal_id, created_at) VALUES "
                  "('awaiting_approval', '{}', ?, '2026-10-06 12:00:00.000000')", (deal,))
        c.execute("INSERT INTO jobs (status, inputs, created_at) VALUES "
                  "('rejected', '{}', '2026-10-06 12:00:00.000000')")
        for job in (1, 2, 2):
            c.execute("INSERT INTO segments (job_id, seq, status, context_in) VALUES "
                      "(?, ?, 'awaiting_approval', '{}')",
                      (job, c.execute("SELECT COUNT(*) FROM segments WHERE job_id = ?",
                                      (job,)).fetchone()[0] + 1))
        for seg, status, decided in [(1, "pending", None), (2, "approved", 1),
                                     (3, "rejected", 1)]:
            c.execute("INSERT INTO approvals (segment_id, category, proposed_action, status, "
                      "decided_by, decided_at) VALUES (?, 'outbound', ?, ?, ?, ?)",
                      (seg, json.dumps(action), status, decided,
                       "2026-10-07 09:00:00.000000" if decided else None))

    command.upgrade(cfg, "0004")
    assert "approvals" not in _tables(db) and {"task", "handoff"} <= _tables(db)
    with sqlite3.connect(db) as c:
        tasks = c.execute("SELECT deal_id, job_id, task_type, assignment_mode, status "
                          "FROM task ORDER BY id").fetchall()
        assert tasks == [(deal, 1, "send_email", "human_required", "review"),
                         (None, 2, "send_email", "human_required", "done"),
                         (None, 2, "send_email", "human_required", "cancelled")]
        handoffs = c.execute("SELECT direction, trigger, status, resolved_by, context_package, "
                             "directive FROM handoff ORDER BY id").fetchall()
        assert [h[2] for h in handoffs] == ["open", "resolved", "resolved"]
        assert [h[3] for h in handoffs] == [None, "u", "u"]
        for h in handoffs:
            assert h[0] == "bot_to_human" and h[1] == "policy_required"
            validate_bot_to_human(json.loads(h[4]))  # migrated packages are valid
        assert json.loads(handoffs[1][5])["decision"] == "approve"
        assert json.loads(handoffs[2][5])["decision"] == "reject"

    command.downgrade(cfg, "0003")
    assert "approvals" in _tables(db) and not {"task", "handoff"} & _tables(db)
    with sqlite3.connect(db) as c:
        back = c.execute("SELECT status, category, decided_by FROM approvals "
                         "ORDER BY id").fetchall()
        assert back == [("pending", "outbound", None), ("approved", "outbound", 1),
                        ("rejected", "outbound", 1)]
    command.upgrade(cfg, "head")


def test_existing_deals_get_a_wall_with_their_owner(tmp_path):
    db, cfg = tmp_path / "c.db", _cfg(tmp_path / "c.db")
    command.upgrade(cfg, "0004")
    with sqlite3.connect(db) as c:
        c.execute("INSERT INTO users (username, password_hash, role) VALUES "
                  "('u', 'h', 'admin'), ('v', 'h', 'member')")
        _deal(c, "D-1", "u")
        _deal(c, "D-2", "v")
    command.upgrade(cfg, "0005")
    with sqlite3.connect(db) as c:
        rows = c.execute("SELECT d.external_id, w.name, u.username, m.removed_at FROM wall w "
                         "JOIN deals d ON d.id = w.deal_id JOIN wall_member m ON m.wall_id = "
                         "w.id JOIN users u ON u.id = m.user_id ORDER BY d.id").fetchall()
        assert rows == [("D-1", "D-1 wall", "u", None), ("D-2", "D-2 wall", "v", None)]
        assert "created_by" in [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
    command.downgrade(cfg, "0004")
    assert not {"wall", "wall_member", "agent_run"} & _tables(db)
    with sqlite3.connect(db) as c:
        assert "created_by" not in [r[1] for r in c.execute("PRAGMA table_info(jobs)")]
        assert c.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 2


def test_full_downgrade_to_baseline_and_back(tmp_path):
    cfg = _cfg(tmp_path / "d.db")
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0001")
    assert {"task", "handoff", "agent_run", "wall", "wall_member"}.isdisjoint(
        _tables(tmp_path / "d.db"))
    command.upgrade(cfg, "head")


def test_alembic_check_reports_no_drift(tmp_path):
    cfg = _cfg(tmp_path / "e.db")
    command.upgrade(cfg, "head")
    command.check(cfg)  # raises if the models and the migrations disagree
