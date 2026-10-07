"""Keyword retrieval over a deal's own documents (harness category 2): plain BM25 in the
standard library, no embeddings, nothing leaves the machine. Deterministic: ties are broken by
document id and chunk number."""
import math
import re
from collections import Counter
from dataclasses import dataclass

CHUNK_CHARS = 600
CHUNK_OVERLAP = 100
_K1, _B = 1.5, 0.75
_STOP = frozenset("""a an and are as at be by for from has have in is it its of on or that the
this to was were will with we you your our their they he she his her not no but if then than
so such into about over under per pdf obj endobj stream endstream tj td tf bt et""".split())


@dataclass
class Chunk:
    document_id: int
    filename: str
    index: int
    text: str
    score: float = 0.0


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 1 and t not in _STOP]


def chunk(document_id: int, filename: str, text: str, size: int = CHUNK_CHARS,
          overlap: int = CHUNK_OVERLAP) -> list[Chunk]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    step = max(1, size - overlap)
    return [Chunk(document_id, filename, i, text[start:start + size])
            for i, start in enumerate(range(0, max(1, len(text) - overlap), step))]


def bm25(query: str, chunks: list[Chunk], top_k: int = 4) -> list[Chunk]:
    """The top_k chunks by BM25 score against the query; chunks scoring 0 are left out."""
    q = set(tokens(query))
    if not q or not chunks:
        return []
    docs = [tokens(c.text) for c in chunks]
    n = len(docs)
    avg = sum(len(d) for d in docs) / n or 1.0
    df = Counter(t for d in docs for t in set(d))
    scored = []
    for c, d in zip(chunks, docs):
        tf = Counter(d)
        score = 0.0
        for term in q:
            if tf[term]:
                idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf[term] * (_K1 + 1) / (
                    tf[term] + _K1 * (1 - _B + _B * len(d) / avg))
        if score > 0:
            scored.append(Chunk(c.document_id, c.filename, c.index, c.text, round(score, 4)))
    scored.sort(key=lambda c: (-c.score, c.document_id, c.index))
    return scored[:top_k]
