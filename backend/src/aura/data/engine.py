from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from aura.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    url = url or get_settings().database_url
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            # One shared connection, else every thread would see an empty database.
            kwargs["poolclass"] = StaticPool
    eng = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        def on_connect(conn, _):
            # SQLite ignores FOREIGN KEY clauses unless enabled per connection.
            conn.execute("PRAGMA foreign_keys=ON")
            # Take transaction control from pysqlite (which would not BEGIN before SAVEPOINT
            # or DDL); SQLAlchemy emits BEGIN below. Needed for unit-of-work rollbacks and
            # the savepoints repositories use.
            conn.isolation_level = None

        event.listen(eng, "connect", on_connect)
        event.listen(eng, "begin", lambda conn: conn.exec_driver_sql("BEGIN"))
    return eng


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)
