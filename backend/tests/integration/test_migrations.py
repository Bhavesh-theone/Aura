"""The PostgreSQL baseline migration: up, down and up again on a scratch database, no drift
from the models, and the constraints, triggers and grants it installs.

(The SQLite chain 0001-0013 lives in migrations/sqlite_legacy/ for reference and is no
longer run; its data upgrades are covered for real data by aura.data.migrate_sqlite.)
"""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect, make_url, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

import aura.data.models.tables  # noqa: F401
from aura.config import get_settings
from aura.data.engine import Base
from aura.data.seed import alembic_config
from tests.integration.pgtest import owner_url


@pytest.fixture()
def scratch():
    """An empty database, migrated by the test itself: (owner url, app url)."""
    name = f"{make_url(get_settings().migration_database_url).database}_mig"
    admin = create_engine(owner_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    app = make_url(get_settings().database_url).set(database=name)
    yield owner_url(name), app.render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


def _tables(url) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def _scalar(url, sql, **params):
    eng = create_engine(url)
    try:
        with eng.begin() as conn:
            return conn.execute(text(sql), params).scalar()
    finally:
        eng.dispose()


def test_baseline_goes_up_down_and_up_again(scratch):
    owner, _ = scratch
    cfg = alembic_config(owner)
    command.upgrade(cfg, "head")
    assert Base.metadata.tables.keys() <= _tables(owner)
    assert _scalar(owner, "SELECT count(*) FROM pg_proc WHERE proname LIKE 'aura\\_%'") == 7
    command.downgrade(cfg, "base")
    assert _tables(owner) == {"alembic_version"}
    assert _scalar(owner, "SELECT count(*) FROM pg_proc WHERE proname LIKE 'aura\\_%'") == 0
    command.upgrade(cfg, "head")
    assert Base.metadata.tables.keys() <= _tables(owner)


def test_models_and_migration_have_not_drifted(scratch):
    owner, _ = scratch
    command.upgrade(alembic_config(owner), "head")
    eng = create_engine(owner)
    with eng.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    eng.dispose()
    assert diff == []


def test_native_types_extensions_and_indexes(scratch):
    owner, _ = scratch
    command.upgrade(alembic_config(owner), "head")
    eng = create_engine(owner)
    with eng.connect() as conn:
        types = dict(conn.execute(text(
            "SELECT table_name || '.' || column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public'")).all())
    eng.dispose()
    assert types["deals.profile"] == types["audit_entries.payload"] == "jsonb"
    assert types["audit_entries.created_at"] == "timestamp with time zone"
    assert types["finding.quantified_impact_inr"] == types["agent_run.cost_inr"] == "numeric"
    assert types["deals.id"] == "bigint"
    assert types["doc_chunk.tsv"] == "tsvector" and types["doc_chunk.embedding"] == \
        "USER-DEFINED"
    exts = _scalar(owner, "SELECT string_agg(extname, ',' ORDER BY extname) FROM pg_extension")
    assert {"vector", "pg_trgm"} <= set(exts.split(","))
    idx = _scalar(owner, "SELECT indexdef FROM pg_indexes "
                         "WHERE indexname = 'ix_doc_chunk_embedding_hnsw'")
    assert "hnsw" in idx and "vector_cosine_ops" in idx and "m='16'" in idx
    assert "gin" in _scalar(owner, "SELECT indexdef FROM pg_indexes "
                                   "WHERE indexname = 'ix_deals_profile'")


def test_check_constraints_hold_for_raw_sql(scratch):
    owner, _ = scratch
    command.upgrade(alembic_config(owner), "head")
    eng = create_engine(owner)
    with eng.begin() as c:
        c.execute(text("INSERT INTO users (username, password_hash, role) "
                       "VALUES ('u', 'h', 'analyst')"))
        c.execute(text("INSERT INTO party (party_type, display_name, created_at) "
                       "VALUES ('company', 'P', now())"))
        c.execute(text("INSERT INTO party_contact (party_id, name, email, is_primary, "
                       "created_by, created_at) VALUES (1, '', 'a@b.co', true, 'x', now())"))
    bad = ["INSERT INTO party_contact (party_id, name, email, is_primary, created_by, "
           "created_at) VALUES (1, '', 'A@B.co', false, 'x', now())",
           "INSERT INTO party_contact (party_id, name, email, is_primary, created_by, "
           "created_at) VALUES (1, '', 'a@b.co', false, 'x', now())",  # unique per party
           "INSERT INTO suppression (kind, value, reason, created_by, created_at) "
           "VALUES ('phone', 'x', '', 'x', now())",
           "INSERT INTO party_identifier (party_id, scheme, value) VALUES (1, 'PAN', 'abcde1234f')",
           "INSERT INTO deals (external_id, name, stage, transaction_class, owner, opened_at, "
           "profile) VALUES ('X', 'X', 'ORIGINATED', 'DEBT', 'u', now(), '[]')",  # profile: object
           "INSERT INTO deals (external_id, name, stage, transaction_class, owner, opened_at) "
           "VALUES ('Y', 'Y', 'CLOSED', 'DEBT', 'u', now())",  # terminal needs an outcome
           "INSERT INTO users (username, password_hash, role) VALUES ('v', 'h', 'root')"]
    for sql in bad:
        with pytest.raises(IntegrityError):
            with eng.begin() as c:
                c.execute(text(sql))
    eng.dispose()


def test_ids_are_identity_columns_that_accept_explicit_values(scratch):
    owner, _ = scratch
    command.upgrade(alembic_config(owner), "head")
    eng = create_engine(owner)
    with eng.begin() as c:
        c.execute(text("INSERT INTO party (id, party_type, display_name, created_at) "
                       "VALUES (41, 'company', 'kept id', now())"))
        c.execute(text("SELECT setval(pg_get_serial_sequence('party', 'id'), 42, false)"))
        new_id = c.execute(text("INSERT INTO party (party_type, display_name, created_at) "
                                "VALUES ('company', 'next', now()) RETURNING id")).scalar()
    eng.dispose()
    assert new_id == 42


def test_the_app_role_has_dml_only(scratch):
    owner, app = scratch
    command.upgrade(alembic_config(owner), "head")
    for sql in ("CREATE TABLE sneaky (id int)", "UPDATE alembic_version SET version_num = 'x'",
                "DROP TABLE users", "TRUNCATE users"):
        with pytest.raises((ProgrammingError, DBAPIError)):
            _scalar(app, sql)
    assert _scalar(app, "SELECT version_num FROM alembic_version") == "0003_embed_run_vlm_page"
