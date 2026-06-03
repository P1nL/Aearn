from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Language = Literal["javascript", "python", "typescript", "sql", "java", "go", "csharp", "html_css"]
LearningMode = Literal["goal_based", "material_based"]
RuntimeTier = Literal[
    "browser_preview",
    "python_stdout_test",
    "node_typescript_test",
    "sql_query_test",
    "managed_compiled_test",
    "compiled_sandbox_later",
]
TargetLevel = Literal["beginner", "intermediate", "advanced", "beginner_to_intermediate"]


class TimeBudget(BaseModel):
    minutes_per_day: int | None = Field(default=None, ge=1)
    days_per_week: int | None = Field(default=None, ge=1, le=7)
    deadline: date | None = None


class MaterialInput(BaseModel):
    type: str = Field(min_length=1)
    title: str | None = None
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("material content must not be blank")
        return stripped


class ClarificationAnswer(BaseModel):
    question_id: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class UserCreateRequest(BaseModel):
    display_name: str = Field(min_length=1)
    learning_style: str | None = None
    teaching_preference: str | None = None
    encouragement_preference: str | None = None
    profession: str | None = None
    background_context: str | None = None
    preferred_time_slots: list[dict[str, object]] = Field(default_factory=list)
    reminder_preference: dict[str, object] = Field(default_factory=dict)

    @field_validator("display_name")
    @classmethod
    def display_name_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("display_name must not be blank")
        return stripped


class PlanGenerateRequest(BaseModel):
    user_id: str = Field(min_length=1)
    mode: LearningMode
    goal_text: str | None = None
    language: Language | None = None
    course_id: str | None = None
    target_level: TargetLevel = "beginner"
    materials: list[MaterialInput] = Field(default_factory=list)
    time_budget: TimeBudget | None = None
    profession: str | None = None
    clarification_answers: list[ClarificationAnswer] = Field(default_factory=list)


class DraftKnowledgePoint(BaseModel):
    temp_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    skill_tags: list[str] = Field(default_factory=list)
    source: Literal["template", "user_material", "agent_generated"] = "template"
    exercise_refs: list[str] = Field(default_factory=list)


class DraftModule(BaseModel):
    temp_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str | None = None
    order_index: int = Field(ge=0)
    is_skippable: bool = True
    is_adjustable: bool = True
    estimated_sessions: int = Field(default=1, ge=1)
    source: Literal["template", "user_material", "agent_generated"] = "template"
    knowledge_points: list[DraftKnowledgePoint] = Field(min_length=1)


class RuntimeBoundary(BaseModel):
    runtime_tier: RuntimeTier
    unsupported_languages: list[str] = Field(default_factory=list)
    notice: str


class PlanDraft(BaseModel):
    draft_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    language_course_id: str = Field(min_length=1)
    goal_text: str = Field(min_length=1)
    language: Language
    target_level: TargetLevel
    mode: LearningMode
    deadline: date | None = None
    modules: list[DraftModule] = Field(min_length=1)
    runtime_boundary: RuntimeBoundary
    source_attribution: list[str] = Field(default_factory=list)


class PlanConfirmRequest(BaseModel):
    user_id: str = Field(min_length=1)
    plan_draft: PlanDraft


class ApiErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object]
    request_id: str
    recoverable: bool


class ApiErrorEnvelope(BaseModel):
    error: ApiErrorDetail


class FlexiblePreferencePayload(BaseModel):
    model_config = ConfigDict(extra="allow")
