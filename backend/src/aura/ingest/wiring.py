"""Wiring the core search and indexing services to PostgreSQL and the embedder, for the API,
the worker and the eval runner."""
import threading
import time

from sqlalchemy.orm import Session

from aura.core.services.retrieval import Chunk
from aura.core.services.search import SearchParams, search
from aura.data.repositories.sql_ingest import SqlChunkRepository
from aura.data.walls import Viewer

_lock = threading.Lock()
_query_embedder = None


class QueryEmbedder:
    """Embeds search queries for interactive use: no retries, a short timeout, and after a
    failure it stays out of the way for `cooldown` seconds (search then runs on full text
    only) instead of making every request wait on a model that is down."""

    def __init__(self, inner, cooldown: float = 30.0):
        self.inner, self.cooldown = inner, cooldown
        self.model, self.dimensions = inner.model, inner.dimensions
        self._down_until = 0.0

    def embed(self, texts: list[str], kind: str = "query") -> list[list[float]]:
        if time.monotonic() < self._down_until:
            raise RuntimeError("embedding model unavailable (cooling down)")
        try:
            return self.inner.embed(texts, kind=kind)
        except Exception:
            self._down_until = time.monotonic() + self.cooldown
            raise


def query_embedder():
    """The process-wide query embedder built from settings (tests replace it)."""
    global _query_embedder
    with _lock:
        if _query_embedder is None:
            from aura.config import get_settings
            from aura.ingest.embedder import FakeEmbedder, OllamaEmbedder
            s = get_settings()
            inner = FakeEmbedder() if s.embedder == "fake" else OllamaEmbedder(
                s.ollama_base_url, s.embed_model, s.embed_batch, timeout=15.0, max_retries=0)
            _query_embedder = QueryEmbedder(inner)
        return _query_embedder


def set_query_embedder(embedder) -> None:
    global _query_embedder
    with _lock:
        _query_embedder = embedder


def search_params(k: int | None = None) -> SearchParams:
    from aura.config import get_settings
    s = get_settings()
    return SearchParams(k=k or s.retrieval_top_k, candidates=s.search_candidates,
                        rrf_k=s.rrf_k, ef_search=s.hnsw_ef_search)


def make_searcher(session: Session, viewer: Viewer, embedder=None):
    """A context_assembly Searcher: hybrid search as `viewer`, results as retrieval Chunks."""
    chunks = SqlChunkRepository(session, viewer)

    def run(deal_id: int, query: str, k: int) -> list[Chunk]:
        if not (query or "").strip():
            return []
        response = search(deal_id, query[:500], chunks,
                          embedder if embedder is not None else query_embedder(),
                          search_params(k))
        return [Chunk(document_id=r.document_id, filename=r.filename, index=r.chunk_index,
                      text=r.text, score=r.score, page_from=r.page_from, page_to=r.page_to,
                      source="hybrid") for r in response.results]
    return run


def make_indexed_text(session: Session, viewer: Viewer, limit_chars: int = 20_000):
    chunks = SqlChunkRepository(session, viewer)
    return lambda document_id: chunks.document_text(document_id, limit_chars)
