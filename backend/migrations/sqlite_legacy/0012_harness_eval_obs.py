"""Harness evaluation, security and observability.

- eval_run and eval_case_result: golden-set evaluations (python -m aura.evals.run).
- capability_autonomy: autonomy level per capability (2 autonomous, 1 supervised, 0 off),
  seeded at level 2 for classify_document, extract_financials and draft_email.
- trace_span: locally stored spans; jobs and agent_run gain trace_id and span_id.
- deal_note: internal notes written by the deals MCP tool add_internal_note.
- handoff.trigger may now be 'untrusted_content' (prompt-injection screening).

Downgrade turns 'untrusted_content' handoffs into 'policy_required' (the old vocabulary's
closest trigger) and drops the new columns and tables.

Revision ID: 0012_harness_eval_obs
Revises: 0011_harness_reliability
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_harness_eval_obs"
down_revision = "0011_harness_reliability"
branch_labels = None
depends_on = None

OLD_TRIGGERS = ["confidence_below_threshold", "materiality_gate", "policy_required",
                "explicit_request", "human_correction"]
NEW_TRIGGERS = OLD_TRIGGERS + ["untrusted_content"]
CAPABILITIES = ["classify_document", "extract_financials", "draft_email"]


def _in(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    with op.batch_alter_table("handoff") as batch:
        batch.drop_constraint("ck_trigger_valid", type_="check")
        batch.create_check_constraint("ck_trigger_valid", f"trigger IN ({_in(NEW_TRIGGERS)})")

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("span_id", sa.String(16), nullable=True))
        batch.create_index("ix_jobs_trace_id", ["trace_id"])

    with op.batch_alter_table("agent_run") as batch:
        batch.add_column(sa.Column("trace_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("span_id", sa.String(16), nullable=True))
        batch.create_index("ix_agent_run_trace_id", ["trace_id"])

    op.create_table(
        "eval_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("orchestrator", sa.String(16), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("golden_sha256", sa.String(64), nullable=False),
        sa.Column("n_cases", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
    )
    op.create_index("ix_eval_run_capability", "eval_run", ["capability"])

    op.create_table(
        "eval_case_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("eval_run_id", sa.Integer(), sa.ForeignKey("eval_run.id"), nullable=False),
        sa.Column("case_id", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("expected", sa.JSON(), nullable=False),
        sa.Column("actual", sa.JSON(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("agent_run.id"), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_eval_case_result_eval_run_id", "eval_case_result", ["eval_run_id"])

    autonomy = op.create_table(
        "capability_autonomy",
        sa.Column("capability", sa.String(64), primary_key=True),
        sa.Column("level", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("pinned_model", sa.String(128), nullable=True),
        sa.Column("demoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("level BETWEEN 0 AND 2", name="ck_level_valid"),
    )
    op.bulk_insert(autonomy, [{"capability": c, "level": 2, "updated_by": "migration"}
                              for c in CAPABILITIES])

    op.create_table(
        "trace_span",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trace_id", sa.String(32), nullable=False),
        sa.Column("span_id", sa.String(16), nullable=False),
        sa.Column("parent_span_id", sa.String(16), nullable=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_trace_span_trace_id", "trace_span", ["trace_id"])
    op.create_index("ix_trace_span_deal_id", "trace_span", ["deal_id"])

    op.create_table(
        "deal_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("deal_id", sa.Integer(), sa.ForeignKey("deals.id"), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("author", sa.String(64), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deal_note_deal_id", "deal_note", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_deal_note_deal_id", "deal_note")
    op.drop_table("deal_note")
    op.drop_index("ix_trace_span_deal_id", "trace_span")
    op.drop_index("ix_trace_span_trace_id", "trace_span")
    op.drop_table("trace_span")
    op.drop_table("capability_autonomy")
    op.drop_index("ix_eval_case_result_eval_run_id", "eval_case_result")
    op.drop_table("eval_case_result")
    op.drop_index("ix_eval_run_capability", "eval_run")
    op.drop_table("eval_run")

    with op.batch_alter_table("agent_run") as batch:
        batch.drop_index("ix_agent_run_trace_id")
        batch.drop_column("span_id")
        batch.drop_column("trace_id")

    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_trace_id")
        batch.drop_column("span_id")
        batch.drop_column("trace_id")

    with op.batch_alter_table("handoff") as batch:
        batch.drop_constraint("ck_trigger_valid", type_="check")
    op.execute("UPDATE handoff SET trigger = 'policy_required' "
               "WHERE trigger = 'untrusted_content'")
    with op.batch_alter_table("handoff") as batch:
        batch.create_check_constraint("ck_trigger_valid", f"trigger IN ({_in(OLD_TRIGGERS)})")
