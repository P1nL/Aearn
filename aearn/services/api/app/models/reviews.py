from typing import Literal

from pydantic import BaseModel, Field, field_validator


ExplanationResult = Literal["passed", "partial", "failed"]


class StartReviewSessionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1)


class ReviewExplanationCheck(BaseModel):
    result: ExplanationResult = "passed"
    score: int = Field(default=2, ge=0, le=2)
    feedback: str | None = None


class SubmitReviewExerciseResultRequest(BaseModel):
    exercise_id: str = Field(min_length=1)
    attempt_id: str | None = Field(default=None, min_length=1)
    code: str = Field(min_length=1)
    filled_blanks: dict[str, str] = Field(default_factory=dict)
    submit_version: int = Field(default=1, ge=1)
    explanation: str | None = None
    hint_usage_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    explanation_check: ReviewExplanationCheck | None = None
    code_hash: str | None = None

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("code must not be blank")
        return stripped
