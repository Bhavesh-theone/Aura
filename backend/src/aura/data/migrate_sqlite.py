"""Copy an Aura SQLite database (the pre-PostgreSQL backend/aura.db) into PostgreSQL.

    uv run python -m aura.data.migrate_sqlite --from aura.db
    uv run python -m aura.data.migrate_sqlite --from C:/tmp/copy.db \
        --to postgresql+psycopg://aura_owner:...@127.0.0.1:5433/aura_scratch

* The SQLite file is opened read-only and never changed: it stays as the backup.
* The target (default AURA_MIGRATION_DATABASE_URL, i.e. aura_owner on `aura`) is brought to
  the Alembic head first. It must be empty; --force empties it (TRUNCATE) first.
* Every row keeps its primary key; identity sequences then move past the highest id.
* audit_entries are copied value for value (prev_hash, row_hash, created_at, payload), and
  the chain is re-verified on PostgreSQL with the same compute_row_hash the app uses. The
  copy is refused (rolled back) if a single row no longer hashes to its stored row_hash.
* The audit anchor file of the source is copied to the target's anchor path when the two
  differ (they are the same file for backend/aura.db -> the `aura` database).
* Stage-guard SQL is re-synced to its PostgreSQL form (seed_reference), since the copied
  rows still hold the SQLite dialect (`is_executed = 1`, json_array_length).
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (BigInteger, Boolean, DateTime, Integer, create_engine, insert,
                        make_url, null, select, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from aura.config import BACKEND_DIR, get_settings
from aura.core.domain.audit import GENESIS_HASH, AuditEntry, compute_row_hash
from aura.data.engine import Base
from aura.data.models import tables  # noqa: F401  (registers every table)
from aura.data.models.tables import AuditRow, InrAmount

BATCH = 1000


def _convert(column, value):
    """One SQLite value -> what the PostgreSQL column takes."""
    if value is None:
        return null() if isinstance(column.type, JSONB) else None
    kind = column.type
    if isinstance(kind, JSONB):
        return json.loads(value) if isinstance(value, (str, bytes)) else value
    if isinstance(kind, DateTime):
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, timezone.utc)
        parsed = datetime.fromisoformat(str(value))
        # SQLite kept UTC wall-clock time without an offset (the app only writes UTC).
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(kind, Boolean):
        return bool(int(value)) if isinstance(value, (int, str)) else bool(value)
    if isinstance(kind, InrAmount):
        return Decimal(str(value))
    if isinstance(kind, (Integer, BigInteger)):
        return int(value)
    return value


def _source_tables(src: sqlite3.Connection) -> dict[str, list[str]]:
    names = [r[0] for r in src.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    return {n: [c[1] for c in src.execute(f'PRAGMA table_info("{n}")')] for n in names}


def _target_rows(conn, table: str) -> int:
    return conn.scalar(text(f'SELECT count(*) FROM "{table}"'))


def default_source_anchor(source: Path) -> Path:
    """Where the SQLite-era app kept the anchor for this file."""
    if source.resolve() == (BACKEND_DIR / "aura.db").resolve():
        return BACKEND_DIR / "data" / "audit_anchor.json"
    return Path(str(source) + ".audit_anchor.json")


def target_anchor(url: str) -> Path:
    database = make_url(url).database or "aura"
    name = "audit_anchor.json" if database == "aura" else f"audit_anchor.{database}.json"
    return BACKEND_DIR / "data" / name


def verify_copied_chain(session: Session) -> tuple[int, int | None]:
    """(rows checked, first broken id or None), recomputed from the PostgreSQL rows."""
    prev, n = GENESIS_HASH, 0
    for row in session.scalars(select(AuditRow).order_by(AuditRow.id)):
        entry = AuditEntry(id=row.id, job_id=row.job_id, actor=row.actor, action=row.action,
                           payload=row.payload or {}, created_at=row.created_at,
                           deal_id=row.deal_id)
        if row.prev_hash != prev or row.row_hash != compute_row_hash(prev, entry):
            return n, row.id
        prev, n = row.row_hash, n + 1
    return n, None


def migrate(source: Path, target_url: str, force: bool = False,
            anchor_from: Path | None = None, out=print) -> dict[str, tuple[int, int]]:
    """Copy every table; returns {table: (sqlite rows, postgres rows)}."""
    if not source.exists():
        raise SystemExit(f"{source} does not exist")
    from alembic import command
    from aura.data.seed import alembic_config
    command.upgrade(alembic_config(target_url), "head")

    src = sqlite3.connect(f"file:{source.resolve().as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    have = _source_tables(src)
    engine = create_engine(target_url, connect_args={"options": "-c timezone=UTC"})
    targets = [t for t in Base.metadata.sorted_tables]
    counts: dict[str, tuple[int, int]] = {}
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('aura.viewer', :v, true)"), {"v": ":system"})
            filled = {t.name: n for t in targets if (n := _target_rows(conn, t.name))}
            if filled and not force:
                raise SystemExit(f"target is not empty ({filled}); use --force to replace it")
            if filled:
                names = ", ".join(f'"{t.name}"' for t in targets)
                conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
                out(f"--force: emptied {len(filled)} non-empty table(s)")
            for table in targets:
                if table.name not in have:
                    counts[table.name] = (0, 0)
                    continue
                cols = [c for c in table.columns if c.name in have[table.name]
                        and c.computed is None]
                skipped = set(have[table.name]) - {c.name for c in table.columns}
                if skipped:
                    out(f"  {table.name}: SQLite-only column(s) not copied: {sorted(skipped)}")
                names = ", ".join(f'"{c.name}"' for c in cols)
                rows = src.execute(f'SELECT {names} FROM "{table.name}"').fetchall()
                batch = [{c.name: _convert(c, r[c.name]) for c in cols} for r in rows]
                for i in range(0, len(batch), BATCH):
                    conn.execute(insert(table), batch[i:i + BATCH])
                for c in table.columns:
                    if c.identity is not None:
                        conn.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', "
                            f"'{c.name}'), (SELECT coalesce(max(\"{c.name}\"), 0) + 1 "
                            f"FROM \"{table.name}\"), false)"))
                counts[table.name] = (len(rows), _target_rows(conn, table.name))
            extra = sorted(set(have) - {t.name for t in targets} - {"alembic_version"})
            if extra:
                out(f"SQLite tables with no PostgreSQL counterpart (not copied): {extra}")
            with Session(bind=conn) as s:
                checked, broken = verify_copied_chain(s)
            if broken is not None:
                raise SystemExit(f"audit chain does not verify on PostgreSQL at entry id "
                                 f"{broken} ({checked} rows fine before it); nothing copied")
            out(f"audit chain verified on PostgreSQL: {checked} entries hash identically")
            mismatched = {t: c for t, c in counts.items() if c[0] != c[1]}
            if mismatched:
                raise SystemExit(f"row counts differ after copy: {mismatched}; nothing copied")
    finally:
        src.close()

    # Stage-guard SQL in its PostgreSQL form (the copied rows hold the SQLite dialect).
    from aura.data.seed import seed_reference
    with Session(engine) as s:
        seed_reference(s)
    engine.dispose()

    anchor_src = anchor_from or default_source_anchor(source)
    anchor_dst = target_anchor(target_url)
    if anchor_src.exists() and anchor_src.resolve() != anchor_dst.resolve():
        shutil.copyfile(anchor_src, anchor_dst)
        out(f"audit anchor copied: {anchor_src} -> {anchor_dst}")
    elif anchor_src.exists():
        out(f"audit anchor kept in place: {anchor_dst}")
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from", dest="source", required=True, help="SQLite file to copy")
    ap.add_argument("--to", dest="target", help="PostgreSQL URL of the schema owner "
                    "(default: AURA_MIGRATION_DATABASE_URL)")
    ap.add_argument("--force", action="store_true", help="empty a non-empty target first")
    ap.add_argument("--anchor-from", type=Path, help="audit anchor of the source "
                    "(default: the one the SQLite app used for that file)")
    args = ap.parse_args(argv)
    target = args.target or get_settings().migration_database_url
    if not target:
        raise SystemExit("set AURA_MIGRATION_DATABASE_URL or pass --to")
    # Relative paths work from the repository root (backend/aura.db) or from backend/.
    source = next((p for p in (Path(args.source), BACKEND_DIR / args.source,
                               BACKEND_DIR.parent / args.source) if p.exists()),
                  Path(args.source))
    counts = migrate(source, target, args.force, args.anchor_from)
    width = max(len(t) for t in counts)
    print(f"{'table'.ljust(width)}  sqlite  postgres")
    for table, (a, b) in counts.items():
        print(f"{table.ljust(width)}  {a:6d}  {b:8d}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
