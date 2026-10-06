"""The demo dataset builds through the real services on a fresh database, leaves a clean
audit chain and fully guarded forward moves, and a second run adds nothing."""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[2]


def _run(db: Path) -> str:
    proc = subprocess.run([sys.executable, "-m", "aura.data.demo", "--db", str(db)],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8",
                          timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_demo_builds_once_and_is_idempotent(tmp_path):
    db = tmp_path / "demo.db"
    out = _run(db)
    assert "17 deal(s) built" in out and "Audit chain: OK" in out

    con = sqlite3.connect(db)
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    counts = {t: q(f"SELECT COUNT(*) FROM {t}")[0][0]
              for t in ("deals", "audit_entries", "deal_stage_history", "handoff", "document")}
    stages = dict(q("SELECT external_id, stage FROM deals WHERE external_id LIKE 'AUR-%'"))
    assert {"CLOSED", "LAPSED", "WITHDRAWN", "REJECTED", "ABORTED", "ORIGINATED",
            "DILIGENCE", "CONDITIONS_PRECEDENT"} <= set(stages.values())
    assert set(dict(q("SELECT transaction_class, 1 FROM deals"))) >= {
        "DEBT", "EQUITY", "MNA", "HYBRID", "JV", "LPGP", "ALLIANCE"}
    # Every forward move of a demo deal has its guard evaluations linked (SM1 = 100%).
    unguarded = q("""
        SELECT h.id FROM deal_stage_history h JOIN deals d ON d.id = h.deal_id
        WHERE d.external_id LIKE 'AUR-%' AND h.from_stage IS NOT NULL AND h.is_regression = 0
          AND h.to_stage NOT IN ('LAPSED','WITHDRAWN','REJECTED','ABORTED')
          AND NOT EXISTS (SELECT 1 FROM stage_guard_evaluation e WHERE e.history_id = h.id)""")
    assert unguarded == []
    # Demo audit rows are in time order, and the agent work is honestly the stub.
    rows = q("SELECT created_at FROM audit_entries WHERE id > (SELECT MIN(id) FROM "
             "audit_entries WHERE action = 'user_created') ORDER BY id")
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)
    assert {m for (m,) in q("SELECT DISTINCT model_id FROM agent_run")} == {"stub"}
    assert q("SELECT COUNT(*) FROM segments WHERE status = 'queued'")[0][0] == 0
    assert q("SELECT COUNT(*) FROM handoff WHERE status != 'resolved'")[0][0] == 5
    con.close()

    out = _run(db)
    assert "0 deal(s) built, 17 already present" in out and "Audit chain: OK" in out
    con = sqlite3.connect(db)
    again = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}
    assert again == counts
    assert json.loads(json.dumps(again))  # plain ints
