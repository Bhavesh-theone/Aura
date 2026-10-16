"""Deal intake (phase 3): documents staged on an intake before the deal exists, the
intake's extraction queue and progress, and intake-scoped model runs.

Revision ID: 0004_deal_intake
Revises: 0003_embed_run_vlm_page
Create Date: 2026-10-13

- document, doc_chunk and index_job: deal_id becomes nullable and intake_id (FK deal_intake)
  is added; every row has one or the other (CHECK). A staged file is a normal document row
  with deal_id NULL, indexed by the normal queue; confirming the intake re-points the
  document, its chunks and its index job to the new deal (nothing is parsed twice) and keeps
  intake_id as lineage.
- agent_run gains intake_id: the intake extractor's model calls (archetype
  'intake_extractor'), re-pointed to the deal on confirm.
- deal_intake gains hints, external_id, progress, the extraction queue columns
  (extract_status, attempts, not_before, claimed_by/at, error, meta) and trace ids.
- Row-level security: a row with no deal but an intake is visible only to the intake's
  creator (aura_viewer_intake_ids(), SECURITY DEFINER over deal_intake). agent_run rows of an
  intake are no longer visible to everyone like other deal-less runs.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004_deal_intake'
down_revision = '0003_embed_run_vlm_page'
branch_labels = None
depends_on = None

APP_ROLE = "aura_app"
_VISIBLE = "IN (SELECT unnest(aura_visible_deal_ids()))"
_MINE = "IN (SELECT unnest(aura_viewer_intake_ids()))"
STAGED = ("document", "doc_chunk", "index_job")
NEW_POLICIES = {
    **{t: f"aura_is_system() OR deal_id {_VISIBLE} OR (deal_id IS NULL AND intake_id {_MINE})"
       for t in STAGED},
    "agent_run": (f"aura_is_system() OR deal_id {_VISIBLE} OR "
                  f"(deal_id IS NULL AND (intake_id IS NULL OR intake_id {_MINE}))"),
}
OLD_POLICIES = {
    **{t: f"aura_is_system() OR deal_id {_VISIBLE}" for t in STAGED},
    "agent_run": f"aura_is_system() OR deal_id IS NULL OR deal_id {_VISIBLE}",
}
FUNCTION = """CREATE FUNCTION aura_viewer_intake_ids() RETURNS bigint[] LANGUAGE sql STABLE
  SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT coalesce(array_agg(id), '{}'::bigint[]) FROM deal_intake
   WHERE created_by = aura_viewer() $$"""


def _policies(policies: dict[str, str]) -> None:
    for table, expr in policies.items():
        op.execute(f"DROP POLICY IF EXISTS wall_visibility ON {table}")
        op.execute(f"CREATE POLICY wall_visibility ON {table} USING ({expr}) "
                   f"WITH CHECK ({expr})")


def upgrade() -> None:
    for table in STAGED:
        op.add_column(table, sa.Column('intake_id', sa.BigInteger(), nullable=True))
        op.create_foreign_key(f'fk_{table}_intake_id', table, 'deal_intake',
                              ['intake_id'], ['id'])
        op.create_index(op.f(f'ix_{table}_intake_id'), table, ['intake_id'], unique=False)
        op.alter_column(table, 'deal_id', existing_type=sa.BigInteger(), nullable=True)
        op.create_check_constraint(f'ck_{table}_deal_or_intake', table,
                                   'deal_id IS NOT NULL OR intake_id IS NOT NULL')
    op.add_column('agent_run', sa.Column('intake_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_agent_run_intake_id', 'agent_run', 'deal_intake',
                          ['intake_id'], ['id'])
    op.create_index(op.f('ix_agent_run_intake_id'), 'agent_run', ['intake_id'], unique=False)

    jsonb_obj = sa.text("'{}'::jsonb")
    op.add_column('deal_intake', sa.Column('hints', postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=jsonb_obj, nullable=False))
    op.add_column('deal_intake', sa.Column('external_id', sa.String(length=32), nullable=True))
    op.add_column('deal_intake', sa.Column('progress', postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=jsonb_obj, nullable=False))
    op.add_column('deal_intake', sa.Column('extract_status', sa.String(length=16),
                                           server_default='idle', nullable=False))
    op.add_column('deal_intake', sa.Column('extract_attempts', sa.Integer(),
                                           server_default='0', nullable=False))
    op.add_column('deal_intake', sa.Column('extract_not_before', sa.DateTime(timezone=True),
                                           nullable=True))
    op.add_column('deal_intake', sa.Column('extract_claimed_by', sa.String(length=128),
                                           nullable=True))
    op.add_column('deal_intake', sa.Column('extract_claimed_at', sa.DateTime(timezone=True),
                                           nullable=True))
    op.add_column('deal_intake', sa.Column('extract_error', sa.Text(), nullable=True))
    op.add_column('deal_intake', sa.Column('extract_meta',
                                           postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=jsonb_obj, nullable=False))
    op.add_column('deal_intake', sa.Column('trace_id', sa.String(length=32), nullable=True))
    op.add_column('deal_intake', sa.Column('span_id', sa.String(length=16), nullable=True))
    op.create_check_constraint(
        'ck_intake_extract_status', 'deal_intake',
        "extract_status IN ('idle', 'queued', 'running', 'done', 'dead_letter')")
    op.create_index('ix_deal_intake_extract_runnable', 'deal_intake',
                    ['extract_status', 'extract_not_before'], unique=False)

    op.execute(FUNCTION)
    _policies(NEW_POLICIES)
    # Deal ids for intakes confirmed without one (AUR-0001, ...): a sequence, because the app
    # role cannot see every deal (RLS) to work out the next free number.
    op.execute("CREATE SEQUENCE aura_deal_external_id_seq")
    op.execute(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT USAGE, SELECT ON SEQUENCE aura_deal_external_id_seq TO {APP_ROLE};
        GRANT EXECUTE ON FUNCTION aura_viewer_intake_ids() TO {APP_ROLE};
      END IF;
    END $$""")


