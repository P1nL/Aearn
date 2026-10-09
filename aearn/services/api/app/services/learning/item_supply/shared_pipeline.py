"""Default-off native public generation: prepare, idle IO, settle, fenced staging.

There is no reviewer, publisher, course mapping or coverage authority here.
"""
from __future__ import annotations

from app.services.learning.item_supply.diagnostic_policy import EvidencePolicy
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
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
    PreparedSharedGeneration, SharedPipelineStageResult, native_request,
)
from app.services.learning.item_supply.shared_pipeline_repository import (
    SharedPipelineArtifactRepository, generation_resources,
)
from app.services.learning.item_supply.storage_contracts import checked_model


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
                 trusted_model_bindings: Mapping[tuple[str, str], str] | None = None) -> None:
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

    @property
    def generation_enabled(self) -> bool:
        return (self.enabled and self.settings.learning_item_supply_enabled
                and self.settings.learning_item_generation_enabled and self.settings.learning_item_network_enabled)

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
                           evidence_policy: EvidencePolicy | None = None) -> PreparedSharedGeneration | None:
        if not self.generation_enabled:
            return None
        now = now or datetime.now(UTC)
        request, _ = native_request(request)
        binding = self._binding(lease, request, provider, now=now)
        if self.runtime.next_stage(lease) != "generating":
            raise PipelineRepositoryError("GENERATION_STAGE_MISMATCH")
        self.artifacts.require_source(source_authority)
        sources = tuple(checked_model(source_authority.authorize(m), SourceReceiptV2) for m in request.materials)
        if any(s.mode != "current_authority" for s in sources):
            raise PipelineRepositoryError("SHARED_SOURCE_AUTHORITY_REQUIRED")
        policy = self.artifacts.freeze_generation_policy(lease, request,
            policy=AutonomousEvidencePolicyV2() if evidence_policy is None else evidence_policy, now=now)
        attempts = provider.request_attempt_bound
        reservation = self.budget.reserve(lease=lease, reservation_key=f"gen.{request.candidate_id.hex}",
                                           now=now, amounts=generation_resources(request, attempts))
        # A replayed reservation is NOT new provider permission, including after
        # restart/unknown. A new attempt needs a fresh funded candidate reservation.
        if not reservation.allowed or reservation.reservation_id is None or reservation.reason == "REPLAY":
            return None
        prepared = PreparedSharedGeneration(lease, request, reservation.reservation_id, sources, attempts, binding, policy.policy_hash)
        self._prepared[prepared.reservation_id] = (prepared, self._seal(prepared), source_authority, provider)
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
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("PROVIDER_IO_REQUIRES_IDLE_TRANSACTION")
        self._started.add(prepared.reservation_id)
        result = generate_candidate(prepared.request, provider=provider,
                                    source_authority=_PreparedSources(prepared.sources), enabled=True)
        self._results[prepared.reservation_id] = checked_model(result, GenerationResultV2)
        return result

    def _result(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> GenerationResultV2:
        self._issued(prepared)
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

    def settle_generation(self, prepared: PreparedSharedGeneration, result: GenerationResultV2) -> None:
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
                candidates=int(result.state == "staged"))
        self.budget.settle(lease=prepared.lease, reservation_id=prepared.reservation_id,
            settlement_key=f"generation.{prepared.request.candidate_id.hex}",
            usage_state="known" if actual is not None else "unknown", actual=actual, cost_amount=None,
            receipt_hash=canonical_hash(provider.model_dump(mode="json")) if actual is not None and provider is not None else None)

    def commit_generation(self, prepared: PreparedSharedGeneration, result: GenerationResultV2, *,
                          source_authority: RagSourceAuthority) -> SharedPipelineStageResult:
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
        row = self.artifacts.store_generation(lease=lease, request=prepared.request, result=result,
            artifact_key=f"generation.{prepared.request.candidate_id.hex}", now=now, source_authority=source_authority)
        control = self.runtime._control(lease, now=now)
        self.runtime.checkpoint(lease, CheckpointV1(stage="generating", attempt=control["attempt_count"],
            status="completed", receipt_hash=row["artifact_hash"], safe_reason="candidate_staged"), now=now)
        return SharedPipelineStageResult("staged", "candidate_staged", UUID(str(row["id"])))
