"""Point the whole test run at the aura_test database before any aura module builds its
engine. aura_test lives on the same PostgreSQL as aura (scripts/db.ps1); it is dropped,
recreated and migrated once per run by tests/integration/pgtest.py, as aura_owner. The app
code under test connects as aura_app, exactly as in production, so RLS applies.

Unit tests never connect: they only import modules (engine creation is lazy).
"""
import os

from sqlalchemy import make_url

from aura.config import Settings

# AURA_TEST_DATABASE lets two runs (two worktrees, two agents) use separate databases.
TEST_DB = os.environ.get("AURA_TEST_DATABASE", "aura_test")
_base = Settings()
_owner = _base.migration_database_url or \
    "postgresql+psycopg://aura_owner:aura_owner_dev@127.0.0.1:5433/aura"

os.environ["AURA_DATABASE_URL"] = make_url(_base.database_url).set(
    database=TEST_DB).render_as_string(hide_password=False)
os.environ["AURA_MIGRATION_DATABASE_URL"] = make_url(_owner).set(
    database=TEST_DB).render_as_string(hide_password=False)
