from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


ExplanationResult = Literal["passed", "partial", "failed"]
ReviewWarmupAction = Literal["answer", "skip"]
ReviewPatchVerdict = Literal["pass", "fail", "uncertain"]
ReviewPatchNextAction = Literal["accept", "reject", "request_change", "run_more_tests"]


class StartReviewSessionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1)


class ReviewExplanationCheck(BaseModel):
    result: ExplanationResult = "passed"
    score: int = Field(default=2, ge=0, le=2)
    feedback: str | None = None
    judgements: dict[str, object] | None = None


class ReviewWarmupResultRequest(BaseModel):
    action: ReviewWarmupAction = "answer"
    answer: str | None = None

    @field_validator("answer")
    @classmethod
    def normalize_answer(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if len(stripped) > 1200:
            raise ValueError("answer must be at most 1200 characters")
        return stripped or None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "ReviewWarmupResultRequest":
        if self.action == "answer" and self.answer is None:
            raise ValueError("answer is required when action is answer")
        return self


class ReviewAIPatchAnswer(BaseModel):
    verdict: ReviewPatchVerdict
    evidence: str = Field(min_length=1, max_length=1200)
    knowledge_point_risk: str = Field(min_length=1, max_length=800)
    next_action: ReviewPatchNextAction

    @field_validator("evidence", "knowledge_point_risk")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped


class SubmitReviewExerciseResultRequest(BaseModel):
    exercise_id: str = Field(min_length=1)
    attempt_id: str | None = Field(default=None, min_length=1)
    code: str = ""
    filled_blanks: dict[str, str] = Field(default_factory=dict)
    submit_version: int = Field(default=1, ge=1)
    explanation: str | None = None
    hint_usage_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    explanation_check: ReviewExplanationCheck | None = None
    code_hash: str | None = None
    review_ai_patch: ReviewAIPatchAnswer | None = None
    review_ai_patch_answer: ReviewAIPatchAnswer | None = None

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_submit_payload(self) -> "SubmitReviewExerciseResultRequest":
        if self.review_ai_patch_answer is None and self.review_ai_patch is not None:
            self.review_ai_patch_answer = self.review_ai_patch
        if not self.code and self.review_ai_patch is None and self.review_ai_patch_answer is None:
            raise ValueError("code or review_ai_patch is required")
        return self
