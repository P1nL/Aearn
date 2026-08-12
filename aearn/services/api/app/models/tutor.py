from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.learning_tracks import LearningScopeInput

class TutorMutationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateTutorConversationRequest(TutorMutationRequest):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=120)
    learning_scope: LearningScopeInput | None = None


class TutorInputRequest(TutorMutationRequest):
    content: str = Field(min_length=1, max_length=16_000)
    learning_scope: LearningScopeInput | None = None
    planning_facts: dict[str, object] | None = None
    reopen_fact_fields: list[str] = Field(default_factory=list, max_length=7)

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped

    @field_validator("planning_facts")
    @classmethod
    def validate_planning_facts(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return None
        allowed = {
            "language_id", "goal_text", "target_level", "weekly_minutes",
            "experience_level", "teaching_preferences", "pace_constraints",
        }
        if not value or len(value) > len(allowed) or not set(value).issubset(allowed):
            raise ValueError("planning_facts contains unsupported fields")
        return value

    @field_validator("reopen_fact_fields")
    @classmethod
    def validate_reopen_fact_fields(cls, value: list[str]) -> list[str]:
        allowed = {
            "language_id", "goal_text", "target_level", "weekly_minutes",
            "experience_level", "teaching_preferences", "pace_constraints",
        }
        if len(value) != len(set(value)) or not set(value).issubset(allowed):
            raise ValueError("reopen_fact_fields contains unsupported fields")
        return value


class CorrectTutorMemoryRequest(TutorMutationRequest):
    statement: str = Field(min_length=1, max_length=180)

    @field_validator("statement")
    @classmethod
    def require_visible_statement(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("statement must not be blank")
        return stripped


class UpdateTutorPreferencesRequest(TutorMutationRequest):
    inferred_memory_enabled: bool | None = None
    expected_memory_setting_version: str | None = Field(default=None, min_length=1, max_length=160)
    proactive_paused: bool | None = None

    @model_validator(mode="after")
    def require_one_preference(self) -> "UpdateTutorPreferencesRequest":
        if self.inferred_memory_enabled is None and self.proactive_paused is None:
            raise ValueError("at least one Tutor preference is required")
        return self


class HarnessCutoverConfirmRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    cutover_version: str = Field(min_length=1, max_length=120)
    summary_version: int = Field(ge=1)
    preview_nonce: str = Field(min_length=1, max_length=160)
    summary_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )
    confirm: bool
