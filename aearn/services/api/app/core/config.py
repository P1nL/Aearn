from functools import lru_cache
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, model_validator


DEEPSEEK_V4_FLASH_MODEL = "deepseek-v4-flash"
DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS = 1_000_000
DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS = 384_000
DEFAULT_TUTOR_CONTEXT_TOKEN_BUDGET = 512
DEFAULT_TUTOR_MAX_OUTPUT_TOKENS = 1_200
DEFAULT_TUTOR_DECISION_MAX_OUTPUT_TOKENS = 1_200
DEEPSEEK_V4_FLASH_TUTOR_DECISION_MAX_OUTPUT_TOKENS = 16_384
DEFAULT_TUTOR_CONTEXT_WINDOW_TOKENS = 5_296
DEFAULT_TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS = 128
DEFAULT_TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS = 256


ROOT_DIR = Path(__file__).resolve().parents[4]
load_dotenv(ROOT_DIR / ".env")


def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: str) -> int:
    return int(_env_str(name, default))


def _env_bool(name: str, default: str) -> bool:
    return _env_str(name, default).lower() in ("true", "1", "yes")


def _env_float(name: str, default: str) -> float:
    return float(_env_str(name, default))


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
    tutor_provider_debug_capture_mode: str = Field(
        default_factory=lambda: _env_str(
            "TUTOR_PROVIDER_DEBUG_CAPTURE_MODE",
            "off",
        ).lower()
    )
    tutor_provider_debug_capture_key: SecretStr | None = Field(
        default_factory=lambda: (
            SecretStr(value)
            if (value := _env_optional("TUTOR_PROVIDER_DEBUG_CAPTURE_KEY_BASE64"))
            else None
        ),
        repr=False,
    )
    tutor_provider_debug_capture_directory: str | None = Field(
        default_factory=lambda: _env_optional("TUTOR_PROVIDER_DEBUG_CAPTURE_DIRECTORY")
    )
    tutor_provider_debug_capture_max_bytes: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_PROVIDER_DEBUG_CAPTURE_MAX_BYTES",
            "1048576",
        ),
        ge=4096,
        le=16_777_216,
    )
    tutor_provider_debug_capture_retention_hours: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_PROVIDER_DEBUG_CAPTURE_RETENTION_HOURS",
            "24",
        ),
        ge=1,
        le=168,
    )
    tutor_deepseek_v4_flash_context_window_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS",
            str(DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS),
        ),
        ge=1,
        le=DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS,
    )
    tutor_deepseek_v4_flash_max_output_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS",
            str(DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS),
        ),
        ge=1,
        le=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
    )
    tutor_default_context_window_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_CONTEXT_WINDOW_TOKENS",
            str(DEFAULT_TUTOR_CONTEXT_WINDOW_TOKENS),
        ),
        ge=1,
    )
    tutor_default_output_reserve_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_CONTEXT_OUTPUT_RESERVE_TOKENS",
            str(DEFAULT_TUTOR_MAX_OUTPUT_TOKENS),
        ),
        ge=1,
    )
    tutor_default_decision_max_output_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_DECISION_MAX_OUTPUT_TOKENS",
            str(DEFAULT_TUTOR_DECISION_MAX_OUTPUT_TOKENS),
        ),
        ge=1,
    )
    tutor_deepseek_v4_flash_decision_max_output_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_DEEPSEEK_V4_FLASH_DECISION_MAX_OUTPUT_TOKENS",
            str(DEEPSEEK_V4_FLASH_TUTOR_DECISION_MAX_OUTPUT_TOKENS),
        ),
        ge=1,
        le=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
    )
    tutor_deepseek_responses_json_schema_enabled: bool = Field(
        default_factory=lambda: _env_bool(
            "TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED",
            "false",
        )
    )
    tutor_deepseek_repair_thinking_disabled: bool = Field(
        default_factory=lambda: _env_bool(
            "TUTOR_DEEPSEEK_REPAIR_THINKING_DISABLED",
            "true",
        )
    )
    tutor_context_protocol_reserve_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS",
            str(DEFAULT_TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS),
        ),
        ge=1,
    )
    tutor_context_safety_margin_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS",
            str(DEFAULT_TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS),
        ),
        ge=1,
    )
    tutor_deepseek_v4_flash_max_dynamic_target_tokens: int = Field(
        default_factory=lambda: _env_int(
            "TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS",
            "384000",
        ),
        ge=1,
        le=384_000,
    )
    tutor_context_max_dynamic_target_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_MAX_DYNAMIC_TARGET_TOKENS", "512"),
        ge=1,
    )
    tutor_context_compact_target_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_COMPACT_TARGET_TOKENS", "16000"),
        ge=1,
    )
    tutor_context_normal_target_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_NORMAL_TARGET_TOKENS", "64000"),
        ge=1,
    )
    tutor_context_complex_target_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_COMPLEX_TARGET_TOKENS", "192000"),
        ge=1,
    )
    tutor_context_extended_target_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_EXTENDED_TARGET_TOKENS", "384000"),
        ge=1,
    )
    tutor_context_warning_ratio: float = Field(
        default_factory=lambda: _env_float("TUTOR_CONTEXT_WARNING_RATIO", "0.8"),
        gt=0,
        le=1,
    )
    tutor_context_critical_ratio: float = Field(
        default_factory=lambda: _env_float("TUTOR_CONTEXT_CRITICAL_RATIO", "0.95"),
        gt=0,
        le=1,
    )
    tutor_context_max_expansions: int = Field(
        default_factory=lambda: _env_int("TUTOR_CONTEXT_MAX_EXPANSIONS", "1"),
        ge=0,
        le=3,
    )
    tutor_context_fixed_mode: str | None = Field(default_factory=lambda: _env_optional("TUTOR_CONTEXT_FIXED_MODE"))
    exa_api_key: str | None = Field(default_factory=lambda: _env_optional("EXA_API_KEY"))
    plan_generation_enabled: bool = Field(
        default_factory=lambda: _env_str("PLAN_GENERATION_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    real_execution_enabled: bool = Field(
        default_factory=lambda: _env_str("REAL_EXECUTION_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    tutor_executor_enabled: bool = Field(
        default_factory=lambda: _env_str("TUTOR_EXECUTOR_ENABLED", "false").lower() in ("true", "1", "yes")
    )
    tutor_thread_turn_v2_enabled: bool = Field(
        default_factory=lambda: _env_bool("TUTOR_THREAD_TURN_V2_ENABLED", "false")
    )
    tutor_proactive_scheduler_enabled: bool = Field(
        default_factory=lambda: _env_bool("TUTOR_PROACTIVE_SCHEDULER_ENABLED", "true")
    )
    tutor_background_hard_paused: bool = Field(
        default_factory=lambda: _env_bool("TUTOR_BACKGROUND_HARD_PAUSED", "false")
    )
    tutor_proactive_cutover_eligible: bool = Field(
        default_factory=lambda: _env_bool("TUTOR_PROACTIVE_CUTOVER_ELIGIBLE", "true")
    )
    tutor_inferred_memory_enabled: bool = Field(
        default_factory=lambda: _env_bool("TUTOR_INFERRED_MEMORY_ENABLED", "false")
    )
    tutor_proactive_daily_budget: int = Field(
        default_factory=lambda: _env_int("TUTOR_PROACTIVE_DAILY_BUDGET", "1")
    )
    tutor_curation_daily_budget: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_DAILY_BUDGET", "0")
    )
    tutor_curation_max_output_tokens: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_MAX_OUTPUT_TOKENS", "0"), ge=0
    )
    # Server-only HMAC material for opaque learner-history pagination cursors.
    # Local development has a bounded fallback; shared deployments must set the env value.
    tutor_cursor_signing_key: str = Field(
        default_factory=lambda: _env_str("TUTOR_CURSOR_SIGNING_KEY", "aearn-local-history-cursor-v1")
    )
    tutor_proactive_concurrency_limit: int = Field(
        default_factory=lambda: _env_int("TUTOR_PROACTIVE_CONCURRENCY_LIMIT", "1")
    )
    tutor_curation_concurrency_limit: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_CONCURRENCY_LIMIT", "1")
    )
    tutor_proactive_cooldown_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_PROACTIVE_COOLDOWN_SECONDS", "86400")
    )
    tutor_curation_cooldown_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_COOLDOWN_SECONDS", "3600")
    )
    tutor_proactive_circuit_failure_threshold: int = Field(
        default_factory=lambda: _env_int("TUTOR_PROACTIVE_CIRCUIT_FAILURE_THRESHOLD", "1")
    )
    tutor_curation_circuit_failure_threshold: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_CIRCUIT_FAILURE_THRESHOLD", "1")
    )
    tutor_scheduler_circuit_window_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_SCHEDULER_CIRCUIT_WINDOW_SECONDS", "3600")
    )
    tutor_proactive_lease_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_PROACTIVE_LEASE_SECONDS", "60")
    )
    tutor_curation_lease_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_CURATION_LEASE_SECONDS", "60")
    )
    tutor_scheduler_max_retry_attempts: int = Field(
        default_factory=lambda: _env_int("TUTOR_SCHEDULER_MAX_RETRY_ATTEMPTS", "2")
    )
    tutor_scheduler_retry_backoff_seconds: int = Field(
        default_factory=lambda: _env_int("TUTOR_SCHEDULER_RETRY_BACKOFF_SECONDS", "60")
    )

    @model_validator(mode="after")
    def _validate_tutor_context_limits(self) -> "Settings":
        if self.tutor_provider_debug_capture_mode not in {"off", "rejected"}:
            raise ValueError("TUTOR_PROVIDER_DEBUG_CAPTURE_MODE must be off or rejected")
        if (
            self.tutor_provider_debug_capture_mode == "rejected"
            and self.tutor_provider_debug_capture_key is None
        ):
            raise ValueError("Rejected provider capture requires an encryption key")
        if self.uses_deepseek_v4_flash_responses and (
            self.tutor_deepseek_v4_flash_max_output_tokens
            >= self.tutor_deepseek_v4_flash_context_window_tokens
        ):
            raise ValueError("DeepSeek V4 Flash max output tokens must leave room within the context window")
        if (
            self.tutor_deepseek_v4_flash_decision_max_output_tokens
            > self.tutor_deepseek_v4_flash_max_output_tokens
        ):
            raise ValueError("DeepSeek V4 Flash Tutor decision output exceeds the provider maximum")
        if self.tutor_default_decision_max_output_tokens > self.tutor_default_output_reserve_tokens:
            raise ValueError("Tutor decision output exceeds the default output reserve")
        input_hard_limit = self.tutor_context_window_capacity_tokens - self.tutor_context_output_reserve_tokens
        if input_hard_limit <= self.tutor_context_protocol_reserve_tokens + self.tutor_context_safety_margin_tokens:
            raise ValueError("Tutor context reserves must leave positive required input capacity")
        maximum_dynamic_target = self.tutor_context_max_dynamic_target_capacity_tokens
        if maximum_dynamic_target > (
            input_hard_limit
            - self.tutor_context_protocol_reserve_tokens
            - self.tutor_context_safety_margin_tokens
        ):
            raise ValueError("Tutor maximum dynamic target exceeds the configured input capacity")
        if not self.tutor_context_warning_ratio < self.tutor_context_critical_ratio:
            raise ValueError("Tutor context warning ratio must be below the critical ratio")
        if self.tutor_context_fixed_mode not in {None, "compact", "normal", "complex", "extended"}:
            raise ValueError("TUTOR_CONTEXT_FIXED_MODE is invalid")
        return self

    @property
    def tutor_provider_debug_capture_path(self) -> Path:
        if self.tutor_provider_debug_capture_directory is not None:
            return Path(self.tutor_provider_debug_capture_directory)
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Aearn" / "provider-debug"
        state_home = os.getenv("XDG_STATE_HOME")
        if state_home:
            return Path(state_home) / "aearn" / "provider-debug"
        return Path.home() / ".local" / "state" / "aearn" / "provider-debug"

    @property
    def llm_provider_type(self) -> str:
        return self.llm_type.strip().lower()

    @property
    def uses_deepseek_v4_flash_responses(self) -> bool:
        return (
            self.llm_provider_type == "deepseek"
            and str(self.llm_model or "").strip() == DEEPSEEK_V4_FLASH_MODEL
        )

    @property
    def tutor_context_window_capacity_tokens(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return self.tutor_deepseek_v4_flash_context_window_tokens
        return self.tutor_default_context_window_tokens

    @property
    def tutor_context_output_reserve_tokens(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return self.tutor_deepseek_v4_flash_max_output_tokens
        return self.tutor_default_output_reserve_tokens

    @property
    def tutor_context_max_dynamic_target_capacity_tokens(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return self.tutor_deepseek_v4_flash_max_dynamic_target_tokens
        return self.tutor_context_max_dynamic_target_tokens

    @property
    def tutor_context_token_budget(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return (
                self.tutor_deepseek_v4_flash_context_window_tokens
                - self.tutor_deepseek_v4_flash_max_output_tokens
            )
        return min(
            DEFAULT_TUTOR_CONTEXT_TOKEN_BUDGET,
            self.tutor_context_max_dynamic_target_tokens,
        )

    @property
    def tutor_max_output_tokens(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return self.tutor_deepseek_v4_flash_max_output_tokens
        return DEFAULT_TUTOR_MAX_OUTPUT_TOKENS

    @property
    def tutor_decision_max_output_tokens(self) -> int:
        if self.uses_deepseek_v4_flash_responses:
            return self.tutor_deepseek_v4_flash_decision_max_output_tokens
        return self.tutor_default_decision_max_output_tokens

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
