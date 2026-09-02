"""Strict HTTP request contracts for LessonDocument routes."""
from __future__ import annotations

from typing import Annotated, Literal

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


class LessonBlockReferenceSourceV1(_StrictModel):
    kind: Literal["lesson_block"] = "lesson_block"
    document_id: str = Field(min_length=1, max_length=120)
    document_content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    assignment_version: int = Field(ge=1)
    block_id: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    citation_id: str | None = Field(default=None, min_length=1, max_length=160)


class LessonContextReferenceSourceV1(_StrictModel):
    kind: Literal["context_reference"] = "context_reference"
    reference_id: str = Field(min_length=1, max_length=120)


class LessonArtifactReferenceSourceV1(_StrictModel):
    kind: Literal["artifact"] = "artifact"
    artifact_id: str = Field(min_length=1, max_length=120)
    artifact_version: int = Field(ge=1)


LessonDocumentReferenceSourceV1 = Annotated[
    LessonBlockReferenceSourceV1
    | LessonContextReferenceSourceV1
    | LessonArtifactReferenceSourceV1,
    Field(discriminator="kind"),
]


class ResolveLessonDocumentReferenceRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    knowledge_key: str = Field(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]{0,159}$")
    source: LessonDocumentReferenceSourceV1
