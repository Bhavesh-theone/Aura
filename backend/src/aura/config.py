from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AURA_", extra="ignore")

    database_url: str = "sqlite:///./aura.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_ttl_minutes: int = 480
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
