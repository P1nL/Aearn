"""Append-only shared confidential staging in the caller's B1d transaction.

These rows are NOT learner-private provenance, bank versions, or publish grants.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash, learning_item_uuid
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.contracts import CoverageBlueprintV1
from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, check_finite_public_presentation,
    check_finite_public_request, check_finite_source_spec,
)
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import ProfileKeyV1
from app.services.learning.item_supply.pipeline_repository import ArtifactKind, PipelineReceipt, PipelineRepositoryError
from app.services.learning.item_supply.policies import CoverageObligationV1, ResourceAmounts, derive_runtime_contract_hash
from app.services.learning.item_supply.provider_adapter import GENERATION_ADAPTER_VERSION, GENERATION_PROMPT_VERSION
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.review_contracts_v2 import AdmissionEvaluationV2, BlindSolveReceiptV2, ReviewBundleV2
from app.services.learning.item_supply.shared_pipeline_contracts import match_shared_request
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2, checked_model
from app.services.learning.item_supply.diagnostic_policy import (
    AdmissionEvaluationV3, AutonomousEvidencePolicyV3, EvidencePolicy, ReviewBundleV3,
    SharedGenerationPolicyBindingV3, checked_policy,
)
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

if TYPE_CHECKING:
    from app.services.learning.item_supply.persistent_pack_committed_admission import IssuedCommittedChildAdmission
    from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
    from app.services.learning.item_supply.shared_generation_durability import IssuedRevisionGenerationPersistence
    from app.services.learning.item_supply.controlled_counterexample import ControlledCounterexampleOwner
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision
    from app.services.learning.item_supply.shared_pipeline_contracts import PreparedSharedGeneration
    from app.services.learning.item_supply.shared_continuation import (
        SharedCandidateContinuationBindingV1, SharedCandidateContinuationOwner,
    )


@dataclass(frozen=True)
class ResolvedSharedGeneration:
    """Original immutable author facts and DISTINCT current operation context."""
    artifact: dict[str, Any]
    request: GenerationRequestV2
    source: LearningItemSourceV1
    receipt: GenerationReceiptV2
    lease: JobLeaseV1
    continuation_binding: SharedCandidateContinuationBindingV1 | None = None

_TYPES: dict[str, type[BaseModel]] = {
    "validation": CandidateValidationV2, "blind_solve": BlindSolveReceiptV2,
    "review_bundle": ReviewBundleV2, "admission_evaluation": AdmissionEvaluationV2,
}


def generation_resources(request: GenerationRequestV2, attempts: int, *, revision: bool = False) -> ResourceAmounts:
    if type(attempts) is not int or not 1 <= attempts <= 3:
        raise PipelineRepositoryError("PROVIDER_ATTEMPT_BOUND_INVALID")
    return ResourceAmounts(requests=attempts, input_tokens=request.limits.max_input_bytes * attempts,
                           output_tokens=request.limits.max_output_tokens * attempts, candidates=1,
                           revision_rounds=1 if revision else 0)


class SharedPipelineArtifactRepository:
    def __init__(self, conn: Connection[dict[str, Any]], *, enabled: bool = False) -> None:
        self.conn, self.enabled = conn, enabled
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.budget = ItemSupplyBudgetRepository(conn)

    def require_owner(self) -> None:
        if not self.enabled:
            raise PipelineRepositoryError("SHARED_PIPELINE_DISABLED")
        if self.conn.info.transaction_status != TransactionStatus.INTRANS:
            raise PipelineRepositoryError("SHARED_CALLER_TRANSACTION_REQUIRED")
        row = self.conn.execute("SELECT current_database() AS db").fetchone()
        if row is None or row["db"] != "aearn_b1d_sandbox_20261001":
            raise PipelineRepositoryError("SHARED_PIPELINE_OUTSIDE_B1D")

    def context(self, lease: JobLeaseV1, *, now: datetime) -> dict[str, Any]:
        lease = checked_model(lease, JobLeaseV1)
        if lease.visibility != "public":
            raise PipelineRepositoryError("SHARED_PIPELINE_REQUIRED")
        self.require_owner()
        self.runtime._control(lease, now=now)
        row = self.conn.execute(
            "SELECT j.root_id,r.blueprint_id,r.canonical_key,b.blueprint_hash,b.objective_hash,"
            "b.policy_version,b.snapshot_json,o.obligation_json,o.provider_key,"
            "p.profile_hash,p.profile_json->'profile_key' AS profile_key,c.attempt_count "
            "FROM tutor_item_supply_shared_jobs j "
            "JOIN tutor_item_supply_shared_budget_roots r ON r.id=j.root_id "
            "JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id "
            "JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id "
            "JOIN tutor_item_supply_shared_job_controls c ON c.job_id=j.id "
            "JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id "
            "WHERE j.id=%s FOR SHARE OF j,r,b,o,p", (lease.job_id,),
        ).fetchone()
        if row is None:
            raise PipelineRepositoryError("SHARED_ROOT_UNAVAILABLE")
        blueprint = CoverageBlueprintV1.model_validate_json(json.dumps(row["snapshot_json"]))
        expected = CoverageObligationV1(blueprint_hash=blueprint.blueprint_hash,
            scope_hash=blueprint.scope.scope_hash, objective_hash=blueprint.objective_hash,
            purpose=blueprint.scope.purpose.value, runtime_contract_hash=derive_runtime_contract_hash(blueprint.scope),
            visibility="public", policy_version=blueprint.policy_version)
        obligation = CoverageObligationV1.model_validate_json(json.dumps(row["obligation_json"]))
        key = ProfileKeyV1.model_validate_json(json.dumps(row["profile_key"]))
        if (obligation != expected or row["canonical_key"] != expected.canonical_key
                or row["blueprint_hash"] != blueprint.blueprint_hash
                or row["objective_hash"] != blueprint.objective_hash
                or row["policy_version"] != blueprint.policy_version
                or row["profile_hash"] != lease.profile.profile_hash
                or key.key_hash != lease.profile.profile_key_hash or key.provider != row["provider_key"]):
            raise PipelineRepositoryError("SHARED_ROOT_PROFILE_MISMATCH")
        return {**row, "coverage": blueprint, "key": key}

    def request_context(self, lease: JobLeaseV1, request: GenerationRequestV2, *, now: datetime) -> dict[str, Any]:
        row = self.context(lease, now=now)
        target = match_shared_request(request, row["coverage"], lease)
        return {**row, "target": target}

    def _diagnostic_available(self) -> bool:
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_generation_policy_bindings') AS table_id").fetchone()
        return row is not None and row["table_id"] is not None

    def freeze_generation_policy(self, lease: JobLeaseV1, request: GenerationRequestV2, *,
                                 policy: EvidencePolicy, now: datetime) -> EvidencePolicy:
        """Never create a policy-derived coverage/root or reset cumulative history."""
        policy = checked_policy(policy)
        meta = self.request_context(lease, request, now=now)
        if type(policy) is AutonomousEvidencePolicyV2:
            existing = self.generation_policy(lease, request, now=now)
            if type(existing) is not AutonomousEvidencePolicyV2:
                raise PipelineRepositoryError("SHARED_GENERATION_POLICY_CONFLICT")
            return existing
        if not self._diagnostic_available():
            raise PipelineRepositoryError("SHARED_DIAGNOSTIC_MIGRATION_REQUIRED")
        if not isinstance(policy, AutonomousEvidencePolicyV3):
            raise PipelineRepositoryError("SHARED_GENERATION_POLICY_INVALID")
        v3_policy = checked_model(policy, AutonomousEvidencePolicyV3)
        frozen = SharedGenerationPolicyBindingV3(policy=v3_policy, root_id=UUID(str(meta["root_id"])),
            job_id=lease.job_id, candidate_id=request.candidate_id,
            request_hash=canonical_hash(request.model_dump(mode="json")),
            blueprint_hash=meta["coverage"].blueprint_hash,
            profile_hash=lease.profile.profile_hash, lease_generation=lease.generation)
        prior = self.conn.execute("SELECT payload_json FROM tutor_item_supply_shared_generation_policy_bindings "
            "WHERE candidate_id=%s FOR SHARE", (request.candidate_id,)).fetchone()
        if prior is not None:
            if SharedGenerationPolicyBindingV3.model_validate_json(json.dumps(prior["payload_json"])) != frozen:
                raise PipelineRepositoryError("SHARED_GENERATION_POLICY_CONFLICT")
            return policy
        # Policy must precede the one funded author attempt, not upgrade old work.
        if self.budget._reservation_by_key(lease, f"gen.{request.candidate_id.hex}") is not None:
            raise PipelineRepositoryError("SHARED_GENERATION_POLICY_TOO_LATE")
        self.conn.execute("INSERT INTO tutor_item_supply_shared_generation_policy_bindings "
            "(candidate_id,root_id,job_id,lease_generation,request_hash,profile_hash,policy_hash,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (request.candidate_id,frozen.root_id,lease.job_id,lease.generation,frozen.request_hash,
             frozen.profile_hash,policy.policy_hash,Jsonb(frozen.model_dump(mode="json"))))
        return policy

    def generation_policy(self, lease: JobLeaseV1, request: GenerationRequestV2, *, now: datetime) -> EvidencePolicy:
        meta = self.context(lease, now=now)
        if not self._diagnostic_available():
            return AutonomousEvidencePolicyV2()
        row = self.conn.execute("SELECT * FROM tutor_item_supply_shared_generation_policy_bindings "
            "WHERE candidate_id=%s FOR SHARE", (request.candidate_id,)).fetchone()
        if row is None:
            return AutonomousEvidencePolicyV2()
        frozen = SharedGenerationPolicyBindingV3.model_validate_json(json.dumps(row["payload_json"]))
        if (frozen.request_hash != canonical_hash(request.model_dump(mode="json"))
                or frozen.root_id != UUID(str(meta["root_id"]))
                or frozen.blueprint_hash != meta["coverage"].blueprint_hash
                or frozen.profile_hash != request.profile.profile_hash
                or row["policy_hash"] != frozen.policy.policy_hash
                or row["request_hash"] != frozen.request_hash
                or row["payload_hash"] != frozen.binding_hash
                or UUID(str(row["job_id"])) != frozen.job_id
                or row["lease_generation"] != frozen.lease_generation
                or UUID(str(row["root_id"])) != frozen.root_id
                or row["profile_hash"] != frozen.profile_hash
                or UUID(str(row["candidate_id"])) != frozen.candidate_id):
            raise PipelineRepositoryError("SHARED_GENERATION_POLICY_STALE")
        return frozen.policy

    def published_generation_policy(self, artifact: dict[str, Any]) -> EvidencePolicy:
        """Read frozen historical author binding, NEVER demand a revived old lease."""
        self.require_owner()
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        if not self._diagnostic_available():
            return AutonomousEvidencePolicyV2()
        row = self.conn.execute("SELECT * FROM tutor_item_supply_shared_generation_policy_bindings "
            "WHERE candidate_id=%s FOR SHARE", (request.candidate_id,)).fetchone()
        if row is None:
            return AutonomousEvidencePolicyV2()
        frozen = SharedGenerationPolicyBindingV3.model_validate_json(json.dumps(row["payload_json"]))
        if (frozen.request_hash != canonical_hash(request.model_dump(mode="json"))
                or frozen.root_id != UUID(str(artifact["root_id"]))
                or frozen.job_id != UUID(str(artifact["job_id"]))
                or frozen.lease_generation != artifact["lease_generation"]
                or frozen.profile_hash != request.profile.profile_hash
                or row["request_hash"] != frozen.request_hash or row["payload_hash"] != frozen.binding_hash
                or row["policy_hash"] != frozen.policy.policy_hash
                or UUID(str(row["root_id"])) != frozen.root_id
                or UUID(str(row["job_id"])) != frozen.job_id
                or row["lease_generation"] != frozen.lease_generation
                or row["profile_hash"] != frozen.profile_hash
                or UUID(str(row["candidate_id"])) != frozen.candidate_id):
            raise PipelineRepositoryError("SHARED_PUBLISHED_GENERATION_POLICY_STALE")
        return frozen.policy

    def require_source(self, authority: RagSourceAuthority) -> None:
        if type(authority) is not RagSourceAuthority or authority.connection is not self.conn:
            raise PipelineRepositoryError("SHARED_SOURCE_AUTHORITY_REQUIRED")

    def reservation(self, lease: JobLeaseV1, request: GenerationRequestV2, *, attempts: int,
                    settled: bool = False) -> UUID:
        revision = self.revision_preparation(lease, request)
        row = self.budget._reservation_by_key(lease, f"gen.{request.candidate_id.hex}")
        if (row is None or row["lease_generation"] != lease.generation
                or self.budget._reservation_amounts(lease, UUID(str(row["id"])))
                != generation_resources(request, attempts, revision=revision is not None).as_dict()):
            raise PipelineRepositoryError("SHARED_GENERATION_RESERVATION_MISMATCH")
        rid = UUID(str(row["id"]))
        if settled and self.conn.execute(
            "SELECT id FROM tutor_item_supply_shared_runtime_settlements "
            "WHERE reservation_id=%s AND settlement_key=%s",
            (rid, f"generation.{request.candidate_id.hex}"),
        ).fetchone() is None:
            raise PipelineRepositoryError("SHARED_GENERATION_UNSETTLED")
        return rid

    def revision_preparation(self, lease: JobLeaseV1, request: GenerationRequestV2) -> dict[str, Any] | None:
        """DATA routing only; finding a row never mints author capability."""
        installed = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_revision_preparations') AS table_id").fetchone()
        if installed is None or installed["table_id"] is None:
            return None
        row = self.conn.execute("SELECT * FROM tutor_item_supply_shared_revision_preparations WHERE child_job_id=%s FOR SHARE",
            (lease.job_id,)).fetchone()
        if row is not None and (row["candidate_id"] != request.candidate_id
                or row["payload_json"]["request"] != request.model_dump(mode="json")):
            raise PipelineRepositoryError("REVISION_CHILD_CONTEXT_REQUIRED")
        return row

    def controlled_preparation(self, lease: JobLeaseV1, request: GenerationRequestV2) -> dict[str,Any] | None:
        """DENY-only routing. An immutable row does not restore a producer issuer."""
        installed = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_controlled_counterexample_preparations') AS t, "
            "to_regclass('public.tutor_item_supply_shared_controlled_execution_preparations') AS execution_t").fetchone()
        if installed is None or installed["t"] is None:
            return None
        rows = self.conn.execute("SELECT * FROM tutor_item_supply_shared_controlled_counterexample_preparations "
            "WHERE job_id=%s OR candidate_id=%s FOR SHARE",(lease.job_id,request.candidate_id)).fetchall()
        if installed["execution_t"] is not None:
            rows += self.conn.execute("SELECT * FROM tutor_item_supply_shared_controlled_execution_preparations "
                "WHERE job_id=%s OR candidate_id=%s FOR SHARE",(lease.job_id,request.candidate_id)).fetchall()
        if not rows:
            return None
        if (len(rows)!=1 or rows[0]["job_id"]!=lease.job_id or rows[0]["candidate_id"]!=request.candidate_id
                or rows[0]["payload_json"]["request"]!=request.model_dump(mode="json")):
            raise PipelineRepositoryError("CONTROLLED_CANDIDATE_CONTEXT_REQUIRED")
        return rows[0]

    def store_generation(self, *, lease: JobLeaseV1, request: GenerationRequestV2,
                         result: GenerationResultV2, artifact_key: str, now: datetime,
                         source_authority: RagSourceAuthority,
                         revision_owner: NativeRevisionOwner | None = None,
                         revision_preparation: PreparedNativeRevision | None = None,
                         revision_generation: PreparedSharedGeneration | None = None,
                         controlled_owner: ControlledCounterexampleOwner | None = None,
                         controlled_generation: PreparedSharedGeneration | None = None,
                         persistence: IssuedRevisionGenerationPersistence | None = None) -> dict[str, Any]:
        original_result = result
        request = checked_model(request, GenerationRequestV2)
        result = checked_model(result, GenerationResultV2)
        meta = self.request_context(lease, request, now=now)
        self.require_source(source_authority)
        self._key(artifact_key)
        controlled = self.controlled_preparation(lease,request)
        if controlled is not None:
            from app.services.learning.item_supply.controlled_counterexample import ControlledCounterexampleOwner
            if (type(controlled_owner) is not ControlledCounterexampleOwner or controlled_generation is None
                    or controlled_owner.conn is not self.conn or controlled_owner.generation.artifacts is not self):
                raise PipelineRepositoryError("CONTROLLED_ORIGINAL_AUTHOR_CONTEXT_REQUIRED")
            controlled_owner.writer_binding(controlled_generation,original_result)
        elif controlled_owner is not None or controlled_generation is not None:
            raise PipelineRepositoryError("CONTROLLED_FROZEN_PARENT_REQUIRED")
        revision = self.revision_preparation(lease,request)
        if persistence is not None:
            from app.services.learning.item_supply.shared_generation_durability import (
                IssuedRevisionGenerationPersistence, RevisionGenerationDurability,
            )
            if (type(persistence) is not IssuedRevisionGenerationPersistence or revision is None or controlled is not None
                    or type(persistence.owner) is not RevisionGenerationDurability or persistence.owner.conn is not self.conn
                    or any(v is not None for v in (revision_owner,revision_preparation,revision_generation,controlled_owner,controlled_generation))
                    or persistence.owner.generation.artifacts is not self or persistence.request != request
                    or persistence.result != result or persistence.source_authority is not source_authority):
                raise PipelineRepositoryError("GENERATION_PERSISTENCE_ISSUER_REQUIRED")
            output,_,current_lease = persistence.owner.verify(persistence)
            if output["preparation_id"] != revision["id"] or lease != current_lease:
                raise PipelineRepositoryError("GENERATION_DURABLE_BINDING_CHANGED")
        elif revision is not None:
            from app.services.learning.item_supply.native_revision import NativeRevisionOwner

            if (type(revision_owner) is not NativeRevisionOwner or revision_owner.conn is not self.conn
                    or revision_preparation is None or revision_generation is None
                    or revision_owner.generation.artifacts is not self):
                raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_CONTEXT_REQUIRED")
            revision_owner.author_binding(revision_preparation,revision_generation,original_result)
        elif any(v is not None for v in (revision_owner,revision_preparation,revision_generation)):
            raise PipelineRepositoryError("REVISION_FROZEN_CHILD_REQUIRED")
        if result.state != "staged" or result.source is None or result.receipt is None:
            raise PipelineRepositoryError("PIPELINE_CANDIDATE_NOT_STAGED")
        source, receipt = result.source, result.receipt
        provider = receipt.provider
        if (receipt.candidate_id != request.candidate_id or receipt.scope_hash != request.scope_hash
                or source.blueprint != request.blueprint
                or (source.public.item_key, source.public.version) != (request.item_key, request.version)
                or (request.blueprint.version != FLEXIBLE_FACTORY_VERSION
                    and request.public_template is not None and source.public != request.public_template)
                or provider.mode != "provider" or provider.provider != meta["provider_key"]
                or provider.model != provider.configured_model
                or provider.provider_version != GENERATION_ADAPTER_VERSION
                or provider.prompt_version != GENERATION_PROMPT_VERSION
                or len(receipt.sources) != len(request.materials)):
            raise PipelineRepositoryError("SHARED_GENERATION_IDENTITY_MISMATCH")
        if request.blueprint.version == FLEXIBLE_FACTORY_VERSION:
            try:
                # Rebuild the explicit server spec, keeping request -> template
                # exact. Only generated presentation may differ in this version.
                public = check_finite_public_request(request)
                if request.public_template != public:
                    raise ValueError("finite_request_template_mismatch")
                check_finite_public_presentation(source.public, public, public_spec_version=request.blueprint.version)
            except ValueError:
                raise PipelineRepositoryError("SHARED_GENERATION_IDENTITY_MISMATCH") from None
        for material, expected in zip(request.materials, receipt.sources, strict=True):
            source_authority.assert_current(material, expected)
        reservation_id = self.reservation(lease, request, attempts=provider.request_attempt_bound, settled=True)
        self.runtime._control(lease, now=now)
        source_json, receipt_json, request_json = (source.model_dump(mode="json"),
                                                  receipt.model_dump(mode="json"), request.model_dump(mode="json"))
        expected_hash = canonical_hash({"source": source_json, "receipt": receipt_json, "request": request_json})
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_generation_artifacts "
            "(root_id,blueprint_id,job_id,lease_owner,lease_generation,lease_state_version,reservation_id,"
            "candidate_id,item_id,version_id,target_id,target_definition_hash,artifact_key,source_hash,content_hash,"
            "source_json,receipt_json,request_json) VALUES(" + ",".join(["%s"] * 18) + ") "
            "ON CONFLICT(job_id,lease_generation,artifact_key) DO NOTHING RETURNING *",
            (meta["root_id"], meta["blueprint_id"], lease.job_id, lease.lease_owner, lease.generation,
             lease.state_version, reservation_id, request.candidate_id, learning_item_uuid("item", request.item_key),
             learning_item_uuid("version", f"{request.item_key}@{request.version}"), meta["target"].target_id,
             meta["target"].definition_hash, artifact_key, source.source_hash, source.content_hash,
             Jsonb(source_json), Jsonb(receipt_json), Jsonb(request_json)),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_shared_generation_artifacts "
                "WHERE job_id=%s AND lease_generation=%s AND artifact_key=%s",
                (lease.job_id, lease.generation, artifact_key),
            ).fetchone()
        if row is None or row["artifact_hash"] != expected_hash:
            raise PipelineRepositoryError("SHARED_GENERATION_CONFLICT")
        return row

    def get_generation(self, *, lease: JobLeaseV1, artifact_id: UUID, now: datetime) -> dict[str, Any]:
        self.context(lease, now=now)
        row = self.conn.execute(
            "SELECT * FROM tutor_item_supply_shared_generation_artifacts "
            "WHERE id=%s AND job_id=%s AND lease_generation=%s",
            (artifact_id, lease.job_id, lease.generation),
        ).fetchone()
        if row is None:
            raise PipelineRepositoryError("SHARED_ARTIFACT_UNAVAILABLE")
        return row

    def resolve_generation(self, *, lease: JobLeaseV1, artifact_id: UUID, now: datetime,
                           source_authority: RagSourceAuthority, spec: FiniteCandidateSpecV1,
                           continuation_owner: SharedCandidateContinuationOwner | None = None) -> ResolvedSharedGeneration:
        """Resolve unchanged author DATA, never relabel an old row or restore seals.

        get_generation stays strict. Its exact unavailable result can be resolved
        only by the concrete same-connection adoption owner and current C checks.
        """
        from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner

        self.require_source(source_authority)
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        if continuation_owner is not None and (type(continuation_owner) is not SharedCandidateContinuationOwner
                                               or continuation_owner.conn is not self.conn):
            raise PipelineRepositoryError("SHARED_CONTINUATION_OWNER_REQUIRED")
        try:
            artifact = self.get_generation(lease=lease, artifact_id=artifact_id, now=now)
        except PipelineRepositoryError as exc:
            if str(exc) != "SHARED_ARTIFACT_UNAVAILABLE" or continuation_owner is None:
                raise
            adopted = continuation_owner.resolve(lease=lease, artifact_id=artifact_id,
                                                 spec=spec, source_authority=source_authority)
            receipt = GenerationReceiptV2.model_validate_json(json.dumps(adopted.original_artifact["receipt_json"]))
            return ResolvedSharedGeneration(adopted.original_artifact, adopted.original_request,
                adopted.source, receipt, lease, adopted.binding)
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
        receipt = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        meta = self.request_context(lease, request, now=now)
        if (meta["coverage"] != spec.coverage_blueprint or request.blueprint != spec.blueprint
                or request.public_template != spec.public_template
                or source.blueprint != request.blueprint or receipt.candidate_id != request.candidate_id
                or receipt.scope_hash != request.scope_hash or receipt.source_hash != source.source_hash
                or receipt.content_hash != source.content_hash or artifact["source_hash"] != source.source_hash
                or artifact["content_hash"] != source.content_hash
                or UUID(str(artifact["candidate_id"])) != request.candidate_id
                or canonical_hash({k: artifact[k + "_json"] for k in ("source", "receipt", "request")}) != artifact["artifact_hash"]):
            raise PipelineRepositoryError("SHARED_GENERATION_RESOLUTION_MISMATCH")
        try:
            check_finite_source_spec(source, spec)
        except ValueError:
            raise PipelineRepositoryError("SHARED_GENERATION_RESOLUTION_MISMATCH") from None
        for material, expected in zip(request.materials, receipt.sources, strict=True):
            if expected.mode != "current_authority":
                raise PipelineRepositoryError("SHARED_SOURCE_AUTHORITY_REQUIRED")
            source_authority.assert_current(material, expected)
        self.runtime._control(lease, now=now)
        return ResolvedSharedGeneration(artifact, request, source, receipt, lease)

    def store_receipt(self, *, lease: JobLeaseV1, artifact_id: UUID, kind: ArtifactKind,
                      payload: PipelineReceipt, artifact_key: str, now: datetime,
                      source_authority: RagSourceAuthority, spec: FiniteCandidateSpecV1 | None = None,
                      continuation_owner: SharedCandidateContinuationOwner | None = None) -> dict[str, Any]:
        continuation_hash = None
        if spec is not None:
            resolved = self.resolve_generation(lease=lease, artifact_id=artifact_id, now=now,
                source_authority=source_authority, spec=spec, continuation_owner=continuation_owner)
            generation, request, original = resolved.artifact, resolved.request, resolved.receipt
            if resolved.continuation_binding is not None:
                continuation_hash = resolved.continuation_binding.binding_hash
        else:
            if continuation_owner is not None:
                raise PipelineRepositoryError("SHARED_CONTINUATION_SPEC_REQUIRED")
            generation = self.get_generation(lease=lease, artifact_id=artifact_id, now=now)
            request = GenerationRequestV2.model_validate_json(json.dumps(generation["request_json"]))
            self.request_context(lease, request, now=now)
            original = GenerationReceiptV2.model_validate_json(json.dumps(generation["receipt_json"]))
        self._key(artifact_key)
        self.require_source(source_authority)
        for material, expected in zip(request.materials, original.sources, strict=True):
            source_authority.assert_current(material, expected)
        expected_type = _TYPES.get(kind)
        policy = self.generation_policy(lease, request, now=now)
        if type(policy) is AutonomousEvidencePolicyV3:
            if kind == "review_bundle":
                expected_type = ReviewBundleV3
            elif kind == "admission_evaluation":
                expected_type = AdmissionEvaluationV3
        if expected_type is None or type(payload) is not expected_type:
            raise PipelineRepositoryError("PIPELINE_RECEIPT_TYPE_INVALID")
        checked = checked_model(payload, expected_type)
        data = checked.model_dump(mode="json")
        binding = data.get("binding", data)
        if (not isinstance(binding, dict) or binding.get("content_hash") != generation["content_hash"]
                or binding.get("source_hash") != generation["source_hash"]
                or data.get("publication_enabled", False) is not False):
            raise PipelineRepositoryError("PIPELINE_RECEIPT_STALE")
        if isinstance(checked, (BlindSolveReceiptV2, ReviewBundleV2, AdmissionEvaluationV2, ReviewBundleV3, AdmissionEvaluationV3)):
            if (checked.binding.candidate_key != str(generation["item_id"])
                    or checked.binding.version_key != str(generation["version_id"])
                    or checked.binding.profile_hash != lease.profile.profile_hash
                    or checked.binding.policy_hash != policy.policy_hash):
                raise PipelineRepositoryError("PIPELINE_VERSION_MISMATCH")
        self.runtime._control(lease, now=now)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_pipeline_receipts "
            "(job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,item_id,version_id,"
            "source_hash,content_hash,artifact_key,artifact_kind,schema_version,payload_json,continuation_binding_hash) "
            "VALUES(" + ",".join(["%s"] * 14) + ") "
            "ON CONFLICT(job_id,lease_generation,artifact_kind,artifact_key) DO NOTHING RETURNING *",
            (lease.job_id, lease.lease_owner, lease.generation, lease.state_version, artifact_id,
             generation["item_id"], generation["version_id"], generation["source_hash"], generation["content_hash"],
             artifact_key, kind, data["schema_version"], Jsonb(data), continuation_hash),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_shared_pipeline_receipts "
                "WHERE job_id=%s AND lease_generation=%s AND artifact_kind=%s AND artifact_key=%s",
                (lease.job_id, lease.generation, kind, artifact_key),
            ).fetchone()
        if (row is None or row["receipt_hash"] != canonical_hash(data)
                or UUID(str(row["generation_artifact_id"])) != artifact_id
                or row.get("continuation_binding_hash") != continuation_hash):
            raise PipelineRepositoryError("SHARED_RECEIPT_CONFLICT")
        return row

    @staticmethod
    def _key(key: str) -> None:
        if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,159}", key) is None:
            raise PipelineRepositoryError("PIPELINE_ARTIFACT_KEY_INVALID")

    def store_committed_evaluation(self, frame: IssuedCommittedChildAdmission, *, facts: IssuedSharedAdmissionFactsV1) -> dict[str, Any]:
        """Explicit current admission action; evidence binding keeps the historical review profile."""
        from app.services.learning.item_supply.persistent_pack_committed_admission import require
        require(frame)
        self.require_owner()
        if self.conn is not frame.owner.conn or facts.receipt_id != frame.admission_id:
            raise PipelineRepositoryError("COMMITTED_ADMISSION_EVALUATION_OWNER_REQUIRED")
        frame.facts_owner.verify(facts,lease=frame.lease)
        stored = self.conn.execute("SELECT payload_hash,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_admission_facts WHERE id=%s FOR SHARE",(facts.receipt_id,)).fetchone()
        if stored is None or stored["same_transaction"] or stored["payload_hash"] != facts.receipt_hash:
            raise PipelineRepositoryError("COMMITTED_ADMISSION_COMMITTED_FACTS_REQUIRED")
        data = facts.evaluation.model_dump(mode="json")
        q,lease = frame.quality,frame.lease
        if (facts.evaluation.binding != q.bundle.binding or facts.evaluation.publication_enabled
                or type(facts.evaluation) is not AdmissionEvaluationV3):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_ORIGINAL_EVALUATION_REQUIRED")
        row = self.conn.execute("INSERT INTO tutor_item_supply_shared_pipeline_receipts "
            "(job_id,lease_owner,lease_generation,lease_state_version,generation_artifact_id,item_id,version_id,source_hash,content_hash,"
            "artifact_key,artifact_kind,schema_version,payload_json,continuation_binding_hash) VALUES("+",".join(["%s"]*14)+") RETURNING *",
            (lease.job_id,lease.lease_owner,lease.generation,lease.state_version,facts.generation_artifact_id,facts.item_id,facts.version_id,
            q.source.source_hash,q.source.content_hash,"native_admission."+facts.receipt_id.hex,"admission_evaluation",
            data["schema_version"],Jsonb(data),None)).fetchone()
        if row is None or row["receipt_hash"] != canonical_hash(data):
            raise PipelineRepositoryError("COMMITTED_ADMISSION_EVALUATION_CONFLICT")
        return row
