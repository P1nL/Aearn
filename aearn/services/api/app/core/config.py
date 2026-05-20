from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field


ROOT_DIR = Path(__file__).resolve().parents[4]
load_dotenv(ROOT_DIR / ".env")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: str) -> int:
    return int(_env_str(name, default))


def _env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class Settings(BaseModel):
    app_env: str = Field(default_factory=lambda: _env_str("APP_ENV", "development"))
    api_host: str = Field(default_factory=lambda: _env_str("API_HOST", "127.0.0.1"))
    api_port: int = Field(default_factory=lambda: _env_int("API_PORT", "8001"))
    database_url: str = Field(
        default_factory=lambda: _env_str(
            "DATABASE_URL",
            "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable",
        )
    )
    redis_url: str = Field(default_factory=lambda: _env_str("REDIS_URL", "redis://127.0.0.1:6379/0"))
    celery_broker_url: str = Field(
        default_factory=lambda: _env_str("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    )
    celery_result_backend: str = Field(
        default_factory=lambda: _env_str("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1")
    )
    llm_type: str = Field(default_factory=lambda: _env_str("LLM_TYPE", "disabled").lower() or "disabled")
    openai_api_key: str | None = Field(default_factory=lambda: _env_optional("OPENAI_API_KEY"))
    openai_base_url: str | None = Field(default_factory=lambda: _env_optional("OPENAI_BASE_URL"))
    openai_model: str | None = Field(default_factory=lambda: _env_optional("OPENAI_MODEL"))
    llm_timeout_seconds: float = Field(default_factory=lambda: float(_env_str("LLM_TIMEOUT_SECONDS", "20")))

    @property
    def openai_compatible_configured(self) -> bool:
        return (
            self.llm_type == "openai"
            and _present(self.openai_api_key)
            and _present(self.openai_base_url)
            and _present(self.openai_model)
        )

    @property
    def llm_configuration_status(self) -> str:
        if self.llm_type in {"", "disabled", "none", "off"}:
            return "disabled"
        if self.llm_type != "openai":
            return "unsupported"
        if not self.openai_compatible_configured:
            return "incomplete"
        return "configured"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())
