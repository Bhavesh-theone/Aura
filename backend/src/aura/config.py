from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/ — anchors .env and the database so the launch directory doesn't matter.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_prefix="AURA_",
                                      extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'aura.db').as_posix()}"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 480
    ollama_base_url: str = "http://localhost:11434"
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
