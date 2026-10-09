"""Native PUBLIC blind/six-role review staging, not final facts or admission.

All database phases use the caller's B1d transaction. New IO needs a new P3
allowance; committed validation is data, never rehydrated runner capability.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, check_finite_source_spec
from app.services.learning.item_supply.finite_candidate_validation import FiniteCandidateValidationInputsV1, prepare_finite_candidate_validation
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.finite_task_ambiguity import (
    FiniteAmbiguityPlanV1, FiniteAmbiguityReceiptV1, FiniteTaskAmbiguityOwner, build_finite_ambiguity_plan,
)
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context
from app.services.learning.item_supply.finite_static_blind_scorer import FiniteStaticBlindScorer
from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2, GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, server_clock
from app.services.learning.item_supply.review_contracts_v2 import (
    BlindSolveReceiptV2, CandidateBindingV2, ProviderIdentityV2, check_subject,
)
from app.services.learning.item_supply.review_provider import (
    BoundedOpenAIReviewClient, JsonBlindSolverV2, JsonReviewerV2,
    blind_solve_candidate, review_candidate_for_policy, review_resource_plan,
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

Scorer = SandboxBlindAnswerScorer | FiniteStaticBlindScorer


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


@dataclass(frozen=True)
class SharedReviewResult:
    blind: BlindSolveReceiptV2 | None
    bundle: ReviewBundle | None
    safe_reason: str
    ambiguity: FiniteAmbiguityReceiptV1 | None = None


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
                 continuation_owner: SharedCandidateContinuationOwner | None = None) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
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

    @property
    def review_enabled(self) -> bool:
        return self.enabled and self.settings.learning_item_supply_enabled and self.settings.learning_item_network_enabled

    @staticmethod
    def _seal(p: PreparedSharedReview) -> str:
        return canonical_hash({"lease": p.lease.model_dump(mode="json"), "artifact_id": str(p.artifact_id),
            "artifact_hash": p.artifact_hash, "validation_receipt_id": str(p.validation_receipt_id),
            "spec": p.spec.model_dump(mode="json"), "source": p.source.model_dump(mode="json"),
            "request": p.request.model_dump(mode="json"), "validation": p.validation.model_dump(mode="json"),
            "binding": p.binding.model_dump(mode="json"), "author_identity": p.author_identity,
            "reservation_id": str(p.reservation_id), "identities": [i.model_dump(mode="json") for i in p.provider_identities],
            "provider_resources": p.provider_resources.model_dump(mode="json"), "resources": p.resources.model_dump(mode="json"),
            "inputs": p.inputs.model_dump(mode="json"), "ambiguity_plan": p.ambiguity_plan.model_dump(mode="json"),
            "ambiguity_run_id": str(p.ambiguity_run_id)})

    @staticmethod
    def _result_hash(result: SharedReviewResult) -> str:
        return canonical_hash({"blind": None if result.blind is None else result.blind.model_dump(mode="json"),
            "bundle": None if result.bundle is None else result.bundle.model_dump(mode="json"), "reason": result.safe_reason,
            "ambiguity": None if result.ambiguity is None else result.ambiguity.model_dump(mode="json")})

    def _issued(self, p: PreparedSharedReview) -> tuple[RagSourceAuthority, JsonBlindSolverV2, tuple[JsonReviewerV2, ...], Scorer]:
        if not self.review_enabled:
            raise PipelineRepositoryError("SHARED_REVIEW_DISABLED")
        entry = self._prepared.get(p.reservation_id)
        if entry is None or entry[0] is not p or entry[1] != self._seal(p):
            raise PipelineRepositoryError("SHARED_REVIEW_PREPARED_UNAVAILABLE")
        return entry[2], entry[3], entry[4], entry[5]

    @staticmethod
    def _review_deadline(lease: JobLeaseV1) -> datetime:
        return min(lease.expires_at, lease.parent_deadline,
                   lease.profile.bound_at + timedelta(milliseconds=lease.profile.values.stage_deadline_ms))

    def _ambiguity_context(self, p: PreparedSharedReview) -> tuple[RunnerPort | None, FiniteTaskAmbiguityOwner]:
        self._issued(p)
        runner, owner = self._prepared[p.reservation_id][6:]
        if (type(owner) is not FiniteTaskAmbiguityOwner or owner._runner is not runner
                or owner._deadline != self._review_deadline(p.lease)):
            raise PipelineRepositoryError("SHARED_AMBIGUITY_OWNER_MISMATCH")
        return runner, owner

    def _load(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
              spec: FiniteCandidateSpecV1, authority: RagSourceAuthority) -> tuple[dict[str, Any], LearningItemSourceV1, GenerationRequestV2, CandidateValidationV2]:
        self.artifacts.require_source(authority)
        now = server_clock(self.conn, datetime.now(UTC))
        resolved = self.artifacts.resolve_generation(lease=lease, artifact_id=artifact_id, now=now,
            source_authority=authority, spec=spec, continuation_owner=self.continuation_owner)
        if resolved.lease != lease or self.runtime.next_stage(lease) != "reviewing":
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
        if (model is None or any(type(port._client) is not BoundedOpenAIReviewClient
                or port.frozen_profile != lease.profile or port.request_attempt_bound != 1 for port in ports)
                or any(i.provider != meta["provider_key"] or i.model != model for i in identities)
                or len({i.identity for i in identities}) != 7):
            raise PipelineRepositoryError("SHARED_REVIEW_PROVIDER_PROFILE_MISMATCH")
        return identities

    def prepare_review(self, *, lease: JobLeaseV1, artifact_id: UUID, validation_receipt_id: UUID,
                       spec: FiniteCandidateSpecV1, source_authority: RagSourceAuthority,
                       solver: JsonBlindSolverV2, reviewers: tuple[JsonReviewerV2, ...],
                       runner: RunnerPort | None = None) -> PreparedSharedReview | None:
        if not self.review_enabled:
            return None
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        self.artifacts.require_owner()
        artifact, source, request, validation = self._load(lease=lease, artifact_id=artifact_id,
            validation_receipt_id=validation_receipt_id, spec=spec, authority=source_authority)
        binding = CandidateBindingV2(candidate_key=str(artifact["item_id"]), version_key=str(artifact["version_id"]),
            source_hash=source.source_hash, content_hash=source.content_hash, policy_hash=self.artifacts.generation_policy(lease, request, now=server_clock(self.conn, datetime.now(UTC))).policy_hash,
            profile_hash=lease.profile.profile_hash, runtime_key=source.blueprint.runtime_profile_id or "static-exact-v1",
            risk_tier=source.blueprint.publication_policy.risk_tier)
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
                                             parent_deadline_at=self._review_deadline(lease))
        with finite_review_context(source, spec=spec, materials=request.materials):
            check_subject(source, binding, validation)
            provider_plan = review_resource_plan(source, binding=binding, validation_receipt=validation,
                                                solver=solver, reviewers=reviewers)
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        ambiguity_plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
        ambiguity_owner = FiniteTaskAmbiguityOwner(runner, parent_deadline_at=self._review_deadline(lease))
        resources = _combined_resources(provider_plan, scorer.resource_plan(source), ambiguity_owner.resource_plan(ambiguity_plan))
        if resources.execution_seconds > (self._review_deadline(lease) - server_clock(self.conn, datetime.now(UTC))).total_seconds():
            raise PipelineRepositoryError("SHARED_REVIEW_EXECUTION_DEADLINE_INSUFFICIENT")
        reserved = self.budget.reserve(lease=lease, reservation_key=f"review.{artifact_id.hex}",
            amounts=resources, now=server_clock(self.conn, datetime.now(UTC)))
        if not reserved.allowed or reserved.reservation_id is None or reserved.reason == "REPLAY":
            return None
        p = PreparedSharedReview(lease, artifact_id, artifact["artifact_hash"], validation_receipt_id, spec, source,
            request, validation, binding, author, reserved.reservation_id, identities, provider_plan, resources,
            inputs, ambiguity_plan, uuid4())
        self._prepared[p.reservation_id] = (p, self._seal(p), source_authority, solver, reviewers, scorer, runner, ambiguity_owner)
        return p

    def _fence(self, p: PreparedSharedReview, *, before_io: bool = False) -> None:
        authority, solver, reviewers, scorer = self._issued(p)
        _, ambiguity_owner = self._ambiguity_context(p)
        artifact, source, request, validation = self._load(lease=p.lease, artifact_id=p.artifact_id,
            validation_receipt_id=p.validation_receipt_id, spec=p.spec, authority=authority)
        if self.artifacts.generation_policy(p.lease, request, now=server_clock(self.conn, datetime.now(UTC))).policy_hash != p.binding.policy_hash:
            raise PipelineRepositoryError("SHARED_REVIEW_POLICY_CHANGED")
        if ((source, request, validation, artifact["artifact_hash"]) != (p.source, p.request, p.validation, p.artifact_hash)
                or self._identities(p.lease, solver, reviewers) != p.provider_identities):
            raise PipelineRepositoryError("SHARED_REVIEW_INPUTS_CHANGED")
        with finite_review_context(source, spec=p.spec, materials=request.materials):
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
                blind = blind_solve_candidate(p.source, binding=p.binding, author_identity=p.author_identity,
                                              solver=solver, scorer=scorer)
                if not scorer.verify(blind.score, p.source):
                    raise PipelineRepositoryError("SHARED_BLIND_RESULT_UNVERIFIED")
                policy = policy_for_hash(p.binding.policy_hash)
                if completed_blind_allowed(blind, policy):
                    bundle = review_candidate_for_policy(p.source, binding=p.binding, validation_receipt=p.validation,
                        author_identity=p.author_identity, blind_solve_receipt=blind, reviewers=reviewers, policy=policy)
                    reason = "peer_review_staged"
                else:
                    reason = "blind_solution_rejected"
        except Exception:
            reason = "finite_ambiguity_pending" if ambiguity is None else ("blind_solve_pending" if blind is None else "review_pending")
        result = SharedReviewResult(blind, bundle, reason, ambiguity)
        self._results[p.reservation_id] = (result, self._result_hash(result))
        return result

    def _result(self, p: PreparedSharedReview, result: SharedReviewResult) -> Scorer:
        _, _, _, scorer = self._issued(p)
        stored = self._results.get(p.reservation_id)
        if stored is None or stored[0] is not result or stored[1] != self._result_hash(result):
            raise PipelineRepositoryError("SHARED_REVIEW_RESULT_UNAVAILABLE")
        return scorer

    def settle_review(self, p: PreparedSharedReview, result: SharedReviewResult) -> None:
        self.artifacts.require_owner()
        self._result(p, result)
        # Seven provider ports do not attest aggregate per-attempt usage. Never
        # release their allocation by guessing zero, including partial failures.
        self.budget.settle(lease=p.lease, reservation_id=p.reservation_id,
            settlement_key=f"review.{p.artifact_id.hex}", usage_state="unknown", actual=None,
            cost_amount=None, receipt_hash=None)

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
        self.artifacts.require_owner()
        scorer = self._result(p, result)
        self._fence(p)
        self._require_settlement(p)
        if result.blind is None or result.bundle is None or result.ambiguity is None:
            raise PipelineRepositoryError("SHARED_REVIEW_FULL_EVIDENCE_REQUIRED")
        blind = checked_model(result.blind, BlindSolveReceiptV2)
        bundle = checked_bundle(result.bundle)
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
