"""Chunking invariants, the embedders (fake, and Ollama over a mocked transport), Reciprocal
Rank Fusion and the search service's degradation, all without a database."""
import json
from pathlib import Path

import httpx
import pytest

from aura.core.domain.ingest import Block, ChunkHit, EmbeddingError, ParsedDocument
from aura.core.ports.ingest import Embedder
from aura.core.ports.orchestrator import TransientModelError
from aura.core.services.chunking import ChunkingParams, chunk_document
from aura.core.services.search import SearchParams, rrf_fuse, search
from aura.ingest.embedder import DIMENSIONS, FakeEmbedder, OllamaEmbedder
from aura.ingest.parsers import ParserLimits, parse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingest"
SMALL = ChunkingParams(target_tokens=60, overlap_tokens=10)  # 240 chars, 40 overlap


def _words(n: int, start: int = 0) -> str:
    return " ".join(f"word{i}" for i in range(start, start + n)) + "."


# ------------------------------------------------------------------ chunking

def test_same_input_gives_the_same_chunks():
    parsed = parse((FIXTURES / "nilgiri_spa_draft.docx").read_bytes(), "spa.docx",
                   limits=ParserLimits())
    assert chunk_document(parsed) == chunk_document(parsed)
    assert [c.index for c in chunk_document(parsed)] == list(range(len(chunk_document(parsed))))


def test_long_text_is_windowed_to_the_target_with_overlap_and_no_text_lost():
    text = _words(400)
    chunks = chunk_document(ParsedDocument([Block("text", text, 1)]), SMALL)
    assert len(chunks) > 5
    assert all(len(c.text) <= SMALL.target_chars for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        tail = a.text.split()[-3:]
        assert all(w in b.text.split() for w in tail[-2:]), "consecutive chunks overlap"
    covered = set(" ".join(c.text for c in chunks).split())
    assert covered == set(text.split())
    assert all(not c.text[0].isspace() and c.text.split()[0].startswith("word")
               for c in chunks)  # windows start at a word, never mid-word


def test_headings_start_new_chunks_and_consecutive_headings_stay_together():
    blocks = [Block("heading", "Agreement", 1), Block("heading", "1. Price", 1),
              Block("text", "Price is INR 312 crore.", 1), Block("heading", "2. Escrow", 2),
              Block("text", "Ten percent in escrow.", 2)]
    chunks = chunk_document(ParsedDocument(blocks))
    assert [c.text for c in chunks] == ["Agreement\n\n1. Price\n\nPrice is INR 312 crore.",
                                        "2. Escrow\n\nTen percent in escrow."]
    assert [c.heading for c in chunks] == ["1. Price", "2. Escrow"]
    assert [(c.page_from, c.page_to) for c in chunks] == [(1, 1), (2, 2)]


def test_text_spanning_pages_records_the_page_range():
    blocks = [Block("text", "Alpha " * 10, 3), Block("text", "Beta " * 10, 4)]
    (chunk,) = chunk_document(ParsedDocument(blocks))
    assert (chunk.page_from, chunk.page_to) == (3, 4)


def test_tables_are_split_by_whole_rows_with_the_header_repeated():
    header = ["Lender", "Facility", "Amount"]
    rows = [header] + [[f"Bank {i}", "Term loan", str(i * 10)] for i in range(60)]
    blocks = [Block("heading", "Sheet: Debt"), Block("table", "", 5, rows=rows)]
    chunks = chunk_document(ParsedDocument(blocks), SMALL)
    assert len(chunks) > 3 and all(c.kind == "table" for c in chunks)
    seen = []
    for c in chunks:
        lines = c.text.split("\n")
        assert lines[0] == "Sheet: Debt" and lines[1] == "Lender | Facility | Amount"
        for line in lines[2:]:
            assert line.count(" | ") == 2, "a row is never cut"
            seen.append(line)
        assert c.page_from == c.page_to == 5
    assert seen == [" | ".join(r) for r in rows[1:]]  # every row once, in order


def test_a_single_row_longer_than_the_target_is_its_own_chunk():
    rows = [["k", "v"], ["a", "x" * 1000], ["b", "short"]]
    chunks = chunk_document(ParsedDocument([Block("table", "", None, rows=rows)]), SMALL)
    assert [c.text.split("\n")[1:] for c in chunks] == [["a | " + "x" * 1000], ["b | short"]]


def test_empty_documents_give_no_chunks():
    assert chunk_document(ParsedDocument([])) == []
    assert chunk_document(ParsedDocument([Block("text", "   ")])) == []


# ------------------------------------------------------------------ embedders

def test_fake_embedder_is_deterministic_normalised_and_768_wide():
    e = FakeEmbedder()
    assert isinstance(e, Embedder)
    a, b = e.embed(["GST show cause notice", "GST show cause notice"])
    assert a == b and len(a) == DIMENSIONS
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
    near, far = e.embed(["show cause notice GST demand", "cafeteria menu"], kind="query")

    def cos(u, v):
        return sum(x * y for x, y in zip(u, v))
    assert cos(a, near) > cos(a, far)
    assert e.embed([""])[0][0] == 1.0  # no features: still a unit vector


def _ollama(handler, **kw) -> OllamaEmbedder:
    return OllamaEmbedder("http://127.0.0.1:11434", batch=kw.pop("batch", 2),
                          client=httpx.Client(transport=httpx.MockTransport(handler)),
                          sleep=lambda s: None, **kw)


def test_ollama_embedder_prefixes_batches_and_checks_dimensions():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body["input"])
        assert request.url.path == "/api/embed" and body["model"] == "nomic-embed-text"
        return httpx.Response(200, json={"embeddings": [[0.1] * 768 for _ in body["input"]]})
    e = _ollama(handler)
    out = e.embed(["a", "b", "c"])
    assert len(out) == 3 and seen == [["search_document: a", "search_document: b"],
                                      ["search_document: c"]]
    e.embed(["q"], kind="query")
    assert seen[-1] == ["search_query: q"]


