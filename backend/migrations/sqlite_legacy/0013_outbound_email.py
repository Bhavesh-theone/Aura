"""Outbound email (Gmail, drafts first).

- party_contact: a party's email contacts (primary, verified by a dealmaker).
- suppression: the do-not-contact list (an address or a whole domain).
- outbound_message: one row per approved draft_email handoff that reached the outbound step
  (queued, drafted, sent, blocked or failed); unique per handoff, which is what makes a
  retried or resumed segment unable to send twice.

Downgrade drops the three tables.

Revision ID: 0013_outbound_email
Revises: 0012_harness_eval_obs
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_outbound_email"
down_revision = "0012_harness_eval_obs"
branch_labels = None
depends_on = None

EMAIL_FORMAT_CHECK = ("email = lower(email) AND email LIKE '%_@_%._%' "
                      "AND email NOT LIKE '% %' AND email NOT LIKE '%@%@%'")


def upgrade() -> None:
    op.create_table(
        "party_contact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("party_id", "email", name="uq_party_contact_email"),
        sa.CheckConstraint(EMAIL_FORMAT_CHECK, name="ck_party_contact_email"),
    )
    op.create_index("ix_party_contact_party_id", "party_contact", ["party_id"])

    op.create_table(
        "suppression",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("value", sa.String(254), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "value", name="uq_suppression_kind_value"),
        sa.CheckConstraint("kind IN ('email', 'domain')", name="ck_kind_valid"),
    )

    op.create_table(
        "outbound_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("handoff_id", sa.Integer(), sa.ForeignKey("handoff.id"), nullable=False,
                  unique=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=True),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("party.id"), nullable=True),
        sa.Column("to_email", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gmail_id", sa.String(128), nullable=True),
        sa.Column("gmail_thread_id", sa.String(128), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(32), nullable=True),
        sa.CheckConstraint("mode IN ('off', 'gmail_draft', 'gmail_send')",
                           name="ck_mode_valid"),
        sa.CheckConstraint("status IN ('queued', 'drafted', 'sent', 'blocked', 'failed')",
                           name="ck_status_valid"),
    )
    op.create_index("ix_outbound_message_deal_id", "outbound_message", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_outbound_message_deal_id", "outbound_message")
    op.drop_table("outbound_message")
    op.drop_table("suppression")
    op.drop_index("ix_party_contact_party_id", "party_contact")
    op.drop_table("party_contact")
