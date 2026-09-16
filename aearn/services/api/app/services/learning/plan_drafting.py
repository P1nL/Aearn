"""Typed planning-session and draft contracts built on the frozen LearningPlan domain."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.learning.contracts import LearningPlan, LearningPlanModule, LearningPlanNode, stable_key


PLAN_DRAFT_GENERATOR_VERSION = "learning-plan-draft-capability-v1"
PLAN_DRAFT_POLICY_VERSION = "learning-plan-draft-policy-v1"


class LearningPlanSessionStatus(StrEnum):
    COLLECTING = "collecting"
    DRAFT_READY = "draft_ready"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class LearningPlanExperienceLevel(StrEnum):
    NEW = "new"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CompactPlanProfile(_StrictModel):
    language_id: str = Field(min_length=1, max_length=80)
    goal_text: str = Field(min_length=1, max_length=200)
    target_level: str = Field(min_length=1, max_length=120)
    weekly_minutes: int = Field(ge=15, le=10_080)
    experience_level: LearningPlanExperienceLevel
    teaching_preferences: list[str] = Field(default_factory=list, max_length=4)
    pace_summary: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=240)

    @field_validator("teaching_preferences")
    @classmethod
    def validate_preferences(cls, values: list[str]) -> list[str]:
        normalized = [" ".join(value.split()) for value in values]
        if len(normalized) != len(set(normalized)) or any(not value or len(value) > 80 for value in normalized):
            raise ValueError("teaching preferences must be unique bounded text")
        return normalized


class CompactPlanNode(_StrictModel):
    knowledge_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    is_core: bool = True
    prerequisite_keys: list[str] = Field(default_factory=list, max_length=8)
    required_capabilities: list[str] = Field(default_factory=list, max_length=8)
    catalog_knowledge_key: str | None = Field(
        default=None, min_length=1, max_length=160,
        description="Exact published catalog knowledge key; keeps the course step identity separate. Never infer an alias from a title.",
    )

    @field_validator("catalog_knowledge_key")
    @classmethod
    def normalize_catalog_key(cls, value: str | None) -> str | None:
        return stable_key(value, label="catalog_knowledge_key") if value is not None else None

    @field_validator("knowledge_key")
    @classmethod
    def normalize_knowledge_key(cls, value: str) -> str:
        return stable_key(value, label="knowledge_key")

    @field_validator("prerequisite_keys", "required_capabilities")
    @classmethod
    def normalize_keys(cls, values: list[str]) -> list[str]:
        normalized = [stable_key(value, label="stable key") for value in values]
        if len(normalized) != len(set(normalized)):
            raise ValueError("stable keys must be unique")
        return normalized


class CompactPlanModule(_StrictModel):
    module_key: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=300)
    is_core: bool = True
    is_skippable: bool = False
    nodes: list[CompactPlanNode] = Field(min_length=1, max_length=8)

    @field_validator("module_key")
    @classmethod
    def normalize_module_key(cls, value: str) -> str:
        return stable_key(value, label="module_key")

    @model_validator(mode="after")
    def validate_node_keys(self) -> "CompactPlanModule":
        keys = [node.knowledge_key for node in self.nodes]
        if len(keys) != len(set(keys)):
            raise ValueError("knowledge keys must be unique within a module")
        return self


@dataclass(frozen=True, slots=True)
class LearningPlanSourceSummary:
    source_id: str
    display_name: str
    trust_tier: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "display_name": self.display_name,
            "trust_tier": self.trust_tier,
        }


@dataclass(frozen=True, slots=True)
class LearningPlanDraftArtifact:
    profile: CompactPlanProfile
    plan: LearningPlan
    sources: tuple[LearningPlanSourceSummary, ...]

    @property
    def content_hash(self) -> str:
        payload = {
            "profile": self.profile.model_dump(mode="json"),
            "plan_hash": self.plan.content_hash,
            "sources": [source.as_dict() for source in self.sources],
            "generator_version": self.plan.generator_version,
            "policy_version": self.plan.policy_version,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def decode_compact_profile(profile_json: str) -> CompactPlanProfile:
    return CompactPlanProfile.model_validate(_json_object(profile_json, label="profile_json"))


def decode_compact_modules(module_json_values: tuple[str, ...]) -> tuple[CompactPlanModule, ...]:
    return tuple(
        CompactPlanModule.model_validate(_json_object(value, label=f"module_{index}"))
        for index, value in enumerate(module_json_values, start=1)
    )


def build_plan_draft(
    *,
    profile: CompactPlanProfile,
    modules: tuple[CompactPlanModule, ...],
    sources: tuple[LearningPlanSourceSummary, ...],
    change_reason: str,
) -> LearningPlanDraftArtifact:
    if not 2 <= len(modules) <= 8:
        raise ValueError("plan draft must contain 2..8 modules")
    domain_modules = tuple(
        LearningPlanModule(
            module_key=module.module_key,
            title=module.title,
            description=module.description,
            order_index=module_index,
            is_core=module.is_core,
            is_skippable=module.is_skippable,
            nodes=tuple(
                LearningPlanNode(
                    knowledge_key=node.knowledge_key,
                    title=node.title,
                    description=node.description,
                    order_index=node_index,
                    is_core=node.is_core,
                    prerequisite_keys=tuple(node.prerequisite_keys),
                    required_capabilities=tuple(node.required_capabilities) or (profile.language_id,),
                    catalog_knowledge_key=node.catalog_knowledge_key,
                )
                for node_index, node in enumerate(module.nodes)
            ),
        )
        for module_index, module in enumerate(modules)
    )
    plan = LearningPlan(
        title=profile.title,
        target_level=profile.target_level,
        generator_version=PLAN_DRAFT_GENERATOR_VERSION,
        policy_version=PLAN_DRAFT_POLICY_VERSION,
        change_reason=change_reason,
        modules=domain_modules,
    )
    return LearningPlanDraftArtifact(profile=profile, plan=plan, sources=sources)


def decode_plan_draft(
    *,
    profile_json: str,
    module_json_values: tuple[str, ...],
    sources: tuple[LearningPlanSourceSummary, ...],
    change_reason: str,
) -> LearningPlanDraftArtifact:
    return build_plan_draft(
        profile=decode_compact_profile(profile_json),
        modules=decode_compact_modules(module_json_values),
        sources=sources,
        change_reason=change_reason,
    )


def draft_artifact_from_row(row: Mapping[str, object]) -> LearningPlanDraftArtifact:
    profile_raw = row.get("profile_json")
    plan_raw = row.get("plan_json")
    source_raw = row.get("source_summary_json")
    if not isinstance(profile_raw, Mapping) or not isinstance(plan_raw, Mapping):
        raise ValueError("stored plan draft payload is invalid")
    profile = CompactPlanProfile.model_validate(profile_raw)
    modules_raw = plan_raw.get("modules")
    if not isinstance(modules_raw, list):
        raise ValueError("stored plan modules are invalid")
    plan = LearningPlan(
        title=str(plan_raw.get("title") or ""),
        target_level=str(plan_raw.get("target_level") or ""),
        generator_version=str(row.get("generator_version") or ""),
        policy_version=str(row.get("policy_version") or ""),
        change_reason=str(row.get("change_reason") or ""),
        modules=tuple(_domain_module(item) for item in modules_raw if isinstance(item, Mapping)),
    )
    sources = tuple(
        LearningPlanSourceSummary(
            source_id=str(item.get("source_id") or ""),
            display_name=str(item.get("display_name") or ""),
            trust_tier=str(item.get("trust_tier") or ""),
        )
        for item in (source_raw if isinstance(source_raw, list) else [])
        if isinstance(item, Mapping)
    )
    return LearningPlanDraftArtifact(profile=profile, plan=plan, sources=sources)


def _domain_module(raw: Mapping[str, object]) -> LearningPlanModule:
    nodes_raw = raw.get("nodes")
    nodes = nodes_raw if isinstance(nodes_raw, list) else []
    return LearningPlanModule(
        module_key=str(raw.get("module_key") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        order_index=_int(raw.get("order_index")),
        is_core=bool(raw.get("is_core", True)),
        is_skippable=bool(raw.get("is_skippable", False)),
        nodes=tuple(_domain_node(item) for item in nodes if isinstance(item, Mapping)),
    )


def _domain_node(raw: Mapping[str, object]) -> LearningPlanNode:
    prerequisites = raw.get("prerequisite_keys")
    capabilities = raw.get("required_capabilities")
    return LearningPlanNode(
        knowledge_key=str(raw.get("knowledge_key") or ""),
        title=str(raw.get("title") or ""),
        description=str(raw.get("description") or ""),
        order_index=_int(raw.get("order_index")),
        is_core=bool(raw.get("is_core", True)),
        prerequisite_keys=tuple(str(value) for value in prerequisites) if isinstance(prerequisites, list) else (),
        required_capabilities=tuple(str(value) for value in capabilities) if isinstance(capabilities, list) else (),
    )


def _json_object(value: str, *, label: str) -> dict[str, object]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    return parsed


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0
