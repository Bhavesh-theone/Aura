"""Embedders: the Embedder port.

OllamaEmbedder calls a local Ollama (POST /api/embed) with nomic-embed-text, which wants a task
prefix: "search_document: " for what is stored and "search_query: " for what is searched.
Requests go in batches (embed_batch), transient failures (connection refused, timeout, 5xx)
are retried with backoff, and every vector is checked to have 768 dimensions.

FakeEmbedder is deterministic (hashed word and character-trigram features, L2-normalised,
768 dimensions): no model, no network. Texts that share words land close together, so the
hybrid search behaves sensibly in tests.
"""
import hashlib
import math
import re
import time

import httpx

from aura.core.domain.ingest import EmbeddingError
from aura.core.ports.orchestrator import TransientModelError

DIMENSIONS = 768
PREFIX = {"document": "search_document: ", "query": "search_query: "}
MAX_INPUT_CHARS = 8000  # nomic-embed-text's context is 2048 tokens (8192 with RoPE scaling)


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str = "nomic-embed-text", batch: int = 16,
                 timeout: float = 60.0, max_retries: int = 2, backoff: float = 1.0,
                 dimensions: int = DIMENSIONS, client: httpx.Client | None = None,
                 sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.model, self.batch, self.dimensions = model, max(1, batch), dimensions
        self.max_retries, self.backoff, self._sleep = max_retries, backoff, sleep
        self._client = client or httpx.Client(timeout=timeout)

    def _post(self, inputs: list[str]) -> list[list[float]]:
        attempt = 0
        while True:
            try:
                r = self._client.post(f"{self.base_url}/api/embed",
                                      json={"model": self.model, "input": inputs,
                                            "truncate": True})
                if r.status_code >= 500 or r.status_code == 429:
                    raise TransientModelError(f"Ollama /api/embed answered {r.status_code}: "
                                              f"{r.text[:200]}")
                if r.status_code == 404:
                    raise EmbeddingError(f"embedding model {self.model!r} is not available in "
                                         f"Ollama (ollama pull {self.model})")
                r.raise_for_status()
                vectors = r.json().get("embeddings")
                if not isinstance(vectors, list):
                    raise EmbeddingError("Ollama /api/embed returned no embeddings")
                return vectors
            except (httpx.TransportError, TransientModelError) as exc:
                if attempt >= self.max_retries:
                    if isinstance(exc, TransientModelError):
                        raise
                    raise TransientModelError(f"Ollama unreachable at {self.base_url}: "
                                              f"{exc}") from exc
                self._sleep(self.backoff * 2 ** attempt)
                attempt += 1

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if kind not in PREFIX:
            raise ValueError(f"kind must be one of {sorted(PREFIX)}")
        prefixed = [PREFIX[kind] + (t or " ")[:MAX_INPUT_CHARS] for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(prefixed), self.batch):
            group = prefixed[i:i + self.batch]
            vectors = self._post(group)
            if len(vectors) != len(group):
                raise EmbeddingError(f"{len(vectors)} embeddings for {len(group)} inputs")
            for v in vectors:
                if len(v) != self.dimensions:
                    raise EmbeddingError(f"{self.model} returned {len(v)} dimensions, "
                                         f"expected {self.dimensions}")
            out.extend([float(x) for x in v] for v in vectors)
        return out


_WORD = re.compile(r"[a-z0-9]+")


class FakeEmbedder:
    model = "fake-hash-768"

    def __init__(self, dimensions: int = DIMENSIONS):
        self.dimensions = dimensions
        self.calls: list[tuple[int, str]] = []

    def _vector(self, text: str) -> list[float]:
        v = [0.0] * self.dimensions
        words = _WORD.findall((text or "").lower())
        feats = [(w, 1.0) for w in words]
        feats += [(f"#{w[i:i + 3]}", 0.3) for w in words if len(w) > 3
                  for i in range(len(w) - 2)]
        for feat, weight in feats:
            h = hashlib.blake2b(feat.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dimensions
            v[idx] += weight if h[4] & 1 else -weight
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        if norm == 1.0 and not any(v):
            v[0] = 1.0
            return v
        return [x / norm for x in v]

    def embed(self, texts: list[str], kind: str = "document") -> list[list[float]]:
        if kind not in PREFIX:
            raise ValueError(f"kind must be one of {sorted(PREFIX)}")
        self.calls.append((len(texts), kind))
        return [self._vector(t) for t in texts]


def make_embedder(settings=None):
    """The configured embedder (AURA_EMBEDDER=ollama|fake)."""
    if settings is None:
        from aura.config import get_settings
        settings = get_settings()
    if settings.embedder == "fake":
        return FakeEmbedder()
    return OllamaEmbedder(settings.ollama_base_url, settings.embed_model, settings.embed_batch,
                          settings.embed_timeout_seconds, settings.embed_max_retries)


def embedder_available(embedder, timeout: float = 3.0) -> bool:
    if isinstance(embedder, FakeEmbedder):
        return True
    try:
        r = httpx.get(f"{embedder.base_url}/api/tags", timeout=timeout)
        names = {m.get("name", "").split(":")[0] for m in r.json().get("models", [])}
        return r.status_code == 200 and embedder.model.split(":")[0] in names
    except Exception:
        return False
