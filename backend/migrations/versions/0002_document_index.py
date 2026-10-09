"""Document indexing (phase 2): index state on document, chunk metadata, the indexing queue
(index_job) and embedding lineage (embed_run), both under row-level security.

Revision ID: 0002_document_index
Revises: 0001
Create Date: 2026-10-09

- document gains index_status (pending | indexed | failed), indexed_at, chunk_count, ocr_used,
  page_count, index_warnings and index_error. Existing documents start 'pending'; index them
  with `uv run python -m aura.ingest.backfill`.
- doc_chunk gains meta (heading, table header, prompt-injection screening of the chunk).
- index_job: one row per document, claimed with FOR UPDATE SKIP LOCKED by the worker.
- embed_run: one row per embedding batch.
index_job has a NOT NULL deal_id and embed_run a nullable one: they get the same wall policy
as the other deal-scoped tables (aura_is_system() or the deal is visible to aura.viewer).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_document_index'
down_revision = '0001'
branch_labels = None
depends_on = None

APP_ROLE = "aura_app"
_VISIBLE = "IN (SELECT unnest(aura_visible_deal_ids()))"
POLICIES = {
    "index_job": f"aura_is_system() OR deal_id {_VISIBLE}",
    "embed_run": f"aura_is_system() OR deal_id IS NULL OR deal_id {_VISIBLE}",
}


def upgrade() -> None:
    op.create_table('embed_run',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=True),
    sa.Column('document_id', sa.BigInteger(), nullable=True),
    sa.Column('model', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('batch_size', sa.Integer(), nullable=False),
    sa.Column('input_chars', sa.Integer(), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=True),
    sa.Column('span_id', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('document', 'query')", name='ck_embed_run_kind'),
    sa.CheckConstraint("status IN ('ok', 'error')", name='ck_embed_run_status'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_embed_run_deal_id'), 'embed_run', ['deal_id'], unique=False)
    op.create_table('index_job',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('document_id', sa.BigInteger(), nullable=False),
    sa.Column('deal_id', sa.BigInteger(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='queued', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('not_before', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claimed_by', sa.String(length=128), nullable=True),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.String(length=64), nullable=True),
    sa.Column('trace_id', sa.String(length=32), nullable=True),
    sa.Column('span_id', sa.String(length=16), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('queued', 'running', 'done', 'dead_letter')", name='ck_index_job_status'),
    sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], ),
    sa.ForeignKeyConstraint(['document_id'], ['document.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('document_id')
    )
    op.create_index(op.f('ix_index_job_deal_id'), 'index_job', ['deal_id'], unique=False)
    op.create_index('ix_index_job_runnable', 'index_job', ['status', 'not_before'], unique=False)
    op.add_column('doc_chunk', sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False))
    op.add_column('document', sa.Column('index_status', sa.String(length=16), server_default='pending', nullable=False))
    op.add_column('document', sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('document', sa.Column('chunk_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('document', sa.Column('ocr_used', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('document', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('document', sa.Column('index_warnings', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('document', sa.Column('index_error', sa.Text(), nullable=True))
    op.create_check_constraint("ck_document_index_status", "document",
                               "index_status IN ('pending', 'indexed', 'failed')")
    for table, expr in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY wall_visibility ON {table} USING ({expr}) "
                   f"WITH CHECK ({expr})")
    op.execute(f"""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON index_job, embed_run TO {APP_ROLE};
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};
      END IF;
    END $$""")


def downgrade() -> None:
    for table in POLICIES:
        op.execute(f"DROP POLICY IF EXISTS wall_visibility ON {table}")
    op.drop_constraint("ck_document_index_status", "document", type_="check")
    op.drop_column('document', 'index_error')
    op.drop_column('document', 'index_warnings')
    op.drop_column('document', 'page_count')
    op.drop_column('document', 'ocr_used')
    op.drop_column('document', 'chunk_count')
    op.drop_column('document', 'indexed_at')
    op.drop_column('document', 'index_status')
    op.drop_column('doc_chunk', 'meta')
    op.drop_index('ix_index_job_runnable', table_name='index_job')
    op.drop_index(op.f('ix_index_job_deal_id'), table_name='index_job')
    op.drop_table('index_job')
    op.drop_index(op.f('ix_embed_run_deal_id'), table_name='embed_run')
    op.drop_table('embed_run')
