"""Pydantic HTTP contracts for LearningTrack planning sessions."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearningPlanSessionMutationRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateLearningPlanSessionRequest(LearningPlanSessionMutationRequest):
    preferred_language_id: str | None = Field(default=None, min_length=1, max_length=80)


class CancelLearningPlanSessionRequest(LearningPlanSessionMutationRequest):
    expected_session_version: int = Field(ge=1)


class ConfirmLearningPlanSessionRequest(LearningPlanSessionMutationRequest):
    expected_session_version: int = Field(ge=1)
    draft_id: str = Field(min_length=1, max_length=120)
    draft_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
