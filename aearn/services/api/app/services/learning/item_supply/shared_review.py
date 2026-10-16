"""Native PUBLIC blind/six-role review staging, not final facts or admission.

All database phases use the caller's B1d transaction. New IO needs a new P3
allowance; committed validation is data, never rehydrated runner capability.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
from typing import TYPE_CHECKING, Any, TypeAlias
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.blind_protocol import (
    BlindProtocol, LEGACY_BLIND_PROTOCOL, blind_prompt_version, checked_blind_protocol,
)
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, check_finite_source_spec
from app.services.learning.item_supply.finite_candidate_validation import FiniteCandidateValidationInputsV1, prepare_finite_candidate_validation
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.finite_task_ambiguity import (
    FiniteAmbiguityPlanV1, FiniteAmbiguityReceiptV1, FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan,
)
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.private_blind_diagnostics import PrivateBlindAudit, PrivateBlindAuditSink
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, server_clock
from app.services.learning.item_supply.review_contracts_v2 import (
    BlindSolveReceiptV2, CandidateBindingV2, ProviderIdentityV2, ReviewReport, check_subject,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2,
    blind_input, blind_solve_candidate, review_candidate_for_policy, review_resource_plan,
)
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
from app.services.learning.item_supply.shared_pipeline_repository import SharedPipelineArtifactRepository
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.diagnostic_policy import (
    ReviewBundle, checked_bundle, completed_blind_allowed, policy_for_hash,
)
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2
from app.services.learning.item_supply.review_protocol import (
    configured_review_protocol, make_review_request, report_protocol, verify_review_report,
)
from app.services.learning.item_supply.review_rubrics import LEGACY_REVIEW_PROTOCOL, ReviewProtocol
from app.services.learning.item_supply.review_observability import (
    ReviewFailureObservation, ReviewFailurePhase, observe_review_failure,
)
from app.services.learning.item_supply.review_deliberation import prepare_review_deliberation
from app.services.learning.item_supply.review_deliberation_contracts import ReviewDeliberationPlanV1

Scorer: TypeAlias = SandboxBlindAnswerScorer | FiniteStaticBlindScorer

if TYPE_CHECKING:
    from app.services.learning.item_supply.native_review_investigation import (
        NativeReviewInvestigationOwner, PreparedNativeReviewInvestigation,
    )


@dataclass(frozen=True)
class PreparedSharedReview:
    lease: JobLeaseV1
    artifact_id: UUID
    artifact_hash: str
    validation_receipt_id: UUID
    spec: FiniteCandidateSpecV1
    source: LearningItemSourceV1
    request: GenerationRequestV2
    validation: CandidateValidationV2
    binding: CandidateBindingV2
    author_identity: str
    reservation_id: UUID
    provider_identities: tuple[ProviderIdentityV2, ...]
    provider_resources: ResourceAmounts
    resources: ResourceAmounts
    inputs: FiniteCandidateValidationInputsV1
    ambiguity_plan: FiniteAmbiguityPlanV1
    ambiguity_run_id: UUID
    review_protocol: ReviewProtocol = LEGACY_REVIEW_PROTOCOL
    blind_protocol: BlindProtocol = LEGACY_BLIND_PROTOCOL
    blind_input_hash: str | None = None
    blind_envelope_hash: str | None = None
    blind_configuration_hash: str | None = None
    persistent_committed_frame: dict[str,Any] | None = None


@dataclass(frozen=True)
class SharedReviewResult:
    blind: BlindSolveReceiptV2 | None
    bundle: ReviewBundle | None
    safe_reason: str
    ambiguity: FiniteAmbiguityReceiptV1 | None = None
    partial_reports: tuple[ReviewReport, ...] = field(default=(), repr=False)
    observation: ReviewFailureObservation | None = field(default=None, repr=False)

    def observation_payload(self) -> dict[str, object] | None:
        return self.observation.payload() if self.observation is not None else None


@dataclass(frozen=True)
class VerifiedSharedReviewEvidence:
    """Private projection, NOT a capability; final issuer must call the owner again."""
    binding: CandidateBindingV2
    blind: BlindSolveReceiptV2
    bundle: ReviewBundle
    ambiguity: FiniteAmbiguityReceiptV1
    blind_terminals: tuple[RunnerTerminalProofV1, ...]
    ambiguity_terminals: tuple[RunnerTerminalProofV1, ...]
    execution_usage: ResourceAmounts


def _combined_resources(provider: ResourceAmounts, blind: ResourceAmounts,
                        ambiguity: ResourceAmounts) -> ResourceAmounts:
    return ResourceAmounts(requests=provider.requests, input_tokens=provider.input_tokens,
        output_tokens=provider.output_tokens, execution_seconds=blind.execution_seconds + ambiguity.execution_seconds)


@dataclass(frozen=True)
class SharedReviewStageResult:
    state: str
    blind_receipt_id: UUID | None
    review_receipt_id: UUID | None
    pending_boundaries: tuple[str, ...] = (
        "finite_ambiguity_owner_pending", "course_family_coverage_pending", "shared_final_facts_pending",
    )
    publication_enabled: bool = False


class SharedReviewPipeline:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, enabled: bool = False,
                 trusted_model_bindings: Mapping[tuple[str, str], str] | None = None,
                 continuation_owner: SharedCandidateContinuationOwner | None = None,
                 private_blind_audit_sink: PrivateBlindAuditSink | None = None,
                 blind_protocol: BlindProtocol | None = None) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        self._blind_protocol = None if blind_protocol is None else checked_blind_protocol(blind_protocol)
        self._models = dict(trusted_model_bindings or {})
        if continuation_owner is not None and (type(continuation_owner) is not SharedCandidateContinuationOwner
                                               or continuation_owner.conn is not conn):
            raise PipelineRepositoryError("SHARED_CONTINUATION_OWNER_REQUIRED")
        self.continuation_owner = continuation_owner
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.budget = ItemSupplyBudgetRepository(conn)
        self._prepared: dict[UUID, tuple[PreparedSharedReview, str, RagSourceAuthority,
                                         JsonBlindSolverV2, tuple[JsonReviewerV2, ...], Scorer,
                                         RunnerPort | None, FiniteTaskAmbiguityOwner]] = {}
        self._started: set[UUID] = set()
        self._results: dict[UUID, tuple[SharedReviewResult, str]] = {}
        self._independent_rounds: dict[UUID, tuple[int, frozenset[UUID]]] = {}
        self._operation_deadlines: dict[UUID, datetime] = {}
        self._private_blind_audit_sink = private_blind_audit_sink
        self._private_blind_audits: dict[UUID,PrivateBlindAudit] = {}
        self._committed_frames: dict[UUID,tuple[PreparedSharedReview,SharedReviewResult,Any,str]] = {}

    def private_blind_audit_status(self, p: PreparedSharedReview) -> dict[str,object] | None:
        """Private acknowledgement/status DATA only; no answer, expected option or authority."""
        with finite_review_context(p.source,spec=p.spec,materials=p.request.materials):
            self._issued(p)
        audit = self._private_blind_audits.get(p.reservation_id)
        return None if audit is None else audit.status()

    def reissue_committed_phase(self, *, phase: Any, review_receipt_id: UUID,
            source_authority: RagSourceAuthority) -> tuple[PreparedSharedReview, SharedReviewResult]:
        """Original-issued read-only finding frame, NOT old IO/admission authority.

        Immutable review DATA remains byte-identical; the new execution lease
        comes ONLY from the concrete persistent phase. No seven-port rerun.
        """
        from app.services.learning.item_supply.persistent_pack import PersistentPackTaskOwner
        from app.services.learning.item_supply.persistent_pack_contracts import IssuedPackPhase
        from app.services.learning.item_supply.diagnostic_policy import parse_bundle
        if (type(self) is not SharedReviewPipeline or type(phase) is not IssuedPackPhase
                or type(phase.owner) is not PersistentPackTaskOwner or phase.owner.conn is not self.conn
                or phase.version is None or phase.version.artifact_id is None
                or type(self.continuation_owner) is not SharedCandidateContinuationOwner):
            raise PipelineRepositoryError("COMMITTED_REVIEW_CONCRETE_PERSISTENT_OWNER_REQUIRED")
        phase.owner.require_phase(phase,kind="candidate")
        artifact_id=phase.version.artifact_id
        held=self.conn.execute("SELECT item_supply_internal.controlled_counterexample_held(job_id) AS held "
            "FROM tutor_item_supply_shared_generation_artifacts WHERE id=%s",(artifact_id,)).fetchone()
        if held is None or held["held"] is not False:
            raise PipelineRepositoryError("COMMITTED_REVIEW_CONTROLLED_ANCESTRY_DENIED")
        continuation=self.continuation_owner
        assert continuation is not None
        adopted=continuation.resolve(lease=phase.record.lease,artifact_id=artifact_id,
            spec=phase.version.specification,source_authority=source_authority)
        row=self.conn.execute("SELECT *,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s AND generation_artifact_id=%s "
            "AND artifact_kind='review_bundle' AND mode='live' FOR SHARE",(review_receipt_id,artifact_id)).fetchone()
        if row is None or row["same_transaction"]:
            raise PipelineRepositoryError("COMMITTED_REVIEW_ORIGINAL_RECEIPT_REQUIRED")
        bundle=parse_bundle(row["payload_json"])
        if row["receipt_hash"]!=bundle.bundle_hash:
            raise PipelineRepositoryError("COMMITTED_REVIEW_HASH_MISMATCH")
        blind_rows=self.conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts "
            "WHERE job_id=%s AND lease_generation=%s AND generation_artifact_id=%s AND artifact_kind='blind_solve' "
            "AND receipt_hash=%s AND mode='live' FOR SHARE",(row["job_id"],row["lease_generation"],artifact_id,
                bundle.blind_solve.receipt_hash)).fetchall()
        validations=self.conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts "
            "WHERE job_id=%s AND lease_generation=%s AND generation_artifact_id=%s AND artifact_kind='validation' "
            "AND mode='live' FOR SHARE",(row["job_id"],row["lease_generation"],artifact_id)).fetchall()
        if len(blind_rows)!=1 or len(validations)!=1:
            raise PipelineRepositoryError("COMMITTED_REVIEW_EXACT_BLIND_VALIDATION_REQUIRED")
        blind=BlindSolveReceiptV2.model_validate_json(json.dumps(blind_rows[0]["payload_json"]))
        validation=CandidateValidationV2.model_validate_json(json.dumps(validations[0]["payload_json"]))
        source,request,spec=adopted.source,adopted.original_request,phase.version.specification
        if spec.target_id!="python-kc-binding-v1":
            raise PipelineRepositoryError("COMMITTED_EXECUTION_REVIEW_FRAME_UNWIRED")
        inputs=prepare_finite_candidate_validation(source,spec=spec,materials=request.materials)
        if (inputs.static_facts is None or validation!=inputs.static_facts.validation
                or validations[0]["receipt_hash"]!=validation.evidence_hash or blind!=bundle.blind_solve
                or blind_rows[0]["receipt_hash"]!=blind.receipt_hash
                or bundle.binding.source_hash!=source.source_hash or bundle.binding.content_hash!=source.content_hash
                or bundle.binding.runtime_key!=(source.blueprint.runtime_profile_id or "static-exact-v1")):
            raise PipelineRepositoryError("COMMITTED_REVIEW_EXACT_SOURCE_VALIDATION_REQUIRED")
        reservation_id=UUID(row["artifact_key"].removeprefix("review_bundle."))
        if blind_rows[0]["artifact_key"]!="blind_solve."+reservation_id.hex:
            raise PipelineRepositoryError("COMMITTED_REVIEW_EXACT_RESERVATION_KEY_REQUIRED")
        settlement=self.conn.execute("SELECT * FROM tutor_item_supply_shared_runtime_settlements "
            "WHERE reservation_id=%s AND settlement_key=%s FOR SHARE",(reservation_id,"review."+artifact_id.hex)).fetchone()
        reservation=self.conn.execute("SELECT * FROM tutor_item_supply_shared_reservations WHERE id=%s "
            "AND root_id=%s AND job_id=%s AND lease_generation=%s FOR SHARE",
            (reservation_id,phase.record.root_id,row["job_id"],row["lease_generation"])).fetchone()
        if settlement is None or settlement["usage_state"]!="unknown" or reservation is None:
            raise PipelineRepositoryError("COMMITTED_REVIEW_ORIGINAL_SETTLEMENT_REQUIRED")
        old_protocol=report_protocol(bundle.reports[0])
        with finite_review_context(source,spec=spec,materials=request.materials):
            for report in bundle.reports:
                if report_protocol(report)!=old_protocol:
                    raise PipelineRepositoryError("COMMITTED_REVIEW_PROTOCOL_MISMATCH")
                verify_review_report(report,make_review_request(source,binding=bundle.binding,
                    validation_receipt=validation,role=report.role,protocol=old_protocol))
        identities=(blind.run.provider_identity,*(r.run.provider_identity for r in bundle.reports))
        current_key=self.artifacts.context(phase.record.lease,now=server_clock(self.conn,datetime.now(UTC)))["key"]
        ports: list[JsonBlindSolverV2 | JsonReviewerV2]=[]
        port: JsonBlindSolverV2 | JsonReviewerV2
        from app.services.learning.item_supply.blind_protocol import blind_protocol_for_prompt_version
        blind_protocol=blind_protocol_for_prompt_version(blind.run.prompt_version)
        for index,identity in enumerate(identities):
            client=BoundedOpenAIReviewClient(self.settings,profile=phase.record.lease.profile)
            if (client.model!=identity.model or client.configured_provider!=identity.provider
                    or self._models.get((client.configured_provider,current_key.model_version))!=client.model):
                raise PipelineRepositoryError("COMMITTED_REVIEW_CURRENT_MODEL_BINDING_REQUIRED")
            if index==0:
                port=JsonBlindSolverV2(client,identity=identity,profile_hash=phase.record.lease.profile.profile_hash,
                    timeout_seconds=100,max_output_tokens=61440,max_input_bytes=262144,blind_protocol=blind_protocol)
            else:
                port=JsonReviewerV2(client,identity=identity,role=bundle.reports[index-1].role,
                    profile_hash=phase.record.lease.profile.profile_hash,timeout_seconds=100,max_output_tokens=61440,
                    max_input_bytes=262144,review_protocol=old_protocol)
            ports.append(port)
        solver=ports[0]
        if not isinstance(solver,JsonBlindSolverV2) or any(not isinstance(p,JsonReviewerV2) for p in ports[1:]):
            raise PipelineRepositoryError("COMMITTED_REVIEW_ORIGINAL_TYPED_PORTS_REQUIRED")
        reviewers=tuple(p for p in ports[1:] if isinstance(p,JsonReviewerV2))
        scorer=FiniteStaticBlindScorer(binding=bundle.binding,spec=spec,materials=request.materials)
        ambiguity_plan=build_finite_ambiguity_plan(source,spec=spec,inputs=inputs)
        ambiguity_owner=FiniteTaskAmbiguityOwner(None,parent_deadline_at=phase.record.valid_until)
        # Actual zero-IO deterministic interpretation, not restored runner seals.
        ambiguity=ambiguity_owner.run(source,ambiguity_plan,spec=spec,inputs=inputs,run_id=uuid4())
        frame={"schema_version":"persistent_committed_review_frame_v1","phase_id":str(phase.record.phase_id),
            "review_receipt_id":str(review_receipt_id),"blind_receipt_id":str(blind_rows[0]["id"]),
            "validation_receipt_id":str(validations[0]["id"]),"review_hash":bundle.bundle_hash,
            "blind_hash":blind.receipt_hash,"validation_hash":validation.evidence_hash,
            "continuation_binding_hash":adopted.binding.binding_hash}
        # The frame is read-only. Old resource amounts are DATA, never a fresh allowance.
        p=PreparedSharedReview(phase.record.lease,artifact_id,adopted.original_artifact["artifact_hash"],
            validations[0]["id"],spec,source,request,validation,bundle.binding,bundle.author_identity,
            reservation_id,identities,ResourceAmounts(),ResourceAmounts(),inputs,ambiguity_plan,ambiguity.run_id,
            old_protocol,blind_protocol,persistent_committed_frame=frame)
        result=SharedReviewResult(blind,bundle,"committed_review_data_only",ambiguity)
        self._prepared[reservation_id]=(p,self._seal(p),source_authority,solver,reviewers,scorer,None,ambiguity_owner)
        self._committed_frames[reservation_id]=(p,result,phase,canonical_hash(frame))
        self.require_committed_phase(p,result,phase=phase)
        return p,result

    def require_committed_phase(self, p: PreparedSharedReview, result: SharedReviewResult, *, phase: Any) -> dict[str,Any]:
        entry=self._committed_frames.get(p.reservation_id)
        issued=self._prepared.get(p.reservation_id)
        if (entry is None or entry[0] is not p or entry[1] is not result or entry[2] is not phase
                or p.persistent_committed_frame is None or entry[3]!=canonical_hash(p.persistent_committed_frame)
                or issued is None or issued[0] is not p
                or issued[1]!=self._seal(p)):
            raise PipelineRepositoryError("COMMITTED_REVIEW_NEW_ISSUER_SEAL_REQUIRED")
        phase.owner.require_phase(phase,kind="candidate")
        authority=self._prepared[p.reservation_id][2]
        continuation=self.continuation_owner
        if type(continuation) is not SharedCandidateContinuationOwner:
            raise PipelineRepositoryError("COMMITTED_REVIEW_CONCRETE_CONTINUATION_REQUIRED")
        assert continuation is not None
        continuation.resolve(lease=phase.record.lease,artifact_id=p.artifact_id,spec=p.spec,source_authority=authority)
        for kind,id_field,hash_field in (("review_bundle","review_receipt_id","review_hash"),
                ("blind_solve","blind_receipt_id","blind_hash"),("validation","validation_receipt_id","validation_hash")):
            row=self.conn.execute("SELECT * FROM tutor_item_supply_shared_pipeline_receipts WHERE id=%s "
                "AND artifact_kind=%s AND generation_artifact_id=%s AND mode='live' FOR SHARE",
                (UUID(p.persistent_committed_frame[id_field]),kind,p.artifact_id)).fetchone()
            if row is None or row["receipt_hash"]!=p.persistent_committed_frame[hash_field]:
                raise PipelineRepositoryError("COMMITTED_REVIEW_CURRENT_DATA_CHANGED")
        return self.artifacts.context(phase.record.lease,now=server_clock(self.conn,datetime.now(UTC)))

    @property
    def blind_protocol(self) -> BlindProtocol | None:
        """Optional composition expectation; preparation seals the actual solver."""
        return None if self._blind_protocol is None else checked_blind_protocol(self._blind_protocol)

    @staticmethod
    def _blind_configuration_hash(solver: JsonBlindSolverV2) -> str:
        return canonical_hash({"blind_protocol": solver.blind_protocol,
            "profile_hash": solver._profile_hash, "timeout_seconds": solver._timeout_seconds,
            "max_output_tokens": solver._max_output_tokens, "max_input_bytes": solver._max_input_bytes})

    @property
    def review_enabled(self) -> bool:
        return self.enabled and self.settings.learning_item_supply_enabled and self.settings.learning_item_network_enabled

    @staticmethod
    def _seal(p: PreparedSharedReview) -> str:
        payload: dict[str, Any] = {"lease": p.lease.model_dump(mode="json"), "artifact_id": str(p.artifact_id),
            "artifact_hash": p.artifact_hash, "validation_receipt_id": str(p.validation_receipt_id),
            "spec": p.spec.model_dump(mode="json"), "source": p.source.model_dump(mode="json"),
            "request": p.request.model_dump(mode="json"), "validation": p.validation.model_dump(mode="json"),
            "binding": p.binding.model_dump(mode="json"), "author_identity": p.author_identity,
            "reservation_id": str(p.reservation_id), "identities": [i.model_dump(mode="json") for i in p.provider_identities],
            "provider_resources": p.provider_resources.model_dump(mode="json"), "resources": p.resources.model_dump(mode="json"),
            "inputs": p.inputs.model_dump(mode="json"), "ambiguity_plan": p.ambiguity_plan.model_dump(mode="json"),
            "ambiguity_run_id": str(p.ambiguity_run_id)}
        if p.review_protocol != LEGACY_REVIEW_PROTOCOL:
            payload["review_protocol"] = p.review_protocol
        if checked_blind_protocol(p.blind_protocol) != LEGACY_BLIND_PROTOCOL:
            payload["blind_protocol"] = p.blind_protocol
            payload["blind_input_hash"] = p.blind_input_hash
            payload["blind_envelope_hash"] = p.blind_envelope_hash
            payload["blind_configuration_hash"] = p.blind_configuration_hash
        if p.persistent_committed_frame is not None:
            payload["persistent_committed_frame"]=p.persistent_committed_frame
        return canonical_hash(payload)

    @staticmethod
    def _result_hash(result: SharedReviewResult) -> str:
        payload: dict[str, object] = {"blind": None if result.blind is None else result.blind.model_dump(mode="json"),
            "bundle": None if result.bundle is None else result.bundle.model_dump(mode="json"), "reason": result.safe_reason,
            "ambiguity": None if result.ambiguity is None else result.ambiguity.model_dump(mode="json")}
        if result.partial_reports:
            payload["partial_reports"] = [r.model_dump(mode="json") for r in result.partial_reports]
        observation = result.observation_payload()
        if observation is not None:
            payload["observation"] = observation
        return canonical_hash(payload)

    def _issued(self, p: PreparedSharedReview) -> tuple[RagSourceAuthority, JsonBlindSolverV2, tuple[JsonReviewerV2, ...], Scorer]:
        if not self.review_enabled:
            raise PipelineRepositoryError("SHARED_REVIEW_DISABLED")
        entry = self._prepared.get(p.reservation_id)
        if entry is None or entry[0] is not p or entry[1] != self._seal(p):
            raise PipelineRepositoryError("SHARED_REVIEW_PREPARED_UNAVAILABLE")
        if p.persistent_committed_frame is not None:
            context=self._committed_frames.get(p.reservation_id)
            if context is None:
                raise PipelineRepositoryError("COMMITTED_REVIEW_NEW_ISSUER_SEAL_REQUIRED")
            self.require_committed_phase(p,context[1],phase=context[2])
            return entry[2],entry[3],entry[4],entry[5]
        if ((self.blind_protocol is not None and p.blind_protocol != self.blind_protocol)
                or entry[3].blind_protocol != p.blind_protocol
                or (p.blind_protocol != LEGACY_BLIND_PROTOCOL
                    and self._blind_configuration_hash(entry[3]) != p.blind_configuration_hash)):
            raise PipelineRepositoryError("SHARED_BLIND_PROTOCOL_CHANGED")
        deadline = self._operation_deadlines.get(p.reservation_id)
        if deadline is not None:
            if (any(getattr(port._client, "operation_deadline_at", deadline) != deadline for port in (entry[3], *entry[4]))
                    or (type(entry[5]) is SandboxBlindAnswerScorer and entry[5]._deadline != deadline)):
                raise PipelineRepositoryError("SHARED_RECHECK_DEADLINE_CHANGED")
        return entry[2], entry[3], entry[4], entry[5]

    @staticmethod
    def _review_deadline(lease: JobLeaseV1) -> datetime:
        return min(lease.expires_at, lease.parent_deadline,
                   lease.profile.bound_at + timedelta(milliseconds=lease.profile.values.stage_deadline_ms))

    def _ambiguity_context(self, p: PreparedSharedReview) -> tuple[RunnerPort | None, FiniteTaskAmbiguityOwner]:
        self._issued(p)
        runner, owner = self._prepared[p.reservation_id][6:]
        if (type(owner) is not FiniteTaskAmbiguityOwner or owner._runner is not runner
                or owner._deadline != self._operation_deadlines.get(p.reservation_id, self._review_deadline(p.lease))):
            raise PipelineRepositoryError("SHARED_AMBIGUITY_OWNER_MISMATCH")
        return runner, owner

    def _load(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
              spec: FiniteCandidateSpecV1, authority: RagSourceAuthority,
              allowed_stages: tuple[str, ...] = ("reviewing",)) -> tuple[dict[str, Any], LearningItemSourceV1, GenerationRequestV2, CandidateValidationV2]:
        if allowed_stages not in {("reviewing",), ("reviewing", "investigating")}:
            raise PipelineRepositoryError("REVIEW_STAGE_MISMATCH")
        self.artifacts.require_source(authority)
        now = server_clock(self.conn, datetime.now(UTC))
        resolved = self.artifacts.resolve_generation(lease=lease, artifact_id=artifact_id, now=now,
            source_authority=authority, spec=spec, continuation_owner=self.continuation_owner)
        if resolved.lease != lease or self.runtime.next_stage(lease) not in allowed_stages:
            raise PipelineRepositoryError("REVIEW_STAGE_MISMATCH")
        artifact, request, source, generation = resolved.artifact, resolved.request, resolved.source, resolved.receipt
        # Original author facts remain immutable. Adoption inherits generation
        # DATA only; current-job validation and its actual checkpoint are required.
        meta = self.artifacts.context(lease, now=now)
        if (meta["coverage"] != spec.coverage_blueprint or UUID(str(meta["root_id"])) != UUID(str(artifact["root_id"]))
                or request.blueprint != spec.blueprint or request.public_template != spec.public_template
                or source.blueprint != spec.blueprint
                or source.source_hash != artifact["source_hash"] or source.content_hash != artifact["content_hash"]
                or generation.source_hash != source.source_hash or generation.content_hash != source.content_hash
                or generation.candidate_id != request.candidate_id
                or canonical_hash({"source": artifact["source_json"], "receipt": artifact["receipt_json"],
                                   "request": artifact["request_json"]}) != artifact["artifact_hash"]):
            raise PipelineRepositoryError("SHARED_REVIEW_INPUT_MISMATCH")
        try:
            check_finite_source_spec(source, spec)
        except ValueError:
            raise PipelineRepositoryError("SHARED_REVIEW_INPUT_MISMATCH") from None
        if resolved.continuation_binding is None and request.profile != lease.profile:
            raise PipelineRepositoryError("SHARED_REVIEW_PROFILE_MISMATCH")
        for material, expected in zip(request.materials, generation.sources, strict=True):
            authority.assert_current(material, expected)
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        stored = self.conn.execute(
            "SELECT r.payload_json,r.receipt_hash,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=%s AND r.generation_artifact_id=%s "
            "AND r.job_id=%s AND r.lease_generation=%s AND r.artifact_kind='validation' AND r.mode='live'",
            (validation_receipt_id, artifact_id, lease.job_id, lease.generation),
        ).fetchone()
        if stored is None or stored["same_transaction"]:
            raise PipelineRepositoryError("SHARED_COMMITTED_VALIDATION_REQUIRED")
        validation = CandidateValidationV2.model_validate_json(json.dumps(stored["payload_json"]))
        if (stored["receipt_hash"] != validation.evidence_hash or validation.state != "machine_verified"
                or validation.source_hash != source.source_hash or validation.content_hash != source.content_hash):
            raise PipelineRepositoryError("SHARED_VALIDATION_NOT_VERIFIED")
        if inputs.static_facts is not None:
            if validation != inputs.static_facts.validation:
                raise PipelineRepositoryError("SHARED_STATIC_VALIDATION_MISMATCH")
        elif (validation.execution_evidence is None or validation.mode != "live"
              or validation.execution_evidence.scorer_version != spec.coverage_blueprint.scope.scorer_version):
            raise PipelineRepositoryError("SHARED_EXECUTION_VALIDATION_MISMATCH")
        self.runtime._control(lease, now=server_clock(self.conn, now))
        return artifact, source, request, validation

    def _identities(self, lease: JobLeaseV1, solver: JsonBlindSolverV2,
                    reviewers: tuple[JsonReviewerV2, ...]) -> tuple[ProviderIdentityV2, ...]:
        if (type(solver) is not JsonBlindSolverV2 or len(reviewers) != 6
                or any(type(r) is not JsonReviewerV2 for r in reviewers)
                or tuple(r.role for r in reviewers) != REQUIRED_REVIEW_ROLES):
            raise PipelineRepositoryError("SHARED_REVIEW_SEVEN_PORTS_REQUIRED")
        meta = self.artifacts.context(lease, now=datetime.now(UTC))
        key = meta["key"]
        model = self._models.get((key.provider, key.model_version))
        ports = (solver, *reviewers)
        identities = tuple(checked_model(port.provider_identity, ProviderIdentityV2) for port in ports)
        # Only this concrete native client may further narrow the original HTTP
        # timeout. Arbitrary client/port subclasses remain denied.
        from app.services.learning.item_supply.native_revision_recheck import _RecheckClient

        if (model is None or any(type(port._client) not in {BoundedOpenAIReviewClient, _RecheckClient}
                or port.frozen_profile != lease.profile or port.request_attempt_bound != 1 for port in ports)
                or any(i.provider != meta["provider_key"] or i.model != model for i in identities)
                or len({i.identity for i in identities}) != 7):
            raise PipelineRepositoryError("SHARED_REVIEW_PROVIDER_PROFILE_MISMATCH")
        return identities

    def prepare_review(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
                       spec: FiniteCandidateSpecV1, source_authority: RagSourceAuthority,
                       solver: JsonBlindSolverV2, reviewers: tuple[JsonReviewerV2, ...],
                       runner: RunnerPort | None = None,
                       operation_deadline_at: datetime | None = None) -> PreparedSharedReview | None:
        if not self.review_enabled:
            return None
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        deadline = self._review_deadline(lease)
        if operation_deadline_at is not None:
            if operation_deadline_at.tzinfo is None:
                raise PipelineRepositoryError("SHARED_RECHECK_DEADLINE_REQUIRED")
            deadline = min(deadline, operation_deadline_at)
        self.artifacts.require_owner()
        artifact, source, request, validation = self._load(lease=lease, artifact_id=artifact_id,
            validation_receipt_id=validation_receipt_id, spec=spec, authority=source_authority)
        binding = CandidateBindingV2(candidate_key=str(artifact["item_id"]), version_key=str(artifact["version_id"]),
            source_hash=source.source_hash, content_hash=source.content_hash, policy_hash=self.artifacts.generation_policy(lease, request, now=server_clock(self.conn, datetime.now(UTC))).policy_hash,
            profile_hash=lease.profile.profile_hash, runtime_key=source.blueprint.runtime_profile_id or "static-exact-v1",
            risk_tier=source.blueprint.publication_policy.risk_tier)
        blind_protocol = solver.blind_protocol
        if self.blind_protocol is not None and blind_protocol != self.blind_protocol:
            raise PipelineRepositoryError("SHARED_BLIND_PROTOCOL_MISMATCH")
        identities = self._identities(lease, solver, reviewers)
        generation = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        author = f"{generation.provider.provider}.item_author"
        if author in {i.identity for i in identities}:
            raise PipelineRepositoryError("SHARED_AUTHOR_REVIEW_IDENTITY_CONFLICT")
        scorer: Scorer
        if spec.target_id == "python-kc-binding-v1":
            if runner is not None:
                raise PipelineRepositoryError("SHARED_STATIC_RUNNER_DENIED")
            scorer = FiniteStaticBlindScorer(binding=binding, spec=spec, materials=request.materials)
        else:
            if runner is None:
                raise PipelineRepositoryError("SHARED_BLIND_RUNNER_REQUIRED")
            scorer = SandboxBlindAnswerScorer(runner, binding=binding, finite_spec=spec,
                                             parent_deadline_at=deadline)
        blind_input_hash, blind_envelope_hash, blind_configuration_hash = None, None, None
        with finite_review_context(source, spec=spec, materials=request.materials):
            check_subject(source, binding, validation)
            if blind_protocol != LEGACY_BLIND_PROTOCOL:
                blind_request = blind_input(source, binding, blind_protocol=blind_protocol)
                blind_input_hash = blind_request.input_hash
                blind_envelope_hash = solver.input_envelope_hash(blind_request)
                blind_configuration_hash = self._blind_configuration_hash(solver)
            provider_plan = review_resource_plan(source, binding=binding, validation_receipt=validation,
                                                solver=solver, reviewers=reviewers)
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        ambiguity_plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
        ambiguity_owner = FiniteTaskAmbiguityOwner(runner, parent_deadline_at=deadline)
        resources = _combined_resources(provider_plan, scorer.resource_plan(source), ambiguity_owner.resource_plan(ambiguity_plan))
        if resources.execution_seconds > (deadline - server_clock(self.conn, datetime.now(UTC))).total_seconds():
            raise PipelineRepositoryError("SHARED_REVIEW_EXECUTION_DEADLINE_INSUFFICIENT")
        reserved = self.budget.reserve(lease=lease, reservation_key=f"review.{artifact_id.hex}",
            amounts=resources, now=server_clock(self.conn, datetime.now(UTC)))
        if not reserved.allowed or reserved.reservation_id is None or reserved.reason == "REPLAY":
            return None
        p = PreparedSharedReview(lease, artifact_id, artifact["artifact_hash"], validation_receipt_id, spec, source,
            request, validation, binding, author, reserved.reservation_id, identities, provider_plan, resources,
            inputs, ambiguity_plan, uuid4(), configured_review_protocol(reviewers), blind_protocol,
            blind_input_hash, blind_envelope_hash, blind_configuration_hash)
        self._prepared[p.reservation_id] = (p, self._seal(p), source_authority, solver, reviewers, scorer, runner, ambiguity_owner)
        if operation_deadline_at is not None:
            self._operation_deadlines[p.reservation_id] = deadline
        return p

    def prepare_independent_review(self, *, bundle_version: int, forbidden_run_ids: frozenset[UUID],
                                   lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
                                   spec: FiniteCandidateSpecV1, source_authority: RagSourceAuthority,
                                   solver: JsonBlindSolverV2, reviewers: tuple[JsonReviewerV2, ...],
                                   runner: RunnerPort | None = None,
                                   operation_deadline_at: datetime | None = None) -> PreparedSharedReview | None:
        """Explicit new round; provider inputs remain precisely the NEW subject.

        Version/ancestral IDs are server-side dispatch guards, never opinions
        appended to blind/reviewer prompts. Historical default seals stay exact.
        """
        if type(bundle_version) is not int or bundle_version<2 or type(forbidden_run_ids) is not frozenset:
            raise PipelineRepositoryError("SHARED_INDEPENDENT_ROUND_BINDING_REQUIRED")
        p = self.prepare_review(lease=lease,artifact_id=artifact_id,validation_receipt_id=validation_receipt_id,
            spec=spec,source_authority=source_authority,solver=solver,reviewers=reviewers,runner=runner,
            operation_deadline_at=operation_deadline_at)
        if p is not None:
            self._independent_rounds[p.reservation_id] = (bundle_version,forbidden_run_ids)
        return p

    def _fence(self, p: PreparedSharedReview, *, before_io: bool = False) -> None:
        if p.persistent_committed_frame is not None:
            if before_io:
                raise PipelineRepositoryError("COMMITTED_REVIEW_DATA_NOT_HTTP_AUTHORITY")
            context=self._committed_frames.get(p.reservation_id)
            if context is None:
                raise PipelineRepositoryError("COMMITTED_REVIEW_NEW_ISSUER_SEAL_REQUIRED")
            self.require_committed_phase(p,context[1],phase=context[2])
            return
        authority, solver, reviewers, scorer = self._issued(p)
        deadline = self._operation_deadlines.get(p.reservation_id)
        if deadline is not None and server_clock(self.conn, datetime.now(UTC)) >= deadline:
            raise PipelineRepositoryError("SHARED_RECHECK_DEADLINE_REACHED")
        if configured_review_protocol(reviewers) != p.review_protocol:
            raise PipelineRepositoryError("SHARED_REVIEW_PROTOCOL_CHANGED")
        _, ambiguity_owner = self._ambiguity_context(p)
        artifact, source, request, validation = self._load(lease=p.lease, artifact_id=p.artifact_id,
            validation_receipt_id=p.validation_receipt_id, spec=p.spec, authority=authority)
        if self.artifacts.generation_policy(p.lease, request, now=server_clock(self.conn, datetime.now(UTC))).policy_hash != p.binding.policy_hash:
            raise PipelineRepositoryError("SHARED_REVIEW_POLICY_CHANGED")
        if ((source, request, validation, artifact["artifact_hash"]) != (p.source, p.request, p.validation, p.artifact_hash)
                or self._identities(p.lease, solver, reviewers) != p.provider_identities):
            raise PipelineRepositoryError("SHARED_REVIEW_INPUTS_CHANGED")
        with finite_review_context(source, spec=p.spec, materials=request.materials):
            if p.blind_protocol != LEGACY_BLIND_PROTOCOL:
                blind_request = blind_input(source, p.binding, blind_protocol=p.blind_protocol)
                if (blind_request.input_hash != p.blind_input_hash
                        or solver.input_envelope_hash(blind_request) != p.blind_envelope_hash):
                    raise PipelineRepositoryError("SHARED_BLIND_ENVELOPE_CHANGED")
            plan = review_resource_plan(source, binding=p.binding, validation_receipt=validation, solver=solver, reviewers=reviewers)
        inputs = prepare_finite_candidate_validation(source, spec=p.spec, materials=request.materials)
        if inputs != p.inputs or build_finite_ambiguity_plan(source, spec=p.spec, inputs=inputs) != p.ambiguity_plan:
            raise PipelineRepositoryError("SHARED_AMBIGUITY_PLAN_CHANGED")
        if before_io and _combined_resources(plan, scorer.resource_plan(source), ambiguity_owner.resource_plan(p.ambiguity_plan)) != p.resources:
            raise PipelineRepositoryError("SHARED_REVIEW_EXECUTION_PLAN_CHANGED")
        row = self.budget._reservation_by_key(p.lease, f"review.{p.artifact_id.hex}")
        if (plan != p.provider_resources or row is None or UUID(str(row["id"])) != p.reservation_id
                or row["lease_generation"] != p.lease.generation
                or self.budget._reservation_amounts(p.lease, p.reservation_id) != p.resources.as_dict()):
            raise PipelineRepositoryError("SHARED_REVIEW_RESERVATION_MISMATCH")

    def run_review(self, p: PreparedSharedReview) -> SharedReviewResult:
        if p.persistent_committed_frame is not None:
            raise PipelineRepositoryError("COMMITTED_REVIEW_DATA_NOT_HTTP_AUTHORITY")
        _, solver, reviewers, scorer = self._issued(p)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        if p.reservation_id in self._started:
            raise PipelineRepositoryError("SHARED_REVIEW_ALREADY_DISPATCHED")
        with self.conn.transaction():
            self._fence(p, before_io=True)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        self._started.add(p.reservation_id)
        _, ambiguity_owner = self._ambiguity_context(p)
        blind, bundle, ambiguity, reason = None, None, None, "finite_ambiguity_pending"
        partial_reports: tuple[ReviewReport, ...] = ()
        observation = None
        phase: ReviewFailurePhase = "finite_ambiguity"
        try:
            # Funded in prepare. Distinguish the finite interpretation first so
            # missing execution does not trigger seven unnecessary model calls.
            ambiguity = ambiguity_owner.run(p.source, p.ambiguity_plan, spec=p.spec,
                                              inputs=p.inputs, run_id=p.ambiguity_run_id)
            if not ambiguity_owner.verify(ambiguity, p.source, spec=p.spec, inputs=p.inputs):
                raise PipelineRepositoryError("SHARED_AMBIGUITY_RESULT_UNVERIFIED")
            with self.conn.transaction():
                self._fence(p)
            if self.conn.info.transaction_status != TransactionStatus.IDLE:
                raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
            with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
                phase = "blind_score"
                audit = None
                if self._private_blind_audit_sink is not None:
                    audit = PrivateBlindAudit(self._private_blind_audit_sink,operation=dict(
                        review_reservation_id=str(p.reservation_id),generation_artifact_id=str(p.artifact_id),
                        artifact_hash=p.artifact_hash,job_id=str(p.lease.job_id),lease_generation=p.lease.generation,
                        prepared_hash=self._seal(p)))
                    self._private_blind_audits[p.reservation_id] = audit
                blind = blind_solve_candidate(p.source, binding=p.binding, author_identity=p.author_identity,
                                              solver=solver, scorer=scorer,private_audit=audit,blind_protocol=p.blind_protocol)
                if not scorer.verify(blind.score, p.source):
                    raise PipelineRepositoryError("SHARED_BLIND_RESULT_UNVERIFIED")
                policy = policy_for_hash(p.binding.policy_hash)
                if completed_blind_allowed(blind, policy):
                    phase = "review_bundle"
                    independent = self._independent_rounds.get(p.reservation_id)
                    if independent is None:
                        bundle = review_candidate_for_policy(p.source, binding=p.binding, validation_receipt=p.validation,
                            author_identity=p.author_identity, blind_solve_receipt=blind, reviewers=reviewers, policy=policy,
                            blind_protocol=p.blind_protocol)
                    else:
                        bundle = review_candidate_for_policy(p.source,binding=p.binding,validation_receipt=p.validation,
                            author_identity=p.author_identity,blind_solve_receipt=blind,reviewers=reviewers,policy=policy,
                            bundle_version=independent[0],blind_protocol=p.blind_protocol)
                        if independent[1] & {blind.run.run_id,*(r.run.run_id for r in bundle.reports)}:
                            partial_reports = tuple(bundle.reports)
                            bundle = None
                            raise PipelineRepositoryError("SHARED_ANCESTRAL_REVIEW_RUN_REUSED")
                    reason = "peer_review_staged"
                else:
                    reason = "blind_solution_rejected"
            if p.reservation_id in self._operation_deadlines:
                with self.conn.transaction():
                    self._fence(p)
        except Exception as exc:
            if p.reservation_id in self._operation_deadlines and bundle is not None:
                partial_reports = tuple(bundle.reports)
                bundle = None  # Retain reports as data, never a usable failed recheck bundle.
            if isinstance(exc, AutonomousReviewError):
                partial_reports = exc.partial_reports
                observation = exc.observation
            if observation is None:
                observation = observe_review_failure(exc, phase=phase)
            reason = "finite_ambiguity_pending" if ambiguity is None else ("blind_solve_pending" if blind is None else "review_pending")
        result = SharedReviewResult(blind, bundle, reason, ambiguity, partial_reports, observation)
        self._results[p.reservation_id] = (result, self._result_hash(result))
        return result

    def _result(self, p: PreparedSharedReview, result: SharedReviewResult) -> Scorer:
        _, _, _, scorer = self._issued(p)
        if p.persistent_committed_frame is not None:
            context=self._committed_frames.get(p.reservation_id)
            if context is None:
                raise PipelineRepositoryError("COMMITTED_REVIEW_NEW_ISSUER_SEAL_REQUIRED")
            self.require_committed_phase(p,result,phase=context[2])
            return scorer
        stored = self._results.get(p.reservation_id)
        if stored is None or stored[0] is not result or stored[1] != self._result_hash(result):
            raise PipelineRepositoryError("SHARED_REVIEW_RESULT_UNAVAILABLE")
        return scorer

    def settle_review(self, p: PreparedSharedReview, result: SharedReviewResult) -> None:
        if p.persistent_committed_frame is not None:
            raise PipelineRepositoryError("COMMITTED_REVIEW_DATA_NOT_SETTLEMENT_AUTHORITY")
        self.artifacts.require_owner()
        self._result(p, result)
        # Seven provider ports do not attest aggregate per-attempt usage. Never
        # release their allocation by guessing zero, including partial failures.
        self.budget.settle(lease=p.lease, reservation_id=p.reservation_id,
            settlement_key=f"review.{p.artifact_id.hex}", usage_state="unknown", actual=None,
            cost_amount=None, receipt_hash=None)

    def prepare_investigation(self, p: PreparedSharedReview, result: SharedReviewResult, *,
                             owner: NativeReviewInvestigationOwner, lease: JobLeaseV1,
                             review_receipt_id: UUID) -> PreparedNativeReviewInvestigation | None:
        """Explicit default-off original-owner seam, never called by run_review.

        Requires already committed full review DATA. The concrete owner either
        separately reserves one new investigation or stays pending; no invented
        reviewing checkpoint, no revival of final/quarantined history.
        """
        from app.services.learning.item_supply.native_review_investigation import NativeReviewInvestigationOwner

        if type(owner) is not NativeReviewInvestigationOwner or owner.review is not self or owner.conn is not self.conn:
            raise PipelineRepositoryError("NATIVE_INVESTIGATION_ORIGINAL_SHARED_OWNER_REQUIRED")
        return owner.prepare(original=p, result=result, lease=lease, review_receipt_id=review_receipt_id)

    def _verify_blind_binding(self, p: PreparedSharedReview, blind: BlindSolveReceiptV2) -> None:
        """Original expected protocol, not a receipt-selected authority upgrade."""
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            request = blind_input(p.source, p.binding, blind_protocol=p.blind_protocol)
            if (blind.binding != p.binding or blind.run.profile_hash != p.binding.profile_hash
                    or blind.run.input_hash != request.input_hash
                    or blind.run.prompt_version != blind_prompt_version(p.blind_protocol)):
                raise PipelineRepositoryError("SHARED_BLIND_PROTOCOL_UNVERIFIED")

    def prepare_review_followup(self, p: PreparedSharedReview, result: SharedReviewResult) -> ReviewDeliberationPlanV1:
        """Explicit verified PRIVATE pending route with original-owner DB reads/fences.

        No provider/runner IO, reservation or checkpoint is performed here.

        No native investigation/revision/lineage owner is installed. The old
        seven/eight-call reservation is never reused to dispatch another round.
        Current cap-zero campaigns stay cap zero. A future server owner must
        separately freeze/prepare every operation against the SAME original root
        and history; this data projection cannot resume quarantined candidates.
        """
        self.artifacts.require_owner()
        self._issued(p)
        scorer = self._result(p, result)
        self._fence(p)
        self._require_settlement(p)
        if result.bundle is None or result.blind is None:
            raise PipelineRepositoryError("SHARED_REVIEW_FULL_BUNDLE_REQUIRED")
        bundle = checked_bundle(result.bundle)
        self._verify_blind_binding(p, result.blind)
        if (bundle.binding != p.binding or bundle.blind_solve != result.blind
                or bundle.author_identity != p.author_identity
                or tuple(r.run.provider_identity for r in bundle.reports) != p.provider_identities[1:]
                or result.blind.run.provider_identity != p.provider_identities[0]
                or not scorer.verify(result.blind.score, p.source)):
            raise PipelineRepositoryError("SHARED_REVIEW_FOLLOWUP_UNVERIFIED")
        now = server_clock(self.conn, datetime.now(UTC))
        meta = self.budget._job_meta(p.lease, now=now)
        limits, user_limits = self.budget._active_limits(meta, p.lease, now)
        if limits is None or user_limits is None:
            raise PipelineRepositoryError("SHARED_REVIEW_FOLLOWUP_BUDGET_UNAVAILABLE")
        # Passive upper bounds, NOT remaining allowance. The original P3 reserve
        # must still enforce root/window, cumulative usage and retained UNKNOWN.
        ceiling = ResourceAmounts(**{kind: min(int(row["cap_amount"]) for row in limits + user_limits
            if row["resource_kind"] == kind) for kind in ResourceAmounts().as_dict()})
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            if any(report_protocol(report) != p.review_protocol for report in bundle.reports):
                raise PipelineRepositoryError("SHARED_REVIEW_PROTOCOL_CHANGED")
            return prepare_review_deliberation(source=p.source, validation=p.validation, bundle=bundle,
                lease=p.lease, budget_root_id=UUID(str(meta["root_id"])), resource_ceiling=ceiling,
                blind_protocol=p.blind_protocol)

    def _verified_ambiguity(self, p: PreparedSharedReview, result: SharedReviewResult, *,
                            runner: RunnerPort | None) -> tuple[ResourceAmounts, tuple[RunnerTerminalProofV1, ...]]:
        original_runner, owner = self._ambiguity_context(p)
        receipt = result.ambiguity
        if (runner is not original_runner or receipt is None or receipt.plan != p.ambiguity_plan
                or receipt.run_id != p.ambiguity_run_id):
            raise PipelineRepositoryError("SHARED_AMBIGUITY_RESULT_UNVERIFIED")
        return owner.verified_evidence(receipt, p.source, spec=p.spec, inputs=p.inputs, runner=runner)

    def _require_settlement(self, p: PreparedSharedReview) -> None:
        settled = self.conn.execute(
            "SELECT id,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s AND settlement_key=%s",
            (p.reservation_id, f"review.{p.artifact_id.hex}"),
        ).fetchone()
        if settled is None or settled["same_transaction"]:
            raise PipelineRepositoryError("SHARED_COMMITTED_REVIEW_SETTLEMENT_REQUIRED")

    def verified_review_evidence(self, p: PreparedSharedReview, result: SharedReviewResult, *,
                                 runner: RunnerPort | None) -> VerifiedSharedReviewEvidence:
        """Current caller transaction; projections cannot rehydrate original issuers.

        The final facts owner must retain this pipeline and the SAME actual
        runner, and invoke this method again when verifying, not trust saved JSON.
        """
        if p.persistent_committed_frame is not None:
            raise PipelineRepositoryError("COMMITTED_PARENT_DATA_NOT_FRESH_ADMISSION_EVIDENCE")
        self.artifacts.require_owner()
        scorer = self._result(p, result)
        self._fence(p)
        self._require_settlement(p)
        if result.blind is None or result.bundle is None or result.ambiguity is None:
            raise PipelineRepositoryError("SHARED_REVIEW_FULL_EVIDENCE_REQUIRED")
        blind = checked_model(result.blind, BlindSolveReceiptV2)
        self._verify_blind_binding(p, blind)
        bundle = checked_bundle(result.bundle)
        with finite_review_context(p.source, spec=p.spec, materials=p.request.materials):
            for report in bundle.reports:
                if report_protocol(report) != p.review_protocol:
                    raise PipelineRepositoryError("SHARED_REVIEW_PROTOCOL_CHANGED")
                verify_review_report(report, make_review_request(p.source, binding=p.binding,
                    validation_receipt=p.validation, role=report.role, protocol=p.review_protocol))
        if (blind.binding != p.binding or not completed_blind_allowed(blind, policy_for_hash(p.binding.policy_hash)) or bundle.binding != p.binding
                or bundle.author_identity != p.author_identity or bundle.blind_solve != blind
                or blind.run.provider_identity != p.provider_identities[0]
                or tuple(r.run.provider_identity for r in bundle.reports) != p.provider_identities[1:]
                or not scorer.verify(blind.score, p.source)):
            raise PipelineRepositoryError("SHARED_REVIEW_EVIDENCE_UNVERIFIED")
        ambiguity_usage, ambiguity_terminals = self._verified_ambiguity(p, result, runner=runner)
        blind_terminals: tuple[RunnerTerminalProofV1, ...] = ()
        blind_usage = ResourceAmounts()
        if p.spec.target_id == "python-kc-binding-v1":
            if runner is not None or type(scorer) is not FiniteStaticBlindScorer:
                raise PipelineRepositoryError("SHARED_STATIC_RUNNER_DENIED")
        else:
            if type(scorer) is not SandboxBlindAnswerScorer or scorer._runner is not runner or runner is None:
                raise PipelineRepositoryError("SHARED_BLIND_RUNNER_IDENTITY_MISMATCH")
            original = scorer._issued.get(blind.score.receipt_hash)
            if original is None or not runner.verify(original.receipt, request=original.request):
                raise PipelineRepositoryError("SHARED_BLIND_RESULT_UNVERIFIED")
            blind_terminals = (RunnerTerminalProofV1.model_validate_json(json.dumps(original.receipt.to_payload())),)
            blind_usage = scorer.resource_usage(blind.score)
        usage = ResourceAmounts(execution_seconds=blind_usage.execution_seconds + ambiguity_usage.execution_seconds)
        if usage.execution_seconds > p.resources.execution_seconds:
            raise PipelineRepositoryError("SHARED_REVIEW_EXECUTION_USAGE_EXCEEDED")
        return VerifiedSharedReviewEvidence(p.binding, blind, bundle, result.ambiguity,
                                            blind_terminals, ambiguity_terminals, usage)

    def commit_review(self, p: PreparedSharedReview, result: SharedReviewResult) -> SharedReviewStageResult:
        if p.persistent_committed_frame is not None:
            raise PipelineRepositoryError("COMMITTED_PARENT_DATA_CANNOT_REWRITE_REVIEW")
        self.artifacts.require_owner()
        scorer = self._result(p, result)
        self._fence(p)
        self._require_settlement(p)
        pending: tuple[str, ...] = ("course_family_coverage_pending", "shared_final_facts_pending")
        if result.ambiguity is None:
            pending = ("finite_ambiguity_owner_pending", *pending)
        else:
            original_runner, _ = self._ambiguity_context(p)
            self._verified_ambiguity(p, result, runner=original_runner)
        authority, _, _, _ = self._issued(p)
        blind_id, bundle_id = None, None
        if result.blind is not None:
            blind = checked_model(result.blind, BlindSolveReceiptV2)
            self._verify_blind_binding(p, blind)
            if (blind.binding != p.binding or blind.run.provider_identity != p.provider_identities[0]
                    or not scorer.verify(blind.score, p.source)):
                raise PipelineRepositoryError("SHARED_BLIND_RESULT_UNVERIFIED")
            blind_id = self._store(p, "blind_solve", blind, authority)
        if result.bundle is not None:
            bundle = checked_bundle(result.bundle)
            if (bundle.binding != p.binding or bundle.blind_solve != result.blind
                    or tuple(r.run.provider_identity for r in bundle.reports) != p.provider_identities[1:]):
                raise PipelineRepositoryError("SHARED_REVIEW_BUNDLE_STALE")
            bundle_id = self._store(p, "review_bundle", bundle, authority)
        # Named interpretation evidence does not establish final facts, family
        # independence or coverage; keep the reviewing checkpoint incomplete.
        return SharedReviewStageResult(result.safe_reason, blind_id, bundle_id, pending)

    def _store(self, p: PreparedSharedReview, kind: str, payload: BlindSolveReceiptV2 | ReviewBundle,
               authority: RagSourceAuthority) -> UUID:
        from typing import cast
        from app.services.learning.item_supply.pipeline_repository import ArtifactKind

        row = self.artifacts.store_receipt(lease=p.lease, artifact_id=p.artifact_id, kind=cast(ArtifactKind, kind),
            payload=payload, artifact_key=f"{kind}.{p.reservation_id.hex}", now=server_clock(self.conn, datetime.now(UTC)),
            source_authority=authority, continuation_owner=self.continuation_owner, spec=p.spec)
        return UUID(str(row["id"]))
