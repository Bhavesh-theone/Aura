"""Mandates in the SOSPE §6.2 shape.

mandate gains side (sell|buy|raise|deploy|partner) and status (draft|active|paused|fulfilled|
expired|withdrawn). mandate_criteria {kind, attribute, value text, weight} becomes
{criterion_key, operator, value JSON, hardness, weight 0..1}.

Data mapping: kind -> hardness, attribute -> criterion_key, operator 'eq', the old text value
becomes a JSON string, weight is clamped into 0..1. Existing mandates become 'active' with a
side taken from their deal's transaction class. The T3 guard's SQL follows the column rename.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

SIDES = "'sell', 'buy', 'raise', 'deploy', 'partner'"
STATUSES = "'draft', 'active', 'paused', 'fulfilled', 'expired', 'withdrawn'"
OPERATORS = "'eq', 'in', 'gte', 'lte', 'between', 'not_in', 'contains'"
SIDE_FOR_CLASS = ("CASE (SELECT transaction_class FROM deals WHERE deals.id = mandate.deal_id) "
                  "WHEN 'MNA' THEN 'sell' WHEN 'JV' THEN 'partner' "
                  "WHEN 'ALLIANCE' THEN 'partner' ELSE 'raise' END")
OLD_T3, NEW_T3 = "c.kind = 'hard'", "c.hardness = 'hard'"


def _swap_t3(old: str, new: str) -> None:
    op.get_bind().execute(sa.text(
        "UPDATE stage_guard SET sql_text = replace(sql_text, :old, :new) "
        "WHERE guard_name = 'T3_hard_criterion'"), {"old": old, "new": new})


def upgrade() -> None:
    with op.batch_alter_table("mandate") as batch:
        batch.add_column(sa.Column("side", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=True))
    op.execute(f"UPDATE mandate SET side = {SIDE_FOR_CLASS}, status = 'active'")
    with op.batch_alter_table("mandate") as batch:
        batch.alter_column("side", existing_type=sa.String(length=16), nullable=False)
        batch.alter_column("status", existing_type=sa.String(length=16), nullable=False)
        batch.create_check_constraint("ck_side_valid", f"side IN ({SIDES})")
        batch.create_check_constraint("ck_status_valid", f"status IN ({STATUSES})")

    op.create_table(
        "mandate_criteria_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mandate_id", sa.Integer(), nullable=False),
        sa.Column("criterion_key", sa.String(length=100), nullable=False),
        sa.Column("operator", sa.String(length=16), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("hardness", sa.String(length=16), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.CheckConstraint("hardness IN ('hard', 'soft', 'preference')",
                           name="ck_hardness_valid"),
        sa.CheckConstraint(f"operator IN ({OPERATORS})", name="ck_operator_valid"),
        sa.CheckConstraint("hardness != 'soft' OR weight IS NOT NULL",
                           name="ck_soft_needs_weight"),
        sa.CheckConstraint("weight IS NULL OR (weight >= 0 AND weight <= 1)",
                           name="ck_weight_range"),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandate.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.execute("INSERT INTO mandate_criteria_new (id, mandate_id, criterion_key, operator, "
               "value, hardness, weight) SELECT id, mandate_id, attribute, 'eq', "
               "json_quote(value), kind, CASE WHEN weight IS NULL THEN NULL "
               "WHEN weight < 0 THEN 0 WHEN weight > 1 THEN 1 ELSE weight END "
               "FROM mandate_criteria")
    op.drop_index("ix_mandate_criteria_mandate_id", table_name="mandate_criteria")
    op.drop_table("mandate_criteria")
    op.rename_table("mandate_criteria_new", "mandate_criteria")
    op.create_index("ix_mandate_criteria_mandate_id", "mandate_criteria", ["mandate_id"])
    _swap_t3(OLD_T3, NEW_T3)


def downgrade() -> None:
    _swap_t3(NEW_T3, OLD_T3)
    op.create_table(
        "mandate_criteria_old",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("mandate_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("attribute", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=500), nullable=False),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.CheckConstraint("kind != 'soft' OR weight IS NOT NULL", name="ck_soft_needs_weight"),
        sa.CheckConstraint("kind IN ('hard', 'soft', 'preference')", name="ck_kind_valid"),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandate.id"]),
        sa.PrimaryKeyConstraint("id"))
    # A JSON string goes back as its text; lists and numbers keep their JSON text.
    op.execute("INSERT INTO mandate_criteria_old (id, mandate_id, kind, attribute, value, "
               "weight) SELECT id, mandate_id, hardness, criterion_key, "
               "substr(CASE WHEN json_type(value) = 'text' THEN json_extract(value, '$') "
               "ELSE value END, 1, 500), weight FROM mandate_criteria")
    op.drop_index("ix_mandate_criteria_mandate_id", table_name="mandate_criteria")
    op.drop_table("mandate_criteria")
    op.rename_table("mandate_criteria_old", "mandate_criteria")
    op.create_index("ix_mandate_criteria_mandate_id", "mandate_criteria", ["mandate_id"])
    with op.batch_alter_table("mandate") as batch:
        batch.drop_constraint("ck_status_valid", type_="check")
        batch.drop_constraint("ck_side_valid", type_="check")
        batch.drop_column("status")
        batch.drop_column("side")
