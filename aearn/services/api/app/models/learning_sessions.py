from typing import Literal

from pydantic import BaseModel, Field, field_validator


RunMode = Literal["preview", "visible_tests"]
RuntimeStatus = Literal["success", "runtime_error", "timeout", "unsupported"]
NextAction = Literal["retry_same", "show_hint", "explain_error", "review_variant", "schedule_review", "advance_next"]
FsrsRating = Literal["Again", "Hard", "Good", "Easy"]
HintLevel = Literal["nudge", "concept", "code_shape"]
ExplanationFocus = Literal["core_logic", "boundary_condition", "ai_generated_change"]
LearningMessageRole = Literal["user"]


class StartLearningSessionRequest(BaseModel):
    user_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    knowledge_point_id: str = Field(min_length=1)


class LearningMessageRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    role: LearningMessageRole
    content: str = Field(min_length=1, max_length=4000)
    client_message_id: str = Field(min_length=1, max_length=160)

    @field_validator("content", "client_message_id")
    @classmethod
    def message_field_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message field must not be blank")
        return stripped


class RunExerciseRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    code: str = Field(min_length=1)
    filled_blanks: dict[str, str] = Field(default_factory=dict)
    runtime_profile_id: str | None = None
    run_mode: RunMode = "visible_tests"
    code_hash: str | None = None

    @field_validator("code")
    @classmethod
    def code_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("code must not be blank")
        return stripped


class SubmitExerciseRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    attempt_id: str = Field(min_length=1)
    code: str = Field(min_length=1)
    filled_blanks: dict[str, str] = Field(default_factory=dict)
    submit_version: int | None = Field(default=None, ge=1)
    explanation: str | None = None
    hint_usage_count: int = Field(default=0, ge=0)
    error_count: int | None = Field(default=None, ge=0)
    code_hash: str | None = None

    @field_validator("code")
    @classmethod
    def submit_code_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("code must not be blank")
        return stripped


class HintRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    attempt_id: str = Field(min_length=1)
    current_code: str = Field(min_length=1)
    blank_id: str = Field(min_length=1)
    hint_level: HintLevel

    @field_validator("current_code")
    @classmethod
    def current_code_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("current_code must not be blank")
        return stripped


class ExplainErrorFailedTest(BaseModel):
    case_id: str = Field(min_length=1)
    case_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ExplainErrorRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    error_message: str | None = None
    stderr: str | None = None
    failed_tests: list[ExplainErrorFailedTest] = Field(default_factory=list)
    current_code: str = Field(min_length=1)

    @field_validator("current_code")
    @classmethod
    def explain_current_code_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("current_code must not be blank")
        return stripped

    @field_validator("failed_tests")
    @classmethod
    def failed_tests_must_be_reasonable(cls, value: list[ExplainErrorFailedTest]) -> list[ExplainErrorFailedTest]:
        return value[:8]


class CheckExplanationRequest(BaseModel):
    user_id: str | None = Field(default=None, min_length=1)
    explanation: str = Field(min_length=1)
    focus: ExplanationFocus = "core_logic"
    round: int = Field(default=1, ge=1)

    @field_validator("explanation")
    @classmethod
    def explanation_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("explanation must not be blank")
        return stripped
