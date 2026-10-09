"""Immutable declaration snapshot, not runtime/source/inventory readiness."""
from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from app.services.grounding.autonomous.contracts import FrozenContract
from app.services.learning.item_bank.contracts import (
    LearningItemInteraction,
    LearningItemKind,
    LearningItemPurpose,
    canonical_hash,
)
from app.services.runners.language_capabilities import (
    LANGUAGE_CAPABILITIES,
    PUBLIC_COURSE_LANGUAGE_MAP,
    CapabilityState,
    ExecutionMode,
    ExerciseGenerationState,
    GroundingState,
    PresentationMode,
    ReviewFeedbackSupport,
    RunnerKey,
    SourceTrustPolicy,
    StaticAnalysisSupport,
    TestSupport,
)


_LanguageId = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]{0,79}$")
]
_Text = Annotated[str, Field(min_length=1, max_length=1000)]
_Version = Annotated[
    str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
]


class _MatrixContract(FrozenContract):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, revalidate_instances="always"
    )


class LanguageCapabilityDeclaration(_MatrixContract):
    """Copy all fields of the existing LanguageCapability without inferring readiness."""

    language_id: _LanguageId
    display_name: _Text
    aliases: tuple[Annotated[str, Field(min_length=1, max_length=80)], ...] = Field(
        max_length=32
    )
    current_public_course_language: _LanguageId | None
    capability_state: CapabilityState
    lesson_generation: CapabilityState
    grounding: GroundingState
    exercise_generation: ExerciseGenerationState
    execution: ExecutionMode
    tests: TestSupport
    static_analysis: StaticAnalysisSupport
    review_feedback: ReviewFeedbackSupport
    presentation: PresentationMode
    ux_disclosure: _Text
    runner_key: RunnerKey
    source_trust_policy: SourceTrustPolicy
    enabled_for_public_selection: bool
    sandbox_boundary: Annotated[str, Field(min_length=1, max_length=160)] | None


class PublicCourseLanguageDeclaration(_MatrixContract):
    course_language_id: _LanguageId
    language_ids: tuple[_LanguageId, ...] = Field(min_length=1, max_length=32)


class DeliverySliceDeclaration(_MatrixContract):
    """Versioned bounded delivery target, never a passed acceptance row."""

    slice_id: Literal["M01", "M02", "M03"]
    version: Literal["item_supply_first_batch_v1"] = "item_supply_first_batch_v1"
    language_id: _LanguageId
    dialect: Literal["sqlite"] | None
    item_kind: LearningItemKind
    item_purpose: LearningItemPurpose
    interaction: LearningItemInteraction
    content_contract_target: _Version
    gate_contract_target: _Version
    gate_adapter_status: Literal["existing_contract", "planned_adapter"]
    acceptance_status: Literal["not_executed"] = "not_executed"

    @model_validator(mode="after")
    def bounded_release_target(self) -> DeliverySliceDeclaration:
        # These are the three approved release rows, not another item registry.
        actual = (
            self.language_id, self.dialect, self.item_kind, self.item_purpose,
            self.interaction, self.content_contract_target, self.gate_contract_target,
            self.gate_adapter_status,
        )
        expected: tuple[object, ...]
        if self.slice_id == "M01":
            expected = (
                "python", None, LearningItemKind.KNOWLEDGE_CHECK,
                LearningItemPurpose.KNOWLEDGE_CHECK, LearningItemInteraction.RESPOND,
                "single_choice", "knowledge_check_v1", "existing_contract",
            )
        elif self.slice_id == "M02":
            expected = (
                "python", None, LearningItemKind.CODE, LearningItemPurpose.EXERCISE,
                LearningItemInteraction.RUN, "stdout_test",
                "GateExecutionAssessmentAdapterV1", "planned_adapter",
            )
        else:
            expected = (
                "sql", "sqlite", LearningItemKind.SQL, LearningItemPurpose.EXERCISE,
                LearningItemInteraction.QUERY, "sql_v2",
                "GateExecutionAssessmentAdapterV1", "planned_adapter",
            )
        if actual != expected:
            raise ValueError("invalid delivery slice target")
        return self


