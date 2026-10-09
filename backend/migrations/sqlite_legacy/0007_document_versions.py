"""Document versions and the executed flag.

document.version becomes document.current_version, and every version has a doc_version row
(existing documents get one row for the version they hold). is_executed marks a signed copy.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document") as batch:
        batch.alter_column("version", new_column_name="current_version")
        batch.add_column(sa.Column("is_executed", sa.Boolean(), server_default="0",
                                   nullable=False))
    op.create_table(
        "doc_version",
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=64), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["document.id"]),
        sa.PrimaryKeyConstraint("document_id", "version"))
    op.execute("INSERT INTO doc_version (document_id, version, sha256, byte_size, "
               "uploaded_by, uploaded_at) SELECT id, current_version, sha256, byte_size, "
               "uploaded_by, uploaded_at FROM document")


def downgrade() -> None:
    op.drop_table("doc_version")
    with op.batch_alter_table("document") as batch:
        batch.drop_column("is_executed")
        batch.alter_column("current_version", new_column_name="version")