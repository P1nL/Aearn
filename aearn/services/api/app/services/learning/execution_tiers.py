"""Single server-side authority for learner-visible execution tiers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from aearn_shared.execution import RuntimeCatalogRegistryV1, runtime_id_for_profile
from app.services.learning.contracts import (
    ExecutionComposition,
    ExecutionTier,
    ExecutionTierProjection,
)
from app.services.runners.language_capabilities import LanguageCapability


class ExecutorAvailabilityPort(Protocol):
    def is_runtime_available(self, runtime_id: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class StaticExecutorAvailability:
    available_runtime_ids: frozenset[str] = frozenset()

    def is_runtime_available(self, runtime_id: str) -> bool:
        return runtime_id in self.available_runtime_ids


@dataclass(frozen=True, slots=True)
class ExecutionTierInputs:
    composition: ExecutionComposition
    local_runner_available: bool
    runtime_registry: RuntimeCatalogRegistryV1 | None
    executor_availability: ExecutorAvailabilityPort | None


class ExecutionTierResolver:
    """Resolve one honest tier without launching either a runner or executor."""

    def resolve(
        self,
        *,
        language: LanguageCapability,
        inputs: ExecutionTierInputs,
    ) -> ExecutionTierProjection:
        runtime_id = runtime_id_for_profile(runtime_tier=language.execution, language=language.language_id)
        if inputs.composition is ExecutionComposition.PUBLIC:
            if (
                runtime_id is not None
                and inputs.runtime_registry is not None
                and inputs.runtime_registry.lock_for(runtime_id) is not None
                and inputs.executor_availability is not None
                and inputs.executor_availability.is_runtime_available(runtime_id)
            ):
                return ExecutionTierProjection(
                    tier=ExecutionTier.CONTAINER_VERIFIED,
                    disclosure="This language has a reviewed container runtime with compatible executor health.",
                    runtime_id=runtime_id,
                )
            return self._static_or_unavailable(language)

        if language.supports_execution and inputs.local_runner_available:
            return ExecutionTierProjection(
                tier=ExecutionTier.TEACHING_LOCAL,
                disclosure=(
                    "Local teaching execution is available for controlled development or internal demonstration; "
                    "it is not a public container-isolation claim."
                ),
                runtime_id=runtime_id,
            )
        return self._static_or_unavailable(language)

    @staticmethod
    def _static_or_unavailable(language: LanguageCapability) -> ExecutionTierProjection:
        supports_static_teaching = (
            language.lesson_generation not in {"unsupported", "planned"}
            or language.exercise_generation == "static_review"
            or language.review_feedback in {"full", "static_only"}
            or language.grounding in {"official", "trusted"}
            or language.tests == "static_review_only"
        )
        if supports_static_teaching:
            return ExecutionTierProjection(
                tier=ExecutionTier.STATIC_ONLY,
                disclosure="Teaching and static code review are available, but code is not claimed to have run or compiled.",
            )
        return ExecutionTierProjection(
            tier=ExecutionTier.UNAVAILABLE,
            disclosure="This language does not currently have a verified teaching or execution path.",
        )
