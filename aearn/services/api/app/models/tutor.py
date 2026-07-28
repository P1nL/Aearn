from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class TutorMutationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateTutorConversationRequest(TutorMutationRequest):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=120)


class TutorInputRequest(TutorMutationRequest):
    content: str = Field(min_length=1, max_length=16_000)

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped


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
