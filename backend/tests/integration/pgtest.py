"""The test database: aura_test, created and migrated once per run, emptied per test.

ensure_database() drops and recreates aura_test as aura_owner and runs the Alembic baseline
on it (so the tests run against the real migration, policies and grants included).
fresh_engine() empties every table (TRUNCATE ... RESTART IDENTITY, as the owner) and returns
the app's engine, which connects as aura_app.
"""
import gc
from functools import cache

from alembic import command
from sqlalchemy import create_engine, make_url, text

from aura.config import get_settings
from aura.data.engine import engine as app_engine


def owner_url(database: str | None = None) -> str:
    url = make_url(get_settings().migration_database_url)
    if database:
        url = url.set(database=database)
    return url.render_as_string(hide_password=False)


@cache
def owner_engine():
    ensure_database()
    return create_engine(owner_url(), connect_args={"options": "-c timezone=UTC"})


@cache
def ensure_database() -> None:
    db = make_url(get_settings().migration_database_url).database
    assert db and db != "aura", "tests must never run against the aura database"
    admin = create_engine(owner_url("postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db}"'))
        # A session a test leaked mid-transaction would hold its locks for the rest of the
        # run and block every later TRUNCATE: the server ends such sessions after 3 s.
        conn.execute(text(f'ALTER DATABASE "{db}" SET idle_in_transaction_session_timeout '
                          "= '3s'"))
    admin.dispose()
    from aura.data.seed import alembic_config
    command.upgrade(alembic_config(owner_url()), "head")


@cache
def _dirty_query() -> str:
    """One query naming every table that has rows or whose id sequence has moved: only
    those need a TRUNCATE (truncating all 39 tables every test costs ~0.3 s)."""
    with owner_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT c.relname, max('public.' || s.relname) FROM pg_class c "
            "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
            "LEFT JOIN pg_depend d ON d.refobjid = c.oid "
            "  AND d.classid = 'pg_class'::regclass AND d.deptype IN ('a', 'i') "
            "LEFT JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S' "
            "WHERE c.relkind = 'r' AND c.relname <> 'alembic_version' "
            "GROUP BY c.relname ORDER BY 1")).all()
    parts = []
    for name, seq in rows:
        moved = (f" OR (SELECT last_value IS NOT NULL FROM pg_sequences "
                 f"WHERE schemaname || '.' || sequencename = '{seq}')") if seq else ""
        parts.append(f"SELECT '{name}' WHERE EXISTS (SELECT 1 FROM \"{name}\"){moved}")
    return " UNION ALL ".join(parts)


def truncate_all() -> None:
    gc.collect()  # a session a test forgot to close gives its connection (and locks) back
    with owner_engine().begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))  # fail, never hang
        dirty = conn.scalars(text(_dirty_query())).all()
        if dirty:
            names = ", ".join(f'"{n}"' for n in dirty)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


def fresh_engine():
    """An empty, migrated aura_test; the engine the app uses (aura_app)."""
    truncate_all()
    return app_engine
