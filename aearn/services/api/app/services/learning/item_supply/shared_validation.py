"""Default-off B1d PUBLIC validation: prepare / idle IO / settle / fenced commit.

Original runner/port objects remain in this process. Database JSON is audit, not
permission to execute again or to issue facts/admission/publication.
"""
from __future__ import annotations
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from psycopg import Connection
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb
from app.core.config import Settings
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.jobs import CheckpointV1, JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, server_clock
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerPort
from app.services.learning.item_supply.sandbox.repository import execution_resources
from app.services.learning.item_supply.shared_continuation import SharedCandidateContinuationOwner
from app.services.learning.item_supply.shared_pipeline_repository import ResolvedSharedGeneration, SharedPipelineArtifactRepository
from app.services.learning.item_supply.shared_validation_contracts import (
    PreparedSharedValidation, SharedValidationResult, SharedValidationStageResult,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import validate_candidate


class SharedValidationPipeline:
    def __init__(self, conn: Connection[dict[str, Any]], settings: Settings, *, enabled: bool = False,
                 continuation_owner: SharedCandidateContinuationOwner | None = None) -> None:
        self.conn, self.settings, self.enabled = conn, settings, enabled
        self.runtime = ItemSupplyRuntimeRepository(conn)
        self.budget = ItemSupplyBudgetRepository(conn)
        self.artifacts = SharedPipelineArtifactRepository(conn, enabled=enabled)
        if continuation_owner is not None and (type(continuation_owner) is not SharedCandidateContinuationOwner
                                               or continuation_owner.conn is not conn):
            raise PipelineRepositoryError("SHARED_CONTINUATION_OWNER_REQUIRED")
        self.continuation_owner = continuation_owner
        self._continuation_bindings: dict[UUID, str] = {}
        self._prepared: dict[UUID, tuple[PreparedSharedValidation, str, RagSourceAuthority,
                                         SandboxCandidateExecutionPort | None]] = {}
        self._started: set[UUID] = set()
        self._results: dict[UUID, tuple[SharedValidationResult, str]] = {}
        self._operation_deadlines: dict[UUID, datetime] = {}

    @property
    def validation_enabled(self) -> bool:
        return self.enabled and self.settings.learning_item_supply_enabled

    def _payload(self, p: PreparedSharedValidation) -> dict[str, Any]:
        payload = {"lease": p.lease.model_dump(mode="json"), "artifact_id": str(p.artifact_id),
                "artifact_hash": p.artifact_hash, "source_hash": p.source.source_hash, "content_hash": p.source.content_hash,
                "request": p.request.model_dump(mode="json"), "spec": p.spec.model_dump(mode="json"),
                "inputs": p.inputs.model_dump(mode="json"),
                "resources": None if p.resources is None else p.resources.model_dump(mode="json")}
        if p.preparation_id in self._continuation_bindings:
            payload["continuation_binding_hash"] = self._continuation_bindings[p.preparation_id]
        return payload

    @staticmethod
    def _result_payload(result: SharedValidationResult) -> dict[str, Any]:
        return {"validation": None if result.validation is None else result.validation.model_dump(mode="json"),
                "actual": None if result.actual is None else result.actual.model_dump(mode="json"),
                "terminals": list(result.terminal_receipts), "safe_reason": result.safe_reason,
                "publication_enabled": False}

    def _issued(self, p: PreparedSharedValidation) -> tuple[RagSourceAuthority, SandboxCandidateExecutionPort | None]:
        if not self.validation_enabled:
            raise PipelineRepositoryError("SHARED_VALIDATION_DISABLED")
        entry = self._prepared.get(p.preparation_id)
        seal = canonical_hash({"payload": self._payload(p), "reservation_id": str(p.reservation_id)})
        if entry is None or entry[0] is not p or entry[1] != seal:
            raise PipelineRepositoryError("SHARED_VALIDATION_PREPARED_UNAVAILABLE")
        deadline = self._operation_deadlines.get(p.preparation_id)
        if deadline is not None and entry[3] is not None and entry[3]._deadline != deadline:
            raise PipelineRepositoryError("SHARED_VALIDATION_OPERATION_DEADLINE_CHANGED")
        return entry[2], entry[3]

    def _load(self, lease: JobLeaseV1, artifact_id: UUID, spec: FiniteCandidateSpecV1,
              authority: RagSourceAuthority) -> ResolvedSharedGeneration:
        now = server_clock(self.conn, datetime.now(UTC))
        resolved = self.artifacts.resolve_generation(lease=lease, artifact_id=artifact_id, now=now,
            source_authority=authority, spec=spec, continuation_owner=self.continuation_owner)
        if self.runtime.next_stage(lease) != "validating":
            raise PipelineRepositoryError("VALIDATION_STAGE_MISMATCH")
        self.runtime._control(lease, now=server_clock(self.conn, now))
        return resolved

    def prepare_validation(self, *, lease: JobLeaseV1, artifact_id: UUID, spec: FiniteCandidateSpecV1,
                           source_authority: RagSourceAuthority, runner: RunnerPort | None = None,
                           operation_deadline_at: datetime | None = None) -> PreparedSharedValidation | None:
        """Caller short transaction; supply a refreshed public lease after generation."""
        if not self.validation_enabled:
            return None
        self.artifacts.require_owner()
        lease, spec = checked_model(lease, JobLeaseV1), checked_model(spec, FiniteCandidateSpecV1)
        deadline = min(lease.expires_at, lease.parent_deadline)
        if operation_deadline_at is not None:
            if operation_deadline_at.tzinfo is None:
                raise PipelineRepositoryError("SHARED_VALIDATION_OPERATION_DEADLINE_REQUIRED")
            deadline = min(deadline, operation_deadline_at, lease.profile.parent_deadline_at,
                lease.profile.bound_at + timedelta(milliseconds=lease.profile.values.stage_deadline_ms))
            if server_clock(self.conn, datetime.now(UTC)) >= deadline:
                raise PipelineRepositoryError("SHARED_VALIDATION_OPERATION_DEADLINE_REACHED")
        resolved = self._load(lease, artifact_id, spec, source_authority)
        artifact, source, request = resolved.artifact, resolved.source, resolved.request
        inputs = prepare_finite_candidate_validation(source, spec=spec, materials=request.materials)
        port, resources = None, None
        if inputs.static_facts is not None:
            if runner is not None:
                raise PipelineRepositoryError("SHARED_STATIC_RUNNER_DENIED")
        else:
            if runner is None:
                raise PipelineRepositoryError("SHARED_EXECUTION_RUNNER_REQUIRED")
            port = SandboxCandidateExecutionPort(runner, probe_plan=inputs.probe_plan, finite_spec=spec,
                                                parent_deadline_at=deadline)
            resources = execution_resources(port.resource_plan(source))
            if resources.execution_seconds * 1000 > lease.profile.values.stage_deadline_ms:
                raise PipelineRepositoryError("EXECUTION_RESOURCE_PROFILE_BOUND")
        pid = uuid4()
        if resolved.continuation_binding is not None:
            self._continuation_bindings[pid] = resolved.continuation_binding.binding_hash
        p = PreparedSharedValidation(pid, lease, artifact_id, artifact["artifact_hash"], source, request, spec, inputs, resources, None)
        payload = self._payload(p)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_validation_preparations "
            "(id,job_id,root_id,lease_owner,lease_generation,lease_state_version,profile_hash,generation_artifact_id,"
            "item_id,version_id,source_hash,content_hash,reservation_key,payload_json,resources_json,continuation_binding_hash) "
            "VALUES(" + ",".join(["%s"] * 16) + ") "
            "ON CONFLICT(job_id,lease_generation,generation_artifact_id) DO NOTHING RETURNING id",
            (pid, lease.job_id, artifact["root_id"], lease.lease_owner, lease.generation, lease.state_version,
             lease.profile.profile_hash, artifact_id, artifact["item_id"], artifact["version_id"],
             source.source_hash, source.content_hash, f"shared.execution.{pid.hex}" if resources else None,
             Jsonb(payload), Jsonb(resources.model_dump(mode="json")) if resources else None,
             self._continuation_bindings.get(pid)),
        ).fetchone()
        if row is None:
            return None  # Immutable readback is not a new execution allowance.
        if resources is not None:
            # Same P3 cumulative owner; 490 provides shared intent/header/allocation
            # fences. Never call the private-only reserve_execution entrance.
            reserved = self.budget._reserve_budget(lease=lease, reservation_key=f"shared.execution.{pid.hex}",
                requested=resources, now=server_clock(self.conn, datetime.now(UTC)))
            if not reserved.allowed or reserved.reservation_id is None or reserved.reason == "REPLAY":
                raise PipelineRepositoryError("SHARED_EXECUTION_RESERVATION_DENIED")
            p = PreparedSharedValidation(pid, lease, artifact_id, artifact["artifact_hash"], source,
                request, spec, inputs, resources, reserved.reservation_id)
        seal = canonical_hash({"payload": payload, "reservation_id": str(p.reservation_id)})
        self._prepared[pid] = (p, seal, source_authority, port)
        if operation_deadline_at is not None:
            self._operation_deadlines[pid] = deadline
        return p

    def _fence(self, p: PreparedSharedValidation, *, before_io: bool = False) -> None:
        authority, port = self._issued(p)
        deadline = self._operation_deadlines.get(p.preparation_id)
        if deadline is not None and server_clock(self.conn, datetime.now(UTC)) >= deadline:
            raise PipelineRepositoryError("SHARED_VALIDATION_OPERATION_DEADLINE_REACHED")
        resolved = self._load(p.lease, p.artifact_id, p.spec, authority)
        artifact, source, request = resolved.artifact, resolved.source, resolved.request
        current_binding = None if resolved.continuation_binding is None else resolved.continuation_binding.binding_hash
        if current_binding != self._continuation_bindings.get(p.preparation_id):
            raise PipelineRepositoryError("SHARED_VALIDATION_ADOPTION_CHANGED")
        if (artifact["artifact_hash"] != p.artifact_hash or source != p.source or request != p.request
                or prepare_finite_candidate_validation(source, spec=p.spec, materials=request.materials) != p.inputs):
            raise PipelineRepositoryError("SHARED_VALIDATION_INPUTS_CHANGED")
        row = self.conn.execute("SELECT payload_hash FROM tutor_item_supply_shared_validation_preparations WHERE id=%s",
                                (p.preparation_id,)).fetchone()
        if row is None or row["payload_hash"] != canonical_hash(self._payload(p)):
            raise PipelineRepositoryError("SHARED_VALIDATION_PREPARATION_NOT_COMMITTED")
        if port is not None:
            assert p.resources is not None and p.reservation_id is not None
            if before_io and execution_resources(port.resource_plan(source)) != p.resources:
                raise PipelineRepositoryError("SHARED_EXECUTION_PLAN_CHANGED")
            reservation = self.budget._reservation_by_key(p.lease, f"shared.execution.{p.preparation_id.hex}")
            if (reservation is None or UUID(str(reservation["id"])) != p.reservation_id
                    or reservation["lease_generation"] != p.lease.generation
                    or self.budget._reservation_amounts(p.lease, p.reservation_id) != p.resources.as_dict()):
                raise PipelineRepositoryError("SHARED_EXECUTION_RESERVATION_NOT_COMMITTED")

    def run_validation(self, p: PreparedSharedValidation) -> SharedValidationResult:
        _, port = self._issued(p)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")
        if p.preparation_id in self._started:
            raise PipelineRepositoryError("SHARED_EXECUTION_ALREADY_DISPATCHED")
        with self.conn.transaction():
            self._fence(p, before_io=True)
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")
        self._started.add(p.preparation_id)
        if port is None:
            assert p.inputs.static_facts is not None
            result = SharedValidationResult(p.inputs.static_facts.validation, None, (), "static_exact_verified")
        else:
            try:
                validation = validate_candidate(p.source, execution_port=port, finite_spec=p.spec)
                evidence = validation.execution_evidence
                if evidence is None or evidence.mode != "live" or evidence.isolation != "approved_os_boundary":
                    raise PipelineRepositoryError("SHARED_LIVE_EXECUTION_REQUIRED")
                result = SharedValidationResult(validation, port.resource_usage(evidence), port.receipts(evidence), "execution_terminal")
                self._verify_terminal(p, result, port)
            except Exception:
                # No fabricated terminal or zero usage for partial/failed IO.
                result = SharedValidationResult(None, None, (), "execution_usage_unknown")
        if p.preparation_id in self._operation_deadlines:
            try:
                with self.conn.transaction():
                    self._fence(p)
            except Exception:
                result = SharedValidationResult(None, None, (), "execution_usage_unknown")
        if self.conn.info.transaction_status != TransactionStatus.IDLE:
            raise PipelineRepositoryError("EXECUTOR_IO_REQUIRES_IDLE_TRANSACTION")
        self._results[p.preparation_id] = (result, canonical_hash(self._result_payload(result)))
        return result

    def _result(self, p: PreparedSharedValidation, result: SharedValidationResult) -> SandboxCandidateExecutionPort | None:
        _, port = self._issued(p)
        stored = self._results.get(p.preparation_id)
        if stored is None or stored[0] is not result or stored[1] != canonical_hash(self._result_payload(result)):
            raise PipelineRepositoryError("SHARED_VALIDATION_RESULT_UNAVAILABLE")
        return port

    @staticmethod
    def _verify_terminal(p: PreparedSharedValidation, result: SharedValidationResult,
                         port: SandboxCandidateExecutionPort) -> None:
        evidence = None if result.validation is None else result.validation.execution_evidence
        if (evidence is None or evidence.mode != "live" or evidence.isolation != "approved_os_boundary"
                or not port.verify(evidence, p.source) or result.actual != port.resource_usage(evidence)
                or not result.terminal_receipts or result.terminal_receipts != port.receipts(evidence)
                or evidence.scorer_version != p.spec.coverage_blueprint.scope.scorer_version
                or any(r.get("lock_fingerprint") != p.spec.coverage_blueprint.scope.runtime_profile_hash
                       for r in result.terminal_receipts)):
            raise PipelineRepositoryError("SHARED_EXECUTION_RESULT_UNTRUSTED")
        assert result.actual is not None and p.resources is not None
        if (any(v for k, v in result.actual.as_dict().items() if k != "execution_seconds")
                or result.actual.execution_seconds > p.resources.execution_seconds):
            raise PipelineRepositoryError("SHARED_EXECUTION_USAGE_INVALID")

    def _store_evidence(self, p: PreparedSharedValidation, result: SharedValidationResult) -> UUID:
        payload = self._result_payload(result)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_validation_evidence(preparation_id,reservation_id,payload_json) "
            "VALUES(%s,%s,%s) ON CONFLICT(preparation_id) DO NOTHING RETURNING id,payload_hash",
            (p.preparation_id, p.reservation_id, Jsonb(payload)),
        ).fetchone()
        if row is None:
            row = self.conn.execute("SELECT id,payload_hash FROM tutor_item_supply_shared_validation_evidence WHERE preparation_id=%s",
                                    (p.preparation_id,)).fetchone()
        if row is None or row["payload_hash"] != canonical_hash(payload):
            raise PipelineRepositoryError("SHARED_VALIDATION_EVIDENCE_CONFLICT")
        return UUID(str(row["id"]))

    def settle_validation(self, p: PreparedSharedValidation, result: SharedValidationResult) -> None:
        """Caller commits separately even when the source/lease was lost."""
        self.artifacts.require_owner()
        port = self._result(p, result)
        if port is None:
            return  # Static facts consume no budget and have no terminal.
        known = result.validation is not None
        # The original result was verified at IO completion and remains sealed
        # in this owner. A now-stale runtime/source must not prevent accounting
        # for those actual resources; current authority is checked at commit.
        assert p.reservation_id is not None
        self.budget.settle(lease=p.lease, reservation_id=p.reservation_id,
            settlement_key=f"shared.execution.{p.preparation_id.hex}", usage_state="known" if known else "unknown",
            actual=result.actual if known else None, cost_amount=None,
            receipt_hash=canonical_hash({"receipts": result.terminal_receipts}) if known else None)
        self._store_evidence(p, result)

    def commit_validation(self, p: PreparedSharedValidation, result: SharedValidationResult) -> SharedValidationStageResult:
        self.artifacts.require_owner()
        port = self._result(p, result)
        self._fence(p)
        if port is not None:
            settled = self.conn.execute(
                "SELECT id,xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
                "FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=%s AND settlement_key=%s",
                (p.reservation_id, f"shared.execution.{p.preparation_id.hex}"),
            ).fetchone()
            if settled is None or settled["same_transaction"]:
                raise PipelineRepositoryError("SHARED_EXECUTION_COMMITTED_SETTLEMENT_REQUIRED")
        if result.validation is None:
            self.runtime.mark_preparing(p.lease, reason="execution_usage_unknown", now=datetime.now(UTC))
            return SharedValidationStageResult("blocked", "execution_usage_unknown")
        if port is None:
            assert p.inputs.static_facts is not None
            current = p.inputs.static_facts.validation
        else:
            self._verify_terminal(p, result, port)
            evidence = result.validation.execution_evidence
            assert evidence is not None
            # Exact finite adapter requires the original concrete port, not a
            # wrapper. verify above proves its cached run; validate returns that
            # same cached evidence before the runner loop, with no IO in this tx.
            if port._source_runs.get(p.source.source_hash) != evidence.run_id:
                raise PipelineRepositoryError("SHARED_EXECUTION_CACHE_UNAVAILABLE")
            current = validate_candidate(p.source, execution_port=port, finite_spec=p.spec)
        if current != result.validation:
            raise PipelineRepositoryError("SHARED_VALIDATION_CHANGED")
        evidence_id = self._store_evidence(p, result)
        authority, _ = self._issued(p)
        now = server_clock(self.conn, datetime.now(UTC))
        row = self.artifacts.store_receipt(lease=p.lease, artifact_id=p.artifact_id,
            kind="validation", payload=current, artifact_key=f"validation.{p.preparation_id.hex}",
            now=now, source_authority=authority, spec=p.spec, continuation_owner=self.continuation_owner)
        if current.state == "machine_verified":
            control = self.runtime._control(p.lease, now=server_clock(self.conn, now))
            self.runtime.checkpoint(p.lease, CheckpointV1(stage="validating", attempt=control["attempt_count"],
                status="completed", receipt_hash=row["receipt_hash"], safe_reason="deterministic_verified"), now=now)
        else:
            self.runtime.mark_preparing(p.lease, reason="deterministic_evidence_pending", now=now)
        return SharedValidationStageResult(current.state, "validation_staged", UUID(str(row["id"])), evidence_id)

    def verified_committed_validation(self, p: PreparedSharedValidation, result: SharedValidationResult, *,
                                      lease: JobLeaseV1, receipt_id: UUID) -> CandidateValidationV2:
        """Verify original completed evidence at a later CURRENT child stage.

        Never call _fence(p): p's validating state_version has legitimately
        advanced. Cached issuer/terminal verification performs no executor IO.
        """
        self.artifacts.require_owner()
        port = self._result(p,result)
        authority,_ = self._issued(p)
        lease = checked_model(lease,JobLeaseV1)
        if ((lease.job_id,lease.generation,lease.lease_owner,lease.profile,lease.visibility) !=
                (p.lease.job_id,p.lease.generation,p.lease.lease_owner,p.lease.profile,"public")
                or lease.owner_id is not None or lease.owner_epoch is not None or lease.state_version<p.lease.state_version):
            raise PipelineRepositoryError("SHARED_VALIDATION_CURRENT_OPERATION_REQUIRED")
        now = server_clock(self.conn,datetime.now(UTC))
        self.runtime._control(lease,now=now)
        resolved = self.artifacts.resolve_generation(lease=lease,artifact_id=p.artifact_id,now=now,
            source_authority=authority,spec=p.spec,continuation_owner=self.continuation_owner)
        if (resolved.source != p.source or resolved.request != p.request or resolved.artifact["artifact_hash"] != p.artifact_hash
                or prepare_finite_candidate_validation(p.source,spec=p.spec,materials=p.request.materials) != p.inputs
                or result.validation is None or result.validation.state != "machine_verified"):
            raise PipelineRepositoryError("SHARED_VALIDATION_COMPLETED_DATA_CHANGED")
        row = self.conn.execute("SELECT r.*,r.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_pipeline_receipts r WHERE r.id=%s FOR SHARE",(receipt_id,)).fetchone()
        evidence = self.conn.execute("SELECT e.*,e.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_validation_evidence e WHERE e.preparation_id=%s",(p.preparation_id,)).fetchone()
        if (row is None or row["same_transaction"] or row["job_id"] != lease.job_id or row["lease_generation"] != lease.generation
                or row["generation_artifact_id"] != p.artifact_id or row["artifact_kind"] != "validation"
                or row["receipt_hash"] != result.validation.evidence_hash or row["payload_json"] != result.validation.model_dump(mode="json")
                or evidence is None or evidence["same_transaction"] or evidence["payload_json"] != self._result_payload(result)
                or evidence["payload_hash"] != canonical_hash(self._result_payload(result))):
            raise PipelineRepositoryError("SHARED_VALIDATION_COMMITTED_ORIGINAL_RECEIPTS_REQUIRED")
        if port is None:
            if p.inputs.static_facts is None or p.inputs.static_facts.validation != result.validation:
                raise PipelineRepositoryError("SHARED_STATIC_ORIGINAL_FACTS_REQUIRED")
        else:
            self._verify_terminal(p,result,port)
            usage = self.conn.execute("SELECT s.*,s.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
                "FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=%s AND s.settlement_key=%s",
                (p.reservation_id,"shared.execution."+p.preparation_id.hex)).fetchone()
            if usage is None or usage["same_transaction"] or usage["usage_state"] != "known":
                raise PipelineRepositoryError("SHARED_VALIDATION_COMMITTED_EXECUTION_USAGE_REQUIRED")
        return result.validation
