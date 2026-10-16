"""Default-off same-root revision owner. No new review/discharge/publication authority.

Caller-owned short transactions: prepare child/context, separately prepare author,
commit before IDLE run, separately settle, original writer commit, refresh child
lease, then append lineage. Never hydrate these issued objects from stored JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.diagnostic_policy import policy_for_hash
from app.services.learning.item_supply.finite_candidate_factory import (
    FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, build_finite_candidate_spec, build_finite_generation_request,
)
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.generation_contracts import GenerationLimitsV2, GenerationRequestV2, GenerationResultV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.native_revision_contracts import (
    NativeRevisionAuthorInputBindingV1, NativeRevisionContextV1, NativeRevisionProblemV1,
)
from app.services.learning.item_supply.native_review_investigation import (
    NativeReviewInvestigationOwner, NativeReviewInvestigationRun, PreparedNativeReviewInvestigation,
)
from app.services.learning.item_supply.persistent_pack_committed_revision import CommittedInvestigationEvidence, RECEIPT
from app.services.learning.item_supply.parameter_profiles import ExecutionParameterProfileV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.repository import server_clock
from app.services.learning.item_supply.review_deliberation import substantive_revision_hash
from app.services.learning.item_supply.shared_pipeline import SharedGenerationPipeline
from app.services.learning.item_supply.shared_pipeline_contracts import GenerationSettlementOutcome, PreparedSharedGeneration, SharedPipelineStageResult

if TYPE_CHECKING:
    from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
    from app.services.learning.item_supply.shared_admission_facts_contracts import IssuedSharedAdmissionFactsV1
from app.services.learning.item_supply.shared_pipeline_repository import generation_resources
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True, repr=False)
class PreparedNativeRevision:
    preparation_id: UUID
    investigation: PreparedNativeReviewInvestigation | CommittedInvestigationEvidence
    investigation_result: NativeReviewInvestigationRun | None
    investigation_receipt_id: UUID
    investigation_receipt_hash: str
    lease: JobLeaseV1
    spec: FiniteCandidateSpecV1
    request: GenerationRequestV2
    context: NativeRevisionContextV1
    deadline_at: datetime

    def payload(self) -> dict[str, Any]:
        parent = self.investigation.original
        return {"schema_version": "native_shared_revision_preparation_v1", "preparation_id": str(self.preparation_id),
            "root_id": str(self.investigation.root_id), "parent_job_id": str(self.investigation.lease.job_id),
            "parent_lease": self.investigation.lease.model_dump(mode="json"), "child_lease": self.lease.model_dump(mode="json"),
            "parent_artifact_id": str(parent.artifact_id), "parent_artifact_hash": parent.artifact_hash,
            "investigation_receipt_id": str(self.investigation_receipt_id), "investigation_receipt_hash": self.investigation_receipt_hash,
            "request": self.request.model_dump(mode="json"), "request_hash": canonical_hash(self.request.model_dump(mode="json")),
            "context": self.context.model_dump(mode="json"), "context_hash": self.context.context_hash,
            "specification_hash": self.spec.specification_hash,
            "resources": generation_resources(self.request,1,revision=True).model_dump(mode="json"),
            "reservation_key": "gen."+self.request.candidate_id.hex, "deadline_at": self.deadline_at.isoformat(),
            "parent_substantive_hash": substantive_revision_hash(parent.source),
            "source_deadlines": [{"binding_digest": b, "claim_receipt_id": c, "retained_until": t.isoformat()}
                for b,c,t in self.investigation.source_deadlines],
            "publication_enabled": False, "blockers_discharged": False}


class NativeRevisionOwner:
    def __init__(self, investigation_owner: NativeReviewInvestigationOwner,
                 generation: SharedGenerationPipeline, *, enabled: bool = False) -> None:
        if (type(investigation_owner) is not NativeReviewInvestigationOwner or type(generation) is not SharedGenerationPipeline
                or investigation_owner.conn is not generation.conn):
            raise PipelineRepositoryError("REVISION_SAME_CONCRETE_ORIGINAL_OWNERS_REQUIRED")
        self.investigation_owner, self.generation, self.conn, self.enabled = investigation_owner,generation,generation.conn,enabled
        self._prepared: dict[UUID, tuple[PreparedNativeRevision,str]] = {}
        self._authors: dict[UUID, tuple[PreparedSharedGeneration,OpenAICompatibleGenerationProvider]] = {}
        self._runs: dict[UUID, tuple[GenerationResultV2,str]] = {}

    def _guard(self) -> datetime:
        if not self.enabled or not self.generation.generation_enabled:
            raise PipelineRepositoryError("NATIVE_REVISION_DISABLED")
        self.generation.artifacts.require_owner()
        row = self.conn.execute("SELECT to_regclass('public.tutor_item_supply_shared_revision_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_revision_lineage') AS l, "
            "to_regprocedure('item_supply_internal.native_revision_descendant(uuid)') AS guard").fetchone()
        if row is None or row["p"] is None or row["l"] is None or row["guard"] is None:
            raise PipelineRepositoryError("NATIVE_REVISION_SCHEMA_REQUIRED")
        return server_clock(self.conn,datetime.now(UTC))

    def _parent(self, p: PreparedNativeReviewInvestigation | CommittedInvestigationEvidence, result: NativeReviewInvestigationRun | None,
                receipt_id: UUID) -> dict[str, Any]:
        self._guard()
        if isinstance(p, CommittedInvestigationEvidence):
            if type(p) is not CommittedInvestigationEvidence or result is not None or receipt_id != RECEIPT:
                raise PipelineRepositoryError("REVISION_EXACT_COMMITTED_EVIDENCE_REQUIRED")
            return self.investigation_owner.require_committed_revision(p)
        if type(p) is not PreparedNativeReviewInvestigation or type(result) is not NativeReviewInvestigationRun:
            raise PipelineRepositoryError("REVISION_VALID_ORIGINAL_INVESTIGATION_REQUIRED")
        self.investigation_owner._result(p,result)
        self.investigation_owner._fence(p)
        if result.report is None or result.safe_reason != "investigation_analysis_pending_revision_owner":
            raise PipelineRepositoryError("REVISION_VALID_ORIGINAL_INVESTIGATION_REQUIRED")
        with finite_review_context(p.original.source,spec=p.original.spec,materials=p.original.request.materials):
            expected = result.payload(p)
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_review_investigation_receipts r WHERE r.id=%s FOR SHARE",(receipt_id,)).fetchone()
        if (row is None or row["same_transaction"] or row["preparation_id"] != p.preparation_id
                or row["root_id"] != p.root_id or row["job_id"] != p.lease.job_id
                or row["generation_artifact_id"] != p.original.artifact_id or row["payload_json"] != expected
                or row["snapshot_hash"] != canonical_hash(expected)):
            raise PipelineRepositoryError("REVISION_COMMITTED_ORIGINAL_INVESTIGATION_REQUIRED")
        usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=%s",(row["settlement_id"],)).fetchone()
        if (usage is None or usage["same_transaction"] or usage["reservation_id"] != p.reservation_id
                or usage["settlement_key"] != p.reservation_key or usage["usage_state"] != "unknown"):
            raise PipelineRepositoryError("REVISION_ORIGINAL_UNKNOWN_SETTLEMENT_REQUIRED")
        return row

    def _issued(self, p: PreparedNativeRevision) -> None:
        if type(p) is not PreparedNativeRevision:
            raise PipelineRepositoryError("REVISION_ORIGINAL_PREPARED_REQUIRED")
        entry = self._prepared.get(p.preparation_id)
        parent = p.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            if entry is None or entry[0] is not p or entry[1] != canonical_hash(p.payload()):
                raise PipelineRepositoryError("REVISION_ORIGINAL_PREPARED_REQUIRED")

    def prepare(self, *, investigation: PreparedNativeReviewInvestigation, result: NativeReviewInvestigationRun,
                investigation_receipt_id: UUID) -> PreparedNativeRevision | None:
        if type(investigation) is not PreparedNativeReviewInvestigation or type(result) is not NativeReviewInvestigationRun:
            raise PipelineRepositoryError("REVISION_VALID_ORIGINAL_INVESTIGATION_REQUIRED")
        return self._prepare(investigation=investigation, result=result, investigation_receipt_id=investigation_receipt_id)

    def prepare_committed(self, evidence: CommittedInvestigationEvidence) -> PreparedNativeRevision | None:
        self.investigation_owner.require_committed_revision(evidence)
        return self._prepare(investigation=evidence, result=None, investigation_receipt_id=RECEIPT)

    def _prepare(self, *, investigation: PreparedNativeReviewInvestigation | CommittedInvestigationEvidence,
                 result: NativeReviewInvestigationRun | None, investigation_receipt_id: UUID) -> PreparedNativeRevision | None:
        row = self._parent(investigation,result,investigation_receipt_id)
        predecessor = None
        if isinstance(investigation, CommittedInvestigationEvidence) and investigation.persistent_phase.execution is not None:
            from app.services.learning.item_supply.persistent_pack_fresh_committed_revision import successor_predecessor
            predecessor = successor_predecessor(investigation.persistent_phase)
        if self.conn.execute("SELECT 1 FROM tutor_item_supply_shared_revision_preparations WHERE investigation_receipt_id=%s "
                "AND (%s::uuid IS NULL OR id<>%s)",
                (investigation_receipt_id,predecessor,predecessor)).fetchone() is not None:
            return None  # Replay DATA never issues a new dispatch capability.
        parent = investigation.original
        allocation=parent.spec.allocation
        materials = parent.request.materials
        source_successor = type(investigation) is CommittedInvestigationEvidence and investigation.persistent_phase.source_successor is not None
        if source_successor:
            assert isinstance(investigation, CommittedInvestigationEvidence)
            assert investigation.persistent_phase.source_successor is not None
            materials = investigation.persistent_phase.source_successor.public_materials
        if isinstance(investigation, CommittedInvestigationEvidence):
            allocation=self.investigation_owner._select_registered_child_allocation(investigation.persistent_phase,parent.spec)
            if allocation != investigation.request.revision_allocation:
                raise PipelineRepositoryError("PERSISTENT_FROZEN_FAMILY_PLAN_CHANGED_STOP")
        elif investigation.persistent_phase is not None:
            allocation=self.investigation_owner.child_allocation(investigation)
        family_change=allocation!=parent.spec.allocation
        values = investigation.lease.profile.values
        if values.discussion_rounds<2 or values.revision_rounds<1:
            raise PipelineRepositoryError("REVISION_FROZEN_PROFILE_ROUNDS_REQUIRED")
        profile_row = self.conn.execute("SELECT profile_json FROM tutor_item_supply_parameter_profiles WHERE profile_hash=%s",
            (investigation.lease.profile.profile_hash,)).fetchone()
        if profile_row is None:
            raise PipelineRepositoryError("REVISION_ORIGINAL_REGISTERED_PROFILE_REQUIRED")
        profile = ExecutionParameterProfileV1.model_validate_json(json.dumps(profile_row["profile_json"]))
        if profile.profile_hash != investigation.lease.profile.profile_hash:
            raise PipelineRepositoryError("REVISION_ORIGINAL_REGISTERED_PROFILE_REQUIRED")
        prep_id, candidate = uuid4(),uuid4()
        item_key, version = "native.revision."+candidate.hex, "revision-"+prep_id.hex[:12]
        now = server_clock(self.conn,datetime.now(UTC))
        retry = RetryPolicyV1(max_transient_attempts=1,initial_backoff_ms=1,maximum_backoff_ms=1)
        job = self.generation.runtime.enqueue(root_id=investigation.root_id,
            stage_key="revision."+investigation_receipt_id.hex+(".successor.1" if predecessor is not None else ""),profile=profile,now=now,priority=100,
            aging_seconds=60,visibility="public",parent_job_id=investigation.lease.job_id,retry_policy=retry)
        lease = self.generation.runtime.claim(root_id=investigation.root_id,lease_owner="revision."+prep_id.hex,
            now=now,lease_seconds=max(1,int((investigation.deadline_at-now).total_seconds())),visibility="public")
        if lease is None or lease.job_id != job:
            # Raise: caller MUST rollback the enqueue/claim transaction, including
            # any mistakenly claimed other job. Never silently return None here.
            raise PipelineRepositoryError("REVISION_EXACT_CHILD_JOB_NOT_CLAIMED_ROLLBACK_REQUIRED")
        if lease.profile.profile_hash != investigation.lease.profile.profile_hash or lease.profile.values != values:
            raise PipelineRepositoryError("REVISION_CHILD_PROFILE_CHANGED")
        from app.services.learning.item_supply.development_model_accounting import inherit_development_model_accounting
        inherit_development_model_accounting(self.conn,parent_lease=investigation.lease,child_lease=lease,now=now)
        scope = parent.spec.coverage_blueprint.scope
        spec = build_finite_candidate_spec(target_id=parent.spec.target_id,variant_id=parent.spec.allocation.variant_id,
            seed=parent.spec.seed,item_key=item_key,version=version,materials=materials,
            runtime_profile_hash=None if parent.spec.blueprint.runtime_profile_id is None else scope.runtime_profile_hash,
            scorer_version=scope.scorer_version,assistance_policy_hash=scope.assistance_policy_hash,
            policy_version=parent.spec.coverage_blueprint.policy_version,difficulty_profile=parent.spec.blueprint.difficulty_profile,
            publication_policy=parent.spec.blueprint.publication_policy,
            public_spec_version=FLEXIBLE_FACTORY_VERSION if family_change else parent.spec.blueprint.version,
            allocation=allocation)
        expected_blueprint = parent.spec.blueprint
        if source_successor:
            # _parent has verified the original issued evidence/bridge/execution.
            # Rebind only exact factory-derived citations; never mutate the parent.
            from app.services.learning.item_supply.finite_candidate_factory import _references
            if not family_change:
                raise PipelineRepositoryError("REVISION_SOURCE_SUCCESSOR_REGISTERED_FAMILY_REQUIRED")
            expected_blueprint = expected_blueprint.model_copy(update={
                "source_references": _references(materials, parent.spec.target_id)})
        if (spec.coverage_blueprint != parent.spec.coverage_blueprint
                or (not family_change and spec.blueprint != expected_blueprint)
                or (family_change and spec.blueprint.model_dump(mode="json",exclude={"blueprint_key","version"})
                    !=expected_blueprint.model_dump(mode="json",exclude={"blueprint_key","version"}))):
            raise PipelineRepositoryError("REVISION_FACTORY_CORE_CHANGED")
        request = build_finite_generation_request(spec,candidate_id=candidate,profile=lease.profile,
            materials=materials,limits=GenerationLimitsV2(max_input_bytes=parent.request.limits.max_input_bytes,
                max_output_tokens=DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,max_output_bytes=parent.request.limits.max_output_bytes))
        report = investigation.report if isinstance(investigation, CommittedInvestigationEvidence) else (None if result is None else result.report)
        assert report is not None
        family_revision=None
        if family_change:
            from app.services.learning.item_supply.persistent_pack_repair import PersistentCloneFindingV1, PersistentInvestigationInputV1
            from app.services.learning.item_supply.persistent_pack_revision_contracts import PersistentRegisteredFamilyRevisionV1
            phase=investigation.persistent_phase
            if phase is None or phase.version is None or type(investigation.request) is not PersistentInvestigationInputV1:
                raise PipelineRepositoryError("REVISION_EXACT_PERSISTENT_FAMILY_ISSUER_REQUIRED")
            clones=[d for d in investigation.request.disputes if type(d) is PersistentCloneFindingV1]
            if (len(clones)!=1 or allocation!=investigation.request.revision_allocation
                    or spec.seed!=parent.spec.seed or allocation.variant_id!=parent.spec.allocation.variant_id):
                raise PipelineRepositoryError("REVISION_FROZEN_ACTUAL_CLONE_FAMILY_PLAN_REQUIRED")
            family_revision=PersistentRegisteredFamilyRevisionV1(phase_id=phase.record.phase_id,
                public_slot_id=phase.version.public_slot_id,parent_revision_id=phase.version.revision_id,
                parent_specification_hash=parent.spec.specification_hash,finding_key=clones[0].dispute_key,child_specification=spec)
        context = NativeRevisionContextV1(parent_artifact_id=parent.artifact_id,parent_artifact_hash=parent.artifact_hash,
            parent_source_hash=parent.source.source_hash,parent_content_hash=parent.source.content_hash,
            parent_review_hash=investigation.request.review_receipt_hash,investigation_receipt_id=investigation_receipt_id,
            investigation_receipt_hash=row["snapshot_hash"],investigation_report_hash=canonical_hash(report.model_dump(mode="json")),
            child_candidate_id=candidate,child_item_key=item_key,child_version=version,scope_hash=request.scope_hash,
            policy_hash=parent.binding.policy_hash,target_definition_hash=parent.spec.target_definition_hash,parent_source=parent.source,
            problems=tuple(NativeRevisionProblemV1.from_analysis(a) for a in report.output.analyses),
            schema_version=("native_revision_author_context_v3" if source_successor else
                "native_revision_author_context_v2" if family_change else "native_revision_author_context_v1"),
            persistent_family_revision=family_revision)
        deadline = min(investigation.deadline_at,lease.expires_at,lease.parent_deadline,lease.profile.parent_deadline_at,
            lease.profile.bound_at+timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
        if deadline<=now:
            raise PipelineRepositoryError("REVISION_ANCESTOR_DEADLINE_EXHAUSTED")
        p = PreparedNativeRevision(prep_id,investigation,result,investigation_receipt_id,row["snapshot_hash"],lease,spec,request,context,deadline)
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            payload = p.payload()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_preparations "
            "(id,root_id,parent_job_id,child_job_id,parent_artifact_id,investigation_receipt_id,candidate_id,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",(prep_id,investigation.root_id,investigation.lease.job_id,lease.job_id,
                parent.artifact_id,investigation_receipt_id,candidate,Jsonb(payload),deadline))
        self._prepared[p.preparation_id] = (p,canonical_hash(payload))
        return p

    def generation_context(self, p: PreparedNativeRevision, *, lease: JobLeaseV1, request: GenerationRequestV2,
                           committed: bool = True, completed: bool = False) -> NativeRevisionContextV1:
        self._issued(p)
        self._parent(p.investigation,p.investigation_result,p.investigation_receipt_id)
        now = server_clock(self.conn,datetime.now(UTC))
        lease = checked_model(lease,JobLeaseV1)
        if (request != p.request or lease.job_id != p.lease.job_id or lease.generation != p.lease.generation
                or lease.lease_owner != p.lease.lease_owner or lease.profile != p.lease.profile
                or lease.visibility != "public" or lease.owner_id is not None or lease.owner_epoch is not None
                or now>=p.deadline_at or lease.parent_deadline>p.investigation.lease.parent_deadline):
            raise PipelineRepositoryError("REVISION_CURRENT_CHILD_BINDING_REQUIRED")
        self.generation.runtime._control(lease,now=now)
        if not completed and self.generation.runtime.next_stage(lease) != "generating":
            raise PipelineRepositoryError("REVISION_CHILD_AUTHOR_STAGE_REQUIRED")
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_revision_preparations r WHERE r.id=%s FOR SHARE",(p.preparation_id,)).fetchone()
        parent = p.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            payload = p.payload()
        if row is None or (committed and row["same_transaction"]) or row["snapshot_hash"] != canonical_hash(payload) or row["payload_json"] != payload:
            raise PipelineRepositoryError("REVISION_COMMITTED_FROZEN_CONTEXT_REQUIRED")
        if (not self.generation.settings.uses_deepseek_v4_flash_responses
                or self.generation.settings.tutor_max_output_tokens != DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
                or self.generation._models != self.investigation_owner.review._models):
            raise PipelineRepositoryError("REVISION_FROZEN_PRODUCTION_MODEL_REQUIRED")
        p.context.check_request(request)
        return p.context

    def _source_authority(self, p: PreparedNativeRevision) -> Any:
        if isinstance(p.investigation, CommittedInvestigationEvidence):
            self.investigation_owner.require_committed_revision(p.investigation)
            return p.investigation.persistent_phase.owner.type_owner.source_authority
        authority,_,_,_ = self.investigation_owner.review._issued(p.investigation.original)
        return authority

    def prepare_author(self, p: PreparedNativeRevision, *, provider: OpenAICompatibleGenerationProvider) -> PreparedSharedGeneration | None:
        self.generation_context(p,lease=p.lease,request=p.request,committed=False)
        if type(provider) is not OpenAICompatibleGenerationProvider or provider.request_attempt_bound != 1:
            raise PipelineRepositoryError("REVISION_ONE_ACTUAL_AUTHOR_CALL_REQUIRED")
        if provider._settings != self.generation.settings:
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_CONFIGURATION_REQUIRED")
        if (provider.provider_key,provider.configured_model) != (p.investigation.identity.provider,p.investigation.identity.model):
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_MODEL_REQUIRED")
        authority = self._source_authority(p)
        gen = self.generation.prepare_generation(lease=p.lease,request=p.request,provider=provider,source_authority=authority,
            evidence_policy=policy_for_hash(p.context.policy_hash),revision_owner=self,revision_preparation=p)
        if gen is not None:
            self._authors[p.preparation_id] = (gen,provider)
        return gen

    def run(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration) -> GenerationResultV2:
        self._issued(p)
        original = self._authors.get(p.preparation_id)
        if original is None or original[0] is not gen or p.preparation_id in self._runs:
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_PREPARED_REQUIRED")
        result = self.generation.run_generation(gen,original[1])
        self._runs[p.preparation_id] = (result,canonical_hash(result.model_dump(mode="json")))
        return result

    def _result(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration, result: GenerationResultV2, *, original: bool = True) -> None:
        self._issued(p)
        entry = self._runs.get(p.preparation_id)
        author = self._authors.get(p.preparation_id)
        if (entry is None or author is None or author[0] is not gen or (original and entry[0] is not result)
                or entry[1] != canonical_hash(result.model_dump(mode="json"))):
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_RESULT_REQUIRED")
        self.generation._result(gen,result)

    def settle(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration, result: GenerationResultV2) -> GenerationSettlementOutcome:
        self._result(p,gen,result)
        return self.generation.settle_generation(gen,result)

    def author_binding(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration, result: GenerationResultV2) -> NativeRevisionAuthorInputBindingV1:
        self._result(p,gen,result,original=False)  # Original writer revalidates its data before storage.
        if result.source is None or result.receipt is None or result.state != "staged":
            raise PipelineRepositoryError("REVISION_NEW_CONTENT_REQUIRED")
        source = result.source
        if (source.source_hash==p.context.parent_source_hash or source.content_hash==p.context.parent_content_hash
                or source.public.item_key==p.context.parent_source.public.item_key
                or source.public.version==p.context.parent_source.public.version
                or substantive_revision_hash(source)==substantive_revision_hash(p.context.parent_source)):
            raise PipelineRepositoryError("REVISION_SUBSTANTIVE_NEW_CONTENT_REQUIRED")
        observed = self.generation.revision_author_binding(gen,result)
        if observed.context_hash != p.context.context_hash:
            raise PipelineRepositoryError("REVISION_ACTUAL_AUTHOR_CONTEXT_REQUIRED")
        return observed

    def commit_generation(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration, result: GenerationResultV2) -> SharedPipelineStageResult:
        self._result(p,gen,result)
        self.generation_context(p,lease=gen.lease,request=gen.request,committed=True)
        authority = self._source_authority(p)
        return self.generation.commit_generation(gen,result,source_authority=authority)

    def persist_lineage(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration, result: GenerationResultV2,
                        *, lease: JobLeaseV1) -> UUID:
        self._result(p,gen,result)
        self.generation_context(p,lease=lease,request=p.request,committed=True,completed=True)
        observed = self.author_binding(p,gen,result)
        row = self.conn.execute("SELECT a.*,a.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_generation_artifacts a WHERE a.job_id=%s AND a.candidate_id=%s FOR SHARE",
            (p.lease.job_id,p.request.candidate_id)).fetchone()
        if (row is None or row["same_transaction"] or row["reservation_id"] != gen.reservation_id
                or row["root_id"] != p.investigation.root_id or result.source is None or result.receipt is None
                or row["source_json"] != result.source.model_dump(mode="json")
                or row["receipt_json"] != result.receipt.model_dump(mode="json") or row["request_json"] != p.request.model_dump(mode="json")):
            raise PipelineRepositoryError("REVISION_ORIGINAL_COMMITTED_GENERATION_REQUIRED")
        checkpoint = self.conn.execute("SELECT 1 FROM tutor_item_supply_shared_checkpoints "
            "WHERE job_id=%s AND stage='generating' AND status='completed' AND receipt_hash=%s",
            (p.lease.job_id,row["artifact_hash"])).fetchone()
        if checkpoint is None:
            raise PipelineRepositoryError("REVISION_ORIGINAL_GENERATION_CHECKPOINT_REQUIRED")
        usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
            (gen.reservation_id,"generation."+p.request.candidate_id.hex)).fetchone()
        if usage is None or usage["same_transaction"]:
            raise PipelineRepositoryError("REVISION_COMMITTED_AUTHOR_SETTLEMENT_REQUIRED")
        reservation = self.generation.budget._reservation_by_key(gen.lease,"gen."+p.request.candidate_id.hex)
        if (reservation is None or reservation["id"] != gen.reservation_id
                or reservation["root_id"] != p.investigation.root_id
                or self.generation.budget._reservation_amounts(gen.lease,gen.reservation_id) != generation_resources(p.request,1,revision=True).as_dict()):
            raise PipelineRepositoryError("REVISION_ORIGINAL_ROUND_RESERVATION_REQUIRED")
        if usage["usage_state"]=="known" and self.generation.budget._settlement_amounts("shared",usage["id"]).get("revision_rounds") != 1:
            raise PipelineRepositoryError("REVISION_ACTUAL_ROUND_USAGE_REQUIRED")
        parent = p.investigation.original
        with finite_review_context(parent.source,spec=parent.spec,materials=parent.request.materials):
            preparation_hash = canonical_hash(p.payload())
        payload = {"schema_version": "native_shared_revision_lineage_v1", "preparation_id": str(p.preparation_id),
            "preparation_hash": preparation_hash, "root_id": str(p.investigation.root_id),
            "lease": lease.model_dump(mode="json"), "parent_artifact_id": str(p.investigation.original.artifact_id),
            "child_artifact_id": str(row["id"]), "child_artifact_hash": row["artifact_hash"],
            "context_hash": p.context.context_hash, "author_input": observed.model_dump(mode="json"),
            "provider_receipt_hash": canonical_hash(result.receipt.provider.model_dump(mode="json")),
            "reservation_id": str(gen.reservation_id), "settlement_id": str(usage["id"]), "usage_state": usage["usage_state"],
            "child_substantive_hash": substantive_revision_hash(result.source),
            "publication_enabled": False, "blockers_discharged": False, "admission_eligible": False}
        self.conn.execute("INSERT INTO tutor_item_supply_shared_revision_lineage "
            "(id,preparation_id,root_id,parent_artifact_id,child_artifact_id,child_job_id,reservation_id,settlement_id,payload_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",(p.preparation_id,p.preparation_id,p.investigation.root_id,
                p.investigation.original.artifact_id,row["id"],p.lease.job_id,gen.reservation_id,usage["id"],Jsonb(payload)))
        return p.preparation_id

    def verified_committed_lineage(self, p: PreparedNativeRevision, gen: PreparedSharedGeneration,
                                   result: GenerationResultV2, *, lease: JobLeaseV1,
                                   normal_facts_owner: SharedAdmissionFactsOwner | None = None,
                                   normal_facts: IssuedSharedAdmissionFactsV1 | None = None) -> dict[str, Any]:
        """Original issuer + committed DATA + CURRENT operation, not old stage lease.

        No generating/investigation-stage fence is replayed after checkpoints.
        JSON readback alone can never satisfy _result's process-issued objects.
        """
        self._guard()
        self._result(p,gen,result)
        if normal_facts_owner is not None or normal_facts is not None:
            # Only the explicitly NEW normal mode may identify its own exact
            # child terminal. Controlled ancestry wins before any permission.
            held = self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(%s) AS held",
                (p.lease.job_id,)).fetchone()
            if held is None or held["held"] is not False:
                raise PipelineRepositoryError("SHARED_CONTROLLED_EXPERIMENT_HELD")
            from app.services.learning.item_supply.shared_admission_facts import SharedAdmissionFactsOwner
            from app.services.learning.item_supply.native_normal_revision_readmission import NativeNormalRevisionReadmissionOwner
            if type(normal_facts_owner) is not SharedAdmissionFactsOwner or normal_facts is None:
                raise PipelineRepositoryError("REVISION_NORMAL_ORIGINAL_FACTS_FRAME_REQUIRED")
            assert normal_facts_owner is not None
            normal = normal_facts_owner.normal_readmission_owner
            if (type(normal) is not NativeNormalRevisionReadmissionOwner or normal.conn is not self.conn
                    or normal.recheck.revision_owner is not self):
                raise PipelineRepositoryError("REVISION_NORMAL_ORIGINAL_FACTS_FRAME_REQUIRED")
            frame = normal.require_terminal_frame(facts_owner=normal_facts_owner, facts=normal_facts, lease=lease)
            if (frame.recheck.revision is not p or frame.recheck.author is not gen
                    or frame.recheck.author_result is not result):
                raise PipelineRepositoryError("REVISION_NORMAL_ORIGINAL_CHILD_FRAME_REQUIRED")
        lease = checked_model(lease,JobLeaseV1)
        if ((lease.job_id,lease.generation,lease.lease_owner,lease.profile,lease.visibility) !=
                (p.lease.job_id,p.lease.generation,p.lease.lease_owner,p.lease.profile,"public")
                or lease.owner_id is not None or lease.owner_epoch is not None
                or lease.state_version<p.lease.state_version):
            raise PipelineRepositoryError("REVISION_CURRENT_DESCENDANT_OPERATION_REQUIRED")
        now = server_clock(self.conn,datetime.now(UTC))
        self.generation.runtime._control(lease,now=now)
        if now>=p.deadline_at:
            raise PipelineRepositoryError("REVISION_ORIGINAL_EVIDENCE_DEADLINE_REACHED")
        authority,_ = self.generation._issued(gen)
        lineage = self.conn.execute("SELECT l.*,l.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_revision_lineage l WHERE l.preparation_id=%s FOR SHARE",(p.preparation_id,)).fetchone()
        if lineage is None or lineage["same_transaction"] or lineage["reservation_id"] != gen.reservation_id:
            raise PipelineRepositoryError("REVISION_COMMITTED_ORIGINAL_LINEAGE_REQUIRED")
        resolved = self.generation.artifacts.resolve_generation(lease=lease,artifact_id=lineage["child_artifact_id"],
            now=now,source_authority=authority,spec=p.spec)
        observed = self.author_binding(p,gen,result)
        if (resolved.source != result.source or resolved.receipt != result.receipt or resolved.request != p.request
                or resolved.artifact["root_id"] != p.investigation.root_id
                or lineage["payload_json"]["child_artifact_hash"] != resolved.artifact["artifact_hash"]
                or lineage["payload_json"]["author_input"] != observed.model_dump(mode="json")
                or lineage["snapshot_hash"] != canonical_hash(lineage["payload_json"])
                or self.generation.artifacts.generation_policy(lease,p.request,now=now).policy_hash != p.context.policy_hash):
            raise PipelineRepositoryError("REVISION_COMMITTED_LINEAGE_DATA_CHANGED")
        if normal_facts_owner is None and normal_facts is None:
            terminal = self.conn.execute("SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts "
                "WHERE generation_artifact_id=ANY(%s::uuid[])) OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts "
                "WHERE generation_artifact_id=ANY(%s::uuid[]) AND artifact_kind='admission_evaluation') "
                "OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events WHERE version_id=ANY(%s::uuid[])) AS terminal",
                ([p.investigation.original.artifact_id,resolved.artifact["id"]],
                 [p.investigation.original.artifact_id,resolved.artifact["id"]],
                 [UUID(p.investigation.original.binding.version_key), resolved.artifact["version_id"]])).fetchone()
        else:
            if normal_facts is None:
                raise PipelineRepositoryError("REVISION_NORMAL_ORIGINAL_FACTS_FRAME_REQUIRED")
            # Parent and unrelated child terminals remain unconditional DENY.
            # The exact evaluation/publication generated by this same ORIGINAL
            # facts/publisher is needed for their subsequent final verify calls;
            # DB rows identify permitted history, never restore a capability.
            terminal = self.conn.execute(
                "SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=%s) "
                "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts WHERE generation_artifact_id=%s AND artifact_kind='admission_evaluation') "
                "OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events WHERE version_id=%s) "
                "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_admission_facts WHERE generation_artifact_id=%s AND (id IS DISTINCT FROM %s OR payload_hash IS DISTINCT FROM %s)) "
                "OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_pipeline_receipts e WHERE e.generation_artifact_id=%s AND e.artifact_kind='admission_evaluation' "
                "AND (e.artifact_key IS DISTINCT FROM %s OR e.receipt_hash IS DISTINCT FROM %s OR e.payload_json IS DISTINCT FROM %s "
                "OR e.mode IS DISTINCT FROM 'live' OR e.job_id IS DISTINCT FROM %s OR e.lease_owner IS DISTINCT FROM %s OR e.lease_generation IS DISTINCT FROM %s)) "
                "OR EXISTS(SELECT 1 FROM tutor_learning_item_publication_events event WHERE event.version_id=%s AND NOT EXISTS("
                "SELECT 1 FROM tutor_learning_item_native_publication_proofs proof JOIN tutor_item_supply_shared_pipeline_receipts evaluation ON evaluation.id=proof.evaluation_receipt_id "
                "WHERE proof.id=event.authority_reference_id AND proof.version_id=event.version_id AND proof.generation_artifact_id=%s "
                "AND proof.facts_receipt_id=%s AND proof.proof_json->>'facts_hash'=%s "
                "AND proof.proof_json->'lease'=%s AND evaluation.artifact_key=%s AND evaluation.receipt_hash=%s "
                "AND evaluation.generation_artifact_id=%s AND evaluation.payload_json=%s "
                "AND event.authority_kind='native_v2' AND event.authority_hash=proof.proof_hash "
                "AND event.policy_version=%s AND event.state IN ('agent_reviewed','pilot','published')) "
                "AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_validation_receipts bank_validation "
                "JOIN tutor_learning_item_import_receipts imported ON imported.validation_receipt_id=bank_validation.id "
                "WHERE event.authority_reference_id=bank_validation.id AND imported.initial_publication_event_id=event.id "
                "AND imported.version_id=event.version_id AND bank_validation.version_id=event.version_id "
                "AND event.state='machine_verified' AND event.state_version=1 AND event.predecessor_event_id IS NULL "
                "AND event.authority_kind='validation' AND event.authority_hash=bank_validation.receipt_hash "
                "AND event.policy_version='learning_item_native_import_v2' AND bank_validation.policy_version=event.policy_version "
                "AND bank_validation.schema_version='candidate_validation_v2' AND bank_validation.passed IS NULL "
                "AND bank_validation.native_generation_artifact_id=%s AND bank_validation.native_validation_receipt_id=%s "
                "AND bank_validation.receipt_hash=%s AND bank_validation.native_specification_hash=%s "
                "AND bank_validation.native_import_lease_json=%s AND imported.importer_version='learning_item_native_repository_v2' "
                "AND imported.source_hash=%s AND imported.content_hash=%s)) AS terminal",
                (p.investigation.original.artifact_id, p.investigation.original.artifact_id,
                 UUID(p.investigation.original.binding.version_key), resolved.artifact["id"], normal_facts.receipt_id,
                 normal_facts.receipt_hash, resolved.artifact["id"], "native_admission." + normal_facts.receipt_id.hex,
                 normal_facts.evaluation.evaluation_hash, Jsonb(normal_facts.evaluation.model_dump(mode="json")),
                 lease.job_id, lease.lease_owner, lease.generation, normal_facts.version_id,
                 normal_facts.generation_artifact_id, normal_facts.receipt_id, normal_facts.receipt_hash,
                 Jsonb(lease.model_dump(mode="json")), "native_admission." + normal_facts.receipt_id.hex,
                 normal_facts.evaluation.evaluation_hash, normal_facts.generation_artifact_id,
                 Jsonb(normal_facts.evaluation.model_dump(mode="json")), normal_facts.evaluation.policy_version,
                 normal_facts.generation_artifact_id, normal_facts.validation_receipt_id, normal_facts.validation_receipt_hash,
                 normal_facts.specification_hash, Jsonb(lease.model_dump(mode="json")),
                 normal_facts.evidence.binding.source_hash, normal_facts.evidence.binding.content_hash)).fetchone()
        if terminal is None or terminal["terminal"]:
            raise PipelineRepositoryError("REVISION_FINAL_HISTORY_RETAINED")
        end = server_clock(self.conn, now)
        self.generation.runtime._control(lease, now=end)
        if end>=p.deadline_at or (normal_facts is not None and end>=normal_facts.valid_until):
            raise PipelineRepositoryError("REVISION_ORIGINAL_EVIDENCE_DEADLINE_REACHED")
        return {"artifact":resolved.artifact,"lineage":lineage,"source":resolved.source,"authority":authority}
