"""Native shared staging contracts, not admission or public selection authority."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.grounding.public_course_contracts import PublicCourseEvidenceBindingV1
from app.services.learning.item_supply.contracts import CoverageBlueprintV1, revalidate_contract
from app.services.learning.item_supply.evidence import require_exact_material
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.contracts import FiniteCourseTargetV1
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2, SourceReceiptV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True)
class PreparedSharedGeneration:
    lease: JobLeaseV1
    request: GenerationRequestV2
    reservation_id: UUID
    sources: tuple[SourceReceiptV2, ...]
    attempt_bound: int
    producer_binding: tuple[str, str]
    evidence_policy_hash: str = ""


@dataclass(frozen=True)
class SharedPipelineStageResult:
    state: str
    safe_reason: str
    artifact_id: UUID | None = None


def native_request(request: GenerationRequestV2) -> tuple[GenerationRequestV2, FiniteCourseTargetV1]:
    """Pure namespace/registry check; a current concrete C check is still required."""
    request = checked_model(request, GenerationRequestV2)
    if request.demand_binding is not None:
        raise PipelineRepositoryError("SHARED_PRIVATE_DEMAND_DENIED")
    bindings = []
    for material in request.materials:
        if type(material.binding) is not PublicCourseEvidenceBindingV1:
            raise PipelineRepositoryError("SHARED_NATIVE_SOURCE_REQUIRED")
        require_exact_material(material)
        bindings.append(material.binding)
    first = bindings[0]
    if any((b.target_id, b.target_definition_hash) != (first.target_id, first.target_definition_hash)
           for b in bindings):
        raise PipelineRepositoryError("SHARED_TARGET_MISMATCH")
    return request, get_finite_course_target(first.target_id)


def match_shared_request(request: GenerationRequestV2, coverage: CoverageBlueprintV1,
                         lease: JobLeaseV1) -> FiniteCourseTargetV1:
    request, target = native_request(request)
    coverage = revalidate_contract(coverage, CoverageBlueprintV1)
    lease = checked_model(lease, JobLeaseV1)
    scope, blueprint = coverage.scope, request.blueprint
    # Persisted input identity comparisons are NOT item coverage or family proof.
    if (lease.visibility != "public" or scope.visibility != "public"
            or request.profile != lease.profile or request.scope_hash != scope.scope_hash
            or blueprint.knowledge_key != scope.knowledge_key
            or blueprint.language_id != scope.language_id or scope.language_id != target.language_id
            or scope.subject_id != target.subject_id or scope.subject_version != "1.0"
            or scope.required_facets != target.required_facets
            or blueprint.item_kind != scope.item_kind or scope.item_kind.value != target.assessment.item_kind
            or blueprint.purpose != scope.purpose
            or scope.purpose.value not in (target.assessment.purpose, "remediation")
            or blueprint.required_capabilities != scope.required_capabilities
            or scope.required_capabilities != target.required_capabilities
            or scope.interaction not in blueprint.allowed_interactions
            or scope.interaction.value != target.assessment.interaction
            or scope.assessment_contract_version != target.assessment.assessment_contract_version
            or scope.runtime_profile_id != (target.assessment.runtime_profile_id or "static-exact-v1")
            or blueprint.runtime_profile_id != (None if target.assessment.runtime_profile_id is None
                                                  else target.assessment.execution_contract)):
        raise PipelineRepositoryError("SHARED_REQUEST_SCOPE_MISMATCH")
    return target