def downgrade() -> None:
    _policies(OLD_POLICIES)
    op.execute("DROP SEQUENCE IF EXISTS aura_deal_external_id_seq")
    op.execute("DROP FUNCTION IF EXISTS aura_viewer_intake_ids()")
    op.drop_index('ix_deal_intake_extract_runnable', table_name='deal_intake')
    op.drop_constraint('ck_intake_extract_status', 'deal_intake', type_='check')
    for col in ('span_id', 'trace_id', 'extract_meta', 'extract_error', 'extract_claimed_at',
                'extract_claimed_by', 'extract_not_before', 'extract_attempts',
                'extract_status', 'progress', 'external_id', 'hints'):
        op.drop_column('deal_intake', col)
    op.drop_index(op.f('ix_agent_run_intake_id'), table_name='agent_run')
    op.drop_constraint('fk_agent_run_intake_id', 'agent_run', type_='foreignkey')

    op.drop_column('agent_run', 'intake_id')
    # Staged files of intakes never confirmed have no deal: they cannot survive the downgrade.
    op.execute("DELETE FROM doc_chunk WHERE deal_id IS NULL")
    op.execute("DELETE FROM index_job WHERE deal_id IS NULL")
    op.execute("DELETE FROM doc_access_log WHERE document_id IN "
               "(SELECT id FROM document WHERE deal_id IS NULL)")
    op.execute("DELETE FROM doc_version WHERE document_id IN "
               "(SELECT id FROM document WHERE deal_id IS NULL)")
    op.execute("DELETE FROM extraction WHERE document_id IN "
               "(SELECT id FROM document WHERE deal_id IS NULL)")
    op.execute("UPDATE embed_run SET document_id = NULL WHERE document_id IN "
               "(SELECT id FROM document WHERE deal_id IS NULL)")
    op.execute("DELETE FROM document WHERE deal_id IS NULL")
    for table in reversed(STAGED):
        op.drop_constraint(f'ck_{table}_deal_or_intake', table, type_='check')
        op.alter_column(table, 'deal_id', existing_type=sa.BigInteger(), nullable=False)
        op.drop_index(op.f(f'ix_{table}_intake_id'), table_name=table)
        op.drop_constraint(f'fk_{table}_intake_id', table, type_='foreignkey')
        op.drop_column(table, 'intake_id')