class SupportMatrixSnapshot(_MatrixContract):
    version: Literal["item_supply_support_matrix_v1"] = "item_supply_support_matrix_v1"
    authority: Literal["declaration_only"] = "declaration_only"
    gate_metadata_status: Literal["separate_p0_snapshot"] = "separate_p0_snapshot"
    runtime_readiness: Literal["not_evaluated"] = "not_evaluated"
    source_readiness: Literal["not_evaluated"] = "not_evaluated"
    inventory_readiness: Literal["not_evaluated"] = "not_evaluated"
    languages: tuple[LanguageCapabilityDeclaration, ...] = Field(min_length=1, max_length=128)
    public_course_languages: tuple[PublicCourseLanguageDeclaration, ...] = Field(
        min_length=1, max_length=128
    )
    item_kinds: tuple[LearningItemKind, ...] = Field(min_length=1, max_length=32)
    item_purposes: tuple[LearningItemPurpose, ...] = Field(min_length=1, max_length=32)
    interactions: tuple[LearningItemInteraction, ...] = Field(min_length=1, max_length=32)
    first_batch_slices: tuple[DeliverySliceDeclaration, ...] = Field(
        min_length=3, max_length=3
    )

    @model_validator(mode="after")
    def consistent_declarations(self) -> SupportMatrixSnapshot:
        language_ids = tuple(language.language_id for language in self.languages)
        course_ids = tuple(course.course_language_id for course in self.public_course_languages)
        if (
            language_ids != tuple(sorted(set(language_ids)))
            or course_ids != tuple(sorted(set(course_ids)))
            or self.item_kinds != tuple(sorted(LearningItemKind, key=lambda item: item.value))
            or self.item_purposes != tuple(sorted(LearningItemPurpose, key=lambda item: item.value))
            or self.interactions != tuple(sorted(LearningItemInteraction, key=lambda item: item.value))
            or tuple(row.slice_id for row in self.first_batch_slices) != ("M01", "M02", "M03")
        ):
            raise ValueError("invalid support declaration identity")
        languages = {language.language_id: language for language in self.languages}
        courses = {
            course.course_language_id: course.language_ids for course in self.public_course_languages
        }
        for course in self.public_course_languages:
            if len(set(course.language_ids)) != len(course.language_ids):
                raise ValueError("invalid course language declaration")
            for language_id in course.language_ids:
                language = languages.get(language_id)
                if (
                    language is None
                    or language.current_public_course_language != course.course_language_id
                    or not language.enabled_for_public_selection
                ):
                    raise ValueError("invalid course language declaration")
        for language in self.languages:
            if (
                language.enabled_for_public_selection
                and language.language_id not in courses.get(language.current_public_course_language or "", ())
            ):
                raise ValueError("invalid public selection declaration")
        for row in self.first_batch_slices:
            if row.language_id not in languages:
                raise ValueError("invalid delivery language declaration")
        return self

    @property
    def matrix_hash(self) -> str:
        try:
            checked = _checked_snapshot(self)
            return canonical_hash(checked.model_dump(mode="json"))
        except (ValueError, TypeError, AttributeError, OverflowError):
            raise ValueError("invalid support snapshot") from None

    @property
    def snapshot_hash(self) -> str:
        return self.matrix_hash


def _checked_snapshot(snapshot: SupportMatrixSnapshot) -> SupportMatrixSnapshot:
    if (
        type(snapshot) is not SupportMatrixSnapshot
        or set(snapshot.__dict__) != set(SupportMatrixSnapshot.model_fields)
        or snapshot.__pydantic_extra__
    ):
        raise ValueError("invalid support snapshot")
    collections = (
        (snapshot.languages, LanguageCapabilityDeclaration, 128),
        (snapshot.public_course_languages, PublicCourseLanguageDeclaration, 128),
        (snapshot.first_batch_slices, DeliverySliceDeclaration, 3),
    )
    for rows, kind, limit in collections:
        if type(rows) is not tuple or len(rows) > limit:
            raise ValueError("invalid support snapshot")
        for row in rows:
            if (
                type(row) is not kind
                or set(row.__dict__) != set(kind.model_fields)
                or row.__pydantic_extra__
            ):
                raise ValueError("invalid support declaration")
    return SupportMatrixSnapshot.model_validate(snapshot)


def build_support_matrix() -> SupportMatrixSnapshot:
    """Read pure registries only; current Gate AST facts live in the caller's P0.

    Alias spelling, canonical identities and partial/planned/nonpublic states are
    retained verbatim. The three release targets are explicit metadata, not a
    Cartesian language/type promise or installed adapter/runtime evidence.
    """
    languages = tuple(
        LanguageCapabilityDeclaration.model_validate(asdict(capability))
        for _, capability in sorted(LANGUAGE_CAPABILITIES.items())
    )
    if any(key != capability.language_id for key, capability in LANGUAGE_CAPABILITIES.items()):
        raise ValueError("invalid language registry identity")
    return SupportMatrixSnapshot(
        languages=languages,
        public_course_languages=tuple(
            PublicCourseLanguageDeclaration(course_language_id=key, language_ids=language_ids)
            for key, language_ids in sorted(PUBLIC_COURSE_LANGUAGE_MAP.items())
        ),
        item_kinds=tuple(sorted(LearningItemKind, key=lambda item: item.value)),
        item_purposes=tuple(sorted(LearningItemPurpose, key=lambda item: item.value)),
        interactions=tuple(sorted(LearningItemInteraction, key=lambda item: item.value)),
        first_batch_slices=(
            DeliverySliceDeclaration(
                slice_id="M01", language_id="python", dialect=None,
                item_kind=LearningItemKind.KNOWLEDGE_CHECK,
                item_purpose=LearningItemPurpose.KNOWLEDGE_CHECK,
                interaction=LearningItemInteraction.RESPOND,
                content_contract_target="single_choice",
                gate_contract_target="knowledge_check_v1",
                gate_adapter_status="existing_contract",
            ),
            DeliverySliceDeclaration(
                slice_id="M02", language_id="python", dialect=None,
                item_kind=LearningItemKind.CODE, item_purpose=LearningItemPurpose.EXERCISE,
                interaction=LearningItemInteraction.RUN,
                content_contract_target="stdout_test",
                gate_contract_target="GateExecutionAssessmentAdapterV1",
                gate_adapter_status="planned_adapter",
            ),
            DeliverySliceDeclaration(
                slice_id="M03", language_id="sql", dialect="sqlite",
                item_kind=LearningItemKind.SQL, item_purpose=LearningItemPurpose.EXERCISE,
                interaction=LearningItemInteraction.QUERY,
                content_contract_target="sql_v2",
                gate_contract_target="GateExecutionAssessmentAdapterV1",
                gate_adapter_status="planned_adapter",
            ),
        ),
    )
