"""deal_spine

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06 18:43:33.889365
"""
import json
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from aura.core.domain.audit import GENESIS_HASH, AuditEntry, compute_row_hash
from aura.core.domain.enums import DealStage
from aura.core.policy.stage_policy import TERMINAL_STAGES
from aura.data.triggers import APPEND_ONLY_TABLES, append_only_ddl, trigger_names


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('checklist_item_template',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('default_severity', sa.String(length=16), nullable=False),
    sa.CheckConstraint("default_severity IN ('blocker', 'material', 'standard', 'informational')", name='ck_default_severity_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('party',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('party_type', sa.String(length=16), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("party_type IN ('company', 'llp', 'individual', 'fund', 'institution')", name='ck_party_type_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stage_guard',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('from_stage', sa.String(length=64), nullable=False),
    sa.Column('to_stage', sa.String(length=64), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('guard_name', sa.String(length=64), nullable=False),
    sa.Column('sql_text', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('override_role', sa.String(length=16), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.CheckConstraint("from_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_from_stage_valid'),
    sa.CheckConstraint("severity IN ('blocking', 'warning')", name='ck_severity_valid'),
    sa.CheckConstraint("to_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_to_stage_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('guard_name')
    )
    with op.batch_alter_table('stage_guard', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stage_guard_from_stage'), ['from_stage'], unique=False)

    op.create_table('party_identifier',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('party_id', sa.Integer(), nullable=False),
    sa.Column('scheme', sa.String(length=8), nullable=False),
    sa.Column('value', sa.String(length=32), nullable=False),
    sa.CheckConstraint("scheme IN ('CIN', 'LLPIN', 'PAN', 'GSTIN', 'DIN')", name='ck_scheme_valid'),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scheme', 'value', name='uq_identifier_scheme_value')
    )
    with op.batch_alter_table('party_identifier', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_party_identifier_party_id'), ['party_id'], unique=False)

    op.create_table('condition_precedent',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('cp_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('waiver_justification', sa.Text(), nullable=True),
    sa.CheckConstraint("status != 'waived' OR waiver_justification IS NOT NULL", name='ck_cp_waived_needs_justification'),
    sa.CheckConstraint("status IN ('open', 'in_progress', 'satisfied', 'waived', 'failed')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('condition_precedent', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_condition_precedent_deal_id'), ['deal_id'], unique=False)

    op.create_table('deal_party',
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('party_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.CheckConstraint("role IN ('buyer', 'seller', 'target', 'issuer', 'investor', 'lender', 'advisor', 'counsel')", name='ck_role_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('deal_id', 'party_id', 'role')
    )
    op.create_table('deal_stage_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('from_stage', sa.String(length=64), nullable=True),
    sa.Column('to_stage', sa.String(length=64), nullable=False),
    sa.Column('entered_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('is_regression', sa.Boolean(), nullable=False),
    sa.CheckConstraint("from_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_from_stage_valid'),
    sa.CheckConstraint("to_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_to_stage_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('deal_stage_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_deal_stage_history_deal_id'), ['deal_id'], unique=False)

    op.create_table('diligence_item',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('template_id', sa.Integer(), nullable=True),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('evidence_doc_ids', sa.JSON(), nullable=False),
    sa.Column('waiver_justification', sa.Text(), nullable=True),
    sa.CheckConstraint("severity IN ('blocker', 'material', 'standard', 'informational')", name='ck_severity_valid'),
    sa.CheckConstraint("status != 'satisfied' OR COALESCE(json_array_length(evidence_doc_ids), 0) > 0", name='ck_satisfied_needs_evidence'),
    sa.CheckConstraint("status != 'waived' OR waiver_justification IS NOT NULL", name='ck_waived_needs_justification'),
    sa.CheckConstraint("status IN ('open', 'requested', 'received', 'under_review', 'satisfied', 'waived', 'failed')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['checklist_item_template.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('diligence_item', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_diligence_item_deal_id'), ['deal_id'], unique=False)

    op.create_table('document',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('doc_class', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('contains_upsi', sa.Boolean(), nullable=False),
    sa.Column('sensitivity', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('class_confirmed', sa.Boolean(), nullable=False),
    sa.CheckConstraint("doc_class IN ('teaser', 'nda', 'engagement_letter', 'information_memorandum', 'financial_statements', 'valuation_report', 'term_sheet', 'spa', 'shpa', 'sha', 'loan_agreement', 'dd_report', 'board_resolution', 'cp_evidence', 'correspondence', 'other')", name='ck_doc_class_valid'),
    sa.CheckConstraint('contains_upsi = 0 OR sensitivity = 4', name='ck_upsi_sensitivity'),
    sa.CheckConstraint('sensitivity BETWEEN 1 AND 4', name='ck_sensitivity_range'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_deal_id'), ['deal_id'], unique=False)

    op.create_table('mandate',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mandate', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mandate_deal_id'), ['deal_id'], unique=False)

    op.create_table('stage_guard_evaluation',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('guard_id', sa.Integer(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('result', sa.Boolean(), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('overridden_by', sa.String(length=64), nullable=True),
    sa.Column('override_justification', sa.Text(), nullable=True),
    sa.CheckConstraint('overridden_by IS NULL OR override_justification IS NOT NULL', name='ck_override_justified'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['guard_id'], ['stage_guard.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('stage_guard_evaluation', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stage_guard_evaluation_deal_id'), ['deal_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stage_guard_evaluation_guard_id'), ['guard_id'], unique=False)

    op.create_table('doc_access_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('accessed_by', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('accessed_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('doc_access_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_doc_access_log_document_id'), ['document_id'], unique=False)

    op.create_table('mandate_criteria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mandate_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('attribute', sa.String(length=100), nullable=False),
    sa.Column('value', sa.String(length=500), nullable=False),
    sa.Column('weight', sa.Float(), nullable=True),
    sa.CheckConstraint("kind != 'soft' OR weight IS NOT NULL", name='ck_soft_needs_weight'),
    sa.CheckConstraint("kind IN ('hard', 'soft', 'preference')", name='ck_kind_valid'),
    sa.ForeignKeyConstraint(['mandate_id'], ['mandate.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('mandate_criteria', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mandate_criteria_mandate_id'), ['mandate_id'], unique=False)

    conn = op.get_bind()

    # --- deals: new columns, legacy free-text stages -> ORIGINATED, first history row ---
    with op.batch_alter_table("deals") as batch_op:
        batch_op.add_column(sa.Column("transaction_class", sa.String(16), nullable=False,
                                      server_default="DEBT"))
        batch_op.add_column(sa.Column("outcome", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    conn.execute(sa.text("UPDATE deals SET stage = 'ORIGINATED', opened_at = created_at"))
    conn.execute(sa.text(
        "INSERT INTO deal_stage_history (deal_id, from_stage, to_stage, entered_at, actor, "
        "reason_code, is_regression) SELECT id, NULL, 'ORIGINATED', created_at, 'migration', "
        "NULL, 0 FROM deals"))
    stages = ", ".join(f"'{e.value}'" for e in DealStage)
    terminal = ", ".join(f"'{e.value}'" for e in TERMINAL_STAGES)
    with op.batch_alter_table("deals") as batch_op:
        batch_op.alter_column("opened_at", existing_type=sa.DateTime(timezone=True),
                              nullable=False)
        batch_op.create_check_constraint("ck_stage_valid", f"stage IN ({stages})")
        batch_op.create_check_constraint(
            "ck_transaction_class_valid",
            "transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')")
        batch_op.create_check_constraint(
            "ck_outcome_valid",
            "outcome IN ('closed_won', 'closed_lost', 'withdrawn', 'lapsed', 'rejected', "
            "'aborted')")
        batch_op.create_check_constraint(
            "ck_deal_terminal_consistent",
            f"((stage IN ({terminal})) = (outcome IS NOT NULL)) AND "
            "((outcome IS NOT NULL) = (closed_at IS NOT NULL))")

    # --- audit_entries: deal_id + hash chain, backfilled for existing rows ---
    with op.batch_alter_table("audit_entries") as batch_op:
        batch_op.add_column(sa.Column("deal_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("prev_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("row_hash", sa.String(64), nullable=True))
        batch_op.create_index("ix_audit_entries_deal_id", ["deal_id"])
        batch_op.create_foreign_key("fk_audit_entries_deal_id", "deals", ["deal_id"], ["id"])
    prev = GENESIS_HASH
    rows = conn.execute(sa.text("SELECT id, job_id, actor, action, payload, created_at "
                                "FROM audit_entries ORDER BY id")).fetchall()
    for id_, job_id, actor, action, payload, created_at in rows:
        entry = AuditEntry(id=id_, job_id=job_id, actor=actor, action=action,
                           payload=json.loads(payload), created_at=datetime.fromisoformat(created_at))
        row_hash = compute_row_hash(prev, entry)
        conn.execute(sa.text("UPDATE audit_entries SET prev_hash = :p, row_hash = :h "
                             "WHERE id = :id"), {"p": prev, "h": row_hash, "id": id_})
        prev = row_hash
    with op.batch_alter_table("audit_entries") as batch_op:
        batch_op.alter_column("prev_hash", existing_type=sa.String(64), nullable=False)
        batch_op.alter_column("row_hash", existing_type=sa.String(64), nullable=False)

    for table in APPEND_ONLY_TABLES:
        for ddl in append_only_ddl(table):
            op.execute(ddl)



def downgrade() -> None:
    for table in APPEND_ONLY_TABLES:
        for name in trigger_names(table):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")

    with op.batch_alter_table("deals") as batch_op:
        for name in ("ck_deal_terminal_consistent", "ck_outcome_valid",
                     "ck_transaction_class_valid", "ck_stage_valid"):
            batch_op.drop_constraint(name, type_="check")
        for col in ("closed_at", "opened_at", "outcome", "transaction_class"):
            batch_op.drop_column(col)

    with op.batch_alter_table("audit_entries") as batch_op:
        batch_op.drop_constraint("fk_audit_entries_deal_id", type_="foreignkey")
        batch_op.drop_index("ix_audit_entries_deal_id")
        for col in ("row_hash", "prev_hash", "deal_id"):
            batch_op.drop_column(col)

    with op.batch_alter_table('mandate_criteria', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mandate_criteria_mandate_id'))

    op.drop_table('mandate_criteria')
    with op.batch_alter_table('doc_access_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_doc_access_log_document_id'))

    op.drop_table('doc_access_log')
    with op.batch_alter_table('stage_guard_evaluation', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stage_guard_evaluation_guard_id'))
        batch_op.drop_index(batch_op.f('ix_stage_guard_evaluation_deal_id'))

    op.drop_table('stage_guard_evaluation')
    with op.batch_alter_table('mandate', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mandate_deal_id'))

    op.drop_table('mandate')
    with op.batch_alter_table('document', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_deal_id'))

    op.drop_table('document')
    with op.batch_alter_table('diligence_item', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_diligence_item_deal_id'))

    op.drop_table('diligence_item')
    with op.batch_alter_table('deal_stage_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_deal_stage_history_deal_id'))

    op.drop_table('deal_stage_history')
    op.drop_table('deal_party')
    with op.batch_alter_table('condition_precedent', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_condition_precedent_deal_id'))

    op.drop_table('condition_precedent')
    with op.batch_alter_table('party_identifier', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_party_identifier_party_id'))

    op.drop_table('party_identifier')
    with op.batch_alter_table('stage_guard', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_stage_guard_from_stage'))

    op.drop_table('stage_guard')
    op.drop_table('party')
    op.drop_table('checklist_item_template')
