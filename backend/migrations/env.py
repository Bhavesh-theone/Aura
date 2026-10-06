from alembic import context
from sqlalchemy import create_engine

from aura.config import get_settings
from aura.data.engine import Base
import aura.data.models.tables  # noqa: F401  (registers every table on Base.metadata)

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Tests and tools can override via config.set_main_option("sqlalchemy.url", ...).
    return config.get_main_option("sqlalchemy.url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Plain engine: foreign_keys stays OFF so SQLite batch table rebuilds can drop and
    # recreate parent tables.
    engine = create_engine(_url())
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
