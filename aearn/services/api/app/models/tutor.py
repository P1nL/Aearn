from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.learning_tracks import LearningScopeInput

class _StrictReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LessonSelectionReferenceInput(_StrictReferenceModel):
    kind: Literal["lesson_selection"]
    learning_track_id: UUID
    knowledge_key: str = Field(min_length=1, max_length=160)
    document_id: UUID
    document_content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    block_id: str = Field(min_length=1, max_length=160)
    start_offset: int = Field(ge=0, le=48_000)
    end_offset: int = Field(ge=1, le=48_000)
    excerpt: str = Field(min_length=1, max_length=800)

    @model_validator(mode="after")
    def validate_range(self) -> "LessonSelectionReferenceInput":
        normalized = " ".join(self.excerpt.split())
        if self.end_offset <= self.start_offset or self.end_offset - self.start_offset != len(normalized):
            raise ValueError("lesson selection offsets must match the normalized excerpt")
        return self


class ExerciseFeedbackReferenceInput(_StrictReferenceModel):
    kind: Literal["exercise_feedback"]
    learning_track_id: UUID
    knowledge_key: str = Field(min_length=1, max_length=160)
    attempt_id: UUID


class ExecutionResultReferenceInput(_StrictReferenceModel):
    kind: Literal["execution_result"]
    learning_track_id: UUID
    knowledge_key: str = Field(min_length=1, max_length=160)
    attempt_id: UUID


class ReviewFeedbackReferenceInput(_StrictReferenceModel):
    kind: Literal["review_feedback"]
    learning_track_id: UUID
    knowledge_key: str = Field(min_length=1, max_length=160)
    review_session_id: UUID
    attempt_id: UUID


TutorContextReferenceInput = Annotated[
    LessonSelectionReferenceInput
    | ExerciseFeedbackReferenceInput
    | ExecutionResultReferenceInput
    | ReviewFeedbackReferenceInput,
    Field(discriminator="kind"),
]


class TutorMutationRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateTutorConversationRequest(TutorMutationRequest):
    conversation_id: str | None = Field(default=None, min_length=1, max_length=120)
    learning_scope: LearningScopeInput | None = None


class TutorInputRequest(TutorMutationRequest):
    content: str = Field(min_length=1, max_length=16_000)
    learning_scope: LearningScopeInput | None = None
    planning_facts: dict[str, object] | None = None
    reopen_fact_fields: list[str] = Field(default_factory=list, max_length=7)
    context_references: list[TutorContextReferenceInput] = Field(default_factory=list, max_length=6)

    @field_validator("content")
    @classmethod
    def require_visible_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be blank")
        return stripped

    @field_validator("planning_facts")
    @classmethod
    def validate_planning_facts(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return None
        allowed = {
            "language_id", "goal_text", "target_level", "weekly_minutes",
            "experience_level", "teaching_preferences", "pace_constraints",
        }
        if not value or len(value) > len(allowed) or not set(value).issubset(allowed):
            raise ValueError("planning_facts contains unsupported fields")
        return value

    @field_validator("reopen_fact_fields")
    @classmethod
    def validate_reopen_fact_fields(cls, value: list[str]) -> list[str]:
        allowed = {
            "language_id", "goal_text", "target_level", "weekly_minutes",
            "experience_level", "teaching_preferences", "pace_constraints",
        }
        if len(value) != len(set(value)) or not set(value).issubset(allowed):
            raise ValueError("reopen_fact_fields contains unsupported fields")
        return value


class TutorClarificationResponse(_StrictReferenceModel):
    kind: Literal["clarification"]
    answer_text: str = Field(min_length=1, max_length=16_000)

    @field_validator("answer_text")
    @classmethod
    def require_visible_answer(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("answer_text must not be blank")
        return stripped


class TutorPlanningInputResponse(_StrictReferenceModel):
    kind: Literal["planning_input"]
    question_key: Literal[
        "language_id", "goal_text", "target_level", "weekly_minutes",
        "experience_level", "teaching_preferences", "pace_constraints",
    ]
    catalog_version: Literal["tutor_planning_questions_v1"]
    value: object


class TutorApprovalResponse(_StrictReferenceModel):
    kind: Literal["approval"]
    proposal_identity: str = Field(min_length=1, max_length=160)
    decision: Literal["approve", "deny"]
    reason: str | None = Field(default=None, max_length=400)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


TutorInteractionResponseInput = Annotated[
    TutorClarificationResponse | TutorPlanningInputResponse | TutorApprovalResponse,
    Field(discriminator="kind"),
]


class TutorInteractionRequestResponseRequest(TutorMutationRequest):
    model_config = ConfigDict(extra="forbid")

    expected_request_version: int = Field(ge=1)
    response: TutorInteractionResponseInput


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


class HarnessCutoverConfirmRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    cutover_version: str = Field(min_length=1, max_length=120)
    summary_version: int = Field(ge=1)
    preview_nonce: str = Field(min_length=1, max_length=160)
    summary_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )
    confirm: bool
