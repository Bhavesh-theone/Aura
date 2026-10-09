"""Roles: dealmaker / analyst / compliance beside admin, and an active flag on users.

Existing 'member' users become analysts; the existing admin user bhavesh (who ran the
deals) becomes a dealmaker. Other admins stay admins.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

OLD_ROLES = "'admin', 'member'"
NEW_ROLES = "'admin', 'dealmaker', 'analyst', 'compliance'"


def upgrade() -> None:
    op.add_column("users", sa.Column("active", sa.Boolean(), server_default="1",
                                     nullable=False))
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_role_valid", type_="check")
    op.execute("UPDATE users SET role = 'analyst' WHERE role = 'member'")
    op.execute("UPDATE users SET role = 'dealmaker' WHERE username = 'bhavesh' "
               "AND role = 'admin'")
    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint("ck_role_valid", f"role IN ({NEW_ROLES})")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_role_valid", type_="check")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'dealmaker'")
    op.execute("UPDATE users SET role = 'member' WHERE role IN ('analyst', 'compliance')")
    with op.batch_alter_table("users") as batch:
        batch.create_check_constraint("ck_role_valid", f"role IN ({OLD_ROLES})")
        batch.drop_column("active")