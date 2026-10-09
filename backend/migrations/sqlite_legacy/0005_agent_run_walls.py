"""Model run lineage, deal walls, and the job submitter (PRD F8, F10).

Every existing deal gets a wall whose first member is the deal's owner.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("archetype", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("model_version", sa.String(length=128), nullable=False),
        sa.Column("prompt_template_id", sa.String(length=128), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("input_digest", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("cost_inr", sa.Float(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_run_job_id", "agent_run", ["job_id"])
    op.create_index("ix_agent_run_deal_id", "agent_run", ["deal_id"])

    op.create_table(
        "wall",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deal_id"))
    op.create_table(
        "wall_member",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wall_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["wall_id"], ["wall.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_wall_member_wall_id", "wall_member", ["wall_id"])
    op.create_index("ix_wall_member_user_id", "wall_member", ["user_id"])

    op.add_column("jobs", sa.Column("created_by", sa.String(length=64), nullable=True))

    # Existing deals: one wall each, the owner as its first member.
    conn = op.get_bind()
    conn.execute(sa.text(
        "INSERT INTO wall (deal_id, name) SELECT id, external_id || ' wall' FROM deals"))
    conn.execute(sa.text(
        "INSERT INTO wall_member (wall_id, user_id) SELECT w.id, u.id FROM wall w "
        "JOIN deals d ON d.id = w.deal_id JOIN users u ON u.username = d.owner"))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("created_by")
    for table in ("wall_member", "wall", "agent_run"):
        op.drop_table(table)
