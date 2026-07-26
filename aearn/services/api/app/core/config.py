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
    deepseek_api_key: str | None = Field(default_factory=lambda: _env_optional("DEEPSEEK_API_KEY"))
    deepseek_base_url: str | None = Field(default_factory=lambda: _env_optional("DEEPSEEK_BASE_URL"))
    deepseek_model: str | None = Field(default_factory=lambda: _env_optional("DEEPSEEK_MODEL"))
    llm_timeout_seconds: float = Field(default_factory=lambda: float(_env_str("LLM_TIMEOUT_SECONDS", "20")))
    exa_api_key: str | None = Field(default_factory=lambda: _env_optional("EXA_API_KEY"))
    plan_generation_enabled: bool = Field(
        default_factory=lambda: _env_str("PLAN_GENERATION_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    real_execution_enabled: bool = Field(
        default_factory=lambda: _env_str("REAL_EXECUTION_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    langgraph_enabled: bool = Field(
        default_factory=lambda: _env_str("LANGGRAPH_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    tutor_harness_enabled: bool = Field(
        default_factory=lambda: _env_str("TUTOR_HARNESS_ENABLED", "false").lower() in ("true", "1", "yes")
    )

    @property
    def llm_provider_type(self) -> str:
        return self.llm_type.strip().lower()

    @property
    def openai_configured(self) -> bool:
        return (
            self.llm_provider_type == "openai"
            and _present(self.openai_api_key)
            and _present(self.openai_base_url)
            and _present(self.openai_model)
        )

    @property
    def deepseek_configured(self) -> bool:
        return (
            self.llm_provider_type == "deepseek"
            and _present(self.deepseek_api_key)
            and _present(self.deepseek_base_url)
            and _present(self.deepseek_model)
        )

    @property
    def openai_compatible_configured(self) -> bool:
        return self.openai_configured or self.deepseek_configured

    @property
    def llm_api_key(self) -> str | None:
        if self.llm_provider_type == "deepseek":
            return self.deepseek_api_key
        return self.openai_api_key

    @property
    def llm_base_url(self) -> str | None:
        if self.llm_provider_type == "deepseek":
            return self.deepseek_base_url
        return self.openai_base_url

    @property
    def llm_model(self) -> str | None:
        if self.llm_provider_type == "deepseek":
            return self.deepseek_model
        return self.openai_model

    @property
    def llm_configuration_status(self) -> str:
        provider_type = self.llm_provider_type
        if provider_type in {"", "disabled", "none", "off"}:
            return "disabled"
        if provider_type == "openai":
            return "configured" if self.openai_configured else "incomplete"
        if provider_type == "deepseek":
            return "configured" if self.deepseek_configured else "incomplete"
        return "unsupported"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _present(value: str | None) -> bool:
    return value is not None and bool(value.strip())
