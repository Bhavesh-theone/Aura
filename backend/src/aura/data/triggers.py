"""SQLite triggers that make tables append-only. Shared by create_all and migrations."""
APPEND_ONLY_TABLES = ("audit_entries", "deal_stage_history", "doc_access_log")


def trigger_names(table: str) -> list[str]:
    return [f"trg_{table}_no_update", f"trg_{table}_no_delete"]


def append_only_ddl(table: str) -> list[str]:
    return [
        f"CREATE TRIGGER trg_{table}_{op.lower()} BEFORE {kind} ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"
        for op, kind in (("no_update", "UPDATE"), ("no_delete", "DELETE"))
    ]
