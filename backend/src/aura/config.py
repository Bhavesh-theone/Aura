from functools import lru_cache
from pathlib import Path

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
