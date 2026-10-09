"""Row-level security on PostgreSQL (PRD D1): the database itself hides deals whose wall
does not list the viewer, under raw SQL, whatever the application code does.

Raw SQL here runs as aura_app (the app's role) on plain connections, setting aura.viewer
by hand the way the unit of work does.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from aura.data.engine import engine as app_engine
from aura.data.walls import SYSTEM_VIEWER
from tests.integration.helpers import make_deal, upload
from tests.integration.pgtest import fresh_engine, owner_engine

DEAL_SCOPED = ["deals", "deal_party", "deal_stage_history", "stage_guard_evaluation",
               "mandate", "mandate_criteria", "document", "doc_version", "doc_access_log",
               "extraction", "diligence_item", "finding", "deal_signoff",
               "condition_precedent", "deal_note", "wall", "wall_member", "jobs", "segments",
               "task", "handoff", "agent_run", "audit_entries", "outbound_message",
               "trace_span", "doc_chunk", "deal_intake"]


def as_viewer(viewer: str | None, sql: str, **params):
    """Run one statement as aura_app with aura.viewer set (None: not set at all)."""
    with app_engine.connect() as conn:
        if viewer is not None:
            conn.execute(text("SELECT set_config('aura.viewer', :v, true)"), {"v": viewer})
        result = conn.execute(text(sql), params)
        rows = result.all() if result.returns_rows else result.rowcount
        conn.commit()
        return rows


def count(viewer, table, where="TRUE", **params) -> int:
    return as_viewer(viewer, f"SELECT count(*) FROM {table} WHERE {where}", **params)[0][0]


@pytest.fixture()
def clean():
    fresh_engine()


@pytest.fixture()
def two_deals(api):
    """A: bhavesh's deal, asha not on its wall. B: bhavesh's deal with asha added."""
    a = make_deal(api, "RLS-A")
    upload(api, a, "secret.pdf", content=b"deal A only")
    b = make_deal(api, "RLS-B")
    api.add_member(b, "asha")
    upload(api, b, "shared.pdf", content=b"deal B")
    return a, b


def test_every_deal_scoped_table_has_forced_rls_and_a_policy(clean):
    with owner_engine().connect() as conn:
        rows = {r.relname: (r.relrowsecurity, r.relforcerowsecurity) for r in conn.execute(
            text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                 "WHERE relname = ANY(:t) AND relkind = 'r'"), {"t": DEAL_SCOPED})}
        policies = set(conn.scalars(text("SELECT tablename FROM pg_policies "
                                         "WHERE schemaname = 'public'")))
    assert rows == {t: (True, True) for t in DEAL_SCOPED}
    assert set(DEAL_SCOPED) <= policies


def test_non_member_sees_zero_rows_member_sees_them(two_deals):
    a, b = two_deals
    # asha is not on A's wall: raw SQL returns nothing of A, in every table.
    assert count("asha", "deals", "id = :d", d=a) == 0
    assert count("asha", "document", "deal_id = :d", d=a) == 0
    assert count("asha", "doc_version v JOIN document d ON d.id = v.document_id",
                 "d.deal_id = :d", d=a) == 0
    assert count("asha", "audit_entries", "deal_id = :d", d=a) == 0
    assert count("asha", "deal_stage_history", "deal_id = :d", d=a) == 0
    assert count("asha", "wall", "deal_id = :d", d=a) == 0
    # ...and sees B, where she is a member.
    assert count("asha", "deals", "id = :d", d=b) == 1
    assert count("asha", "document", "deal_id = :d", d=b) == 1
    assert [r[0] for r in as_viewer("asha", "SELECT external_id FROM deals")] == ["RLS-B"]
    # bhavesh is on both walls.
    assert count("bhavesh", "deals") == 2


def test_no_viewer_sees_nothing_and_system_sees_everything(two_deals):
    assert count(None, "deals") == 0
    assert count("", "document") == 0
    assert count("nobody", "audit_entries", "deal_id IS NOT NULL") == 0
    assert count(SYSTEM_VIEWER, "deals") == 2
    assert count(SYSTEM_VIEWER, "document") == 2


def test_removed_member_loses_access_at_once(api, two_deals):
    _, b = two_deals
    r = api.call("DELETE", f"/api/deals/{b}/members", user="priya", json={"username": "asha"})
    assert r.status_code == 200, r.text
    assert count("asha", "deals", "id = :d", d=b) == 0


def test_writes_outside_the_wall_are_rejected(two_deals):
    a, _ = two_deals
    with pytest.raises(ProgrammingError, match="row-level security"):
        as_viewer("asha", "INSERT INTO deal_note (deal_id, body, author, source, created_at) "
                          "VALUES (:d, 'x', 'asha', 'test', now())", d=a)
    # An UPDATE simply finds no row to change.
    assert as_viewer("asha", "UPDATE deals SET name = 'pwned' WHERE id = :d", d=a) == 0
    assert as_viewer(SYSTEM_VIEWER, "SELECT name FROM deals WHERE id = :d", d=a)[0][0] \
        == "Deal RLS-A"


def test_the_app_role_cannot_switch_rls_off(clean):
    with app_engine.connect() as conn:
        bypass = conn.scalar(text("SELECT rolbypassrls OR rolsuper FROM pg_roles "
                                  "WHERE rolname = current_user"))
        assert conn.scalar(text("SELECT current_user")) == "aura_app" and bypass is False
    attempts = ["ALTER TABLE deals DISABLE ROW LEVEL SECURITY",
                "ALTER TABLE deals NO FORCE ROW LEVEL SECURITY",
                "DROP POLICY wall_visibility ON deals",
                "SET ROLE aura_owner"]
    for sql in attempts:
        with pytest.raises(ProgrammingError):
            as_viewer("asha", sql)
    # row_security = off does not turn policies off for a role they apply to: it errors.
    with pytest.raises(DBAPIError, match="row-level security"):
        with app_engine.connect() as conn:
            conn.execute(text("SET LOCAL row_security = off"))
            conn.execute(text("SELECT count(*) FROM deals"))


def test_deal_intake_is_private_to_its_creator(clean):
    as_viewer("asha", "INSERT INTO deal_intake (created_by, status, fields, conflicts) "
                      "VALUES ('asha', 'draft', '{}', '[]')")
    assert count("asha", "deal_intake") == 1
    assert count("bhavesh", "deal_intake") == 0
    assert count(SYSTEM_VIEWER, "deal_intake") == 1
    with pytest.raises(ProgrammingError, match="row-level security"):
        as_viewer("bhavesh", "INSERT INTO deal_intake (created_by) VALUES ('asha')")


def test_doc_chunks_follow_the_deal_wall(two_deals):
    a, _ = two_deals
    doc = as_viewer(SYSTEM_VIEWER, "SELECT id FROM document WHERE deal_id = :d", d=a)[0][0]
    vec = "[" + ",".join(["0.1"] * 768) + "]"
    as_viewer(SYSTEM_VIEWER,
              "INSERT INTO doc_chunk (document_id, deal_id, version, chunk_index, text, kind, "
              "embedding, embedding_model) VALUES (:doc, :d, 1, 0, 'Revenue grew 20 percent', "
              "'text', CAST(:v AS vector), 'nomic-embed-text')", doc=doc, d=a, v=vec)
    assert count("bhavesh", "doc_chunk", "tsv @@ to_tsquery('english', 'revenue')") == 1
    assert count("asha", "doc_chunk") == 0
    nearest = as_viewer("bhavesh", "SELECT embedding <=> CAST(:v AS vector) FROM doc_chunk",
                        v=vec)
    assert nearest[0][0] == pytest.approx(0.0)


def test_append_only_tables_reject_update_and_delete_even_for_the_owner(api):
    make_deal(api, "AO-1")
    for table in ("audit_entries", "deal_stage_history"):
        for sql in (f"UPDATE {table} SET actor = 'x'", f"DELETE FROM {table}"):
            with pytest.raises(DBAPIError, match="append-only"):
                with owner_engine().begin() as conn:
                    conn.execute(text(sql))
            # The app role has no UPDATE/DELETE grant on them at all.
            with pytest.raises(ProgrammingError, match="permission denied"):
                as_viewer(SYSTEM_VIEWER, sql)
