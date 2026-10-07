"""Context assembly (harness category 2): what a model is shown, built deterministically.

- The subject document's text is read through the job user's wall-scoped repositories, both
  at submit and again when the segment runs (assemble_context), so a wall change after submit
  applies: a document the user can no longer see fails the segment instead of leaking.
- Retrieval: for classify_document and draft_email, the deal's other documents are chunked and
  ranked with BM25 (aura.core.services.retrieval); the best chunks ride along with citations.
- Every piece of document text is screened for prompt injection and wrapped as untrusted data
  (aura.core.policy.injection_policy); the screening record goes into the context.
- Compaction: the whole block is capped at max_chars. The least relevant retrieved chunks are
  dropped first, then the excerpt is truncated; what was dropped is recorded.
"""
from dataclasses import dataclass

from aura.core.domain.errors import NotFound
from aura.core.policy.injection_policy import DEFAULT_THRESHOLD, screen_and_wrap, summarise
from aura.core.ports.repositories import DocumentRepository, FileStore
from aura.core.services.retrieval import Chunk, bm25, chunk

RETRIEVAL_CAPABILITIES = frozenset({"classify_document", "draft_email"})
DOCUMENT_CAPABILITIES = frozenset({"classify_document", "extract_financials"})


@dataclass(frozen=True)
class ContextLimits:
    max_chars: int = 6000
    excerpt_chars: int = 2000
    retrieval_top_k: int = 4
    retrieval_doc_chars: int = 20_000
    injection_threshold: float = DEFAULT_THRESHOLD


def _query(context: dict, raw_excerpt: str) -> str:
    if context.get("capability") == "classify_document":
        doc = context.get("document") or {}
        return f"{doc.get('filename', '')} {raw_excerpt[:500]}"
    party, deal = context.get("party") or {}, context.get("deal") or {}
    return f"{context.get('brief', '')} {party.get('display_name', '')} {deal.get('name', '')}"


def compose(context: dict, raw_excerpt: str | None, related: list[Chunk],
            limits: ContextLimits = ContextLimits()) -> dict:
    """The context with its document block screened, wrapped, retrieved and capped. Pure:
    takes the texts already read, so the eval runner and the worker build the same thing."""
    out = dict(context)
    items: list[dict] = []
    budget = limits.max_chars
    truncated = None
    if raw_excerpt is not None and "document" in out:
        doc = dict(out["document"])
        text = raw_excerpt[:limits.excerpt_chars]
        source = f"document {doc.get('id')} ({doc.get('filename')})"
        wrapped, result = screen_and_wrap(text, source)
        if len(wrapped) > budget:
            overhead = len(wrapped) - len(result.text)
            keep = max(0, budget - overhead)
            truncated = {"document_id": doc.get("id"), "kept_chars": keep,
                         "dropped_chars": len(result.text) - keep}
            wrapped, _ = screen_and_wrap(result.text[:keep], source)
        doc["excerpt"] = wrapped
        out["document"] = doc
        budget -= len(wrapped)
        items.append(result.as_dict(f"document:{doc.get('id')}"))

    kept, dropped = [], []
    for c in related:
        wrapped, result = screen_and_wrap(
            c.text, f"document {c.document_id} ({c.filename}), chunk {c.index}")
        item = {"document_id": c.document_id, "filename": c.filename, "chunk": c.index,
                "score": c.score}
        if len(wrapped) <= budget:
            budget -= len(wrapped)
            kept.append({**item, "text": wrapped})
            items.append(result.as_dict(f"document:{c.document_id}#chunk{c.index}"))
        else:
            dropped.append({**item, "chars": len(wrapped)})
    if related or "related" in out:
        out["related"] = kept
        out["citations"] = sorted({k["document_id"] for k in kept})
    out["screening"] = summarise(items, limits.injection_threshold)
    out["context_budget"] = {"max_chars": limits.max_chars,
                             "used_chars": limits.max_chars - budget,
                             "dropped": dropped, "truncated": truncated}
    return out


def assemble_context(context: dict, documents: DocumentRepository | None,
                     store: FileStore | None,
                     limits: ContextLimits = ContextLimits()) -> dict:
    """Re-read the subject document and the related chunks through `documents` (built for the
    job's user) and compose the context. Contexts with no capability pass through."""
    capability = context.get("capability")
    if capability not in DOCUMENT_CAPABILITIES | RETRIEVAL_CAPABILITIES:
        return context
    deal_id = (context.get("deal") or {}).get("id")
    out = dict(context)
    raw = None
    subject_id = None
    if capability in DOCUMENT_CAPABILITIES:
        subject_id = (context.get("document") or {}).get("id")
        doc = documents.get(subject_id) if documents is not None and \
            isinstance(subject_id, int) else None
        if doc is None or doc.deal_id != deal_id:
            raise NotFound("The document is not on this deal or is no longer visible to the "
                           "job's user")
        raw = store.read_head(doc.sha256, limits.excerpt_chars) if store else ""
        out["document"] = {**(context.get("document") or {}), "id": doc.id,
                           "filename": doc.filename, "current_class": doc.doc_class.value,
                           "version": doc.current_version}
    related: list[Chunk] = []
    if capability in RETRIEVAL_CAPABILITIES and documents is not None and store is not None \
            and isinstance(deal_id, int) and limits.retrieval_top_k > 0:
        corpus: list[Chunk] = []
        for d in sorted(documents.list_for_deal(deal_id), key=lambda d: d.id):
            if d.id != subject_id:
                corpus += chunk(d.id, d.filename,
                                store.read_head(d.sha256, limits.retrieval_doc_chars))
        related = bm25(_query(out, raw or ""), corpus, limits.retrieval_top_k)
        out.setdefault("related", [])
    return compose(out, raw, related, limits)


def screening_of(context: dict | None) -> dict:
    return (context or {}).get("screening") or {}
