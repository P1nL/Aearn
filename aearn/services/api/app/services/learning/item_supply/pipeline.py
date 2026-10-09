"""Bounded two-phase generation and explicit P4/P5 composition, default off.

Callers commit prepare transactions before provider IO. Completion never commits
unrelated work or publishes an item. RAG authorization is rechecked on storage.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemKind, LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import (
    GenerationProvider, GenerationRequestV2, GenerationResultV2, PublicMaterialV2,
    SourceAuthority, SourceReceiptV2,
)
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import (
    ArtifactKind, ArtifactMode, PipelineArtifactRepository, PipelineReceipt, PipelineRepositoryError,
)
from app.services.learning.item_supply.parameter_profiles import ProfileKeyV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import (
    CandidateExecutionPort, CandidateValidationV2, validate_candidate,
)
from app.services.learning.item_supply.admission import evaluate_admission_v2
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvaluationV2, AdmissionEvidenceV2, CandidateBindingV2, ReviewBundleV2, ReviewReport,
    check_subject, checked_validation_receipt, receipt_digest,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, BlindAnswerScorerPortV2, BlindSolverPortV2, JsonBlindSolverV2, JsonReviewerV2, ReviewerPortV2,
    blind_solve_candidate, review_candidate, review_resource_plan,
)
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.review_protocol import configured_review_protocol, report_protocol
from app.services.learning.item_supply.review_rubrics import LEGACY_REVIEW_PROTOCOL, ReviewProtocol


@dataclass(frozen=True)
class PreparedGeneration:
    lease: JobLeaseV1
    scope_id: UUID
    request: GenerationRequestV2
    reservation_id: UUID
    sources: tuple[SourceReceiptV2, ...]
    attempt_bound: int
    mode: ArtifactMode
    producer_binding: tuple[str, str] | None = None


@dataclass(frozen=True)
class PipelineStageResult:
    state: str
    safe_reason: str
    artifact_id: UUID | None = None


@dataclass(frozen=True)
class PreparedReview:
    lease: JobLeaseV1
    scope_id: UUID
    artifact_id: UUID
    source: LearningItemSourceV1
    validation: CandidateValidationV2
    binding: CandidateBindingV2
    author_identity: str
    reservation_id: UUID
    mode: ArtifactMode
    attempt_bounds: tuple[int, ...]
    provider_bindings: tuple[tuple[str, str], ...] = ()
    provider_resource_plan: ResourceAmounts | None = None
    review_protocol: ReviewProtocol = LEGACY_REVIEW_PROTOCOL


@dataclass(frozen=True)
class CompletedReview:
    bundle: ReviewBundleV2


class _PreparedSourceAuthority:
    def __init__(self, receipts: tuple[SourceReceiptV2, ...]) -> None:
        self.receipts = {r.material_digest: r for r in receipts}

    def authorize(self, material: PublicMaterialV2) -> SourceReceiptV2:
        receipt = self.receipts.get(material_digest(material))
        if receipt is None:
            raise PipelineRepositoryError("PREPARED_SOURCE_MISMATCH")
        return receipt

    def assert_current(self, material: PublicMaterialV2, expected: SourceReceiptV2) -> SourceReceiptV2:
        # This is only an IO-phase snapshot. Storage still requires the concrete
        # RAG authorizer to take a fresh fence on the repository connection.
        receipt = self.authorize(material)
        if receipt != checked_model(expected, SourceReceiptV2):
            raise PipelineRepositoryError("PREPARED_SOURCE_MISMATCH")
        return receipt


if TYPE_CHECKING:
    from app.services.learning.item_bank.publication import LearningItemPublicationService
    from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
    from app.services.learning.item_supply.admission_facts_contracts import IssuedAdmissionFactsV1
    from app.services.learning.item_supply.sandbox.pipeline import SandboxExecutionPipeline


def _require_explicit_sql_review_execution(
    source: LearningItemSourceV1, resources: ResourceAmounts, *, mode: ArtifactMode,
) -> None:
    if mode != "live":
        return
    from app.services.learning.item_supply.task_ambiguity_owner import (
        CALL_EXECUTION_BOUND, EXECUTION_BOUND, SQL_TARGET_INSTRUCTION,
    )
    from app.services.learning.item_supply.sandbox.python_goal_scorer import PYTHON_GOAL_INSTRUCTION

    if (source.public.instruction_markdown in (SQL_TARGET_INSTRUCTION, PYTHON_GOAL_INSTRUCTION)
            and resources.execution_seconds < CALL_EXECUTION_BOUND + EXECUTION_BOUND):
        raise PipelineRepositoryError("REVIEW_EXECUTION_RESOURCE_PLAN_INCOMPLETE")


class ItemSupplyPipeline:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *,
                 trusted_model_bindings: Mapping[tuple[str, str], str] | None = None) -> None:
        self.conn, self.settings = conn, settings
        # Server-only mapping from profile model-version key to actual configured
        # model. Missing/cross-provider plans stay pending, never guessed aliases.
        self._model_bindings = dict(trusted_model_bindings or {})
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.budget = ItemSupplyBudgetRepository(conn)
        self.artifacts = PipelineArtifactRepository(conn)
        self._review_started: set[UUID] = set()
        self.partial_review_reports: dict[UUID, tuple[ReviewReport, ...]] = {}

    def sandbox_execution(self) -> "SandboxExecutionPipeline":
        """Explicit private P6 path; the original static validator stays unchanged."""
        from app.services.learning.item_supply.sandbox.pipeline import SandboxExecutionPipeline

        return SandboxExecutionPipeline(self.conn, self.settings)

    def _provider_binding(self, lease: JobLeaseV1, provider: str, model: str) -> tuple[str, str]:
        row = self.conn.execute(
            "SELECT o.provider_key,p.profile_hash,p.profile_json->'profile_key' AS profile_key "
            "FROM tutor_item_supply_private_job_controls c "
            "JOIN tutor_item_supply_private_jobs j ON j.id=c.job_id "
            "JOIN tutor_item_supply_private_obligations o ON o.root_id=j.root_id "
            "JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id "
            "WHERE c.job_id=%s AND c.user_id=%s AND c.epoch=%s",
            (lease.job_id, lease.owner_id, lease.owner_epoch),
        ).fetchone()
        if row is None or row["profile_hash"] != lease.profile.profile_hash:
            raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
        key = ProfileKeyV1.model_validate_json(json.dumps(row["profile_key"]))
        if provider != row["provider_key"] or provider != key.provider:
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        configured = self._model_bindings.get((key.provider, key.model_version))
        if configured is None:
            raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
        if model != configured:
            raise PipelineRepositoryError("PROVIDER_MODEL_BINDING_MISMATCH")
        return provider, model

    @property
    def generation_enabled(self) -> bool:
        return (self.settings.learning_item_supply_enabled
                and self.settings.learning_item_generation_enabled
                and self.settings.learning_item_network_enabled)

    def prepare_generation(
        self, *, lease: JobLeaseV1, scope_id: UUID, request: GenerationRequestV2,
        provider: GenerationProvider, source_authority: SourceAuthority,
        mode: ArtifactMode = "live", now: datetime | None = None,
    ) -> PreparedGeneration | None:
        if not self.generation_enabled:
            return None
        now = now or datetime.now(UTC)
        lease = self.artifacts._context(lease, scope_id, now, mode)
        request = checked_model(request, GenerationRequestV2)
        if request.profile != lease.profile or self.runtime.next_stage(lease) != "generating":
            raise PipelineRepositoryError("GENERATION_STAGE_MISMATCH")
        scope = self.conn.execute(
            "SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s",
            (scope_id, lease.owner_id, lease.owner_epoch),
        ).fetchone()
        if scope is None or scope["scope_hash"] != request.scope_hash:
            raise PipelineRepositoryError("GENERATION_SCOPE_MISMATCH")
        if mode == "live" and request.demand_binding is not None:
            from app.services.learning.item_supply.generation_demand import frozen_private_demand

            frozen_private_demand(self.conn, lease=lease, scope_id=scope_id, request=request)
        sources = tuple(source_authority.authorize(m) for m in request.materials)
        if mode == "live" and (not isinstance(source_authority, RagSourceAuthority)
                or source_authority.connection is not self.conn
                or any(r.mode != "current_authority" for r in sources)):
            raise PipelineRepositoryError("SOURCE_AUTHORITY_REQUIRED")
        if mode == "live" and not isinstance(provider, OpenAICompatibleGenerationProvider):
            raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
        producer_binding = (self._provider_binding(lease, provider.provider_key, provider.configured_model)
                            if mode == "live" else None)
        attempts = provider.request_attempt_bound
        if type(attempts) is not int or not 1 <= attempts <= 3:
            raise PipelineRepositoryError("PROVIDER_ATTEMPT_BOUND_INVALID")
        reservation = self.budget.reserve(
            lease=lease, reservation_key=f"gen.{request.candidate_id.hex}", now=now,
            amounts=ResourceAmounts(requests=attempts,
                input_tokens=request.limits.max_input_bytes * attempts,
                output_tokens=request.limits.max_output_tokens * attempts, candidates=1),
        )
        if not reservation.allowed or reservation.reservation_id is None:
            return None
        return PreparedGeneration(lease, scope_id, request, reservation.reservation_id, sources, attempts, mode, producer_binding)

    def run_generation(self, prepared: PreparedGeneration, provider: GenerationProvider) -> GenerationResultV2:
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        if provider.request_attempt_bound != prepared.attempt_bound:
            raise PipelineRepositoryError("PROVIDER_ATTEMPT_BOUND_CHANGED")
        if prepared.mode == "live" and (prepared.producer_binding is None
                or (provider.provider_key, provider.configured_model) != prepared.producer_binding):
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        # A new short owned read transaction ends before external IO.
        with self.conn.transaction():
            self.runtime.refresh_lease(prepared.lease, now=datetime.now(UTC))
        return generate_candidate(prepared.request, provider=provider,
            source_authority=_PreparedSourceAuthority(prepared.sources), enabled=True)

    def settle_generation(self, prepared: PreparedGeneration, result: GenerationResultV2) -> None:
        """May reconcile a lost lease, never advance a stage. Caller commits it."""
        result = checked_model(result, GenerationResultV2)
        receipt = result.receipt
        if receipt is not None and (
            receipt.candidate_id != prepared.request.candidate_id
            or receipt.scope_hash != prepared.request.scope_hash
            or receipt.sources != prepared.sources
            or receipt.provider.request_attempt_bound != prepared.attempt_bound
            or (receipt.provider.actual_requests is not None
                and receipt.provider.actual_requests > prepared.attempt_bound)
        ):
            raise PipelineRepositoryError("GENERATION_SETTLEMENT_IDENTITY_MISMATCH")
        provider = receipt.provider if receipt is not None else None
        live_binding_valid = (prepared.mode != "live" or (prepared.producer_binding is not None
            and provider is not None
            and (provider.provider, provider.configured_model) == prepared.producer_binding
            and provider.model == prepared.producer_binding[1]))
        known = (live_binding_valid and provider is not None and provider.usage.state == "known"
                 and provider.actual_requests is not None
                 and provider.usage.input_tokens is not None and provider.usage.output_tokens is not None)
        actual = None
        if (known and provider is not None and provider.actual_requests is not None
                and provider.usage.input_tokens is not None and provider.usage.output_tokens is not None):
            actual = ResourceAmounts(requests=provider.actual_requests,
                input_tokens=provider.usage.input_tokens, output_tokens=provider.usage.output_tokens,
                candidates=int(result.state == "staged"))
        self.budget.settle(lease=prepared.lease, reservation_id=prepared.reservation_id,
            settlement_key=f"generation.{prepared.request.candidate_id.hex}",
            usage_state="known" if known else "unknown", actual=actual, cost_amount=None,
            receipt_hash=canonical_hash(provider.model_dump(mode="json")) if known and provider is not None else None)

    def commit_generation(
        self, prepared: PreparedGeneration, result: GenerationResultV2,
        *, source_authority: RagSourceAuthority | None = None,
    ) -> PipelineStageResult:
        """Settlement is separate; caller can retain cost even if this fence fails."""
        result = checked_model(result, GenerationResultV2)
        now = datetime.now(UTC)
        lease = self.runtime.refresh_lease(prepared.lease, now=now)
        if (prepared.mode == "live" and result.receipt is not None
                and (result.receipt.provider.provider, result.receipt.provider.configured_model) != prepared.producer_binding):
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        if (prepared.mode == "live" and result.receipt is not None and prepared.producer_binding is not None
                and result.receipt.provider.model != prepared.producer_binding[1]):
            self.runtime.mark_preparing(lease, reason="provider_model_binding_unverified", now=now)
            return PipelineStageResult("blocked", "provider_model_binding_unverified")
        if result.state != "staged":
            self.runtime.mark_preparing(lease, reason=result.safe_reason, now=now)
            return PipelineStageResult(result.state, result.safe_reason)
        row = self.artifacts.store_generation(lease=lease, scope_id=prepared.scope_id,
            request=prepared.request, result=result, artifact_key=f"generation.{prepared.request.candidate_id.hex}",
            now=now, mode=prepared.mode, source_authority=source_authority)
        self.runtime.checkpoint(lease, CheckpointV1(stage="generating", attempt=1, status="completed",
            receipt_hash=row["artifact_hash"], safe_reason="candidate_staged"), now=now)
        return PipelineStageResult("staged", "candidate_staged", UUID(str(row["id"])))

    def validate_generation(
        self, *, lease: JobLeaseV1, scope_id: UUID, artifact_id: UUID,
        mode: ArtifactMode, execution_port: CandidateExecutionPort | None = None,
        source_authority: RagSourceAuthority | None = None,
    ) -> CandidateValidationV2:
        now = datetime.now(UTC)
        lease = self.runtime.refresh_lease(lease, now=now)
        if self.runtime.next_stage(lease) != "validating":
            raise PipelineRepositoryError("VALIDATION_STAGE_MISMATCH")
        artifact = self.artifacts.get_generation(lease=lease, scope_id=scope_id, artifact_id=artifact_id, now=now, mode=mode)
        self._fence_source(artifact, mode, source_authority)
        # P6 owns execution IO plus its resource receipt. Do not run a supplied
        # executor while holding this transaction or invent request/token usage.
        if execution_port is not None:
            raise PipelineRepositoryError("EXECUTION_REQUIRES_P6_BUDGET_ADAPTER")
        from app.services.learning.item_bank.contracts import LearningItemSourceV1
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
        result = validate_candidate(source, execution_port=execution_port)
        row = self.artifacts.store_receipt(lease=lease, scope_id=scope_id, artifact_id=artifact_id,
            kind="validation", payload=result, artifact_key=f"validation.{artifact_id.hex}", now=now, mode=mode)
        if result.state == "machine_verified":
            self.runtime.checkpoint(lease, CheckpointV1(stage="validating", attempt=1, status="completed",
                receipt_hash=row["receipt_hash"], safe_reason="deterministic_verified"), now=datetime.now(UTC))
        else:
            self.runtime.mark_preparing(lease, reason="deterministic_evidence_pending", now=datetime.now(UTC))
        return result

    def _fence_source(self, artifact: dict[str, Any], mode: ArtifactMode,
                      authority: RagSourceAuthority | None) -> None:
        if mode == "synthetic":
            return
        if not isinstance(authority, RagSourceAuthority) or authority.connection is not self.conn:
            raise PipelineRepositoryError("SOURCE_AUTHORITY_REQUIRED")
        from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2
        request = GenerationRequestV2.model_validate_json(json.dumps(artifact["request_json"]))
        receipt = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        if len(request.materials) != len(receipt.sources):
            raise PipelineRepositoryError("SOURCE_RECEIPT_MISMATCH")
        for material, expected in zip(request.materials, receipt.sources, strict=True):
            authority.assert_current(material, expected)

    def prepare_review(
        self, *, lease: JobLeaseV1, scope_id: UUID, artifact_id: UUID,
        mode: ArtifactMode, resources: ResourceAmounts,
        solver: BlindSolverPortV2, reviewers: tuple[ReviewerPortV2, ...],
        source_authority: RagSourceAuthority | None = None,
    ) -> PreparedReview | None:
        if not (self.generation_enabled and self.settings.learning_item_v2_admission_enabled):
            return None
        now = datetime.now(UTC)
        lease = self.runtime.refresh_lease(lease, now=now)
        if self.runtime.next_stage(lease) != "reviewing":
            raise PipelineRepositoryError("REVIEW_STAGE_MISMATCH")
        artifact = self.artifacts.get_generation(lease=lease, scope_id=scope_id, artifact_id=artifact_id, now=now, mode=mode)
        self._fence_source(artifact, mode, source_authority)
        stored = self.conn.execute(
            "SELECT payload_json FROM tutor_item_supply_private_pipeline_receipts WHERE generation_artifact_id=%s AND artifact_kind='validation' AND user_id=%s AND epoch=%s ORDER BY created_at DESC LIMIT 1",
            (artifact_id, lease.owner_id, lease.owner_epoch),
        ).fetchone()
        if stored is None:
            raise PipelineRepositoryError("VALIDATION_RECEIPT_REQUIRED")
        validation = checked_model(
            CandidateValidationV2.model_validate_json(json.dumps(stored["payload_json"])), CandidateValidationV2,
        )
        if validation.state != "machine_verified":
            return None
        resources = checked_model(resources, ResourceAmounts)
        attempt_bounds = self._review_attempt_bounds(solver, reviewers)
        protocol = configured_review_protocol(reviewers)
        provider_bindings: tuple[tuple[str, str], ...] = ()
        if mode == "live":
            if (not isinstance(solver, JsonBlindSolverV2)
                    or any(not isinstance(reviewer, JsonReviewerV2) for reviewer in reviewers)):
                raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
            ports: tuple[BlindSolverPortV2 | ReviewerPortV2, ...] = (solver, *reviewers)
            if any(getattr(port, "frozen_profile", None) != lease.profile for port in ports):
                raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
            provider_bindings = tuple(self._provider_binding(
                lease, port.provider_identity.provider, port.provider_identity.model) for port in ports)
        # Reserve the actual bounded ports, not a guessed retry multiplier.
        if resources.requests < sum(attempt_bounds) or resources.input_tokens <= 0 or resources.output_tokens <= 0:
            raise PipelineRepositoryError("REVIEW_RESOURCE_PLAN_INCOMPLETE")
        from app.services.learning.item_bank.contracts import LearningItemSourceV1
        from app.services.learning.item_supply.generation_contracts import GenerationReceiptV2
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
        generation = GenerationReceiptV2.model_validate_json(json.dumps(artifact["receipt_json"]))
        runtime_key = source.blueprint.runtime_profile_id
        if runtime_key is None and source.public.kind is LearningItemKind.KNOWLEDGE_CHECK:
            runtime_key = "static-exact-v1"
        if runtime_key is None:
            raise PipelineRepositoryError("REVIEW_RUNTIME_BINDING_PENDING")
        binding = CandidateBindingV2(candidate_key=str(artifact["candidate_id"]),
            version_key=str(artifact["version_id"]), source_hash=source.source_hash,
            content_hash=source.content_hash, policy_hash=AutonomousEvidencePolicyV2().policy_hash,
            profile_hash=lease.profile.profile_hash, runtime_key=runtime_key,
            risk_tier=source.blueprint.publication_policy.risk_tier)
        check_subject(source, binding, validation)
        # Reserve blind scoring plus both ambiguity calls before any review IO,
        # not only when the final facts issuer checks the completed receipts.
        _require_explicit_sql_review_execution(source, resources, mode=mode)
        from app.services.learning.item_supply.sandbox.python_goal_scorer import (
            PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION, PYTHON_GOAL_SCORER_VERSION,
        )
        if source.public.kind is LearningItemKind.CODE and source.public.instruction_markdown == PYTHON_GOAL_INSTRUCTION:
            from app.services.learning.item_supply.contracts import SupplyScopeV1
            from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
            build_candidate_probe_plan(source)
            row = self.conn.execute(
                "SELECT snapshot_json FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s FOR SHARE",
                (scope_id, lease.owner_id, lease.owner_epoch),
            ).fetchone()
            scope_contract = None if row is None else SupplyScopeV1.model_validate_json(json.dumps(row["snapshot_json"]))
            if (scope_contract is None or scope_contract.scorer_version != PYTHON_GOAL_SCORER_VERSION
                    or scope_contract.assessment_contract_version != PYTHON_GOAL_ID
                    or validation.execution_evidence is None
                    or validation.execution_evidence.scorer_version != PYTHON_GOAL_SCORER_VERSION):
                raise PipelineRepositoryError("REVIEW_SCORING_CONTRACT_MISMATCH")
        provider_plan = None
        if mode == "live":
            provider_plan = review_resource_plan(source, binding=binding, validation_receipt=validation,
                                                solver=solver, reviewers=reviewers)
            if resources.input_tokens < provider_plan.input_tokens or resources.output_tokens < provider_plan.output_tokens:
                raise PipelineRepositoryError("REVIEW_RESOURCE_PLAN_INCOMPLETE")
        reservation = self.budget.reserve(lease=lease, reservation_key=f"review.{artifact_id.hex}", amounts=resources, now=now)
        if not reservation.allowed or reservation.reservation_id is None or reservation.reason == "REPLAY":
            return None
        return PreparedReview(lease, scope_id, artifact_id, source, validation, binding,
            f"{generation.provider.provider}.item_author", reservation.reservation_id, mode, attempt_bounds, provider_bindings,
            provider_plan, protocol)

    @staticmethod
    def _review_attempt_bounds(solver: BlindSolverPortV2,
                               reviewers: tuple[ReviewerPortV2, ...]) -> tuple[int, ...]:
        bounds = (solver.request_attempt_bound, *(reviewer.request_attempt_bound for reviewer in reviewers))
        if len(reviewers) != 6 or any(type(bound) is not int or not 1 <= bound <= 3 for bound in bounds):
            raise PipelineRepositoryError("REVIEW_RESOURCE_PLAN_INCOMPLETE")
        return bounds

    def run_review(self, prepared: PreparedReview, *, solver: BlindSolverPortV2,
                   scorer: BlindAnswerScorerPortV2, reviewers: tuple[ReviewerPortV2, ...]) -> CompletedReview:
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        if self._review_attempt_bounds(solver, reviewers) != prepared.attempt_bounds:
            raise PipelineRepositoryError("REVIEW_ATTEMPT_BOUND_CHANGED")
        if configured_review_protocol(reviewers) != prepared.review_protocol:
            raise PipelineRepositoryError("REVIEW_PROTOCOL_CHANGED")
        if prepared.reservation_id in self._review_started:
            raise PipelineRepositoryError("REVIEW_ALREADY_DISPATCHED")
        if prepared.mode == "live":
            ports: tuple[BlindSolverPortV2 | ReviewerPortV2, ...] = (solver, *reviewers)
            if (not prepared.provider_bindings
                    or tuple((port.provider_identity.provider, port.provider_identity.model) for port in ports)
                    != prepared.provider_bindings
                    or any(getattr(port, "frozen_profile", None) != prepared.lease.profile for port in ports)):
                raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
            plan = review_resource_plan(prepared.source, binding=prepared.binding,
                validation_receipt=prepared.validation, solver=solver, reviewers=reviewers)
            if plan != prepared.provider_resource_plan:
                raise PipelineRepositoryError("REVIEW_RESOURCE_PLAN_CHANGED")
        with self.conn.transaction():
            self.runtime.refresh_lease(prepared.lease, now=datetime.now(UTC))
        validation = checked_validation_receipt(prepared.validation)
        check_subject(prepared.source, prepared.binding, validation)
        self._review_started.add(prepared.reservation_id)
        blind = blind_solve_candidate(prepared.source, binding=prepared.binding,
            author_identity=prepared.author_identity, solver=solver, scorer=scorer)
        try:
            bundle = review_candidate(prepared.source, binding=prepared.binding,
                validation_receipt=validation, author_identity=prepared.author_identity,
                blind_solve_receipt=blind, reviewers=reviewers)
        except AutonomousReviewError as exc:
            self.partial_review_reports[prepared.reservation_id] = exc.partial_reports
            raise
        return CompletedReview(bundle)

    def settle_review(self, prepared: PreparedReview, completed: CompletedReview | None) -> None:
        # Actual per-attempt counts are not attested by the review ports. The
        # original reservation remains conservative rather than guessed free.
        self.budget.settle(lease=prepared.lease, reservation_id=prepared.reservation_id,
            settlement_key=f"review.{prepared.artifact_id.hex}", usage_state="unknown",
            actual=None, cost_amount=None, receipt_hash=None)

    def commit_review(self, prepared: PreparedReview, completed: CompletedReview,
                      *, source_authority: RagSourceAuthority | None = None,
                      evidence: AdmissionEvidenceV2 | None = None,
                      facts_owner: AdmissionFactsOwner | None = None,
                      facts_receipt: IssuedAdmissionFactsV1 | None = None,
                      private_publisher: LearningItemPublicationService | None = None) -> AdmissionEvaluationV2:
        now = datetime.now(UTC)
        lease = self.runtime.refresh_lease(prepared.lease, now=now)
        artifact = self.artifacts.get_generation(lease=lease, scope_id=prepared.scope_id,
            artifact_id=prepared.artifact_id, now=now, mode=prepared.mode)
        self._fence_source(artifact, prepared.mode, source_authority)
        bundle = checked_model(completed.bundle, ReviewBundleV2)
        if any(report_protocol(report) != prepared.review_protocol for report in bundle.reports):
            raise PipelineRepositoryError("REVIEW_PROTOCOL_CHANGED")
        if prepared.mode == "live":
            runs = (bundle.blind_solve.run, *(report.run for report in bundle.reports))
            if (not prepared.provider_bindings
                    or tuple((run.provider_identity.provider, run.provider_identity.model) for run in runs)
                    != prepared.provider_bindings):
                raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        if bundle.binding != prepared.binding:
            raise PipelineRepositoryError("REVIEW_BUNDLE_STALE")
        # These facts are internal trusted-resolver inputs, never public DTOs.
        facts_gap: str | None = None
        if prepared.mode == "live":
            from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
            from app.services.learning.item_supply.task_ambiguity_owner import AdmissionFactsPending

            if facts_owner is None or facts_receipt is None:
                facts_gap = "admission_facts_owner_missing"
                # A caller DTO/hash is not a production facts issuer.
                facts = AdmissionEvidenceV2(binding=prepared.binding,
                    validation_receipt_hash=receipt_digest(prepared.validation))
            elif type(facts_owner) is not AdmissionFactsOwner or facts_owner.conn is not self.conn:
                raise PipelineRepositoryError("ADMISSION_FACTS_OWNER_REQUIRED")
            else:
                try:
                    facts = facts_owner.verify(facts_receipt, prepared, lease=lease, completed_review=completed)
                except AdmissionFactsPending as exc:
                    facts_gap = exc.reason
                    facts = AdmissionEvidenceV2(binding=prepared.binding,
                        validation_receipt_hash=receipt_digest(prepared.validation))
            # Recheck after facts-owner lock waits, not just at prepare.
            self._fence_source(artifact, prepared.mode, source_authority)
        else:
            facts = checked_model(evidence, AdmissionEvidenceV2) if evidence is not None else AdmissionEvidenceV2(
                binding=prepared.binding, validation_receipt_hash=receipt_digest(prepared.validation))
        if prepared.mode == "synthetic":
            facts = facts.model_copy(update={"source_current": False})
        evaluation = evaluate_admission_v2(prepared.source, binding=prepared.binding,
            policy=AutonomousEvidencePolicyV2(), validation_receipt=prepared.validation,
            author_identity=prepared.author_identity, bundle=bundle, evidence=facts, enabled=True)
        if facts_gap is not None:
            evaluation = evaluation.model_copy(update={
                "safe_reasons": tuple(dict.fromkeys((facts_gap, *evaluation.safe_reasons))),
            })
        receipts: tuple[tuple[ArtifactKind, PipelineReceipt], ...] = (
            ("blind_solve", bundle.blind_solve), ("review_bundle", bundle), ("admission_evaluation", evaluation),
        )
        evaluation_receipt_id: UUID | None = None
        for kind, payload in receipts:
            stored = self.artifacts.store_receipt(lease=lease, scope_id=prepared.scope_id,
                artifact_id=prepared.artifact_id, kind=kind, payload=payload,
                artifact_key=f"{kind}.{bundle.bundle_id.hex}", now=now, mode=prepared.mode)
            if kind == "admission_evaluation" and private_publisher is not None:
                evaluation_receipt_id = UUID(str(stored["id"]))
        if private_publisher is not None and prepared.mode == "live" and evaluation.disposition == "eligible_internal":
            from app.services.learning.item_bank.publication import LearningItemPublicationService

            if (type(private_publisher) is not LearningItemPublicationService
                    or private_publisher.conn is not self.conn or facts_owner is None
                    or facts_receipt is None or evaluation_receipt_id is None):
                raise PipelineRepositoryError("PRIVATE_PUBLICATION_OWNER_REQUIRED")
            # The genuine issuer still holds its seals and this exact lease state.
            # Checkpoint below invalidates it; never publish by replaying old facts.
            private_publisher.publish_internal_private(prepared, completed, lease=lease,
                facts_owner=facts_owner, facts_receipt=facts_receipt,
                evaluation=evaluation, evaluation_receipt_id=evaluation_receipt_id)
        self.runtime.checkpoint(lease, CheckpointV1(stage="reviewing", attempt=1, status="completed",
            receipt_hash=bundle.bundle_hash, safe_reason="review_evidence_recorded"), now=datetime.now(UTC))
        # No P7 campaign/pack or whole-job checkpoint is manufactured here.
        return evaluation
