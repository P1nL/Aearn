"""Strict HTTP request contracts for LessonDocument routes."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LessonMutationRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class PrepareLessonDocumentRequest(LessonMutationRequest):
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)


class StartLessonDocumentRequest(LessonMutationRequest):
    assignment_id: str = Field(min_length=1, max_length=120)
    expected_assignment_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)


class ActivateLessonMigrationRequest(LessonMutationRequest):
    expected_assignment_version: int = Field(ge=1)
