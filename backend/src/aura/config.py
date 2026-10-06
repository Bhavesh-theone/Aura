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


@lru_cache
def get_settings() -> Settings:
    return Settings()
