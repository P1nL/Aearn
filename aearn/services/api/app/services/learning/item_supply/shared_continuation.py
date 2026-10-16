"""Explicit same-root PUBLIC candidate continuation, default off.

Reuses immutable author DATA under freshly checked source authority. It never
rehydrates runner seals, issues a provider allowance, copies a generation row or
pretends the new job performed generation. Stage/repository integration is separate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash, learning_item_uuid
from app.services.learning.item_supply.contracts import CoverageBlueprintV1, Digest
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, check_finite_source_spec
from app.services.learning.item_supply.finite_candidate_validation import (
    FiniteCandidateValidationInputsV1, prepare_finite_candidate_validation,
)
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import CoverageObligationV1, RetryPolicyV1, derive_runtime_contract_hash
from app.services.learning.item_supply.provider_adapter import GENERATION_ADAPTER_VERSION, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, server_clock
from app.services.learning.item_supply.shared_pipeline_contracts import native_request
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model


class SharedCandidateContinuationBindingV1(StorageContract):
    schema_version: Literal["shared_candidate_continuation_v1"] = "shared_candidate_continuation_v1"
    operation_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._:-]{0,79}$")
    root_id: UUID
    canonical_root_key: Digest
    coverage_blueprint_hash: Digest
    scope_hash: Digest
    generation_artifact_id: UUID
    original_job_id: UUID
    original_lease_generation: int = Field(ge=1)
    original_profile_hash: Digest
    artifact_hash: Digest
    original_request_hash: Digest
    material_set_hash: Digest
    source_receipt_set_hash: Digest
    candidate_id: UUID
    item_id: UUID
    version_id: UUID
    source_hash: Digest
    content_hash: Digest
    target_id: str
    target_definition_hash: Digest
    specification_hash: Digest
    adoption_lease: JobLeaseV1
    authority: Literal["immutable_generation_data_only"] = "immutable_generation_data_only"
    execution_authority_reusable: Literal[False] = False
    publication_enabled: Literal[False] = False

    @model_validator(mode="after")
    def distinct_public_job(self) -> SharedCandidateContinuationBindingV1:
        if self.adoption_lease.visibility != "public" or self.adoption_lease.job_id == self.original_job_id:
            raise ValueError("continuation_requires_distinct_public_job")
        return self

    @property
    def binding_hash(self) -> str:
        return canonical_hash(checked_model(self, SharedCandidateContinuationBindingV1).model_dump(mode="json"))


@dataclass(frozen=True)
class ResolvedSharedCandidateContinuation:
    binding: SharedCandidateContinuationBindingV1
    lease: JobLeaseV1
    original_artifact: dict[str, Any]
    source: LearningItemSourceV1
    original_request: GenerationRequestV2
    inputs: FiniteCandidateValidationInputsV1


def bind_shared_candidate_continuation(*, artifact: dict[str, Any], spec: FiniteCandidateSpecV1,
    lease: JobLeaseV1, operation_key: str) -> tuple[SharedCandidateContinuationBindingV1,
        LearningItemSourceV1, GenerationRequestV2, GenerationReceiptV2, FiniteCandidateValidationInputsV1]:
    """Pure exact DATA binding. Caller must check current DB/source authority."""
    spec, lease = checked_model(spec, FiniteCandidateSpecV1), checked_model(lease, JobLeaseV1)
    request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
    source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
    receipt = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
    request, target = native_request(request)
    coverage = CoverageBlueprintV1.model_validate_json(json.dumps(artifact["coverage_json"]))
    scope = coverage.scope
    obligation = CoverageObligationV1(blueprint_hash=coverage.blueprint_hash, scope_hash=scope.scope_hash,
        objective_hash=coverage.objective_hash, purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope), visibility="public", policy_version=coverage.policy_version)
    provider = receipt.provider
    if (artifact.get("generation_completed") is not True or artifact.get("generation_settled") is not True
            or UUID(str(artifact["job_id"])) == lease.job_id or lease.visibility != "public"
            or lease.profile.profile_key_hash != request.profile.profile_key_hash
            or spec.coverage_blueprint != coverage or request.scope_hash != scope.scope_hash
            or artifact["canonical_key"] != obligation.canonical_key
            or request.blueprint != spec.blueprint or request.public_template != spec.public_template
            or source.blueprint != request.blueprint
            or source.source_hash != artifact["source_hash"] or source.content_hash != artifact["content_hash"]
            or request.candidate_id != UUID(str(artifact["candidate_id"]))
            or receipt.candidate_id != request.candidate_id or receipt.scope_hash != request.scope_hash
            or receipt.source_hash != source.source_hash or receipt.content_hash != source.content_hash
            or UUID(str(artifact["item_id"])) != learning_item_uuid("item", request.item_key)
            or UUID(str(artifact["version_id"])) != learning_item_uuid("version", f"{request.item_key}@{request.version}")
            or artifact["target_id"] != target.target_id or target.target_id != spec.target_id
            or artifact["target_definition_hash"] != target.definition_hash
            or provider.mode != "provider" or provider.model != provider.configured_model
            or provider.provider != artifact["provider_key"]
            or provider.provider_version != GENERATION_ADAPTER_VERSION or provider.prompt_version != GENERATION_PROMPT_VERSION
            or len(receipt.sources) != len(request.materials) or any(s.mode != "current_authority" for s in receipt.sources)):
        raise PipelineRepositoryError("SHARED_CONTINUATION_ORIGINAL_MISMATCH")
    try:
        check_finite_source_spec(source, spec)
    except ValueError:
        raise PipelineRepositoryError("SHARED_CONTINUATION_ORIGINAL_MISMATCH") from None
    artifact_hash = canonical_hash({k: artifact[k + "_json"] for k in ("source", "receipt", "request")})
    if artifact_hash != artifact["artifact_hash"]:
        raise PipelineRepositoryError("SHARED_CONTINUATION_ARTIFACT_HASH_MISMATCH")
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
    binding = SharedCandidateContinuationBindingV1(operation_key=operation_key,
        root_id=UUID(str(artifact["root_id"])), canonical_root_key=obligation.canonical_key,
        coverage_blueprint_hash=coverage.blueprint_hash, scope_hash=scope.scope_hash,
        generation_artifact_id=UUID(str(artifact["id"])), original_job_id=UUID(str(artifact["job_id"])),
        original_lease_generation=artifact["lease_generation"], original_profile_hash=request.profile.profile_hash,
        artifact_hash=artifact_hash, original_request_hash=canonical_hash(request.model_dump(mode="json")),
        material_set_hash=canonical_hash([m.model_dump(mode="json") for m in request.materials]),
        source_receipt_set_hash=canonical_hash([s.model_dump(mode="json") for s in receipt.sources]),
        candidate_id=request.candidate_id, item_id=UUID(str(artifact["item_id"])), version_id=UUID(str(artifact["version_id"])),
        source_hash=source.source_hash, content_hash=source.content_hash, target_id=target.target_id,
        target_definition_hash=target.definition_hash, specification_hash=spec.specification_hash, adoption_lease=lease)
    return binding, source, request, receipt, inputs


class _NoContinuationLease(Exception):
    pass


class SharedCandidateContinuationOwner:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, enabled: bool = False) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)

    def _require(self, authority: RagSourceAuthority) -> None:
        if not self.enabled or not self.settings.learning_item_supply_enabled:
            raise PipelineRepositoryError("SHARED_CONTINUATION_DISABLED")
        self.artifacts.require_owner()
        self.artifacts.require_source(authority)

    def _original(self, artifact_id: UUID, authority: RagSourceAuthority) -> dict[str, Any]:
        row = self._original_row(artifact_id)
        request = GenerationRequestV2.model_validate_json(json.dumps(row["request_json"]))
        receipt = GenerationReceiptV2.model_validate_json(json.dumps(row["receipt_json"]))
        for material, expected in zip(request.materials, receipt.sources, strict=True):
            authority.assert_current(material, expected)
        return row

    def _original_row(self, artifact_id: UUID) -> dict[str, Any]:
        """Historical DATA only; callers must separately establish current source permission."""
        row = self.conn.execute(
            "SELECT a.*,r.canonical_key,b.snapshot_json AS coverage_json,o.provider_key,"
            "EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id "
            "AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' "
            "AND cp.receipt_hash=a.artifact_hash) AS generation_completed,"
            "EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id "
            "AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-','')) AS generation_settled "
            "FROM tutor_item_supply_shared_generation_artifacts a "
            "JOIN tutor_item_supply_shared_budget_roots r ON r.id=a.root_id "
            "JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id "
            "JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE a.id=%s", (artifact_id,),
        ).fetchone()
        if row is None:
            raise PipelineRepositoryError("SHARED_CONTINUATION_ORIGINAL_UNAVAILABLE")
        return row

    def adopt(self, *, artifact_id: UUID, spec: FiniteCandidateSpecV1, operation_key: str,
              profile: ExecutionParameterProfileV1, retry_policy: RetryPolicyV1,
              source_authority: RagSourceAuthority, lease_owner: str, lease_seconds: int,
              priority: int = 0, aging_seconds: int = 60) -> ResolvedSharedCandidateContinuation | None:
        """Atomic enqueue/claim/adopt in a caller transaction; no provider/runner IO.

        No parent_job_id: this is an explicit new operation on the SAME root,
        not a child pretending to outlive its ancestor or renewal of the old job.
        A wrong root claim rolls back the entire savepoint including its mutation.
        """
        if not self.enabled or not self.settings.learning_item_supply_enabled:
            return None
        self._require(source_authority)
        spec = checked_model(spec, FiniteCandidateSpecV1)
        profile = checked_model(profile, ExecutionParameterProfileV1)
        self.artifacts._key(operation_key)
        if len(operation_key) > 80:
            raise PipelineRepositoryError("SHARED_CONTINUATION_OPERATION_KEY_INVALID")
        try:
            with self.conn.transaction():
                original = self._original(artifact_id, source_authority)
                request = GenerationRequestV2.model_validate_json(json.dumps(original["request_json"]))
                if profile.profile_key.key_hash != request.profile.profile_key_hash:
                    raise PipelineRepositoryError("SHARED_CONTINUATION_PROFILE_KEY_MISMATCH")
                root_id = UUID(str(original["root_id"]))
                now = server_clock(self.conn, datetime.now(UTC))
                job_id = self.runtime.enqueue(root_id=root_id, stage_key=f"continue.{artifact_id.hex}.{operation_key}",
                    profile=profile, now=now, priority=priority, aging_seconds=aging_seconds, visibility="public",
                    retry_policy=retry_policy)
                lease = self.runtime.claim(root_id=root_id, lease_owner=lease_owner, now=now,
                                           lease_seconds=lease_seconds, visibility="public")
                if lease is None or lease.job_id != job_id:
                    raise _NoContinuationLease()
                meta = self.artifacts.context(lease, now=now)
                if UUID(str(meta["root_id"])) != root_id or meta["coverage"] != spec.coverage_blueprint:
                    raise PipelineRepositoryError("SHARED_CONTINUATION_ROOT_MISMATCH")
                existing = self.conn.execute(
                    "SELECT job_id FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=%s", (job_id,),
                ).fetchone()
                if existing is not None:
                    # Same operation after process restart/lease expiry preserves
                    # its original adoption and new-job parent deadline as well.
                    return self.resolve(lease=lease, artifact_id=artifact_id, spec=spec, source_authority=source_authority)
                # Source must still be current after enqueue/claim locks and DB clock.
                original = self._original(artifact_id, source_authority)
                binding, source, request, _, inputs = bind_shared_candidate_continuation(
                    artifact=original, spec=spec, lease=lease, operation_key=operation_key)
                self.runtime._control(lease, now=server_clock(self.conn, now))
                row = self.conn.execute(
                    "INSERT INTO tutor_item_supply_shared_candidate_continuations "
                    "(job_id,root_id,generation_artifact_id,original_job_id,original_lease_generation,item_id,version_id,"
                    "source_hash,content_hash,operation_key,binding_json) VALUES(" + ",".join(["%s"] * 11) + ") "
                    "ON CONFLICT(job_id) DO NOTHING RETURNING binding_hash",
                    (job_id, root_id, artifact_id, binding.original_job_id, binding.original_lease_generation,
                     binding.item_id, binding.version_id, binding.source_hash, binding.content_hash, operation_key,
                     Jsonb(binding.model_dump(mode="json"))),
                ).fetchone()
                if row is None or row["binding_hash"] != binding.binding_hash:
                    raise PipelineRepositoryError("SHARED_CONTINUATION_ADOPTION_CONFLICT")
                return ResolvedSharedCandidateContinuation(binding, lease, original, source, request, inputs)
        except _NoContinuationLease:
            return None

    def adopt_persistent_phase(self, *, phase: Any, artifact_id: UUID,
            spec: FiniteCandidateSpecV1, source_authority: RagSourceAuthority) -> ResolvedSharedCandidateContinuation:
        """New concrete phase's already-issued job adopts immutable author DATA.

        No enqueue/claim, original-job renewal, generation checkpoint or paid
        permission is fabricated here. The original491 receiver remains final.
        """
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_contracts import IssuedPackPhase
        if (type(self) is not SharedCandidateContinuationOwner or type(phase) is not IssuedPackPhase
                or type(phase.owner) is not PersistentPackTaskOwner or phase.owner.conn is not self.conn
                or phase.version is None or phase.version.artifact_id != artifact_id
                or phase.version.specification != spec):
            raise PipelineRepositoryError("PERSISTENT_ORIGINAL_CONTINUATION_PHASE_REQUIRED")
        self._require(source_authority)
        # Controlled ancestry is checked BEFORE issuing any normal permission.
        held=self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
            "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",(artifact_id,)).fetchone()
        if held is None or held["held"] is not False:
            raise PipelineRepositoryError("PERSISTENT_CONTROLLED_ANCESTRY_DENIED")
        phase.owner.require_phase(phase,kind="candidate")
        original=self._original(artifact_id,source_authority)
        lease=phase.record.lease
        meta=self.artifacts.context(lease,now=server_clock(self.conn,datetime.now(UTC)))
        if (UUID(str(meta["root_id"]))!=phase.record.root_id or UUID(str(original["root_id"]))!=phase.record.root_id
                or meta["coverage"]!=spec.coverage_blueprint):
            raise PipelineRepositoryError("PERSISTENT_CONTINUATION_CANONICAL_ROOT_CHANGED")
        operation="persistent."+phase.record.phase_id.hex
        binding,source,request,_,inputs=bind_shared_candidate_continuation(
            artifact=original,spec=spec,lease=lease,operation_key=operation)
        row=self.conn.execute("INSERT INTO tutor_item_supply_shared_candidate_continuations "
            "(job_id,root_id,generation_artifact_id,original_job_id,original_lease_generation,item_id,version_id,"
            "source_hash,content_hash,operation_key,binding_json) VALUES("+",".join(["%s"]*11)+") "
            "ON CONFLICT(job_id) DO NOTHING RETURNING binding_hash",
            (lease.job_id,phase.record.root_id,artifact_id,binding.original_job_id,binding.original_lease_generation,
             binding.item_id,binding.version_id,binding.source_hash,binding.content_hash,operation,
             Jsonb(binding.model_dump(mode="json")))).fetchone()
        if row is None or row["binding_hash"]!=binding.binding_hash:
            raise PipelineRepositoryError("PERSISTENT_CONTINUATION_BINDING_CONFLICT")
        return ResolvedSharedCandidateContinuation(binding,lease,original,source,request,inputs)

    def resolve(self, *, lease: JobLeaseV1, artifact_id: UUID, spec: FiniteCandidateSpecV1,
                source_authority: RagSourceAuthority) -> ResolvedSharedCandidateContinuation:
        """Read current adopted DATA. No old execution/final-facts capability returned."""
        self._require(source_authority)
        lease = checked_model(lease, JobLeaseV1)
        now = server_clock(self.conn, datetime.now(UTC))
        meta = self.artifacts.context(lease, now=now)
        row = self.conn.execute("SELECT binding_json,binding_hash FROM tutor_item_supply_shared_candidate_continuations "
                                "WHERE job_id=%s AND generation_artifact_id=%s", (lease.job_id, artifact_id)).fetchone()
        if row is None:
            raise PipelineRepositoryError("SHARED_CONTINUATION_ADOPTION_REQUIRED")
        binding = SharedCandidateContinuationBindingV1.model_validate_json(json.dumps(row["binding_json"]))
        if (row["binding_hash"] != binding.binding_hash or binding.adoption_lease.job_id != lease.job_id
                or binding.adoption_lease.profile != lease.profile or UUID(str(meta["root_id"])) != binding.root_id
                or meta["canonical_key"] != binding.canonical_root_key or meta["coverage"] != spec.coverage_blueprint):
            raise PipelineRepositoryError("SHARED_CONTINUATION_CURRENT_BINDING_MISMATCH")
        original = self._original(artifact_id, source_authority)
        expected, source, request, _, inputs = bind_shared_candidate_continuation(
            artifact=original, spec=spec, lease=binding.adoption_lease, operation_key=binding.operation_key)
        if binding != expected:
            raise PipelineRepositoryError("SHARED_CONTINUATION_ORIGINAL_CHANGED")
        self.runtime._control(lease, now=server_clock(self.conn, now))
        return ResolvedSharedCandidateContinuation(binding, lease, original, source, request, inputs)
