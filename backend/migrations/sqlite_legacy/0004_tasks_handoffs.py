"""Tasks and handoffs replace approvals (PRD F7).

Existing approvals become a task plus a bot-to-human handoff each, then the table is dropped.

Revision ID: 0004
Revises: 0003
"""
import json
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

ASSIGNMENT = "'bot_auto', 'bot_supervised', 'human_required'"
TASK_STATUS = "'queued', 'assigned', 'in_progress', 'blocked', 'review', 'done', 'cancelled'"
DIRECTION = "'bot_to_human', 'human_to_bot'"
TRIGGER = ("'confidence_below_threshold', 'materiality_gate', 'policy_required', "
           "'explicit_request', 'human_correction'")
HANDOFF_STATUS = "'open', 'resolved', 'escalated'"

# Lightweight table handles so SQLAlchemy applies datetime and JSON bind processing.
task_t = sa.table(
    "task", sa.column("deal_id", sa.Integer), sa.column("job_id", sa.Integer),
    sa.column("task_type", sa.String), sa.column("assignment_mode", sa.String),
    sa.column("status", sa.String), sa.column("materiality_inr", sa.BigInteger),
    sa.column("created_at", sa.DateTime(timezone=True)))
handoff_t = sa.table(
    "handoff", sa.column("task_id", sa.Integer), sa.column("deal_id", sa.Integer),
    sa.column("direction", sa.String), sa.column("trigger", sa.String),
    sa.column("context_package", sa.JSON), sa.column("directive", sa.JSON),
    sa.column("status", sa.String), sa.column("auto_escalate_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)), sa.column("resolved_by", sa.String),
    sa.column("resolved_at", sa.DateTime(timezone=True)))
approval_t = sa.table(
    "approvals", sa.column("segment_id", sa.Integer), sa.column("category", sa.String),
    sa.column("proposed_action", sa.JSON), sa.column("status", sa.String),
    sa.column("decided_by", sa.Integer), sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)))


