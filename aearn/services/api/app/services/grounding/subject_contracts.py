"""Immutable Subject and capability contracts for the phase-I RAG taxonomy."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.services.runners.language_capabilities import SourceTrustPolicy

SubjectKind = Literal["language_core", "standard_library", "framework", "library", "platform", "database", "toolchain"]
SubjectVersionPolicy = Literal["operator_locked"]
SubjectReleaseState = Literal["implemented", "fixture_only", "shadow", "lesson_only", "static_only", "executable", "planned", "unavailable"]
SubjectAssessment = Literal["lesson", "practice", "execution", "tests", "static_analysis", "review"]
SubjectRuntimeProfile = Literal["browser", "python", "node", "sql", "compiled"]
KNOWN_SUBJECT_FACETS = frozenset({
    "fundamentals", "syntax", "functions", "data-model", "modules", "async", "types", "dom",
    "styling", "accessibility", "queries", "schema", "transactions", "http", "routing",
    "validation", "components", "state", "effects", "server-runtime", "llm-api",
    "tool-calling", "handwritten-rag", "langchain-core", "postgresql-dialect",
})


class GroundingSubject(BaseModel):
    """Developer-declared Subject policy, not observed corpus coverage."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_id: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
    display_name: str = Field(min_length=1, max_length=120)
    subject_kind: SubjectKind
    parent_subject_id: str | None = None
    language_ids: tuple[str, ...] = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    version_policy: SubjectVersionPolicy = "operator_locked"
    source_trust_policy: SourceTrustPolicy
    required_facets: tuple[str, ...] = Field(min_length=1)
    optional_facets: tuple[str, ...] = ()
    runtime_profile_keys: tuple[SubjectRuntimeProfile, ...] = ()
    assessment_capabilities: tuple[SubjectAssessment, ...] = ()
    release_state: SubjectReleaseState

    @model_validator(mode="after")
    def validate_facets(self) -> GroundingSubject:
        for name, values in (
            ("language_ids", self.language_ids), ("aliases", self.aliases),
            ("required_facets", self.required_facets), ("optional_facets", self.optional_facets),
            ("runtime_profile_keys", self.runtime_profile_keys),
            ("assessment_capabilities", self.assessment_capabilities),
        ):
            if len(values) != len(set(values)) or any(not value or value != value.strip() for value in values):
                raise ValueError(f"Subject {self.subject_id} has invalid {name}")
        if self.parent_subject_id == self.subject_id:
            raise ValueError(f"Subject {self.subject_id} cannot parent itself")
        if self.subject_id in {alias.casefold() for alias in self.aliases}:
            raise ValueError(f"Subject {self.subject_id} aliases its own id")
        if not self.display_name.strip():
            raise ValueError(f"Subject {self.subject_id} has empty display_name")
        if set(self.required_facets) & set(self.optional_facets):
            raise ValueError(f"Subject {self.subject_id} has overlapping facets")
        unknown = (set(self.required_facets) | set(self.optional_facets)) - KNOWN_SUBJECT_FACETS
        if unknown:
            raise ValueError(f"Subject {self.subject_id} has unknown facets: {', '.join(sorted(unknown))}")
        assessments = set(self.assessment_capabilities)
        if self.release_state == "fixture_only" and (
            self.runtime_profile_keys or assessments & {"execution", "tests"}
        ):
            raise ValueError(f"Subject {self.subject_id} fixture cannot claim runtime readiness")
        if self.release_state == "lesson_only" and (
            self.runtime_profile_keys or assessments - {"lesson"}
        ):
            raise ValueError(f"Subject {self.subject_id} has inconsistent lesson_only release state")
        if self.release_state == "static_only" and (
            self.runtime_profile_keys or assessments & {"practice", "execution", "tests"}
        ):
            raise ValueError(f"Subject {self.subject_id} has inconsistent static_only release state")
        if self.release_state == "executable" and (
            "execution" not in assessments or not self.runtime_profile_keys
        ):
            raise ValueError(f"Subject {self.subject_id} has inconsistent executable release state")
        return self


class SubjectCapabilityProjection(BaseModel):
    """Internal composition seam; declares no corpus or live runner readiness."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_id: str
    language_ids: tuple[str, ...]
    release_state: SubjectReleaseState
    source_coverage: SubjectReleaseState
    lesson_generation: SubjectReleaseState
    practice_generation: SubjectReleaseState
    execution: SubjectReleaseState
    tests: SubjectReleaseState
    static_analysis: SubjectReleaseState
    review: SubjectReleaseState
    public_release: SubjectReleaseState
    public_course_admissible: bool

    @model_validator(mode="after")
    def validate_admission(self) -> SubjectCapabilityProjection:
        components = (
            self.lesson_generation, self.practice_generation, self.execution,
            self.tests, self.static_analysis, self.review,
        )
        allowed_components = {
            "fixture_only": {"unavailable", "planned", "fixture_only"},
            "shadow": {"unavailable", "planned", "shadow"},
            "planned": {"unavailable", "planned"},
            "unavailable": {"unavailable"},
        }
        allowed = allowed_components.get(self.release_state)
        if allowed is not None and any(component not in allowed for component in components):
            raise ValueError("Subject components cannot exceed an unreleased state")
        if self.release_state == "fixture_only" and (
            self.execution not in {"unavailable", "planned"}
            or self.tests not in {"unavailable", "planned"}
        ):
            raise ValueError("Fixture cannot claim executable assessment readiness")
        if self.release_state == "lesson_only" and any(
            component not in {"unavailable", "planned"}
            for component in (self.practice_generation, self.execution, self.tests, self.static_analysis, self.review)
        ):
            raise ValueError("Lesson-only release cannot claim other assessment readiness")
        if self.release_state == "static_only" and any(
            component not in {"unavailable", "planned"}
            for component in (self.practice_generation, self.execution, self.tests)
        ):
            raise ValueError("Static-only release cannot claim executable assessment readiness")
        if self.release_state == "unavailable" and self.source_coverage == "implemented":
            raise ValueError("Unavailable Subject cannot claim active source coverage")
        if self.public_course_admissible and (
            self.release_state not in {"implemented", "executable"}
            or self.public_release != self.release_state
            or self.source_coverage != "implemented"
        ):
            raise ValueError("Public Subject admission requires implemented release and source coverage")
        return self

    def public_projection(self) -> SubjectCapabilityPublicProjection:
        """Safe subset: fixture/shadow and internal component states never leak."""
        return SubjectCapabilityPublicProjection(
            subject_id=self.subject_id,
            availability="available" if self.public_course_admissible else "unavailable",
        )


class SubjectCapabilityPublicProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    subject_id: str
    availability: Literal["available", "unavailable"]
