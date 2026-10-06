"""Extractions, findings, checklist templates, and database-level identifier formats.

checklist_item_template gains template_id -> checklist_template; the existing item rows are
grouped under one base template (items for every class) and one subclass template per
transaction class they were keyed by. party_identifier gets a GLOB CHECK per scheme.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CLASSES = "'DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE'"
_U, _D, _A = "[A-Z]", "[0-9]", "[0-9A-Z]"
IDENTIFIER_FORMAT = " OR ".join([
    f"(scheme = 'PAN' AND value GLOB '{_U * 5}{_D * 4}{_U}')",
    f"(scheme = 'DIN' AND value GLOB '{_D * 8}')",
    f"(scheme = 'GSTIN' AND value GLOB '{_D * 2}{_U * 5}{_D * 4}{_U}{_A * 3}')",
    f"(scheme = 'CIN' AND value GLOB '[LU]{_D * 5}{_U * 2}{_D * 4}{_U * 3}{_D * 6}')",
    f"(scheme = 'LLPIN' AND value GLOB '{_U * 3}-{_D * 4}')",
])


def upgrade() -> None:
    # Check first, change nothing yet: SQLite cannot roll a half-applied migration back.
    bad = op.get_bind().execute(sa.text(
        f"SELECT id, scheme, value FROM party_identifier WHERE NOT ({IDENTIFIER_FORMAT})")
    ).fetchall()
    if bad:
        raise RuntimeError("malformed identifier(s) must be fixed before upgrading: "
                           + ", ".join(f"#{r[0]} {r[1]} {r[2]!r}" for r in bad))
    op.create_table(
        "extraction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_name", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("feeds_valuation", sa.Boolean(), nullable=False),
        sa.Column("human_verified_by", sa.String(length=64), nullable=True),
        sa.Column("human_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_run_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("NOT feeds_valuation OR confidence >= 0.95 OR "
                           "human_verified_by IS NOT NULL",
                           name="ck_extraction_valuation_gate"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1",
                           name="ck_extraction_confidence_range"),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.ForeignKeyConstraint(["model_run_id"], ["agent_run.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_extraction_document_id", "extraction", ["document_id"])

    op.create_table(
        "finding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diligence_item_id", sa.Integer(), nullable=False),
        sa.Column("finding_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantified_impact_inr", sa.BigInteger(), nullable=True),
        sa.Column("affects_valuation", sa.Boolean(), nullable=False),
        sa.Column("raised_by", sa.String(length=64), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("finding_type IN ('red_flag', 'qualification', 'adjustment', "
                           "'observation')", name="ck_finding_type_valid"),
        sa.CheckConstraint("NOT affects_valuation OR quantified_impact_inr IS NOT NULL",
                           name="ck_finding_impact_required"),
        sa.ForeignKeyConstraint(["diligence_item_id"], ["diligence_item.id"]),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_finding_diligence_item_id", "finding", ["diligence_item_id"])

    op.create_table(
        "checklist_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_class", sa.String(length=16), nullable=True),
        sa.Column("layer", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.CheckConstraint(f"transaction_class IN ({CLASSES})",
                           name="ck_transaction_class_valid"),
        sa.CheckConstraint("layer IN ('base', 'subclass', 'vertical', 'jurisdiction')",
                           name="ck_layer_valid"),
        sa.PrimaryKeyConstraint("id"))

    with op.batch_alter_table("checklist_item_template") as batch:
        batch.add_column(sa.Column("template_id", sa.Integer(), nullable=True))
    conn = op.get_bind()
    classes = [r[0] for r in conn.execute(sa.text(
        "SELECT DISTINCT transaction_class FROM checklist_item_template"))]
    for cls in classes:
        name = ("Base diligence checklist" if cls is None
                else f"{cls.title()} diligence checklist")
        conn.execute(sa.text(
            "INSERT INTO checklist_template (transaction_class, layer, version, name) "
            "VALUES (:c, :l, 1, :n)"),
            {"c": cls, "l": "base" if cls is None else "subclass", "n": name})
        tid = conn.execute(sa.text("SELECT MAX(id) FROM checklist_template")).scalar()
        conn.execute(sa.text(
            "UPDATE checklist_item_template SET template_id = :t WHERE "
            + ("transaction_class IS NULL" if cls is None else "transaction_class = :c")),
            {"t": tid} if cls is None else {"t": tid, "c": cls})
    with op.batch_alter_table("checklist_item_template") as batch:
        batch.alter_column("template_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key("fk_item_template_template", "checklist_template",
                                 ["template_id"], ["id"])
        batch.create_index("ix_checklist_item_template_template_id", ["template_id"])

    with op.batch_alter_table("party_identifier") as batch:
        batch.create_check_constraint("ck_identifier_format", IDENTIFIER_FORMAT)


def downgrade() -> None:
    with op.batch_alter_table("party_identifier") as batch:
        batch.drop_constraint("ck_identifier_format", type_="check")
    with op.batch_alter_table("checklist_item_template") as batch:
        batch.drop_index("ix_checklist_item_template_template_id")
        batch.drop_constraint("fk_item_template_template", type_="foreignkey")
        batch.drop_column("template_id")
    op.drop_table("checklist_template")
    op.drop_table("finding")
    op.drop_table("extraction")