def _dt(value) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _package(action: dict, created: datetime) -> dict:
    """A valid bot-to-human context package for a legacy approval."""
    tool = action.get("tool") or "gated_action"
    summary = action.get("summary") or f"Run {tool}"
    escalate_at = (created + timedelta(hours=24)).isoformat()
    unknown = action.get("category") == "unknown"
    return {
        "what_happened": [f"The agent proposed the action '{tool}'.", summary,
                          "Migrated from the approvals table."],
        "evidence": [{"type": "proposed_action", "tool": tool,
                      "category": action.get("category"),
                      "arguments": action.get("arguments") or {}}],
        "decision_required": {
            "question": f"Decide on the proposed action: {summary}"[:300],
            "options": [
                {"id": "approve", "label": "Approve", "reversible": False,
                 "consequence": "The job continues with this action."},
                {"id": "reject", "label": "Reject", "reversible": True,
                 "consequence": "The job ends here and the proposed action is discarded."}],
            "recommendation": "reject" if unknown else "approve",
            "confidence": 0.5},
        "if_you_do_nothing": {
            "consequence": f"Job stays paused; escalates to admin at {escalate_at}.",
            "auto_escalate_at": escalate_at, "escalates_to_role": "admin"},
        "proposed_action": {"tool": tool, "category": action.get("category"),
                            "arguments": action.get("arguments") or {}, "summary": summary,
                            "materiality_inr": None},
    }


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("task_type", sa.String(length=64), nullable=False),
        sa.Column("assignment_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("materiality_inr", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"assignment_mode IN ({ASSIGNMENT})",
                           name="ck_assignment_mode_valid"),
        sa.CheckConstraint(f"status IN ({TASK_STATUS})", name="ck_status_valid"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"))
    with op.batch_alter_table("task") as batch:
        batch.create_index("ix_task_deal_id", ["deal_id"])
        batch.create_index("ix_task_job_id", ["job_id"])
        batch.create_index("ix_task_status", ["status"])

    op.create_table(
        "handoff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("context_package", sa.JSON(), nullable=False),
        sa.Column("directive", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("auto_escalate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_by", sa.String(length=64), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"direction IN ({DIRECTION})", name="ck_direction_valid"),
        sa.CheckConstraint(f"trigger IN ({TRIGGER})", name="ck_trigger_valid"),
        sa.CheckConstraint(f"status IN ({HANDOFF_STATUS})", name="ck_status_valid"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"]),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"]),
        sa.PrimaryKeyConstraint("id"))
    with op.batch_alter_table("handoff") as batch:
        batch.create_index("ix_handoff_task_id", ["task_id"])
        batch.create_index("ix_handoff_deal_id", ["deal_id"])
        batch.create_index("ix_handoff_status", ["status"])

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT a.id, a.category, a.proposed_action, a.status, a.created_at, a.decided_at, "
        "u.username, s.job_id, j.deal_id FROM approvals a "
        "JOIN segments s ON s.id = a.segment_id JOIN jobs j ON j.id = s.job_id "
        "LEFT JOIN users u ON u.id = a.decided_by ORDER BY a.id")).fetchall()
    for _id, category, action_json, status, created_at, decided_at, username, job_id, deal_id \
            in rows:
        action = json.loads(action_json) if isinstance(action_json, str) else (action_json or {})
        action.setdefault("category", category)
        created = _dt(created_at)
        decided = _dt(decided_at)
        pending = status == "pending"
        task_status = "review" if pending else ("done" if status == "approved" else "cancelled")
        conn.execute(sa.insert(task_t).values(
            deal_id=deal_id, job_id=job_id, task_type=action.get("tool") or "gated_action",
            assignment_mode="human_required", status=task_status, materiality_inr=None,
            created_at=created))
        task_id = conn.execute(sa.text("SELECT last_insert_rowid()")).scalar()
        package = _package(action, created)
        directive = None if pending else {
            "decision": "approve" if status == "approved" else "reject",
            "reasoning": "Decision recorded before the move from approvals to handoffs.",
            "new_constraints": {"do_not_revisit": []},
            "next_checkpoint": {"condition": "None: legacy approval",
                                "escalate_if": "Not applicable"}}
        conn.execute(sa.insert(handoff_t).values(
            task_id=task_id, deal_id=deal_id, direction="bot_to_human",
            trigger="policy_required", context_package=package, directive=directive,
            status="open" if pending else "resolved",
            auto_escalate_at=created + timedelta(hours=24), created_at=created,
            resolved_by=None if pending else (username or "unknown"),
            resolved_at=None if pending else (decided or created)))

    op.drop_table("approvals")


def downgrade() -> None:
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
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"]))
    op.create_index("ix_approvals_status", "approvals", ["status"])
    op.create_index("ix_approvals_segment_id", "approvals", ["segment_id"])

    # Best effort: job-bound handoffs go back as approvals on the job's latest segment.
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT h.context_package, h.directive, h.status, h.created_at, h.resolved_at, "
        "h.resolved_by, t.job_id FROM handoff h JOIN task t ON t.id = h.task_id "
        "WHERE t.job_id IS NOT NULL ORDER BY h.id")).fetchall()
    for package_json, directive_json, status, created_at, resolved_at, resolved_by, job_id \
            in rows:
        package = json.loads(package_json) if isinstance(package_json, str) else package_json
        directive = json.loads(directive_json) if isinstance(directive_json, str) \
            and directive_json != "null" else None
        segment_id = conn.execute(sa.text(
            "SELECT id FROM segments WHERE job_id = :j ORDER BY seq DESC LIMIT 1"),
            {"j": job_id}).scalar()
        if segment_id is None:
            continue
        action = (package or {}).get("proposed_action") or {}
        if status != "resolved":
            legacy = "pending"
        else:
            legacy = ("approved" if (directive or {}).get("decision") in ("approve", "confirm")
                      else "rejected")
        user_id = conn.execute(sa.text("SELECT id FROM users WHERE username = :u"),
                               {"u": resolved_by}).scalar() if resolved_by else None
        category = action.get("category")
        if category not in ("money", "legal", "outbound", "internal_read", "internal_write"):
            category = "unknown"
        conn.execute(sa.insert(approval_t).values(
            segment_id=segment_id, category=category, proposed_action=action, status=legacy,
            decided_by=user_id, decided_at=_dt(resolved_at), created_at=_dt(created_at)))

    for table in ("handoff", "task"):
        op.drop_table(table)
