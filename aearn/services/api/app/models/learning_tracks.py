"""Pydantic HTTP contracts for LearningTrack routes and Tutor scope seams."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.learning.contracts import (
    ExecutionTier,
    LearningPlan,
    LearningPlanModule,
    LearningPlanNode,
    LearningScope,
    LearningScopeKind,
    LearningTaskKind,
    stable_key,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearningPlanNodeDraft(_StrictModel):
    knowledge_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    order_index: int = Field(ge=0)
    is_core: bool = True
    prerequisite_keys: list[str] = Field(default_factory=list, max_length=64)
    required_capabilities: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("knowledge_key")
    @classmethod
    def normalize_knowledge_key(cls, value: str) -> str:
        return stable_key(value, label="knowledge_key")

    @field_validator("prerequisite_keys", "required_capabilities")
    @classmethod
    def normalize_stable_keys(cls, value: list[str]) -> list[str]:
        normalized = [stable_key(item, label="stable key") for item in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("stable keys must be unique")
        return normalized

    def to_domain(self) -> LearningPlanNode:
        return LearningPlanNode(
            knowledge_key=self.knowledge_key,
            title=self.title,
            description=self.description,
            order_index=self.order_index,
            is_core=self.is_core,
            prerequisite_keys=tuple(self.prerequisite_keys),
            required_capabilities=tuple(self.required_capabilities),
        )


class LearningPlanModuleDraft(_StrictModel):
    module_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    order_index: int = Field(ge=0)
    is_core: bool = True
    is_skippable: bool = False
    nodes: list[LearningPlanNodeDraft] = Field(min_length=1, max_length=200)

    @field_validator("module_key")
    @classmethod
    def normalize_module_key(cls, value: str) -> str:
        return stable_key(value, label="module_key")

    def to_domain(self) -> LearningPlanModule:
        return LearningPlanModule(
            module_key=self.module_key,
            title=self.title,
            description=self.description,
            order_index=self.order_index,
            is_core=self.is_core,
            is_skippable=self.is_skippable,
            nodes=tuple(node.to_domain() for node in self.nodes),
        )


class LearningPlanDraft(_StrictModel):
    title: str = Field(min_length=1, max_length=240)
    target_level: str = Field(min_length=1, max_length=120)
    generator_version: str = Field(min_length=1, max_length=160)
    policy_version: str = Field(min_length=1, max_length=160)
    change_reason: str = Field(min_length=1, max_length=600)
    modules: list[LearningPlanModuleDraft] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_complete_plan(self) -> "LearningPlanDraft":
        self.to_domain()
        return self

    def to_domain(self) -> LearningPlan:
        return LearningPlan(
            title=self.title,
            target_level=self.target_level,
            generator_version=self.generator_version,
            policy_version=self.policy_version,
            change_reason=self.change_reason,
            modules=tuple(module.to_domain() for module in self.modules),
        )


class LearningScopeInput(_StrictModel):
    scope_kind: LearningScopeKind = LearningScopeKind.GENERAL
    learning_track_id: UUID | None = None
    task_kind: LearningTaskKind | None = None
    knowledge_key: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_scope(self) -> "LearningScopeInput":
        self.to_domain()
        return self

    def to_domain(self) -> LearningScope:
        return LearningScope(
            scope_kind=self.scope_kind,
            learning_track_id=str(self.learning_track_id) if self.learning_track_id is not None else None,
            task_kind=self.task_kind,
            knowledge_key=self.knowledge_key,
        )


class LearningTrackMutationRequest(_StrictModel):
    user_id: str = Field(min_length=1, max_length=120)
    client_action_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$",
    )


class CreateLearningTrackRequest(LearningTrackMutationRequest):
    language_id: str = Field(min_length=1, max_length=80)
    goal_text: str = Field(min_length=1, max_length=2000)
    target_level: str = Field(min_length=1, max_length=120)
    plan: LearningPlanDraft
    conversation_id: str | None = Field(default=None, min_length=1, max_length=120)


class ProposeLearningPlanRevisionRequest(LearningTrackMutationRequest):
    expected_track_version: int = Field(ge=1)
    plan: LearningPlanDraft


class ActivateLearningPlanRevisionRequest(LearningTrackMutationRequest):
    expected_track_version: int = Field(ge=1)


class ProgressSummaryResponse(_StrictModel):
    total: int = Field(ge=0)
    completed: int = Field(ge=0)
    in_progress: int = Field(ge=0)
    review_due: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class LearningTrackListItemResponse(_StrictModel):
    track_id: str
    language_id: str
    language_display_name: str
    goal_text: str
    target_level: str
    status: Literal["active", "paused", "completed", "archived"]
    version: int = Field(ge=1)
    active_revision_id: str
    active_plan_title: str
    current_knowledge_key: str | None
    current_knowledge_title: str | None
    progress: ProgressSummaryResponse
    review_due_count: int = Field(default=0, ge=0)
    execution_tier: ExecutionTier
    execution_disclosure: str
    last_learned_at: datetime | None
    updated_at: datetime


class LearningTrackDetailResponse(LearningTrackListItemResponse):
    created_at: datetime
    archived_at: datetime | None = None


class LearningTrackNodeResponse(_StrictModel):
    node_id: str
    knowledge_key: str
    title: str
    description: str
    order_index: int
    is_core: bool
    prerequisite_keys: list[str]
    required_capabilities: list[str]
    progress_status: str
    progress_version: int
    mastery_level: str
    mastery_confidence: float


class LearningTrackModuleResponse(_StrictModel):
    module_id: str
    module_key: str
    title: str
    description: str
    order_index: int
    is_core: bool
    is_skippable: bool
    nodes: list[LearningTrackNodeResponse]


class LearningTrackRoadmapResponse(_StrictModel):
    track_id: str
    active_revision_id: str
    title: str
    target_level: str
    modules: list[LearningTrackModuleResponse]


class LearningTrackPlanRevisionResponse(_StrictModel):
    revision_id: str
    predecessor_revision_id: str | None
    status: str
    title: str
    target_level: str
    generator_version: str
    policy_version: str
    change_reason: str
    content_hash: str
    impact: dict[str, object] | None = None
    created_at: datetime
    activated_at: datetime | None = None