def test_ollama_embedder_rejects_the_wrong_dimension():
    e = _ollama(lambda r: httpx.Response(200, json={"embeddings": [[0.0] * 384]}))
    with pytest.raises(EmbeddingError, match="384 dimensions"):
        e.embed(["x"])


def test_ollama_embedder_retries_transient_errors_then_gives_up_as_transient():
    calls = []

    def flaky(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("refused")
        if len(calls) == 2:
            return httpx.Response(503, text="loading")
        return httpx.Response(200, json={"embeddings": [[0.0] * 768]})
    assert len(_ollama(flaky, max_retries=2).embed(["x"])) == 1 and len(calls) == 3

    def down(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(TransientModelError):
        _ollama(down, max_retries=1).embed(["x"])


def test_ollama_embedder_missing_model_is_permanent():
    e = _ollama(lambda r: httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(EmbeddingError, match="ollama pull"):
        e.embed(["x"])


# ------------------------------------------------------------------ fusion and search

def _hit(cid, **kw) -> ChunkHit:
    return ChunkHit(chunk_id=cid, document_id=cid * 10, filename=f"d{cid}.pdf", version=1,
                    chunk_index=0, text=f"text {cid}", kind="text", page_from=1, page_to=1,
                    **kw)


def test_rrf_rewards_agreement_and_breaks_ties_by_chunk_id():
    vector = [_hit(1, distance=0.1), _hit(2, distance=0.2), _hit(3, distance=0.3)]
    fts = [_hit(3, fts_score=0.9, snippet="⟦x⟧"), _hit(4, fts_score=0.5)]
    fused = rrf_fuse({"vector": vector, "fts": fts}, rrf_k=60)
    ids = [h.chunk_id for _, h, _ in fused]
    assert ids[0] == 3  # in both lists
    assert ids[1:] == [1, 2, 4] or ids[1:] == [1, 4, 2]
    score_1 = 1 / 61
    assert fused[1][0] == pytest.approx(score_1)
    # 2 (vector rank 2) and 4 (fts rank 2) tie: the lower chunk id wins
    tied = rrf_fuse({"vector": [_hit(9), _hit(5)], "fts": [_hit(8), _hit(6)]})
    assert [h.chunk_id for _, h, _ in tied] == [8, 9, 5, 6]
    assert fused[0][1].snippet == "⟦x⟧"  # the full-text hit carries the snippet


class _Chunks:
    def __init__(self):
        self.vector_calls = 0

    def vector_search(self, deal_id, vector, limit, ef_search):
        self.vector_calls += 1
        return [_hit(1, distance=0.05), _hit(2, distance=0.4)]

    def text_search(self, deal_id, query, limit):
        return [_hit(2, fts_score=1.2, snippet="the ⟦escrow⟧ amount")]


class _Down:
    model, dimensions = "nomic-embed-text", 768

    def embed(self, texts, kind="document"):
        raise TransientModelError("refused")


def test_search_fuses_both_lists_and_reports_the_score_breakdown():
    chunks = _Chunks()
    out = search(7, "escrow", chunks, FakeEmbedder(), SearchParams(k=5))
    assert out.mode == "hybrid" and out.embedding_model == "fake-hash-768"
    assert [r.chunk_id for r in out.results] == [2, 1]
    top = out.results[0]
    assert top.snippet == "the ⟦escrow⟧ amount"
    assert top.scores["vector_rank"] == 2 and top.scores["fts_rank"] == 1
    assert out.results[1].scores["fts_rank"] is None
    assert out.results[1].snippet == "text 1"


def test_search_degrades_to_full_text_when_the_embedder_is_down():
    chunks = _Chunks()
    out = search(7, "escrow", chunks, _Down())
    assert out.mode == "fts_only" and chunks.vector_calls == 0
    assert out.warnings and [r.chunk_id for r in out.results] == [2]


def test_search_rejects_an_empty_query_and_caps_k():
    from aura.core.domain.errors import RuleViolation
    with pytest.raises(RuleViolation):
        search(1, "   ", _Chunks(), None)
    assert search(1, "x", _Chunks(), None, SearchParams(k=500)).k == 50
