"""Guard evaluations link to the history row they let through; regulatory flags and
compliance sign-off.

Evaluations already recorded for moves that succeeded are linked best-effort: the first
history row of the same deal and the same from/to stage that is not earlier than the
evaluation.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stage_guard_evaluation") as batch:
        batch.add_column(sa.Column("history_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_evaluation_history", "deal_stage_history",
                                 ["history_id"], ["id"])
        batch.create_index("ix_stage_guard_evaluation_history_id", ["history_id"])
    op.execute(
        "UPDATE stage_guard_evaluation SET history_id = ("
        " SELECT h.id FROM deal_stage_history h JOIN stage_guard g"
        "  ON g.id = stage_guard_evaluation.guard_id"
        " WHERE h.deal_id = stage_guard_evaluation.deal_id"
        "  AND h.from_stage = g.from_stage AND h.to_stage = g.to_stage"
        "  AND h.entered_at >= stage_guard_evaluation.attempted_at"
        " ORDER BY h.entered_at, h.id LIMIT 1)"
        " WHERE result = 1 OR overridden_by IS NOT NULL")

    op.add_column("deals", sa.Column("regulatory_flags", sa.JSON(), server_default="[]",
                                     nullable=False))
    op.create_table(
        "deal_signoff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("signed_by", sa.String(length=64), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_deal_signoff_deal_id", "deal_signoff", ["deal_id"])


def downgrade() -> None:
    op.drop_table("deal_signoff")
    with op.batch_alter_table("deals") as batch:
        batch.drop_column("regulatory_flags")
    with op.batch_alter_table("stage_guard_evaluation") as batch:
        batch.drop_index("ix_stage_guard_evaluation_history_id")
        batch.drop_constraint("fk_evaluation_history", type_="foreignkey")
        batch.drop_column("history_id")