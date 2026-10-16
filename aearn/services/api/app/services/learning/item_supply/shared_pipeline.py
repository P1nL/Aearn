"""Default-off native public generation: prepare, idle IO, settle, fenced staging.

There is no reviewer, publisher, course mapping or coverage authority here.
"""
from __future__ import annotations

from app.services.learning.item_supply.diagnostic_policy import EvidencePolicy
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.controlled_counterexample import ControlledCounterexampleOwner
from app.services.learning.item_supply.controlled_counterexample_contracts import ControlledCounterexampleContext, PreparedControlledCounterexample
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import (
    GenerationRequestV2, GenerationResultV2, PublicMaterialV2, SourceReceiptV2,
)
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.provider_adapter import OpenAICompatibleGenerationProvider
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.shared_pipeline_contracts import (
    GenerationSettlementOutcome, PreparedSharedGeneration, SharedPipelineStageResult, native_request,
)
from app.services.learning.item_supply.shared_pipeline_repository import (
    SharedPipelineArtifactRepository, generation_resources,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.native_revision_contracts import (
    NativeRevisionAuthorInputBindingV1, NativeRevisionAuthorTrace,
)

if TYPE_CHECKING:
    from app.services.learning.item_supply.shared_generation_durability import IssuedRevisionGenerationPersistence
    from app.services.learning.item_supply.controlled_case_execution import ControlledCaseExecutionOwner, IssuedControlledCaseExecution
    from app.services.learning.item_supply.native_revision import NativeRevisionOwner, PreparedNativeRevision


class _PreparedSources:
    """IO-only snapshot. The original concrete owner is rechecked before/after IO."""
    def __init__(self, sources: tuple[SourceReceiptV2, ...]) -> None:
        self.sources = {s.material_digest: s for s in sources}

    def authorize(self, material: PublicMaterialV2) -> SourceReceiptV2:
        result = self.sources.get(material_digest(material))
        if result is None:
            raise PipelineRepositoryError("PREPARED_SOURCE_MISMATCH")
        return result

    def assert_current(self, material: PublicMaterialV2, expected: SourceReceiptV2) -> SourceReceiptV2:
        result = self.authorize(material)
        if result != checked_model(expected, SourceReceiptV2):
            raise PipelineRepositoryError("PREPARED_SOURCE_MISMATCH")
        return result


class SharedGenerationPipeline:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, enabled: bool = False,
                 trusted_model_bindings: Mapping[tuple[str, str], str] | None = None,
                 controlled_counterexample_enabled: bool = False) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        self._models = dict(trusted_model_bindings or {})
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.budget = ItemSupplyBudgetRepository(conn)
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)
        # Prepared capabilities are local to this concrete producer. No serialized
        # seal hydration; a restarted worker cannot replay a spent HTTP allowance.
        self._prepared: dict[UUID, tuple[PreparedSharedGeneration, str, RagSourceAuthority,
                                         OpenAICompatibleGenerationProvider]] = {}
        self._started: set[UUID] = set()
        self._results: dict[UUID, GenerationResultV2] = {}
        self._revision: dict[UUID, tuple[NativeRevisionOwner, PreparedNativeRevision, NativeRevisionAuthorTrace]] = {}
        self._revision_inputs: dict[UUID, tuple[NativeRevisionAuthorInputBindingV1, str]] = {}
        self._observed_revision_outputs: dict[UUID, tuple[GenerationResultV2, str]] = {}
        from app.services.learning.item_supply.shared_generation_durability import RevisionGenerationDurability
        self.persistence = RevisionGenerationDurability(self)
        self.counterexamples = ControlledCounterexampleOwner(self,enabled=controlled_counterexample_enabled)

    def prepare_controlled_counterexample(self, *, lease: JobLeaseV1, request: GenerationRequestV2,
            context: ControlledCounterexampleContext, provider: OpenAICompatibleGenerationProvider,
            source_authority: RagSourceAuthority, evidence_policy: EvidencePolicy,
            execution_owner: ControlledCaseExecutionOwner | None = None,
            execution: IssuedControlledCaseExecution | None = None) -> PreparedControlledCounterexample:
        """Caller commits this immutable marker BEFORE the separate funded author prepare."""
        return self.counterexamples.prepare(lease=lease,request=request,context=context,provider=provider,
            source_authority=source_authority,evidence_policy=evidence_policy,
            execution_owner=execution_owner,execution=execution)

    def persist_controlled_counterexample_author(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> UUID:
        """Separately committed DATA receipt after ORIGINAL settlement, before writer commit."""
        return self.counterexamples.persist_author_trace(prepared,result)

    @property
    def generation_enabled(self) -> bool:
        return (self.enabled and self.settings.learning_item_supply_enabled
                and self.settings.learning_item_generation_enabled and self.settings.learning_item_network_enabled)

    def prepare_revision_persistence(self, preparation_id: UUID, *, source_authority: RagSourceAuthority) -> IssuedRevisionGenerationPersistence:
        """Fresh persistence-only capability from committed original output; no IO permission."""
        return self.persistence.prepare(preparation_id, source_authority=source_authority)

    def commit_revision_persistence(self, cap: IssuedRevisionGenerationPersistence) -> SharedPipelineStageResult:
        return self.persistence.commit(cap)

    def persist_revision_lineage(self, cap: IssuedRevisionGenerationPersistence) -> UUID:
        """Separate TOP transaction AFTER artifact/checkpoint commit."""
        return self.persistence.lineage(cap)

    @staticmethod
    def _seal(prepared: PreparedSharedGeneration) -> str:
        return canonical_hash({"lease": prepared.lease.model_dump(mode="json"),
            "request": prepared.request.model_dump(mode="json"), "reservation_id": str(prepared.reservation_id),
            "sources": [s.model_dump(mode="json") for s in prepared.sources],
            "attempt_bound": prepared.attempt_bound, "producer_binding": list(prepared.producer_binding),
            "evidence_policy_hash": prepared.evidence_policy_hash})

    def _issued(self, prepared: PreparedSharedGeneration) -> tuple[RagSourceAuthority, OpenAICompatibleGenerationProvider]:
        entry = self._prepared.get(prepared.reservation_id)
        if entry is None or entry[0] is not prepared or entry[1] != self._seal(prepared):
            raise PipelineRepositoryError("SHARED_PREPARED_UNAVAILABLE")
        if prepared.reservation_id in self.counterexamples._generations:
            self.counterexamples.original_generation(prepared)
        revision = self._revision.get(prepared.reservation_id)
        if revision is not None:
            revision[0]._issued(revision[1])
            if revision[2].context != revision[1].context:
                raise PipelineRepositoryError("REVISION_ORIGINAL_CONTEXT_CHANGED")
        return entry[2], entry[3]

    def _binding(self, lease: JobLeaseV1, request: GenerationRequestV2,
                 provider: OpenAICompatibleGenerationProvider, *, now: datetime) -> tuple[str, str]:
        if type(provider) is not OpenAICompatibleGenerationProvider:
            raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
        meta = self.artifacts.request_context(lease, request, now=now)
        key = meta["key"]
        configured = self._models.get((key.provider, key.model_version))
        if configured is None:
            raise PipelineRepositoryError("PROVIDER_PROFILE_PLAN_PENDING")
        if (provider.provider_key != meta["provider_key"] or provider.configured_model != configured):
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        return provider.provider_key, provider.configured_model

    def prepare_generation(self, *, lease: JobLeaseV1, request: GenerationRequestV2,
                           provider: OpenAICompatibleGenerationProvider, source_authority: RagSourceAuthority,
                           now: datetime | None = None,
                           evidence_policy: EvidencePolicy | None = None,
                           revision_owner: NativeRevisionOwner | None = None,
                           revision_preparation: PreparedNativeRevision | None = None,
                           controlled_context: PreparedControlledCounterexample | None = None) -> PreparedSharedGeneration | None:
        if not self.generation_enabled:
            return None
        now = now or datetime.now(UTC)
        request, _ = native_request(request)
        revision = self.artifacts.revision_preparation(lease,request)
        controlled = self.artifacts.controlled_preparation(lease,request)
        if controlled is not None or controlled_context is not None:
            if controlled_context is None or revision is not None or revision_owner is not None:
                raise PipelineRepositoryError("CONTROLLED_EXPLICIT_ORIGINAL_CONTEXT_REQUIRED")
            authority,original_provider = self.counterexamples.issued(controlled_context)
            self.counterexamples.fence(controlled_context)
            if (controlled_context.lease!=lease or controlled_context.request!=request
                    or authority is not source_authority or original_provider is not provider):
                raise PipelineRepositoryError("CONTROLLED_ORIGINAL_AUTHOR_BINDING_REQUIRED")
        context = None
        if revision is not None or revision_owner is not None or revision_preparation is not None:
            from app.services.learning.item_supply.native_revision import NativeRevisionOwner

            if (type(revision_owner) is not NativeRevisionOwner or revision_preparation is None
                    or revision_owner.generation is not self or revision_owner.conn is not self.conn or revision is None):
                raise PipelineRepositoryError("REVISION_EXPLICIT_ORIGINAL_CONTEXT_REQUIRED")
            context = revision_owner.generation_context(revision_preparation, lease=lease, request=request, committed=False)
        binding = self._binding(lease, request, provider, now=now)
        if self.runtime.next_stage(lease) != "generating":
            raise PipelineRepositoryError("GENERATION_STAGE_MISMATCH")
        self.artifacts.require_source(source_authority)
        if controlled_context is not None:
            # Keep the committed marker's authentic receipt view. Current RAG
            # reauthorization refreshes checked_at_iso, so comparing a second
            # freshly minted timestamp would reject every legal preparation.
            sources = controlled_context.sources
            for material,expected in zip(request.materials,sources,strict=True):
                source_authority.assert_current(material,expected)
        else:
            sources = tuple(checked_model(source_authority.authorize(m), SourceReceiptV2) for m in request.materials)
        if any(s.mode != "current_authority" for s in sources):
            raise PipelineRepositoryError("SHARED_SOURCE_AUTHORITY_REQUIRED")
        policy = self.artifacts.freeze_generation_policy(lease, request,
            policy=AutonomousEvidencePolicyV2() if evidence_policy is None else evidence_policy, now=now)
        attempts = provider.request_attempt_bound
        if context is not None and (attempts != 1 or provider._settings != self.settings):
            raise PipelineRepositoryError("REVISION_ONE_FROZEN_PRODUCTION_AUTHOR_REQUIRED")
        reservation = self.budget.reserve(lease=lease, reservation_key=f"gen.{request.candidate_id.hex}",
                                           now=now, amounts=generation_resources(request, attempts, revision=context is not None))
        # A replayed reservation is NOT new provider permission, including after
        # restart/unknown. A new attempt needs a fresh funded candidate reservation.
        if not reservation.allowed or reservation.reservation_id is None or reservation.reason == "REPLAY":
            return None
        prepared = PreparedSharedGeneration(lease, request, reservation.reservation_id, sources, attempts, binding, policy.policy_hash)
        self._prepared[prepared.reservation_id] = (prepared, self._seal(prepared), source_authority, provider)
        if controlled_context is not None:
            self.counterexamples.attach(prepared,controlled_context)
        if context is not None:
            assert revision_owner is not None and revision_preparation is not None
            self._revision[prepared.reservation_id] = (revision_owner,revision_preparation,NativeRevisionAuthorTrace(context))
        return prepared

    def run_generation(self, prepared: PreparedSharedGeneration,
                       provider: OpenAICompatibleGenerationProvider) -> GenerationResultV2:
        if not self.generation_enabled:
            raise PipelineRepositoryError("SHARED_PIPELINE_DISABLED")
        authority, original_provider = self._issued(prepared)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        if prepared.reservation_id in self._started:
            raise PipelineRepositoryError("SHARED_PROVIDER_ALREADY_DISPATCHED")
        if provider is not original_provider or provider.request_attempt_bound != prepared.attempt_bound:
            raise PipelineRepositoryError("PROVIDER_ATTEMPT_BOUND_CHANGED")
        revision = self._revision.get(prepared.reservation_id)
        context = None
        deadline = None
        controlled = None
        if prepared.reservation_id in self.counterexamples._generations:
            controlled = self.counterexamples.original_generation(prepared)
        # This short fence must finish before any external IO. It rechecks the
        # actual persisted preparation, not just the in-memory DTO.
        with self.conn.transaction():
            now = datetime.now(UTC)
            if self._binding(prepared.lease, prepared.request, provider, now=now) != prepared.producer_binding:
                raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
            if self.artifacts.generation_policy(prepared.lease, prepared.request, now=now).policy_hash != prepared.evidence_policy_hash:
                raise PipelineRepositoryError("SHARED_GENERATION_POLICY_CHANGED")
            if self.runtime.next_stage(prepared.lease) != "generating":
                raise PipelineRepositoryError("GENERATION_STAGE_MISMATCH")
            if self.artifacts.reservation(prepared.lease, prepared.request, attempts=prepared.attempt_bound) != prepared.reservation_id:
                raise PipelineRepositoryError("SHARED_GENERATION_RESERVATION_MISMATCH")
            for material, expected in zip(prepared.request.materials, prepared.sources, strict=True):
                authority.assert_current(material, expected)
            self.runtime._control(prepared.lease, now=now)
            if controlled is not None:
                self.counterexamples.fence(controlled[0])
            elif self.artifacts.controlled_preparation(prepared.lease,prepared.request) is not None:
                raise PipelineRepositoryError("CONTROLLED_EXPLICIT_ORIGINAL_CONTEXT_REQUIRED")
            if revision is not None:
                context = revision[0].generation_context(revision[1], lease=prepared.lease, request=prepared.request, committed=True)
                deadline = revision[1].deadline_at
            elif self.artifacts.revision_preparation(prepared.lease,prepared.request) is not None:
                raise PipelineRepositoryError("REVISION_EXPLICIT_ORIGINAL_CONTEXT_REQUIRED")
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        self._started.add(prepared.reservation_id)
        if controlled is not None:
            result = generate_candidate(prepared.request,provider=provider,source_authority=_PreparedSources(prepared.sources),
                enabled=True,controlled_context=controlled[0].context,controlled_trace=controlled[1],deadline_at=controlled[0].deadline_at)
            try:
                with self.conn.transaction():
                    self.counterexamples.fence(controlled[0])
            except Exception:
                result = GenerationResultV2(state="failed",receipt=result.receipt,safe_reason="source_unavailable")
        elif revision is None:
            result = generate_candidate(prepared.request, provider=provider,
                                        source_authority=_PreparedSources(prepared.sources), enabled=True)
        else:
            result = generate_candidate(prepared.request, provider=provider,
                source_authority=_PreparedSources(prepared.sources), enabled=True,
                supplemental_context=context, revision_trace=revision[2], deadline_at=deadline)
            if result.state == "staged":
                observed_result = checked_model(result, GenerationResultV2)
                self._observed_revision_outputs[prepared.reservation_id] = (
                    observed_result, canonical_hash(observed_result.model_dump(mode="json")))
            if revision[2].binding is not None:
                observed = checked_model(revision[2].binding, NativeRevisionAuthorInputBindingV1)
                self._revision_inputs[prepared.reservation_id] = (observed, canonical_hash(observed.model_dump(mode="json")))
            try:
                with self.conn.transaction():
                    revision[0].generation_context(revision[1],lease=prepared.lease,request=prepared.request,committed=True)
            except Exception:
                # Preserve the paid receipt using the EXISTING closed DTO code.
                result = GenerationResultV2(state="failed",receipt=result.receipt,safe_reason="source_unavailable")
        self._results[prepared.reservation_id] = checked_model(result, GenerationResultV2)
        if controlled is not None:
            self.counterexamples.observe_result(prepared,result)
        return result

    def _result(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> GenerationResultV2:
        self._issued(prepared)
        if prepared.reservation_id in self.counterexamples._generations:
            self.counterexamples.verify_result(prepared,result)
        result = checked_model(result, GenerationResultV2)
        if self._results.get(prepared.reservation_id) != result:
            raise PipelineRepositoryError("SHARED_RESULT_UNAVAILABLE")
        receipt = result.receipt
        if receipt is not None and (receipt.candidate_id != prepared.request.candidate_id
                or receipt.scope_hash != prepared.request.scope_hash or receipt.sources != prepared.sources
                or receipt.provider.request_attempt_bound != prepared.attempt_bound
                or (receipt.provider.actual_requests is not None and receipt.provider.actual_requests > prepared.attempt_bound)):
            raise PipelineRepositoryError("GENERATION_SETTLEMENT_IDENTITY_MISMATCH")
        return result

    def settle_generation(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> GenerationSettlementOutcome:
        """Caller commits even if the later lease/source fence fails; unknown stays reserved."""
        self.artifacts.require_owner()
        result = self._result(prepared, result)
        provider = result.receipt.provider if result.receipt is not None else None
        actual = None
        if (provider is not None and provider.mode == "provider"
                and (provider.provider, provider.configured_model) == prepared.producer_binding
                and provider.model == prepared.producer_binding[1]
                and provider.usage.state == "known" and provider.actual_requests is not None
                and provider.usage.input_tokens is not None and provider.usage.output_tokens is not None):
            actual = ResourceAmounts(requests=provider.actual_requests,
                input_tokens=provider.usage.input_tokens, output_tokens=provider.usage.output_tokens,
                candidates=1 if prepared.reservation_id in self._revision else int(result.state == "staged"),
                revision_rounds=1 if prepared.reservation_id in self._revision else 0)
        self.budget.settle(lease=prepared.lease, reservation_id=prepared.reservation_id,
            settlement_key=f"generation.{prepared.request.candidate_id.hex}",
            usage_state="known" if actual is not None else "unknown", actual=actual, cost_amount=None,
            receipt_hash=canonical_hash(provider.model_dump(mode="json")) if actual is not None and provider is not None else None)
        return self.persistence.capture(prepared, result)

    def commit_generation(self, prepared: PreparedSharedGeneration, result: GenerationResultV2, *,
                          source_authority: RagSourceAuthority) -> SharedPipelineStageResult:
        original_result = result
        result = self._result(prepared, result)
        authority, provider = self._issued(prepared)
        if source_authority is not authority:
            raise PipelineRepositoryError("SHARED_SOURCE_AUTHORITY_REQUIRED")
        now = datetime.now(UTC)
        lease = prepared.lease
        if self._binding(lease, prepared.request, provider, now=now) != prepared.producer_binding:
            raise PipelineRepositoryError("PROVIDER_BUDGET_BINDING_MISMATCH")
        self.artifacts.reservation(lease, prepared.request, attempts=prepared.attempt_bound, settled=True)
        if result.receipt is not None and (
                (result.receipt.provider.provider, result.receipt.provider.configured_model) != prepared.producer_binding
                or result.receipt.provider.model != prepared.producer_binding[1]):
            self.runtime.mark_preparing(lease, reason="provider_model_binding_unverified", now=now)
            return SharedPipelineStageResult("blocked", "provider_model_binding_unverified")
        if result.state != "staged":
            self.runtime.mark_preparing(lease, reason=result.safe_reason, now=now)
            return SharedPipelineStageResult(result.state, result.safe_reason)
        revision = self._revision.get(prepared.reservation_id)
        if prepared.reservation_id in self.counterexamples._generations:
            self.counterexamples.writer_binding(prepared,original_result)
            row = self.artifacts.store_generation(lease=lease,request=prepared.request,result=original_result,
                artifact_key=f"generation.{prepared.request.candidate_id.hex}",now=now,source_authority=source_authority,
                controlled_owner=self.counterexamples,controlled_generation=prepared)
        elif revision is None:
            row = self.artifacts.store_generation(lease=lease, request=prepared.request, result=result,
                artifact_key=f"generation.{prepared.request.candidate_id.hex}", now=now, source_authority=source_authority)
        else:
            revision[0].generation_context(revision[1],lease=lease,request=prepared.request,committed=True)
            if self.persistence.required(prepared):
                self.persistence.committed_output(revision[1].preparation_id)
            row = self.artifacts.store_generation(lease=lease,request=prepared.request,result=original_result,
                artifact_key=f"generation.{prepared.request.candidate_id.hex}",now=now,source_authority=source_authority,
                revision_owner=revision[0],revision_preparation=revision[1],revision_generation=prepared)
        control = self.runtime._control(lease, now=now)
        self.runtime.checkpoint(lease, CheckpointV1(stage="generating", attempt=control["attempt_count"],
            status="completed", receipt_hash=row["artifact_hash"], safe_reason="candidate_staged"), now=now)
        return SharedPipelineStageResult("staged", "candidate_staged", UUID(str(row["id"])))

    def revision_author_binding(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> NativeRevisionAuthorInputBindingV1:
        """Observed producer DATA, not caller-supplied envelope/receipt authority."""
        self._result(prepared,result)
        entry = self._revision_inputs.get(prepared.reservation_id)
        revision = self._revision.get(prepared.reservation_id)
        if entry is None or revision is None or entry[1] != canonical_hash(entry[0].model_dump(mode="json")):
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_ENVELOPE_REQUIRED")
        binding = checked_model(entry[0],NativeRevisionAuthorInputBindingV1)
        if (binding.request_hash != canonical_hash(prepared.request.model_dump(mode="json"))
                or binding.context_hash != revision[2].context.context_hash
                or binding.input_bytes > prepared.request.limits.max_input_bytes):
            raise PipelineRepositoryError("REVISION_ORIGINAL_AUTHOR_ENVELOPE_CHANGED")
        return binding
