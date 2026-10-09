"""Baseline: the schema Aura had before the deal spine (users, deals, jobs, ...).

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_role_valid"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("owner", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["owner"], ["users.username"], onupdate="CASCADE"),
    )
    op.create_index("ix_deals_external_id", "deals", ["external_id"], unique=True)

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("deal_id", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'running', 'awaiting_approval', "
                           "'complete', 'failed', 'rejected')", name="ck_status_valid"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])

    op.create_table(
        "segments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("context_in", sa.JSON(), nullable=False),
        sa.Column("context_out", sa.JSON()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "seq", name="uq_segment_job_seq"),
        sa.CheckConstraint("status IN ('queued', 'running', 'awaiting_approval', 'done', "
                           "'failed')", name="ck_status_valid"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )
    op.create_index("ix_segments_job_id", "segments", ["job_id"])
    op.create_index("ix_segments_status", "segments", ["status"])

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer()),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
    )
    op.create_index("ix_audit_entries_job_id", "audit_entries", ["job_id"])
    op.create_index("ix_audit_entries_action", "audit_entries", ["action"])

    op.create_table(
        "approvals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("segment_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("proposed_action", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.Integer()),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.CheckConstraint("category IN ('money', 'legal', 'outbound', 'internal_read', "
                           "'internal_write', 'unknown')", name="ck_category_valid"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected')",
                           name="ck_status_valid"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]),
    )
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_index("ix_approvals_segment_id", "approvals", ["segment_id"])


def downgrade() -> None:
    for table in ("approvals", "audit_entries", "segments", "jobs", "deals", "users"):
        op.drop_table(table)
