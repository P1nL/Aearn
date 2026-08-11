"""Strict HTTP request contracts for Lesson Gate and module diagnostic routes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PracticeMutationRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class PrepareLessonGateRequest(PracticeMutationRequest):
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)


class LessonGateHintRequest(PracticeMutationRequest):
    expected_gate_version: int = Field(ge=1)


class LessonGateAttemptRequest(PracticeMutationRequest):
    attempt_type: Literal["run", "submit"]
    submission: str = Field(min_length=1, max_length=48_000)
    expected_track_version: int = Field(ge=1)
    expected_progress_version: int = Field(ge=1)
    expected_assignment_version: int = Field(ge=1)
    expected_gate_version: int = Field(ge=1)


class CreateModuleDiagnosticRequest(PracticeMutationRequest):
    expected_track_version: int = Field(ge=1)


class ModuleDiagnosticAttemptRequest(PracticeMutationRequest):
    submission: str = Field(min_length=1, max_length=48_000)
    expected_track_version: int = Field(ge=1)
    expected_session_version: int = Field(ge=1)


class ConfirmModuleDiagnosticSkipRequest(PracticeMutationRequest):
    expected_track_version: int = Field(ge=1)
    expected_session_version: int = Field(ge=1)
