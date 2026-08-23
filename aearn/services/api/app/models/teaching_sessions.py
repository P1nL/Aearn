"""Strict HTTP contracts for LearningTrack teaching-session authority."""
from __future__ import annotations

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.services.learning.teaching_contracts import TeachingControlKey, TeachingSessionMode

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class TeachingSessionMutationRequest(_Strict):
    user_id: UUID
    client_action_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")

class OpenTeachingSessionRequest(TeachingSessionMutationRequest):
    conversation_id: UUID | None = None
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)
    mode: TeachingSessionMode = TeachingSessionMode.GUIDED

class TeachingSessionActionRequest(TeachingSessionMutationRequest):
    control_key: TeachingControlKey
    expected_session_version: int = Field(ge=1)
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)
    target_mode: TeachingSessionMode | None = None
    target_knowledge_key: str | None = Field(default=None, min_length=1, max_length=160)
    reason_code: str | None = Field(default=None, min_length=1, max_length=120)
    admit_run: bool = False

    @field_validator("target_knowledge_key")
    @classmethod
    def normalize_target_key(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else None

    @model_validator(mode="after")
    def validate_shape(self) -> "TeachingSessionActionRequest":
        if self.control_key is TeachingControlKey.SWITCH_MODE and self.target_mode is None:
            raise ValueError("switch_mode requires target_mode")
        if self.control_key is not TeachingControlKey.SWITCH_MODE and self.target_mode is not None:
            raise ValueError("target_mode is only valid for switch_mode")
        if self.control_key is TeachingControlKey.ENTER_NEXT_KNOWLEDGE and self.target_knowledge_key is None:
            raise ValueError("enter_next_knowledge requires target_knowledge_key")
        return self
