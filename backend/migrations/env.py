"""Alembic environment: PostgreSQL only, run as the schema owner (aura_owner).

The URL is, in order: config.set_main_option("sqlalchemy.url", ...) (tests, tools), then
AURA_MIGRATION_DATABASE_URL. The app's own URL (aura_app) cannot run DDL by design.
The SQLite-era chain lives in migrations/sqlite_legacy/ for reference and is never run.
"""
from alembic import context
from sqlalchemy import create_engine

import aura.data.models.tables  # noqa: F401  (registers every table on Base.metadata)
from aura.config import get_settings
from aura.data.engine import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url") or get_settings().migration_database_url
    if not url:
        raise SystemExit("Set AURA_MIGRATION_DATABASE_URL (the aura_owner connection) to run "
                         "migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), connect_args={"options": "-c timezone=UTC"})
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
