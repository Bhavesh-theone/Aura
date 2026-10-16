"""Hybrid search over a deal's indexed chunks (phase 2).

Two ranked lists, both read through the viewer's row-level security (a chunk of a deal the
viewer is not walled into is never returned):
- vector: the query embedded with the 'search_query' task, nearest chunks by cosine distance
  (pgvector `<=>`, HNSW with ef_search);
- full text: websearch_to_tsquery over the chunk's tsvector, ranked by ts_rank_cd, with a
  ts_headline snippet.
They are fused with Reciprocal Rank Fusion: score = sum over lists of 1 / (rrf_k + rank).
Ties break on chunk id, so the order is deterministic. If the embedder is unavailable the
search degrades to full text only and says so (mode 'fts_only').
"""
import time
from dataclasses import dataclass

from aura.core.domain.errors import RuleViolation
from aura.core.domain.ingest import ChunkHit, SearchResponse, SearchResult
from aura.core.ports.ingest import ChunkRepository, Embedder

HIGHLIGHT_START, HIGHLIGHT_END = "⟦", "⟧"
DEFAULT_RRF_K = 60
MAX_K = 50
SNIPPET_CHARS = 280


@dataclass(frozen=True)
class SearchParams:
    k: int = 8
    candidates: int = 40     # top-N taken from each list before fusion
    rrf_k: int = DEFAULT_RRF_K
    ef_search: int = 80


def rrf_fuse(lists: dict[str, list[ChunkHit]], rrf_k: int = DEFAULT_RRF_K
             ) -> list[tuple[float, ChunkHit, dict]]:
    """Fuse ranked lists. Returns (score, hit, per-list ranks), best first; ties by chunk id.
    The hit kept for a chunk prefers the full-text one (it carries the snippet)."""
    scores: dict[int, float] = {}
    ranks: dict[int, dict] = {}
    hits: dict[int, ChunkHit] = {}
    for name, hits_list in lists.items():
        for rank, hit in enumerate(hits_list, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (rrf_k + rank)
            ranks.setdefault(hit.chunk_id, {})[name] = (rank, hit)
            known = hits.get(hit.chunk_id)
            if known is None or (hit.snippet and not known.snippet):
                hits[hit.chunk_id] = hit
    ordered = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [(scores[cid], hits[cid], ranks[cid]) for cid in ordered]


def _snippet(hit: ChunkHit) -> str:
    if hit.snippet:
        return hit.snippet
    text = " ".join(hit.text.split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS].rsplit(" ", 1)[0] + " …"


def search(deal_id: int, query: str, chunks: ChunkRepository, embedder: Embedder | None,
           params: SearchParams = SearchParams()) -> SearchResponse:
    """The k best chunks of the deal for the query. `chunks` must be built for the viewer."""
    query = (query or "").strip()
    if not query:
        raise RuleViolation("q must not be empty")
    if len(query) > 500:
        raise RuleViolation("q must be at most 500 characters")
    k = max(1, min(int(params.k), MAX_K))
    n = max(k, params.candidates)
    started = time.perf_counter()
    warnings: list[str] = []
    lists: dict[str, list[ChunkHit]] = {}
    mode, model = "fts_only", None
    if embedder is not None:
        try:
            vector = embedder.embed([query], kind="query")[0]
            lists["vector"] = chunks.vector_search(deal_id, vector, n, params.ef_search)
            mode, model = "hybrid", embedder.model
        except Exception as exc:  # degrade, never fail the search on the embedder
            warnings.append(f"vector search unavailable ({type(exc).__name__}); "
                            "showing keyword matches only")
    lists["fts"] = chunks.text_search(deal_id, query, n)
    fused = rrf_fuse(lists, params.rrf_k)[:k]
    results = []
    for i, (score, hit, ranks) in enumerate(fused, start=1):
        vec, fts = ranks.get("vector"), ranks.get("fts")
        results.append(SearchResult(
            rank=i, chunk_id=hit.chunk_id, document_id=hit.document_id,
            filename=hit.filename, version=hit.version, chunk_index=hit.chunk_index,
            page_from=hit.page_from, page_to=hit.page_to, kind=hit.kind,
            snippet=_snippet(fts[1] if fts else hit), text=hit.text, score=round(score, 6),
            scores={"rrf": round(score, 6),
                    "vector_rank": vec[0] if vec else None,
                    "vector_distance": round(vec[1].distance, 6)
                    if vec and vec[1].distance is not None else None,
                    "fts_rank": fts[0] if fts else None,
                    "fts_score": round(fts[1].fts_score, 6)
                    if fts and fts[1].fts_score is not None else None}))
    return SearchResponse(query=query, k=k, mode=mode, embedding_model=model,
                          took_ms=int((time.perf_counter() - started) * 1000),
                          results=results, warnings=warnings)
