"""Typed, deterministic contracts for the LearningTrack domain."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Mapping


_STABLE_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class LearningTrackStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PlanRevisionStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class PlanMigrationStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    APPLIED = "applied"


class NodeProgressStatus(StrEnum):
    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REVIEW_DUE = "review_due"
    DIAGNOSTIC_SKIPPED = "diagnostic_skipped"


class MasteryEvidenceKind(StrEnum):
    GATE = "gate"
    MODULE_DIAGNOSTIC = "module_diagnostic"
    REVIEW = "review"
    MODEL_CODE_REVIEW = "model_code_review"
    TRUSTED_IMPORT = "trusted_import"


class MasteryEvidenceEffect(StrEnum):
    REINFORCING = "reinforcing"
    OBSERVATIONAL_NON_DEGRADING = "observational_non_degrading"


class MasteryIndependence(StrEnum):
    INDEPENDENT = "independent"
    HINTED = "hinted"
    REMEDIATED = "remediated"


class MasteryLevel(StrEnum):
    UNSEEN = "unseen"
    EMERGING = "emerging"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"
    DURABLE = "durable"


class LearningScopeKind(StrEnum):
    GENERAL = "general"
    PLAN_DRAFTING = "plan_drafting"
    LEARNING_TRACK = "learning_track"


class LearningTaskKind(StrEnum):
    GENERAL_TUTOR = "general_tutor"
    PLAN_DRAFTING = "plan_drafting"
    LESSON_TEACHING = "lesson_teaching"
    EXERCISE_FEEDBACK = "exercise_feedback"
    REVIEW_COACHING = "review_coaching"
    MODEL_CODE_REVIEW = "model_code_review"
    REMEDIATION = "remediation"


class ExecutionTier(StrEnum):
    TEACHING_LOCAL = "teaching_local"
    CONTAINER_VERIFIED = "container_verified"
    STATIC_ONLY = "static_only"
    UNAVAILABLE = "unavailable"


class ExecutionComposition(StrEnum):
    DEVELOPMENT = "development"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class LearningPlanNode:
    knowledge_key: str
    title: str
    description: str
    order_index: int
    is_core: bool
    prerequisite_keys: tuple[str, ...]
    required_capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_key", stable_key(self.knowledge_key, label="knowledge_key"))
        object.__setattr__(self, "title", bounded_text(self.title, label="node title", maximum=240))
        object.__setattr__(self, "description", bounded_optional_text(self.description, maximum=2000))
        if self.order_index < 0:
            raise ValueError("node order_index must be non-negative")
        prerequisites = tuple(stable_key(item, label="prerequisite key") for item in self.prerequisite_keys)
        if len(prerequisites) != len(set(prerequisites)):
            raise ValueError("node prerequisite keys must be unique")
        if self.knowledge_key in prerequisites:
            raise ValueError("node cannot depend on itself")
        capabilities = tuple(stable_key(item, label="required capability") for item in self.required_capabilities)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("node required capabilities must be unique")
        object.__setattr__(self, "prerequisite_keys", prerequisites)
        object.__setattr__(self, "required_capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class LearningPlanModule:
    module_key: str
    title: str
    description: str
    order_index: int
    is_core: bool
    is_skippable: bool
    nodes: tuple[LearningPlanNode, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_key", stable_key(self.module_key, label="module_key"))
        object.__setattr__(self, "title", bounded_text(self.title, label="module title", maximum=240))
        object.__setattr__(self, "description", bounded_optional_text(self.description, maximum=2000))
        if self.order_index < 0:
            raise ValueError("module order_index must be non-negative")
        if not self.nodes:
            raise ValueError("plan module must contain at least one node")
        object.__setattr__(self, "nodes", tuple(self.nodes))
        node_orders = tuple(item.order_index for item in self.nodes)
        if len(node_orders) != len(set(node_orders)):
            raise ValueError("node order_index must be unique within a module")


@dataclass(frozen=True, slots=True)
class LearningPlan:
    title: str
    target_level: str
    generator_version: str
    policy_version: str
    change_reason: str
    modules: tuple[LearningPlanModule, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "title", bounded_text(self.title, label="plan title", maximum=240))
        object.__setattr__(self, "target_level", bounded_text(self.target_level, label="target_level", maximum=120))
        object.__setattr__(
            self,
            "generator_version",
            bounded_text(self.generator_version, label="generator_version", maximum=160),
        )
        object.__setattr__(self, "policy_version", bounded_text(self.policy_version, label="policy_version", maximum=160))
        object.__setattr__(self, "change_reason", bounded_text(self.change_reason, label="change_reason", maximum=600))
        if not self.modules:
            raise ValueError("plan must contain at least one module")
        object.__setattr__(self, "modules", tuple(self.modules))
        module_keys = tuple(item.module_key for item in self.modules)
        module_orders = tuple(item.order_index for item in self.modules)
        if len(module_keys) != len(set(module_keys)):
            raise ValueError("module_key must be unique within a plan")
        if len(module_orders) != len(set(module_orders)):
            raise ValueError("module order_index must be unique within a plan")
        validate_plan_graph(self)

    @property
    def nodes(self) -> tuple[LearningPlanNode, ...]:
        return tuple(node for module in sorted(self.modules, key=lambda item: item.order_index) for node in sorted(module.nodes, key=lambda item: item.order_index))

    @property
    def content_hash(self) -> str:
        return canonical_plan_hash(self)


@dataclass(frozen=True, slots=True)
class PlanImpact:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    reordered: tuple[str, ...]
    prerequisite_changed: tuple[str, ...]
    retained_progress: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return any((self.added, self.removed, self.reordered, self.prerequisite_changed))

    def as_dict(self) -> dict[str, object]:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "reordered": list(self.reordered),
            "prerequisite_changed": list(self.prerequisite_changed),
            "retained_progress": list(self.retained_progress),
        }


@dataclass(frozen=True, slots=True)
class LearningScope:
    scope_kind: LearningScopeKind = LearningScopeKind.GENERAL
    learning_track_id: str | None = None
    task_kind: LearningTaskKind | None = None
    knowledge_key: str | None = None

    def __post_init__(self) -> None:
        task = self.task_kind or default_task_kind(self.scope_kind)
        object.__setattr__(self, "task_kind", task)
        if self.scope_kind is LearningScopeKind.GENERAL:
            if self.learning_track_id is not None or self.knowledge_key is not None or task is not LearningTaskKind.GENERAL_TUTOR:
                raise ValueError("general scope cannot carry a track, knowledge key, or teaching task")
            return
        if self.scope_kind is LearningScopeKind.PLAN_DRAFTING:
            if self.learning_track_id is not None or self.knowledge_key is not None or task is not LearningTaskKind.PLAN_DRAFTING:
                raise ValueError("plan_drafting scope only permits the plan_drafting task")
            return
        if not self.learning_track_id:
            raise ValueError("learning_track scope requires learning_track_id")
        if task in {LearningTaskKind.GENERAL_TUTOR, LearningTaskKind.PLAN_DRAFTING}:
            raise ValueError("learning_track scope requires a track teaching task")
        if self.knowledge_key is not None:
            object.__setattr__(self, "knowledge_key", stable_key(self.knowledge_key, label="knowledge_key"))


@dataclass(frozen=True, slots=True)
class ExecutionTierProjection:
    tier: ExecutionTier
    disclosure: str
    runtime_id: str | None = None


@dataclass(frozen=True, slots=True)
class MasteryEvidence:
    evidence_id: str
    knowledge_key: str
    evidence_kind: MasteryEvidenceKind
    source_receipt_id: str
    source_receipt_hash: str
    independence: MasteryIndependence
    score: float
    hint_count: int
    attempt_count: int
    summary: Mapping[str, object]
    created_at: datetime
    evidence_effect: MasteryEvidenceEffect = MasteryEvidenceEffect.REINFORCING

    def __post_init__(self) -> None:
        object.__setattr__(self, "knowledge_key", stable_key(self.knowledge_key, label="knowledge_key"))
        if not _SHA256.fullmatch(self.source_receipt_hash):
            raise ValueError("source_receipt_hash must be SHA-256")
        if not 0 <= self.score <= 1:
            raise ValueError("mastery evidence score must be within 0..1")
        if self.hint_count < 0 or self.attempt_count < 1:
            raise ValueError("mastery evidence counters are invalid")


def stable_key(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _STABLE_KEY.fullmatch(normalized):
        raise ValueError(f"{label} must use a stable lowercase identifier")
    return normalized


def bounded_text(value: str, *, label: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{label} must contain 1..{maximum} characters")
    return normalized


def bounded_optional_text(value: str, *, maximum: int) -> str:
    normalized = str(value or "").strip()
    if len(normalized) > maximum:
        raise ValueError(f"text must contain at most {maximum} characters")
    return normalized


def default_task_kind(scope_kind: LearningScopeKind) -> LearningTaskKind:
    if scope_kind is LearningScopeKind.PLAN_DRAFTING:
        return LearningTaskKind.PLAN_DRAFTING
    if scope_kind is LearningScopeKind.LEARNING_TRACK:
        return LearningTaskKind.LESSON_TEACHING
    return LearningTaskKind.GENERAL_TUTOR


def validate_plan_graph(plan: LearningPlan) -> None:
    nodes = plan.nodes
    by_key = {node.knowledge_key: node for node in nodes}
    if len(by_key) != len(nodes):
        raise ValueError("knowledge_key must be unique within a plan")
    for node in nodes:
        missing = sorted(set(node.prerequisite_keys) - set(by_key))
        if missing:
            raise ValueError(f"unknown prerequisite keys: {', '.join(missing)}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError("plan prerequisites must form an acyclic graph")
        visiting.add(key)
        for prerequisite in by_key[key].prerequisite_keys:
            visit(prerequisite)
        visiting.remove(key)
        visited.add(key)

    for key in sorted(by_key):
        visit(key)


def canonical_plan_payload(plan: LearningPlan) -> dict[str, object]:
    return {
        "title": plan.title,
        "target_level": plan.target_level,
        "modules": [
            {
                "module_key": module.module_key,
                "title": module.title,
                "description": module.description,
                "order_index": module.order_index,
                "is_core": module.is_core,
                "is_skippable": module.is_skippable,
                "nodes": [
                    {
                        "knowledge_key": node.knowledge_key,
                        "title": node.title,
                        "description": node.description,
                        "order_index": node.order_index,
                        "is_core": node.is_core,
                        "prerequisite_keys": list(node.prerequisite_keys),
                        "required_capabilities": list(node.required_capabilities),
                    }
                    for node in sorted(module.nodes, key=lambda item: item.order_index)
                ],
            }
            for module in sorted(plan.modules, key=lambda item: item.order_index)
        ],
    }


def canonical_plan_hash(plan: LearningPlan) -> str:
    encoded = json.dumps(canonical_plan_payload(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def calculate_plan_impact(
    current: LearningPlan,
    candidate: LearningPlan,
    *,
    progress_keys: set[str] | frozenset[str] = frozenset(),
) -> PlanImpact:
    current_nodes = {node.knowledge_key: node for node in current.nodes}
    candidate_nodes = {node.knowledge_key: node for node in candidate.nodes}
    current_position = {node.knowledge_key: index for index, node in enumerate(current.nodes)}
    candidate_position = {node.knowledge_key: index for index, node in enumerate(candidate.nodes)}
    retained = set(current_nodes) & set(candidate_nodes)
    return PlanImpact(
        added=tuple(sorted(set(candidate_nodes) - set(current_nodes))),
        removed=tuple(sorted(set(current_nodes) - set(candidate_nodes))),
        reordered=tuple(sorted(key for key in retained if current_position[key] != candidate_position[key])),
        prerequisite_changed=tuple(
            sorted(key for key in retained if current_nodes[key].prerequisite_keys != candidate_nodes[key].prerequisite_keys)
        ),
        retained_progress=tuple(sorted(retained & set(progress_keys))),
    )
