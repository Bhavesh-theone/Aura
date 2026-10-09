"""Engine and sessions: PostgreSQL 16 through psycopg 3, one QueuePool per process.

Every transaction starts by telling PostgreSQL who it acts for (`aura.viewer`, see
aura.data.walls): the row-level security policies on deal-scoped tables read that setting.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from aura.config import get_settings

VIEWER_KEY = "aura_viewer"
_SET_VIEWER = text("SELECT set_config('aura.viewer', :v, true)")


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None, **kwargs):
    url = url or get_settings().database_url
    if not url.startswith("postgresql"):
        raise ValueError("Aura runs on PostgreSQL only (AURA_DATABASE_URL=postgresql+psycopg://"
                         "...). An old SQLite file is imported with aura.data.migrate_sqlite.")
    # timezone=UTC: TIMESTAMPTZ values come back as aware UTC datetimes whatever the server's
    # zone is (the audit hash normalises to UTC, so this is about readable output).
    kwargs.setdefault("connect_args", {}).setdefault("options", "-c timezone=UTC")
    kwargs.setdefault("pool_pre_ping", True)
    kwargs.setdefault("pool_size", 10)
    kwargs.setdefault("max_overflow", 10)
    return create_engine(url, **kwargs)


@event.listens_for(Session, "after_begin")
def _apply_viewer(session: Session, _transaction, connection) -> None:
    """SET LOCAL the session's viewer at the start of every transaction (a fresh
    transaction otherwise starts with no viewer, and RLS then shows no deal rows)."""
    connection.execute(_SET_VIEWER, {"v": session.info.get(VIEWER_KEY, "")})


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
