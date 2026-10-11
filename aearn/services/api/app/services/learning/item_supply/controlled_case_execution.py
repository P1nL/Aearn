"""Default-off, single-use same-case execution issuer; never publication authority.

History is only an audit anchor. Current leases, source receipts and paid-call
capabilities are minted by the original owners, not restored from stored JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.controlled_counterexample_contracts import (
    ControlledCounterexampleContextV3, checked_controlled_context,
)
from app.services.learning.item_supply.development_model_accounting import accounting_batch_for_lease
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, server_clock
from app.services.learning.item_supply.storage_contracts import checked_model

AUTHORIZATION = "controlled-v3-same-case-execution-20261011-1"
ACCEPTED_AUTHORIZATIONS = frozenset((AUTHORIZATION, "controlled-v3-same-case-execution-20261011-2"))
ORIGINAL_CASE_JOB = UUID("b8041728-d460-4ce2-ba29-47cbebd7b861")
PRIOR_FAILED_JOB = UUID("670a94d4-605a-4a39-81f7-8fe424a6b620")
ROOT = UUID("7d4b85ba-a0ec-4348-ac11-3401c6bded47")


@dataclass(frozen=True, repr=False)
class IssuedControlledCaseExecution:
    execution_id: UUID
    authorization_key: str
    root_id: UUID
    candidate_id: UUID
    batch_id: UUID
    original_case_preparation_id: UUID
    original_case_job_id: UUID
    prior_failed_job_id: UUID
    lease: JobLeaseV1
    context: ControlledCounterexampleContextV3
    deadline_at: datetime

    def payload(self) -> dict[str, object]:
        return {"schema_version": "controlled_case_execution_authorization_v1",
            "execution_id": str(self.execution_id), "authorization_key": self.authorization_key,
            "case_key": self.context.experiment_key, "context": self.context.model_dump(mode="json"),
            "context_hash": self.context.context_hash, "root_id": str(self.root_id),
            "candidate_id": str(self.candidate_id), "batch_id": str(self.batch_id),
            "original_case_preparation_id": str(self.original_case_preparation_id),
            "original_case_job_id": str(self.original_case_job_id), "prior_failed_job_id": str(self.prior_failed_job_id),
            "lease": self.lease.model_dump(mode="json"), "profile_hash": self.lease.profile.profile_hash,
            "deadline_at": self.deadline_at.isoformat(), "publication_enabled": False, "admission_eligible": False}


class ControlledCaseExecutionOwner:
    def __init__(self, conn: Connection[dict[str, Any]], *, enabled: bool = False) -> None:
        self.conn, self.enabled = conn, enabled
        self._issued: dict[UUID, tuple[IssuedControlledCaseExecution, str]] = {}
        self._attached: dict[UUID, UUID] = {}

    def _guard(self) -> None:
        if self.enabled is not True:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_DISABLED")
        row = self.conn.execute("SELECT current_database() AS database, "
            "to_regclass('public.tutor_item_supply_shared_controlled_case_executions') AS a, "
            "to_regclass('public.tutor_item_supply_shared_controlled_execution_preparations') AS p, "
            "to_regclass('public.tutor_item_supply_shared_controlled_execution_receipts') AS r, "
            "to_regprocedure('item_supply_internal.controlled_case_execution_history_matches(uuid,uuid,uuid,text)') AS h").fetchone()
        if (row is None or row["database"] != "aearn_b1d_sandbox_20261001"
                or any(row[key] is None for key in ("a", "p", "r", "h"))):
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_518_REQUIRED")

    def issue(self, *, lease: JobLeaseV1, context: ControlledCounterexampleContextV3,
              candidate_id: UUID, authorization_key: str, original_case_job_id: UUID,
              prior_failed_job_id: UUID, now: datetime) -> IssuedControlledCaseExecution:
        self._guard()
        if (type(context) is not ControlledCounterexampleContextV3 or type(candidate_id) is not UUID
                or authorization_key not in ACCEPTED_AUTHORIZATIONS or original_case_job_id != ORIGINAL_CASE_JOB
                or prior_failed_job_id != PRIOR_FAILED_JOB):
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_CLOSED_AUTHORIZATION_REQUIRED")
        context = checked_model(context, ControlledCounterexampleContextV3)
        lease = checked_model(lease, JobLeaseV1)
        now = server_clock(self.conn, now)
        runtime = ItemSupplyRuntimeRepository(self.conn)
        control = runtime._control(lease, now=now)
        batch = accounting_batch_for_lease(self.conn, lease, now=now)
        if (batch is None or batch["root_id"] != ROOT or control["attempt_count"] != 1
                or lease.generation != 1 or runtime.next_stage(lease) != "generating"
                or lease.job_id in (ORIGINAL_CASE_JOB, PRIOR_FAILED_JOB)):
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_NEW_MAPPED_FIRST_CLAIM_REQUIRED")
        history = self.conn.execute("SELECT pp.id FROM tutor_item_supply_shared_controlled_counterexample_preparations pp "
            "WHERE pp.job_id=%s AND item_supply_internal.controlled_case_execution_history_matches(%s,%s,%s,%s)",
            (original_case_job_id, ROOT, original_case_job_id, prior_failed_job_id, context.context_hash)).fetchone()
        if history is None:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_HISTORY_ANCHOR_REQUIRED")
        deadline = min(lease.expires_at, lease.parent_deadline, lease.profile.parent_deadline_at,
            lease.profile.bound_at + timedelta(milliseconds=lease.profile.values.stage_deadline_ms), batch["valid_until"])
        if deadline <= now:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_CURRENT_DEADLINE_REQUIRED")
        issued = IssuedControlledCaseExecution(uuid4(), authorization_key, ROOT, candidate_id, batch["batch_id"],
            UUID(str(history["id"])), original_case_job_id, prior_failed_job_id, lease, context, deadline)
        payload = issued.payload()
        self.conn.execute("INSERT INTO tutor_item_supply_shared_controlled_case_executions "
            "(id,authorization_key,case_key,context_hash,root_id,job_id,candidate_id,batch_id,original_case_preparation_id, "
            "original_case_job_id,prior_failed_job_id,lease_owner,lease_generation,lease_state_version,profile_hash,payload_json,valid_until) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (issued.execution_id,authorization_key,context.experiment_key,context.context_hash,ROOT,lease.job_id,candidate_id,
             issued.batch_id,issued.original_case_preparation_id,original_case_job_id,prior_failed_job_id,lease.lease_owner,
             lease.generation,lease.state_version,lease.profile.profile_hash,Jsonb(payload),deadline))
        self._issued[issued.execution_id] = (issued, canonical_hash(payload))
        return issued

    def verify_identity(self, execution: IssuedControlledCaseExecution, *, lease: JobLeaseV1,
                        context: object, candidate_id: UUID, preparation_id: UUID | None = None) -> None:
        # Original issued-object lookups are deliberately CPU-only. DB fencing
        # belongs in the caller's explicit transaction, not before provider IO.
        if self.enabled is not True:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_DISABLED")
        if type(execution) is not IssuedControlledCaseExecution:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ORIGINAL_ISSUER_REQUIRED")
        entry = self._issued.get(execution.execution_id)
        if (entry is None or entry[0] is not execution or entry[1] != canonical_hash(execution.payload())
                or type(context) is not ControlledCounterexampleContextV3
                or checked_controlled_context(context).context_hash != execution.context.context_hash
                or lease != execution.lease or candidate_id != execution.candidate_id):
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ORIGINAL_BINDING_REQUIRED")
        if preparation_id is not None and self._attached.get(execution.execution_id) != preparation_id:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ORIGINAL_PREPARATION_REQUIRED")

    def verify(self, execution: IssuedControlledCaseExecution, *, lease: JobLeaseV1,
               context: object, candidate_id: UUID, now: datetime, preparation_id: UUID | None = None) -> None:
        self.verify_identity(execution,lease=lease,context=context,candidate_id=candidate_id,preparation_id=preparation_id)
        self._guard()
        entry = self._issued[execution.execution_id]
        now = server_clock(self.conn, now)
        ItemSupplyRuntimeRepository(self.conn)._control(lease, now=now)
        batch = accounting_batch_for_lease(self.conn, lease, now=now)
        row = self.conn.execute("SELECT a.*,a.xmin::text::bigint=(txid_current() %% 4294967296) AS same_transaction "
            "FROM tutor_item_supply_shared_controlled_case_executions a WHERE a.id=%s FOR SHARE", (execution.execution_id,)).fetchone()
        if (batch is None or batch["batch_id"] != execution.batch_id or batch["root_id"] != execution.root_id
                or row is None or row["same_transaction"] or row["payload_json"] != execution.payload()
                or row["snapshot_hash"] != entry[1] or now >= execution.deadline_at):
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_COMMITTED_CURRENT_AUTHORIZATION_REQUIRED")
        attached = self._attached.get(execution.execution_id)
        if preparation_id is None:
            if attached is not None or self.conn.execute("SELECT 1 FROM tutor_item_supply_shared_controlled_execution_preparations "
                    "WHERE execution_id=%s", (execution.execution_id,)).fetchone() is not None:
                raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ALREADY_USED")
        elif attached != preparation_id:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ORIGINAL_PREPARATION_REQUIRED")

    def attach(self, execution: IssuedControlledCaseExecution, preparation_id: UUID) -> None:
        if self._issued.get(execution.execution_id, (None,))[0] is not execution or execution.execution_id in self._attached:
            raise PipelineRepositoryError("CONTROLLED_CASE_EXECUTION_ALREADY_USED")
        self._attached[execution.execution_id] = preparation_id
