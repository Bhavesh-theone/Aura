"""Harness reliability: atomic segment claims, retries and dead letters, run lineage per
segment, and idempotent job submission.

segments gains claimed_by, claimed_at, attempts (default 0), not_before and last_error, and
its status may now be 'dead_letter'. agent_run gains segment_id. A new idempotency_key table
holds (key, username, request_hash, job_id, created_at), unique per key and user.

Downgrade turns dead-lettered segments into 'failed' (the old vocabulary's closest state)
and drops the new columns and table.

Revision ID: 0011_harness_reliability
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_harness_reliability"
down_revision = "0010"
branch_labels = None
depends_on = None

OLD_STATUSES = ["queued", "running", "awaiting_approval", "done", "failed"]
NEW_STATUSES = OLD_STATUSES + ["dead_letter"]


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    with op.batch_alter_table("segments") as batch:
        batch.drop_constraint("ck_status_valid", type_="check")
        batch.add_column(sa.Column("claimed_by", sa.String(128), nullable=True))
        batch.add_column(sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("attempts", sa.Integer(), nullable=False,
                                   server_default="0"))
        batch.add_column(sa.Column("not_before", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_error", sa.Text(), nullable=True))
        batch.create_check_constraint("ck_status_valid", f"status IN ({_in(NEW_STATUSES)})")

    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(sa.Column("segment_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_agent_run_segment_id", "segments", ["segment_id"], ["id"])
        batch.create_index("ix_agent_run_segment_id", ["segment_id"])

    op.create_table(
        "idempotency_key",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.UniqueConstraint("key", "username", name="uq_idempotency_key_user"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_key")

    with op.batch_alter_table("agent_run") as batch:
        batch.drop_index("ix_agent_run_segment_id")
        batch.drop_constraint("fk_agent_run_segment_id", type_="foreignkey")
        batch.drop_column("segment_id")

    with op.batch_alter_table("segments") as batch:
        batch.drop_constraint("ck_status_valid", type_="check")
    op.execute("UPDATE segments SET status = 'failed' WHERE status = 'dead_letter'")
    with op.batch_alter_table("segments") as batch:
        batch.drop_column("last_error")
        batch.drop_column("not_before")
        batch.drop_column("attempts")
        batch.drop_column("claimed_at")
        batch.drop_column("claimed_by")
        batch.create_check_constraint("ck_status_valid", f"status IN ({_in(OLD_STATUSES)})")
