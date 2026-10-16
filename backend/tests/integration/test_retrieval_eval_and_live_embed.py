"""The retrieval eval (fake embedder, in the test database), and one live check of the
Ollama embedder that runs only when nomic-embed-text answers locally."""
import os

import pytest
from sqlalchemy import text

from aura.config import get_settings
from aura.evals.retrieval import evaluate_retrieval
from aura.evals.run import load_golden
from aura.ingest.embedder import FakeEmbedder, OllamaEmbedder, embedder_available


def test_retrieval_eval_scores_the_golden_set_and_leaves_no_pack_behind(api):
    cases, digest = load_golden("retrieval")
    assert len(cases) >= 12
    run = evaluate_retrieval(api.session, FakeEmbedder(), cases, digest, threshold=0.8)
    assert run.id is not None and run.capability == "retrieval"
    assert run.metrics["recall_at_5"] >= 0.8 and run.metrics["mrr"] >= 0.6, run.metrics
    assert run.metrics["ocr_used"] == ["nilgiri_information_memorandum.pdf"]
    by_id = {c.case_id: c for c in run.cases}
    assert by_id["ret-001"].passed  # the OCR'd scanned page is findable
    for table in ("deals", "document", "doc_chunk"):
        n = api.session.execute(text(f"SELECT COUNT(*) FROM {table} WHERE "
                                     + ("external_id = 'EVAL-RETRIEVAL'" if table == "deals"
                                        else "true"))).scalar()
        assert n == 0, table
    assert api.session.execute(text("SELECT COUNT(*) FROM eval_run WHERE capability = "
                                    "'retrieval'")).scalar() == 1


def _live_embedder():
    s = get_settings()
    return OllamaEmbedder(os.environ.get("AURA_LIVE_OLLAMA_URL", "http://127.0.0.1:11434"),
                          s.embed_model, timeout=30.0, max_retries=0)


@pytest.mark.skipif(not embedder_available(_live_embedder(), timeout=2.0),
                    reason="Ollama with nomic-embed-text is not reachable at 127.0.0.1:11434")
def test_live_ollama_nomic_embeddings_are_768_wide_and_rank_sensibly():
    e = _live_embedder()
    docs = e.embed(["The escrow holds ten percent of the purchase price.",
                    "The cafeteria serves idli and dosa on Mondays."])
    (query,) = e.embed(["how much money is held in escrow"], kind="query")
    assert len(docs) == 2 and all(len(v) == 768 for v in docs + [query])

    def cos(u, v):
        return sum(a * b for a, b in zip(u, v)) / (
            sum(a * a for a in u) ** 0.5 * sum(b * b for b in v) ** 0.5)
    assert cos(query, docs[0]) > cos(query, docs[1])
