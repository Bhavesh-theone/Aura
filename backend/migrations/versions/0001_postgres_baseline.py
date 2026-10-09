"""PostgreSQL baseline: the whole schema of the SQLite chain 0001-0013, plus deal profiles,
doc_chunk (pgvector) and deal_intake, with row-level security on every deal-scoped table.

Revision ID: 0001
Revises:
Create Date: 2026-10-09

Run as aura_owner (AURA_MIGRATION_DATABASE_URL). The app role aura_app gets DML grants only,
and none that would let it UPDATE or DELETE an append-only table.

Row-level security (PRD D1). Every transaction of the app sets `aura.viewer` (SET LOCAL, see
aura.data.engine / aura.data.walls) to a username, or to ':system' for the worker, seeding and
other internal callers. The policies show a deal-scoped row when:
  * the viewer is ':system' (the SYSTEM branch: internal work across every wall), or
  * the row's deal is in aura_visible_deal_ids(): deals whose wall currently lists the viewer,
    plus deals the viewer owns that have no wall yet (the moment inside create_deal between
    inserting the deal and creating its wall), or
  * for tables whose deal_id is nullable (jobs, task, handoff, agent_run, audit_entries,
    outbound_message, trace_span): the row belongs to no deal.
Child tables without a deal_id (doc_version, doc_access_log, extraction, mandate_criteria,
finding, segments, wall_member) are visible when their parent row is (the parent's own policy
does the work). deal_intake rows are private to their creator until confirmed.
The helper functions are SECURITY DEFINER (owned by aura_owner, which has BYPASSRLS) so they
can read the wall tables without recursing into those tables' own policies.
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

APP_ROLE = "aura_app"
SYSTEM_VIEWER = ":system"
APPEND_ONLY = ("audit_entries", "deal_stage_history", "doc_access_log")

# Tables with their own deal_id: NOT NULL ones, then nullable ones (no deal = firm-wide).
DEAL_TABLES = ("deal_party", "deal_stage_history", "stage_guard_evaluation", "mandate",
               "document", "diligence_item", "deal_signoff", "condition_precedent",
               "deal_note", "wall", "doc_chunk")
NULLABLE_DEAL_TABLES = ("jobs", "task", "handoff", "agent_run", "audit_entries",
                        "outbound_message", "trace_span")
# Child table -> predicate on its parent (whose policy does the filtering).
CHILD_TABLES = {
    "doc_version": "EXISTS (SELECT 1 FROM document p WHERE p.id = document_id)",
    "doc_access_log": "EXISTS (SELECT 1 FROM document p WHERE p.id = document_id)",
    "extraction": "EXISTS (SELECT 1 FROM document p WHERE p.id = document_id)",
    "mandate_criteria": "EXISTS (SELECT 1 FROM mandate p WHERE p.id = mandate_id)",
    "finding": "EXISTS (SELECT 1 FROM diligence_item p WHERE p.id = diligence_item_id)",
    "segments": "EXISTS (SELECT 1 FROM jobs p WHERE p.id = job_id)",
    "wall_member": "(user_id = aura_viewer_user_id() "
                   "OR EXISTS (SELECT 1 FROM wall p WHERE p.id = wall_id))",
}
_VISIBLE = "IN (SELECT unnest(aura_visible_deal_ids()))"

FUNCTIONS = [
    """CREATE FUNCTION aura_viewer() RETURNS text LANGUAGE sql STABLE AS $$
         SELECT coalesce(current_setting('aura.viewer', true), '') $$""",
    f"""CREATE FUNCTION aura_is_system() RETURNS boolean LANGUAGE sql STABLE AS $$
         SELECT aura_viewer() = '\\{SYSTEM_VIEWER}' $$""",  # \: = a literal colon in text()
    """CREATE FUNCTION aura_viewer_user_id() RETURNS bigint LANGUAGE sql STABLE
         SECURITY DEFINER SET search_path = public, pg_temp AS $$
         SELECT id FROM users WHERE username = aura_viewer() $$""",
    """CREATE FUNCTION aura_visible_deal_ids() RETURNS bigint[] LANGUAGE sql STABLE
         SECURITY DEFINER SET search_path = public, pg_temp AS $$
         SELECT coalesce(array_agg(v.id), '{}'::bigint[]) FROM (
           SELECT w.deal_id AS id FROM wall w
             JOIN wall_member m ON m.wall_id = w.id JOIN users u ON u.id = m.user_id
            WHERE m.removed_at IS NULL AND u.username = aura_viewer()
           UNION
           SELECT d.id FROM deals d
            WHERE d.owner = aura_viewer()
              AND NOT EXISTS (SELECT 1 FROM wall w2 WHERE w2.deal_id = d.id)) v $$""",
    """CREATE FUNCTION aura_deal_has_wall(p_deal_id bigint) RETURNS boolean LANGUAGE sql
         STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
         SELECT EXISTS (SELECT 1 FROM wall WHERE deal_id = p_deal_id) $$""",
    # The audit chain's head across every wall: an appender must link to the newest row
    # even when it cannot see that row's deal.
    """CREATE FUNCTION aura_audit_head() RETURNS text LANGUAGE sql STABLE
         SECURITY DEFINER SET search_path = public, pg_temp AS $$
         SELECT row_hash FROM audit_entries ORDER BY id DESC LIMIT 1 $$""",
    """CREATE FUNCTION aura_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
         BEGIN
           RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
             USING ERRCODE = 'restrict_violation';
         END $$""",
]
FUNCTION_NAMES = ("aura_append_only()", "aura_audit_head()", "aura_deal_has_wall(bigint)",
                  "aura_visible_deal_ids()", "aura_viewer_user_id()", "aura_is_system()",
                  "aura_viewer()")


def _policies() -> dict[str, str]:
    """table -> the USING / WITH CHECK expression of its wall policy."""
    pol = {"deals": f"aura_is_system() OR id {_VISIBLE} "
                    "OR (owner = aura_viewer() AND NOT aura_deal_has_wall(id))"}
    for t in DEAL_TABLES:
        pol[t] = f"aura_is_system() OR deal_id {_VISIBLE}"
    for t in NULLABLE_DEAL_TABLES:
        pol[t] = f"aura_is_system() OR deal_id IS NULL OR deal_id {_VISIBLE}"
    for t, parent in CHILD_TABLES.items():
        pol[t] = f"aura_is_system() OR {parent}"
    pol["deal_intake"] = ("aura_is_system() OR created_by = aura_viewer() OR "
                          f"(status = 'confirmed' AND confirmed_deal_id {_VISIBLE})")
    return pol


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    _create_tables()
    for sql in FUNCTIONS:
        op.execute(sql)
    for table in APPEND_ONLY:
        op.execute(f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION aura_append_only()")
    for table, expr in _policies().items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        if table == "audit_entries":
            # Reads are walled; appends are not: an actor who has just left a wall (removed
            # themself) must still be able to record that. The app appends without RETURNING.
            op.execute(f"CREATE POLICY wall_visibility ON {table} FOR SELECT USING ({expr})")
            op.execute(f"CREATE POLICY audit_append ON {table} FOR INSERT WITH CHECK (true)")
            continue
        op.execute(f"CREATE POLICY wall_visibility ON {table} USING ({expr}) "
                   f"WITH CHECK ({expr})")
    # The app role: DML only, never on alembic_version, never UPDATE/DELETE on append-only
    # tables. Skipped when the role does not exist (a bare database someone migrates by hand).
    op.execute(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT USAGE ON SCHEMA public TO {APP_ROLE};
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
        REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM {APP_ROLE};
        REVOKE UPDATE, DELETE ON {", ".join(APPEND_ONLY)} FROM {APP_ROLE};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
          GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
          GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE};
      END IF;
    END $$""")


