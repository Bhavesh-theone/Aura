"""embed_run also records vision-model page reads (kind 'vlm_page').

Revision ID: 0003_embed_run_vlm_page
Revises: 0002_document_index
Create Date: 2026-10-12

A scanned PDF page read by the local vision model during indexing (AURA_SCAN_VLM) is lineage
of a model call made for ingestion, like an embedding batch: one embed_run row per page
(batch_size 1, input_chars = characters transcribed, dimensions NULL). It is deliberately not
an agent_run row, which would count against the daily model budget and the autonomy metrics.
"""
from alembic import op

revision = '0003_embed_run_vlm_page'
down_revision = '0002_document_index'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint('ck_embed_run_kind', 'embed_run', type_='check')
    op.create_check_constraint('ck_embed_run_kind', 'embed_run',
                               "kind IN ('document', 'query', 'vlm_page')")


def downgrade() -> None:
    op.execute("DELETE FROM embed_run WHERE kind = 'vlm_page'")
    op.drop_constraint('ck_embed_run_kind', 'embed_run', type_='check')
    op.create_check_constraint('ck_embed_run_kind', 'embed_run',
                               "kind IN ('document', 'query')")
