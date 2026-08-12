"""Strict HTTP request contracts for track-scoped ReviewSession."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.learning.practice.model_review_contracts import ModelCodeReviewSubmissionV1


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewMutationRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateReviewSessionRequest(ReviewMutationRequest):
    knowledge_key: str = Field(min_length=1, max_length=160)
    expected_track_version: int = Field(ge=1)
    expected_schedule_version: int = Field(ge=1)
    max_items: int = Field(default=1, ge=1, le=3)


class ReviewWarmupRequest(ReviewMutationRequest):
    response_kind: Literal["answered", "skipped"]
    confidence: Literal["low", "medium", "high"] | None = None
    expected_session_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_warmup(self) -> "ReviewWarmupRequest":
        if self.response_kind == "answered" and self.confidence is None:
            raise ValueError("answered warmup requires confidence")
        if self.response_kind == "skipped" and self.confidence is not None:
            raise ValueError("skipped warmup cannot include confidence")
        return self


class ReviewHintRequest(ReviewMutationRequest):
    hint_level: int = Field(ge=1, le=3)
    expected_session_version: int = Field(ge=1)
    expected_item_version: int = Field(ge=1)


class ReviewAttemptRequest(ReviewMutationRequest):
    submission: str | None = Field(default=None, min_length=1, max_length=48_000)
    review_submission: ModelCodeReviewSubmissionV1 | None = None
    expected_session_version: int = Field(ge=1)
    expected_item_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_submission_shape(self) -> "ReviewAttemptRequest":
        if (self.submission is None) == (self.review_submission is None):
            raise ValueError("exactly one of submission or review_submission is required")
        return self


class FinalizeReviewSessionRequest(ReviewMutationRequest):
    expected_session_version: int = Field(ge=1)