def downgrade() -> None:
    _drop_tables()
    for fn in FUNCTION_NAMES:
        op.execute(f"DROP FUNCTION IF EXISTS {fn}")


def _create_tables() -> None:
    # Generated from aura.data.models.tables (alembic check keeps the two in step).
    op.create_table('capability_autonomy',
    sa.Column('capability', sa.String(length=64), nullable=False),
    sa.Column('level', sa.Integer(), server_default='2', nullable=False),
    sa.Column('pinned_model', sa.String(length=128), nullable=True),
    sa.Column('demoted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.String(length=64), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('level BETWEEN 0 AND 2', name='ck_level_valid'),
    sa.PrimaryKeyConstraint('capability')
    )
    op.create_table('checklist_template',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('layer', sa.String(length=16), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.CheckConstraint("layer IN ('base', 'subclass', 'vertical', 'jurisdiction')", name='ck_layer_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('eval_run',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('capability', sa.String(length=64), nullable=False),
    sa.Column('orchestrator', sa.String(length=16), nullable=False),
    sa.Column('model_id', sa.String(length=128), nullable=False),
    sa.Column('golden_sha256', sa.String(length=64), nullable=False),
    sa.Column('n_cases', sa.Integer(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('threshold', sa.Float(), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_eval_run_capability'), 'eval_run', ['capability'], unique=False)
    op.create_table('party',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('party_type', sa.String(length=16), nullable=False),
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("party_type IN ('company', 'llp', 'fund', 'trust', 'individual', 'government_body', 'foreign_entity', 'partnership', 'sole_prop', 'huf')", name='ck_party_type_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('stage_guard',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('from_stage', sa.String(length=64), nullable=False),
    sa.Column('to_stage', sa.String(length=64), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('guard_name', sa.String(length=64), nullable=False),
    sa.Column('sql_text', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('override_role', sa.String(length=16), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.CheckConstraint("from_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_from_stage_valid'),
    sa.CheckConstraint("severity IN ('blocking', 'warning')", name='ck_severity_valid'),
    sa.CheckConstraint("to_stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_to_stage_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('guard_name')
    )
    op.create_index(op.f('ix_stage_guard_from_stage'), 'stage_guard', ['from_stage'], unique=False)
    op.create_table('suppression',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('value', sa.String(length=254), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("kind IN ('email', 'domain')", name='ck_kind_valid'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('kind', 'value', name='uq_suppression_kind_value')
    )
    op.create_table('trace_span',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('trace_id', sa.String(length=32), nullable=False),
    sa.Column('span_id', sa.String(length=16), nullable=False),
    sa.Column('parent_span_id', sa.String(length=16), nullable=True),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attributes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trace_span_deal_id'), 'trace_span', ['deal_id'], unique=False)
    op.create_index(op.f('ix_trace_span_trace_id'), 'trace_span', ['trace_id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'dealmaker', 'analyst', 'compliance')", name='ck_role_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('checklist_item_template',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('template_id', sa.BigInteger(), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=False),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('default_severity', sa.String(length=16), nullable=False),
    sa.CheckConstraint("default_severity IN ('blocker', 'material', 'standard', 'informational')", name='ck_default_severity_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.ForeignKeyConstraint(['template_id'], ['checklist_template.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checklist_item_template_template_id'), 'checklist_item_template', ['template_id'], unique=False)
    op.create_table('deals',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('external_id', sa.String(length=32), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('stage', sa.String(length=64), nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=False),
    sa.Column('owner', sa.String(length=64), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('regulatory_flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('profile', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('profile_schema_version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("((stage IN ('LAPSED', 'REJECTED', 'ABORTED', 'CLOSED', 'WITHDRAWN')) = (outcome IS NOT NULL)) AND ((outcome IS NOT NULL) = (closed_at IS NOT NULL))", name='ck_deal_terminal_consistent'),
    sa.CheckConstraint("jsonb_typeof(profile) = 'object'", name='ck_deal_profile_object'),
    sa.CheckConstraint("outcome IN ('closed_won', 'closed_lost', 'withdrawn', 'lapsed', 'rejected', 'aborted')", name='ck_outcome_valid'),
    sa.CheckConstraint("stage IN ('ORIGINATED', 'QUALIFIED', 'MANDATED', 'PREPARED', 'MARKETED', 'MATCHED', 'BID_AUCTION', 'NEGOTIATION', 'DILIGENCE', 'DOCUMENTATION', 'CONDITIONS_PRECEDENT', 'CLOSED', 'LAPSED', 'WITHDRAWN', 'REJECTED', 'ABORTED')", name='ck_stage_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.CheckConstraint('profile_schema_version >= 1', name='ck_deal_profile_version'),
    sa.ForeignKeyConstraint(['owner'], ['users.username'], onupdate='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deals_external_id'), 'deals', ['external_id'], unique=True)
    op.create_index('ix_deals_profile', 'deals', ['profile'], unique=False, postgresql_using='gin')
    op.create_table('party_contact',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('party_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('is_primary', sa.Boolean(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verified_by', sa.String(length=64), nullable=True),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("email = lower(email) AND email LIKE '%%_@_%%._%%' AND email NOT LIKE '%% %%' AND email NOT LIKE '%%@%%@%%'", name='ck_party_contact_email'),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('party_id', 'email', name='uq_party_contact_email')
    )
    op.create_index(op.f('ix_party_contact_party_id'), 'party_contact', ['party_id'], unique=False)
    op.create_table('party_identifier',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('party_id', sa.BigInteger(), nullable=False),
    sa.Column('scheme', sa.String(length=8), nullable=False),
    sa.Column('value', sa.String(length=32), nullable=False),
    sa.CheckConstraint("(scheme = 'PAN' AND value ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') OR (scheme = 'DIN' AND value ~ '^[0-9]{8}$') OR (scheme = 'GSTIN' AND value ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$') OR (scheme = 'CIN' AND value ~ '^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$') OR (scheme = 'LLPIN' AND value ~ '^[A-Z]{3}-[0-9]{4}$')", name='ck_identifier_format'),
    sa.CheckConstraint("scheme IN ('CIN', 'LLPIN', 'PAN', 'GSTIN', 'DIN')", name='ck_scheme_valid'),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('scheme', 'value', name='uq_identifier_scheme_value')
    )
    op.create_index(op.f('ix_party_identifier_party_id'), 'party_identifier', ['party_id'], unique=False)
    op.create_table('condition_precedent',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('cp_type', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('waiver_justification', sa.Text(), nullable=True),
    sa.CheckConstraint("status != 'waived' OR waiver_justification IS NOT NULL", name='ck_cp_waived_needs_justification'),
    sa.CheckConstraint("status IN ('open', 'in_progress', 'satisfied', 'waived', 'failed')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_condition_precedent_deal_id'), 'condition_precedent', ['deal_id'], unique=False)
    op.create_table('deal_intake',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='draft', nullable=False),
    sa.Column('transaction_class', sa.String(length=16), nullable=True),
    sa.Column('fields', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('conflicts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('confirmed_deal_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(status = 'confirmed') = (confirmed_deal_id IS NOT NULL)", name='ck_intake_confirmed_deal'),
    sa.CheckConstraint("status IN ('draft', 'processing', 'review', 'confirmed', 'discarded')", name='ck_status_valid'),
    sa.CheckConstraint("transaction_class IN ('DEBT', 'EQUITY', 'MNA', 'HYBRID', 'JV', 'LPGP', 'ALLIANCE')", name='ck_transaction_class_valid'),
    sa.ForeignKeyConstraint(['confirmed_deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deal_intake_created_by'), 'deal_intake', ['created_by'], unique=False)
    op.create_table('deal_party',
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('party_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.CheckConstraint("role IN ('buyer', 'seller', 'target', 'issuer', 'investor', 'lender', 'advisor', 'counsel')", name='ck_role_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('deal_id', 'party_id', 'role')
    )
    op.create_table('deal_signoff',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('signed_by', sa.String(length=64), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('signed_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deal_signoff_deal_id'), 'deal_signoff', ['deal_id'], unique=False)
    op.create_table('deal_stage_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
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
    op.create_index(op.f('ix_deal_stage_history_deal_id'), 'deal_stage_history', ['deal_id'], unique=False)
    op.create_table('diligence_item',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('template_id', sa.BigInteger(), nullable=True),
    sa.Column('prompt', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('evidence_doc_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('waiver_justification', sa.Text(), nullable=True),
    sa.CheckConstraint("severity IN ('blocker', 'material', 'standard', 'informational')", name='ck_severity_valid'),
    sa.CheckConstraint("status != 'satisfied' OR (jsonb_typeof(evidence_doc_ids) = 'array' AND jsonb_array_length(evidence_doc_ids) > 0)", name='ck_satisfied_needs_evidence'),
    sa.CheckConstraint("status != 'waived' OR waiver_justification IS NOT NULL", name='ck_waived_needs_justification'),
    sa.CheckConstraint("status IN ('open', 'requested', 'received', 'under_review', 'satisfied', 'waived', 'failed')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['checklist_item_template.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_diligence_item_deal_id'), 'diligence_item', ['deal_id'], unique=False)
    op.create_table('document',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('doc_class', sa.String(length=32), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('contains_upsi', sa.Boolean(), nullable=False),
    sa.Column('sensitivity', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('class_confirmed', sa.Boolean(), nullable=False),
    sa.Column('is_executed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.CheckConstraint("doc_class IN ('financial_statement', 'cap_table', 'board_resolution', 'moa_aoa', 'term_sheet', 'spa', 'shpa', 'valuation_report', 'tax_return', 'litigation_summary', 'env_clearance', 'engagement_letter', 'nda', 'bank_statement', 'gst_return', 'charge_document', 'land_title')", name='ck_doc_class_valid'),
    sa.CheckConstraint('NOT contains_upsi OR sensitivity = 4', name='ck_upsi_sensitivity'),
    sa.CheckConstraint('sensitivity BETWEEN 1 AND 4', name='ck_sensitivity_range'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_document_deal_id'), 'document', ['deal_id'], unique=False)
    op.create_table('jobs',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('inputs', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.String(length=64), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=True),
    sa.Column('span_id', sa.String(length=16), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'running', 'awaiting_approval', 'complete', 'failed', 'rejected')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_jobs_status'), 'jobs', ['status'], unique=False)
    op.create_index(op.f('ix_jobs_trace_id'), 'jobs', ['trace_id'], unique=False)
    op.create_table('mandate',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('side', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("side IN ('sell', 'buy', 'raise', 'deploy', 'partner')", name='ck_side_valid'),
    sa.CheckConstraint("status IN ('draft', 'active', 'paused', 'fulfilled', 'expired', 'withdrawn')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mandate_deal_id'), 'mandate', ['deal_id'], unique=False)
    op.create_table('wall',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deal_id')
    )
    op.create_table('audit_entries',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('row_hash', sa.String(length=64), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_entries_action'), 'audit_entries', ['action'], unique=False)
    op.create_index(op.f('ix_audit_entries_deal_id'), 'audit_entries', ['deal_id'], unique=False)
    op.create_index(op.f('ix_audit_entries_job_id'), 'audit_entries', ['job_id'], unique=False)
    op.create_table('deal_note',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('author', sa.String(length=64), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_deal_note_deal_id'), 'deal_note', ['deal_id'], unique=False)
    op.create_table('doc_access_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('accessed_by', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('accessed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_doc_access_log_document_id'), 'doc_access_log', ['document_id'], unique=False)
    op.create_table('doc_chunk',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('page_from', sa.Integer(), nullable=True),
    sa.Column('page_to', sa.Integer(), nullable=True),
    sa.Column('kind', sa.String(length=8), server_default='text', nullable=False),
    sa.Column('tsv', postgresql.TSVECTOR(), sa.Computed("to_tsvector('english'::regconfig, text)", persisted=True), nullable=True),
    sa.Column('embedding', Vector(768), nullable=True),
    sa.Column('embedding_model', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('text', 'table')", name='ck_doc_chunk_kind'),
    sa.CheckConstraint('page_from IS NULL OR page_to IS NULL OR page_from <= page_to', name='ck_doc_chunk_pages'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id', 'version', 'chunk_index', name='uq_doc_chunk_position')
    )
    op.create_index(op.f('ix_doc_chunk_deal_id'), 'doc_chunk', ['deal_id'], unique=False)
    op.create_index(op.f('ix_doc_chunk_document_id'), 'doc_chunk', ['document_id'], unique=False)
    op.create_index('ix_doc_chunk_embedding_hnsw', 'doc_chunk', ['embedding'], unique=False, postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.create_index('ix_doc_chunk_tsv', 'doc_chunk', ['tsv'], unique=False, postgresql_using='gin')
    op.create_table('doc_version',
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=False),
    sa.Column('uploaded_by', sa.String(length=64), nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('document_id', 'version')
    )
    op.create_table('finding',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('diligence_item_id', sa.BigInteger(), nullable=False),
    sa.Column('finding_type', sa.String(length=16), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('quantified_impact_inr', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('affects_valuation', sa.Boolean(), nullable=False),
    sa.Column('raised_by', sa.String(length=64), nullable=False),
    sa.Column('raised_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("finding_type IN ('red_flag', 'qualification', 'adjustment', 'observation')", name='ck_finding_type_valid'),
    sa.CheckConstraint('NOT affects_valuation OR quantified_impact_inr IS NOT NULL', name='ck_finding_impact_required'),
    sa.ForeignKeyConstraint(['diligence_item_id'], ['diligence_item.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_finding_diligence_item_id'), 'finding', ['diligence_item_id'], unique=False)
    op.create_table('idempotency_key',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key', 'username', name='uq_idempotency_key_user')
    )
    op.create_table('mandate_criteria',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('mandate_id', sa.BigInteger(), nullable=False),
    sa.Column('criterion_key', sa.String(length=100), nullable=False),
    sa.Column('operator', sa.String(length=16), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hardness', sa.String(length=16), nullable=False),
    sa.Column('weight', sa.Float(), nullable=True),
    sa.CheckConstraint("hardness != 'soft' OR weight IS NOT NULL", name='ck_soft_needs_weight'),
    sa.CheckConstraint("hardness IN ('hard', 'soft', 'preference')", name='ck_hardness_valid'),
    sa.CheckConstraint("operator IN ('eq', 'in', 'gte', 'lte', 'between', 'not_in', 'contains')", name='ck_operator_valid'),
    sa.CheckConstraint('weight IS NULL OR (weight >= 0 AND weight <= 1)', name='ck_weight_range'),
    sa.ForeignKeyConstraint(['mandate_id'], ['mandate.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mandate_criteria_mandate_id'), 'mandate_criteria', ['mandate_id'], unique=False)
    op.create_table('segments',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('context_in', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('context_out', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claimed_by', sa.String(length=128), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'awaiting_approval', 'done', 'failed', 'dead_letter')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'seq', name='uq_segment_job_seq')
    )
    op.create_index(op.f('ix_segments_job_id'), 'segments', ['job_id'], unique=False)
    op.create_index(op.f('ix_segments_status'), 'segments', ['status'], unique=False)
    op.create_table('stage_guard_evaluation',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('guard_id', sa.BigInteger(), nullable=False),
    sa.Column('history_id', sa.BigInteger(), nullable=True),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('result', sa.Boolean(), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('overridden_by', sa.String(length=64), nullable=True),
    sa.Column('override_justification', sa.Text(), nullable=True),
    sa.CheckConstraint('overridden_by IS NULL OR override_justification IS NOT NULL', name='ck_override_justified'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['guard_id'], ['stage_guard.id'], ),
    sa.ForeignKeyConstraint(['history_id'], ['deal_stage_history.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stage_guard_evaluation_deal_id'), 'stage_guard_evaluation', ['deal_id'], unique=False)
    op.create_index(op.f('ix_stage_guard_evaluation_guard_id'), 'stage_guard_evaluation', ['guard_id'], unique=False)
    op.create_index(op.f('ix_stage_guard_evaluation_history_id'), 'stage_guard_evaluation', ['history_id'], unique=False)
    op.create_table('task',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('task_type', sa.String(length=64), nullable=False),
    sa.Column('assignment_mode', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('materiality_inr', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("assignment_mode IN ('bot_auto', 'bot_supervised', 'human_required')", name='ck_assignment_mode_valid'),
    sa.CheckConstraint("status IN ('queued', 'assigned', 'in_progress', 'blocked', 'review', 'done', 'cancelled')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_task_deal_id'), 'task', ['deal_id'], unique=False)
    op.create_index(op.f('ix_task_job_id'), 'task', ['job_id'], unique=False)
    op.create_index(op.f('ix_task_status'), 'task', ['status'], unique=False)
    op.create_table('wall_member',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('wall_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['wall_id'], ['wall.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_wall_member_user_id'), 'wall_member', ['user_id'], unique=False)
    op.create_index(op.f('ix_wall_member_wall_id'), 'wall_member', ['wall_id'], unique=False)
    op.create_table('agent_run',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('task_id', sa.BigInteger(), nullable=True),
    sa.Column('archetype', sa.String(length=64), nullable=False),
    sa.Column('model_id', sa.String(length=128), nullable=False),
    sa.Column('model_version', sa.String(length=128), nullable=False),
    sa.Column('prompt_template_id', sa.String(length=128), nullable=False),
    sa.Column('prompt_hash', sa.String(length=64), nullable=False),
    sa.Column('input_digest', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('output', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('tokens_in', sa.Integer(), nullable=False),
    sa.Column('tokens_out', sa.Integer(), nullable=False),
    sa.Column('cost_inr', sa.Numeric(precision=20, scale=2), server_default='0', nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tool_calls', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('segment_id', sa.BigInteger(), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=True),
    sa.Column('span_id', sa.String(length=16), nullable=True),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.ForeignKeyConstraint(['segment_id'], ['segments.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['task.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_run_deal_id'), 'agent_run', ['deal_id'], unique=False)
    op.create_index(op.f('ix_agent_run_job_id'), 'agent_run', ['job_id'], unique=False)
    op.create_index(op.f('ix_agent_run_segment_id'), 'agent_run', ['segment_id'], unique=False)
    op.create_index(op.f('ix_agent_run_trace_id'), 'agent_run', ['trace_id'], unique=False)
    op.create_table('handoff',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('task_id', sa.BigInteger(), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('direction', sa.String(length=16), nullable=False),
    sa.Column('trigger', sa.String(length=32), nullable=False),
    sa.Column('context_package', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('directive', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('auto_escalate_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_by', sa.String(length=64), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("direction IN ('bot_to_human', 'human_to_bot')", name='ck_direction_valid'),
    sa.CheckConstraint("status IN ('open', 'resolved', 'escalated')", name='ck_status_valid'),
    sa.CheckConstraint("trigger IN ('confidence_below_threshold', 'materiality_gate', 'policy_required', 'explicit_request', 'human_correction', 'untrusted_content')", name='ck_trigger_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['task_id'], ['task.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_handoff_deal_id'), 'handoff', ['deal_id'], unique=False)
    op.create_index(op.f('ix_handoff_status'), 'handoff', ['status'], unique=False)
    op.create_index(op.f('ix_handoff_task_id'), 'handoff', ['task_id'], unique=False)
    op.create_table('eval_case_result',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('eval_run_id', sa.BigInteger(), nullable=False),
    sa.Column('case_id', sa.String(length=64), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('score', sa.Float(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('expected', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('actual', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('agent_run_id', sa.BigInteger(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['agent_run_id'], ['agent_run.id'], ),
    sa.ForeignKeyConstraint(['eval_run_id'], ['eval_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_eval_case_result_eval_run_id'), 'eval_case_result', ['eval_run_id'], unique=False)
    op.create_table('extraction',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('schema_name', sa.String(length=64), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.Column('feeds_valuation', sa.Boolean(), nullable=False),
    sa.Column('human_verified_by', sa.String(length=64), nullable=True),
    sa.Column('human_verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('model_run_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('NOT feeds_valuation OR confidence >= 0.95 OR human_verified_by IS NOT NULL', name='ck_extraction_valuation_gate'),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name='ck_extraction_confidence_range'),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.ForeignKeyConstraint(['model_run_id'], ['agent_run.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_extraction_document_id'), 'extraction', ['document_id'], unique=False)
    op.create_table('outbound_message',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('handoff_id', sa.BigInteger(), nullable=False),
    sa.Column('job_id', sa.BigInteger(), nullable=True),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('party_id', sa.BigInteger(), nullable=True),
    sa.Column('to_email', sa.String(length=254), nullable=False),
    sa.Column('subject', sa.String(length=500), nullable=False),
    sa.Column('mode', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('gmail_id', sa.String(length=128), nullable=True),
    sa.Column('gmail_thread_id', sa.String(length=128), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=True),
    sa.CheckConstraint("mode IN ('off', 'gmail_draft', 'gmail_send')", name='ck_mode_valid'),
    sa.CheckConstraint("status IN ('queued', 'drafted', 'sent', 'blocked', 'failed')", name='ck_status_valid'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['handoff_id'], ['handoff.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.ForeignKeyConstraint(['party_id'], ['party.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('handoff_id')
    )
    op.create_index(op.f('ix_outbound_message_deal_id'), 'outbound_message', ['deal_id'], unique=False)


def _drop_tables() -> None:
    # Generated from aura.data.models.tables (alembic check keeps the two in step).
    op.drop_index(op.f('ix_outbound_message_deal_id'), table_name='outbound_message')
    op.drop_table('outbound_message')
    op.drop_index(op.f('ix_extraction_document_id'), table_name='extraction')
    op.drop_table('extraction')
    op.drop_index(op.f('ix_eval_case_result_eval_run_id'), table_name='eval_case_result')
    op.drop_table('eval_case_result')
    op.drop_index(op.f('ix_handoff_task_id'), table_name='handoff')
    op.drop_index(op.f('ix_handoff_status'), table_name='handoff')
    op.drop_index(op.f('ix_handoff_deal_id'), table_name='handoff')
    op.drop_table('handoff')
    op.drop_index(op.f('ix_agent_run_trace_id'), table_name='agent_run')
    op.drop_index(op.f('ix_agent_run_segment_id'), table_name='agent_run')
    op.drop_index(op.f('ix_agent_run_job_id'), table_name='agent_run')
    op.drop_index(op.f('ix_agent_run_deal_id'), table_name='agent_run')
    op.drop_table('agent_run')
    op.drop_index(op.f('ix_wall_member_wall_id'), table_name='wall_member')
    op.drop_index(op.f('ix_wall_member_user_id'), table_name='wall_member')
    op.drop_table('wall_member')
    op.drop_index(op.f('ix_task_status'), table_name='task')
    op.drop_index(op.f('ix_task_job_id'), table_name='task')
    op.drop_index(op.f('ix_task_deal_id'), table_name='task')
    op.drop_table('task')
    op.drop_index(op.f('ix_stage_guard_evaluation_history_id'), table_name='stage_guard_evaluation')
    op.drop_index(op.f('ix_stage_guard_evaluation_guard_id'), table_name='stage_guard_evaluation')
    op.drop_index(op.f('ix_stage_guard_evaluation_deal_id'), table_name='stage_guard_evaluation')
    op.drop_table('stage_guard_evaluation')
    op.drop_index(op.f('ix_segments_status'), table_name='segments')
    op.drop_index(op.f('ix_segments_job_id'), table_name='segments')
    op.drop_table('segments')
    op.drop_index(op.f('ix_mandate_criteria_mandate_id'), table_name='mandate_criteria')
    op.drop_table('mandate_criteria')
    op.drop_table('idempotency_key')
    op.drop_index(op.f('ix_finding_diligence_item_id'), table_name='finding')
    op.drop_table('finding')
    op.drop_table('doc_version')
    op.drop_index('ix_doc_chunk_tsv', table_name='doc_chunk', postgresql_using='gin')
    op.drop_index('ix_doc_chunk_embedding_hnsw', table_name='doc_chunk', postgresql_using='hnsw', postgresql_with={'m': 16, 'ef_construction': 64}, postgresql_ops={'embedding': 'vector_cosine_ops'})
    op.drop_index(op.f('ix_doc_chunk_document_id'), table_name='doc_chunk')
    op.drop_index(op.f('ix_doc_chunk_deal_id'), table_name='doc_chunk')
    op.drop_table('doc_chunk')
    op.drop_index(op.f('ix_doc_access_log_document_id'), table_name='doc_access_log')
    op.drop_table('doc_access_log')
    op.drop_index(op.f('ix_deal_note_deal_id'), table_name='deal_note')
    op.drop_table('deal_note')
    op.drop_index(op.f('ix_audit_entries_job_id'), table_name='audit_entries')
    op.drop_index(op.f('ix_audit_entries_deal_id'), table_name='audit_entries')
    op.drop_index(op.f('ix_audit_entries_action'), table_name='audit_entries')
    op.drop_table('audit_entries')
    op.drop_table('wall')
    op.drop_index(op.f('ix_mandate_deal_id'), table_name='mandate')
    op.drop_table('mandate')
    op.drop_index(op.f('ix_jobs_trace_id'), table_name='jobs')
    op.drop_index(op.f('ix_jobs_status'), table_name='jobs')
    op.drop_table('jobs')
    op.drop_index(op.f('ix_document_deal_id'), table_name='document')
    op.drop_table('document')
    op.drop_index(op.f('ix_diligence_item_deal_id'), table_name='diligence_item')
    op.drop_table('diligence_item')
    op.drop_index(op.f('ix_deal_stage_history_deal_id'), table_name='deal_stage_history')
    op.drop_table('deal_stage_history')
    op.drop_index(op.f('ix_deal_signoff_deal_id'), table_name='deal_signoff')
    op.drop_table('deal_signoff')
    op.drop_table('deal_party')
    op.drop_index(op.f('ix_deal_intake_created_by'), table_name='deal_intake')
    op.drop_table('deal_intake')
    op.drop_index(op.f('ix_condition_precedent_deal_id'), table_name='condition_precedent')
    op.drop_table('condition_precedent')
    op.drop_index(op.f('ix_party_identifier_party_id'), table_name='party_identifier')
    op.drop_table('party_identifier')
    op.drop_index(op.f('ix_party_contact_party_id'), table_name='party_contact')
    op.drop_table('party_contact')
    op.drop_index('ix_deals_profile', table_name='deals', postgresql_using='gin')
    op.drop_index(op.f('ix_deals_external_id'), table_name='deals')
    op.drop_table('deals')
    op.drop_index(op.f('ix_checklist_item_template_template_id'), table_name='checklist_item_template')
    op.drop_table('checklist_item_template')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_trace_span_trace_id'), table_name='trace_span')
    op.drop_index(op.f('ix_trace_span_deal_id'), table_name='trace_span')
    op.drop_table('trace_span')
    op.drop_table('suppression')
    op.drop_index(op.f('ix_stage_guard_from_stage'), table_name='stage_guard')
    op.drop_table('stage_guard')
    op.drop_table('party')
    op.drop_index(op.f('ix_eval_run_capability'), table_name='eval_run')
    op.drop_table('eval_run')
    op.drop_table('checklist_template')
    op.drop_table('capability_autonomy')
