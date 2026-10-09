"""Private P6 prepare -> committed IO -> settlement -> fenced 460 validation.

No method commits caller work. Only run_execution owns a short read transaction;
it ends before the runner is invoked. Settlement survives a lost execution lease.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.core.config import Settings
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.pipeline import ItemSupplyPipeline
from app.services.learning.item_supply.pipeline_repository import ArtifactMode, PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.sandbox.contracts import RunV2
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.repository import (
    ExecutionIntentV1, SandboxArtifactRepository, SandboxRepository, execution_resources,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import (
    CandidateExecutionEvidenceV2, CandidateValidationV2, validate_candidate,
)


@dataclass(frozen=True)
class PreparedSandboxExecution:
    lease: JobLeaseV1
    intent: ExecutionIntentV1
    reservation_id: UUID
    source: LearningItemSourceV1
    mode: ArtifactMode
    actor_id: UUID
    scope_hash: str


@dataclass(frozen=True)
class SandboxExecutionResult:
    validation: CandidateValidationV2 | None
    actual: ResourceAmounts | None
    executor_receipts: tuple[dict[str, object], ...]
    run: RunV2 | None
    safe_reason: str


class _ReceiptOnlyPort:
    """Re-run deterministic checks without performing container IO in final tx."""
    def __init__(self, port: SandboxCandidateExecutionPort,
                 evidence: CandidateExecutionEvidenceV2) -> None:
        self.port, self.evidence = port, evidence

    def validate(self, source: LearningItemSourceV1) -> CandidateExecutionEvidenceV2:
        if source.source_hash != self.evidence.source_hash:
            raise PipelineRepositoryError("EXECUTION_SOURCE_MISMATCH")
        return self.evidence

    def verify(self, evidence: CandidateExecutionEvidenceV2, source: LearningItemSourceV1) -> bool:
        return self.port.verify(evidence, source)


class SandboxExecutionPipeline:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings) -> None:
        self.conn, self.settings = conn, settings
        self.pipeline = ItemSupplyPipeline(conn, settings)
        self.artifacts = SandboxArtifactRepository(conn)

    def prepare_execution(
        self, *, lease: JobLeaseV1, scope_id: UUID, artifact_id: UUID,
        mode: ArtifactMode, execution_port: SandboxCandidateExecutionPort,
        actor_id: UUID, source_authority: RagSourceAuthority | None = None,
    ) -> PreparedSandboxExecution | None:
        if not self.settings.learning_item_supply_enabled:
            return None
        if not isinstance(execution_port, SandboxCandidateExecutionPort):
            raise PipelineRepositoryError("TRUSTED_EXECUTION_PORT_REQUIRED")
        if not isinstance(actor_id, UUID) or actor_id == lease.owner_id:
            raise PipelineRepositoryError("ISOLATED_EXECUTION_ACTOR_REQUIRED")
        now = datetime.now(UTC)
        lease = self.pipeline.runtime.refresh_lease(lease, now=now)
        if self.pipeline.runtime.next_stage(lease) != "validating":
            raise PipelineRepositoryError("VALIDATION_STAGE_MISMATCH")
        artifact = self.artifacts.get_generation(lease=lease, scope_id=scope_id,
            artifact_id=artifact_id, now=now, mode=mode)
        self.pipeline._fence_source(artifact, mode, source_authority)
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
        resources = execution_resources(execution_port.resource_plan(source))
        repository = SandboxRepository(self.conn)
        intent = repository.create_intent(lease=lease, scope_id=scope_id,
            artifact=artifact, reservation_key=f"execution.{artifact_id.hex}", resources=resources, now=now)
        reserved = self.pipeline.budget.reserve_execution(lease=lease, intent_id=intent.id, now=now)
        if not reserved.allowed or reserved.reservation_id is None:
            return None
        return PreparedSandboxExecution(lease, intent, reserved.reservation_id,
                                        source, mode, actor_id, str(artifact["request_json"]["scope_hash"]))

    def run_execution(self, prepared: PreparedSandboxExecution,
                      execution_port: SandboxCandidateExecutionPort) -> SandboxExecutionResult:
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")
        if not isinstance(execution_port, SandboxCandidateExecutionPort):
            raise PipelineRepositoryError("TRUSTED_EXECUTION_PORT_REQUIRED")
        source = checked_model(prepared.source, LearningItemSourceV1)
        if (source.source_hash != prepared.intent.source_hash or source.content_hash != prepared.intent.content_hash
                or execution_resources(execution_port.resource_plan(source)) != prepared.intent.resources):
            raise PipelineRepositoryError("EXECUTION_PREPARED_BINDING_MISMATCH")
        # Verify that prepare was COMMITTED (not merely rolled back to IDLE),
        # and retain no database transaction across any executor operation.
        with self.conn.transaction():
            repository = SandboxRepository(self.conn)
            intent = repository.get_intent(lease=prepared.lease,
                intent_id=prepared.intent.id, now=datetime.now(UTC))
            if intent != prepared.intent:
                raise PipelineRepositoryError("EXECUTION_PREPARED_BINDING_MISMATCH")
            row = self.conn.execute(
                "SELECT id FROM tutor_item_supply_private_reservations WHERE id=%s AND job_id=%s AND user_id=%s AND epoch=%s AND lease_generation=%s AND reservation_key=%s",
                (prepared.reservation_id, intent.job_id, intent.user_id, intent.epoch,
                 intent.lease_generation, intent.reservation_key),
            ).fetchone()
            if row is None or self.pipeline.budget._reservation_amounts(prepared.lease, prepared.reservation_id) != intent.resources.as_dict():
                raise PipelineRepositoryError("EXECUTION_RESERVATION_NOT_COMMITTED")
            terminal = self.conn.execute(
                "SELECT id FROM tutor_item_supply_private_sandbox_runs WHERE intent_id=%s",
                (intent.id,),
            ).fetchone()
            if terminal is not None:
                raise PipelineRepositoryError("EXECUTION_ALREADY_TERMINAL")
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")
        try:
            validation = validate_candidate(source, execution_port=execution_port)
            evidence = validation.execution_evidence
            if evidence is None or not execution_port.verify(evidence, source):
                return SandboxExecutionResult(validation, None, (), None, "execution_usage_unknown")
            actual = checked_model(execution_port.resource_usage(evidence), ResourceAmounts)
            if any(amount for kind, amount in actual.as_dict().items() if kind != "execution_seconds"):
                raise PipelineRepositoryError("EXECUTION_USAGE_SHAPE_INVALID")
            receipts = execution_port.receipts(evidence)
            if not receipts:
                return SandboxExecutionResult(validation, None, (), None, "execution_usage_unknown")
            run = RunV2(source_run=evidence.run_id, namespace=prepared.intent.actor_namespace,
                tenant_id=prepared.intent.user_id, actor_id=prepared.actor_id,
                scope_hash=prepared.scope_hash, content_hash=source.content_hash,
                profile_hash=prepared.lease.profile.profile_hash, origin="deterministic_probe")
            return SandboxExecutionResult(validation, actual, receipts, run, "execution_terminal")
        except Exception:
            # Partial runs/cleanup faults have incomplete usage; retain the full
            # reservation, never interpret absent receipts as zero consumption.
            return SandboxExecutionResult(None, None, (), None, "execution_usage_unknown")
        finally:
            if self.conn.info.transaction_status != TransactionStatus.IDLE:
                raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")

    def _verified_result(self, prepared: PreparedSandboxExecution, result: SandboxExecutionResult,
                         execution_port: SandboxCandidateExecutionPort) -> CandidateValidationV2 | None:
        if not isinstance(execution_port, SandboxCandidateExecutionPort):
            raise PipelineRepositoryError("TRUSTED_EXECUTION_PORT_REQUIRED")
        if result.validation is None or result.validation.execution_evidence is None:
            return None
        validation = checked_model(result.validation, CandidateValidationV2)
        evidence = validation.execution_evidence
        assert evidence is not None
        if (not execution_port.verify(evidence, prepared.source)
                or result.executor_receipts != execution_port.receipts(evidence)
                or result.actual != execution_port.resource_usage(evidence)
                or result.run is None or result.run.source_run != evidence.run_id
                or result.run.actor_id != prepared.actor_id):
            raise PipelineRepositoryError("EXECUTION_RESULT_UNTRUSTED")
        return validation

    def settle_execution(self, prepared: PreparedSandboxExecution, result: SandboxExecutionResult,
                         execution_port: SandboxCandidateExecutionPort) -> None:
        validation = self._verified_result(prepared, result, execution_port)
        known = validation is not None and result.actual is not None and bool(result.executor_receipts)
        receipt_hash = canonical_hash({"receipts": result.executor_receipts}) if known else None
        self.pipeline.budget.settle(lease=prepared.lease, reservation_id=prepared.reservation_id,
            settlement_key=f"execution.{prepared.intent.id.hex}", usage_state="known" if known else "unknown",
            actual=result.actual if known else None, cost_amount=None, receipt_hash=receipt_hash)
        if known and result.run is not None:
            SandboxRepository(self.conn).record_run(intent=prepared.intent, reservation_id=prepared.reservation_id,
                run=result.run, executor_receipts=result.executor_receipts)

    def commit_execution(self, prepared: PreparedSandboxExecution, result: SandboxExecutionResult,
                         execution_port: SandboxCandidateExecutionPort, *,
                         source_authority: RagSourceAuthority | None = None) -> CandidateValidationV2 | None:
        now = datetime.now(UTC)
        lease = self.pipeline.runtime.refresh_lease(prepared.lease, now=now)
        repository = SandboxRepository(self.conn)
        repository.get_intent(lease=lease, intent_id=prepared.intent.id, now=now)
        # Detailed settlement is independently committed before validation; no
        # implicit settlement or commit can hide the cost of a stale final fence.
        settlement = self.conn.execute(
            "SELECT id, xmin::text::bigint = (txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=%s AND settlement_key=%s",
            (prepared.reservation_id, f"execution.{prepared.intent.id.hex}"),
        ).fetchone()
        if settlement is None:
            raise PipelineRepositoryError("EXECUTION_SETTLEMENT_REQUIRED")
        if settlement["same_transaction"]:
            raise PipelineRepositoryError("EXECUTION_SETTLEMENT_MUST_BE_COMMITTED")
        artifact = self.artifacts.get_generation(lease=lease, scope_id=prepared.intent.scope_id,
            artifact_id=prepared.intent.generation_artifact_id, now=now, mode=prepared.mode)
        self.pipeline._fence_source(artifact, prepared.mode, source_authority)
        validation = self._verified_result(prepared, result, execution_port)
        if validation is None:
            self.pipeline.runtime.mark_preparing(lease, reason="execution_usage_unknown", now=now)
            return None
        source = LearningItemSourceV1.model_validate_json(json.dumps(artifact["source_json"]))
        evidence = validation.execution_evidence
        assert evidence is not None
        current = validate_candidate(source, execution_port=_ReceiptOnlyPort(execution_port, evidence))
        if current != validation:
            raise PipelineRepositoryError("EXECUTION_VALIDATION_CHANGED")
        row = self.artifacts.store_receipt(lease=lease, scope_id=prepared.intent.scope_id,
            artifact_id=prepared.intent.generation_artifact_id, kind="validation", payload=current,
            artifact_key=f"execution_validation.{prepared.intent.id.hex}", now=now, mode=prepared.mode)
        if current.state == "machine_verified":
            self.pipeline.runtime.checkpoint(lease, CheckpointV1(stage="validating", attempt=1,
                status="completed", receipt_hash=row["receipt_hash"], safe_reason="deterministic_verified"), now=now)
            # Code/SQL still has no v1 legacy receipt: P5 review compatibility is
            # pending. Never forge v1 completion or complete/admit the whole job.
        else:
            self.pipeline.runtime.mark_preparing(lease, reason="deterministic_evidence_pending", now=now)
        return current
