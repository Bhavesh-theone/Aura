from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ — anchors .env and the database so the launch directory doesn't matter.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="AURA_",
                                      extra="ignore")

    # PostgreSQL 16 + pgvector (scripts/db.ps1). The app connects as aura_app, a role that is
    # not a superuser and owns no table, so row-level security always applies to it.
    database_url: str = "postgresql+psycopg://aura_app:aura_app_dev@127.0.0.1:5433/aura"
    # Alembic (and the SQLite import) connect as aura_owner, which owns the schema. Unset:
    # the API does not migrate at start-up and only checks the schema is at head.
    migration_database_url: str | None = None
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 480
    ollama_base_url: str = "http://127.0.0.1:11434"  # not localhost: it stalls on Windows
    ollama_model: str = "qwen3.5:4b"
    # Let a thinking model (qwen3.5) reason before answering. Off by default: on a 4B model
    # the reasoning often used the whole output budget and the answer came back empty
    # ("Invalid response from LLM call - None or empty"), and it is 5-10x slower.
    ollama_think: bool = False
    # Actions above this rupee value are draft-only: a human decides (default 5 crore).
    materiality_cap_inr: int = 50_000_000
    # Where the audit anchor file lives. Unset means backend/data/audit_anchor.json for the
    # default database (see aura.data.verify_audit.default_anchor_path).
    audit_anchor_path: str | None = None

    # Harness reliability (see RUNNING.md, "Retries, dead letters and recovery").
    # A RUNNING segment whose claim is older than this is presumed orphaned (crash) and is
    # requeued, or dead-lettered once it has used all its attempts.
    segment_lease_seconds: int = 900
    # Claims per segment before a transient failure dead-letters it.
    segment_max_attempts: int = 3
    # Backoff before a retried segment may run again: base, 2x, 4x, ...
    segment_backoff_seconds: float = 10.0
    # Retries of one model call on a transient error (each attempt is its own agent_run).
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1.0
    # Per-segment budget: exceeding either fails the segment (permanent, not retried).
    max_llm_calls_per_segment: int = 12
    max_segment_seconds: int = 600
    # Daily budget across all segments (agent_run rows since 00:00 UTC). When reached, new
    # segments are deferred to the next UTC day.
    max_llm_calls_per_day: int = 2000
    # How long a model health check is trusted before the worker asks Ollama again.
    orchestrator_health_ttl_seconds: float = 30.0

    # Evaluation and autonomy (RUNNING.md, "Evaluation, autonomy and safety").
    # Pass mark per capability: classify accuracy, extraction case accuracy, draft rubric.
    eval_threshold_classify_document: float = 0.7
    eval_threshold_extract_financials: float = 0.7
    eval_threshold_draft_email: float = 0.8
    # Retrieval (recall@5 of hybrid search on evals/golden/retrieval.jsonl).
    eval_threshold_retrieval: float = 0.8
    # Parsing: mean of table-cell accuracy, row/col field accuracy and key-field recall on
    # the Project Kaveri fixtures (tests/fixtures/parsing), for the PDF parser in use.
    eval_threshold_parsing: float = 0.9
    # Demote a capability when people override it more than this share of decisions...
    autonomy_max_override_rate: float = 0.20
    # ...over at least this many decisions in the last autonomy_window_days days.
    autonomy_min_decisions: int = 20
    autonomy_window_days: int = 30
    # Stub eval runs say nothing about the model; they count for autonomy only if this is on.
    autonomy_counts_stub_evals: bool = False
    # How often the worker re-checks autonomy (0 turns the periodic check off).
    autonomy_check_interval_seconds: float = 3600.0

    # Prompt-injection screening: at or above this risk score a result goes to a person.
    injection_risk_threshold: float = 0.5
    # Context assembly: total characters of document text in a model's context, the subject
    # document's excerpt, and how many retrieved chunks of the deal's other documents.
    max_context_chars: int = 6000
    context_excerpt_chars: int = 2000
    retrieval_top_k: int = 4

    # Document ingestion and search (RUNNING.md, "Documents: formats, indexing and search").
    max_upload_mb: int = 25
    max_pages: int = 300
    ocr_enabled: bool = True
    ocr_max_pages: int = 50
    # A PDF page with fewer extractable characters than this is treated as an image (OCR).
    ocr_min_chars: int = 25
    # PDF parser (RUNNING.md, "PDF parsing: Docling"). 'auto' uses Docling when its optional
    # dependency (uv sync --extra docling) and models are installed, else PyMuPDF. Docling
    # missing, failing, timing out or over its page cap falls back to PyMuPDF (+ RapidOCR),
    # with a warning on the document.
    pdf_parser: Literal["auto", "docling", "pymupdf"] = "auto"
    # Docling's model folder (layout, TableFormer, RapidOcr); nothing is downloaded at run time.
    docling_artifacts: str = str(BACKEND_DIR / "data" / "docling-models")
    docling_max_pages: int = 120
    docling_timeout_s: float = 600.0
    # Second reading of image-only (scanned) PDF pages by a local vision model through Ollama:
    # 'off', 'fallback' (pages whose OCR text is thin, and scans named like KYC papers or board
    # resolutions) or 'always' (every image-only page), at most vlm_max_pages per document.
    # Its numbers count only when OCR saw them too; otherwise the page is marked needs_review.
    scan_vlm: Literal["off", "fallback", "always"] = "fallback"
    vlm_model: str = "qwen3.5:4b"
    vlm_max_pages: int = 5
    vlm_timeout_s: float = 300.0
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 100
    # 'ollama' (nomic-embed-text through Ollama) or 'fake' (deterministic hash vectors, for
    # tests and machines without Ollama; search quality is then keyword-level only).
    embedder: Literal["ollama", "fake"] = "ollama"
    embed_model: str = "nomic-embed-text"
    embed_batch: int = 16
    embed_timeout_seconds: float = 60.0
    embed_max_retries: int = 2
    # Hybrid search: candidates per list, Reciprocal Rank Fusion constant, HNSW ef_search.
    search_candidates: int = 40
    rrf_k: int = 60
    hnsw_ef_search: int = 80
    # Indexing queue: claims before a transient failure dead-letters the job, backoff base.
    index_max_attempts: int = 3
    index_backoff_seconds: float = 15.0
    # Longer than the slowest legitimate run: Docling up to docling_timeout_s plus the vision
    # model on up to vlm_max_pages scanned pages (~1 min each).
    index_lease_seconds: int = 1800

    # Rate limits: job submissions per user per minute (0 = off), model calls at once.
    job_submits_per_minute: int = 20
    max_concurrent_llm_calls: int = 1

    # Local tracing (spans in the trace_span table; nothing is exported).
    tracing_enabled: bool = True

    # Outbound email (RUNNING.md, "Gmail (outbound email)"). Set in .env / the environment
    # only, never through the API: 'off' (default, nothing leaves), 'gmail_draft' (an approved
    # email becomes a Gmail draft) or 'gmail_send' (an approved email is sent).
    outbound_mode: Literal["off", "gmail_draft", "gmail_send"] = "off"
    # Outbound messages (drafted or sent, not blocked) allowed per UTC day.
    outbound_daily_limit: int = 50
    # The Google OAuth Desktop client (never committed; see .gitignore).
    gmail_client_secret_path: str = str(BACKEND_DIR / "client_secret.json")
    # Used only when no OS keyring is available: the encrypted token file and its key.
    gmail_token_file: str = str(BACKEND_DIR / "data" / "gmail_token.enc")


@lru_cache
def get_settings() -> Settings:
    return Settings()
