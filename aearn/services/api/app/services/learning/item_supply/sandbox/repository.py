"""P6 private append-only receipts on the exact disposable database only."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.pipeline_repository import (
    ArtifactMode, PipelineArtifactRepository, PipelineRepositoryError,
)
from app.services.learning.item_supply.policies import ResourceAmounts, SupplyRuntimeError
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository, lock_private_namespace
from app.services.learning.item_supply.sandbox.contracts import (
    ObservationV2, RunV2, TerminalResolver,
)
from app.services.learning.item_supply.sandbox.observations import ObservationCountsV2, ObservationLedger
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

SANDBOX_DATABASE = "aearn_b1d_sandbox_20261001"


def execution_resources(value: ResourceAmounts) -> ResourceAmounts:
    value = checked_model(value, ResourceAmounts)
    if value.execution_seconds <= 0 or any(
        amount for kind, amount in value.as_dict().items() if kind != "execution_seconds"
    ):
        raise SupplyRuntimeError("EXECUTION_ONLY_RESOURCE_SHAPE_REQUIRED")
    return value


class ExecutionIntentV1(StorageContract):
    id: UUID
    user_id: UUID
    epoch: int = Field(ge=1)
    scope_id: UUID
    job_id: UUID
    root_id: UUID
    lease_generation: int = Field(ge=1)
    lease_state_version: int = Field(ge=1)
    lease_owner: str
    generation_artifact_id: UUID
    version_id: UUID
    profile_hash: Digest
    source_hash: Digest
    content_hash: Digest
    actor_namespace: Identifier
    reservation_key: Identifier
    resources: ResourceAmounts

    @model_validator(mode="after")
    def execution_only(self) -> ExecutionIntentV1:
        execution_resources(self.resources)
        if self.actor_namespace != f"sandbox.p6.{self.user_id}":
            raise ValueError("synthetic sandbox actor required")
        return self


def _intent(row: dict[str, Any]) -> ExecutionIntentV1:
    fields = set(ExecutionIntentV1.model_fields) - {"resources"}
    return ExecutionIntentV1.model_validate_json(json.dumps({
        **{field: str(row[field]) if isinstance(row[field], UUID) else row[field]
           for field in fields}, "resources": row["resources_json"],
    }))


class SandboxArtifactRepository(PipelineArtifactRepository):
    """Reuse 460 receipts, adding no RAG/publication authority or old-path change."""

    def _context(self, lease: JobLeaseV1, scope_id: UUID, now: datetime,
                 mode: ArtifactMode) -> JobLeaseV1:
        if mode not in ("live", "synthetic"):
            raise PipelineRepositoryError("PIPELINE_MODE_INVALID")
        SandboxRepository(self.conn).assert_actor(lease)
        return super()._context(lease, scope_id, now, mode)


class SandboxRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn
        row = conn.execute("SELECT current_database() AS db").fetchone()
        if row is None or row["db"] != SANDBOX_DATABASE:
            raise SupplyRuntimeError("SANDBOX_DATABASE_REQUIRED")

    def assert_actor(self, lease: JobLeaseV1) -> None:
        lease = checked_model(lease, JobLeaseV1)
        if lease.visibility != "private" or lease.owner_id is None:
            raise SupplyRuntimeError("PRIVATE_SANDBOX_REQUIRED")
        row = self.conn.execute(
            "SELECT id FROM users WHERE id=%s AND display_name=%s AND deleted_at IS NULL",
            (lease.owner_id, f"sandbox.p6.{lease.owner_id}"),
        ).fetchone()
        if row is None:
            raise SupplyRuntimeError("SYNTHETIC_SANDBOX_ACTOR_REQUIRED")

    def create_intent(self, *, lease: JobLeaseV1, scope_id: UUID,
                      artifact: dict[str, Any], reservation_key: str,
                      resources: ResourceAmounts, now: datetime) -> ExecutionIntentV1:
        self.assert_actor(lease)
        resources = execution_resources(resources)
        if resources.execution_seconds * 1000 > lease.profile.values.stage_deadline_ms:
            raise SupplyRuntimeError("EXECUTION_RESOURCE_PROFILE_BOUND")
        control = ItemSupplyRuntimeRepository(self.conn)._control(lease, now=now)
        if UUID(str(control["scope_id"])) != scope_id:
            raise SupplyRuntimeError("EXECUTION_SCOPE_MISMATCH")
        job = self.conn.execute(
            "SELECT root_id FROM tutor_item_supply_private_jobs WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s",
            (lease.job_id, lease.owner_id, lease.owner_epoch, scope_id),
        ).fetchone()
        if job is None:
            raise SupplyRuntimeError("JOB_UNAVAILABLE")
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_execution_intents "
            "(user_id,epoch,scope_id,job_id,root_id,lease_generation,lease_state_version,lease_owner,"
            "profile_hash,generation_artifact_id,version_id,source_hash,content_hash,actor_namespace,reservation_key,resources_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(job_id,reservation_key) DO NOTHING RETURNING *",
            (lease.owner_id, lease.owner_epoch, scope_id, lease.job_id, job["root_id"],
             lease.generation, lease.state_version, lease.lease_owner, lease.profile.profile_hash,
             artifact["id"], artifact["version_id"], artifact["source_hash"], artifact["content_hash"],
             f"sandbox.p6.{lease.owner_id}", reservation_key, Jsonb(resources.model_dump(mode="json"))),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_private_execution_intents WHERE job_id=%s AND reservation_key=%s AND user_id=%s AND epoch=%s",
                (lease.job_id, reservation_key, lease.owner_id, lease.owner_epoch),
            ).fetchone()
        if row is None:
            raise SupplyRuntimeError("EXECUTION_INTENT_CONFLICT")
        value = self.get_intent(lease=lease, intent_id=UUID(str(row["id"])), now=now)
        if (value.scope_id != scope_id or value.resources != resources
                or str(value.generation_artifact_id) != str(artifact["id"])
                or value.source_hash != artifact["source_hash"]
                or value.content_hash != artifact["content_hash"]):
            raise SupplyRuntimeError("EXECUTION_INTENT_CONFLICT")
        return value

    def get_intent(self, *, lease: JobLeaseV1, intent_id: UUID,
                   now: datetime) -> ExecutionIntentV1:
        self.assert_actor(lease)
        ItemSupplyRuntimeRepository(self.conn)._control(lease, now=now)
        row = self.conn.execute(
            "SELECT i.* FROM tutor_item_supply_private_execution_intents i "
            "JOIN tutor_item_supply_private_jobs j ON j.id=i.job_id AND j.user_id=i.user_id AND j.epoch=i.epoch AND j.root_id=i.root_id AND j.scope_id=i.scope_id "
            "JOIN tutor_item_supply_private_generation_artifacts a ON a.id=i.generation_artifact_id "
            "AND a.user_id=i.user_id AND a.epoch=i.epoch AND a.scope_id=i.scope_id AND a.job_id=i.job_id "
            "AND a.lease_generation=i.lease_generation AND a.version_id=i.version_id AND a.source_hash=i.source_hash AND a.content_hash=i.content_hash "
            "WHERE i.id=%s AND i.job_id=%s AND i.user_id=%s AND i.epoch=%s",
            (intent_id, lease.job_id, lease.owner_id, lease.owner_epoch),
        ).fetchone()
        if row is None:
            raise SupplyRuntimeError("EXECUTION_INTENT_UNAVAILABLE")
        value = _intent(row)
        if (value.lease_generation, value.lease_state_version, value.lease_owner, value.profile_hash) != (
            lease.generation, lease.state_version, lease.lease_owner, lease.profile.profile_hash
        ):
            raise SupplyRuntimeError("EXECUTION_INTENT_STALE")
        return value

    def record_run(self, *, intent: ExecutionIntentV1, reservation_id: UUID,
                   run: RunV2, executor_receipts: tuple[dict[str, object], ...],
                   observations: tuple[ObservationV2, ...] = (),
                   resolver: TerminalResolver | None = None) -> dict[str, Any]:
        intent = checked_model(intent, ExecutionIntentV1)
        run = checked_model(run, RunV2)
        scope = self.conn.execute(
            "SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=%s AND user_id=%s AND epoch=%s",
            (intent.scope_id, intent.user_id, intent.epoch),
        ).fetchone()
        if (run.origin == "real_learner" or run.namespace != intent.actor_namespace
                or run.tenant_id != intent.user_id or run.actor_id == intent.user_id
                or run.content_hash != intent.content_hash or run.profile_hash != intent.profile_hash
                or scope is None or run.scope_hash != scope["scope_hash"]):
            raise SupplyRuntimeError("SANDBOX_RUN_BINDING_MISMATCH")
        terminals: list[dict[str, Any]] = []
        if observations:
            if resolver is None:
                raise SupplyRuntimeError("TERMINAL_AUTHORITY_REQUIRED")
            ledger = ObservationLedger(resolver)
            for observation in observations:
                value = ledger.record(observation)
                if value.run != run:
                    raise SupplyRuntimeError("SANDBOX_RUN_BINDING_MISMATCH")
                terminals.append(value.terminal_receipt.model_dump(mode="json"))
        payload = {"executor_receipts": list(executor_receipts), "terminals": terminals}
        expected = canonical_hash(payload)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_sandbox_runs "
            "(id,user_id,epoch,scope_id,intent_id,reservation_id,origin,run_json,terminal_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING *",
            (run.source_run, intent.user_id, intent.epoch, intent.scope_id, intent.id,
             reservation_id, run.origin, Jsonb(run.model_dump(mode="json")), Jsonb(payload)),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT * FROM tutor_item_supply_private_sandbox_runs WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s",
                (run.source_run, intent.user_id, intent.epoch, intent.scope_id),
            ).fetchone()
        if (row is None or row["receipt_hash"] != expected or row["origin"] != run.origin
                or row["run_json"] != run.model_dump(mode="json") or UUID(str(row["intent_id"])) != intent.id
                or UUID(str(row["reservation_id"])) != reservation_id):
            raise SupplyRuntimeError("SANDBOX_RUN_REPLAY_CONFLICT")
        return row

    def record_observation(self, *, user_id: UUID, epoch: int, scope_id: UUID,
                           observation: ObservationV2, resolver: TerminalResolver) -> UUID:
        # Never let a model-authored DTO or persisted label become count authority.
        value = ObservationLedger(resolver).record(observation)
        if value.origin == "real_learner":
            raise SupplyRuntimeError("LEARNER_COLLECTOR_UNAVAILABLE")
        payload = value.model_dump(mode="json")
        expected = canonical_hash(payload)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_sandbox_observations "
            "(user_id,epoch,scope_id,source_run,origin,scenario,attempt,observation_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT(source_run,scenario,attempt) DO NOTHING RETURNING id,observation_hash",
            (user_id, epoch, scope_id, value.source_run, value.origin, value.scenario, value.attempt, Jsonb(payload)),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id,observation_hash FROM tutor_item_supply_private_sandbox_observations "
                "WHERE source_run=%s AND scenario=%s AND attempt=%s AND user_id=%s AND epoch=%s AND scope_id=%s",
                (value.source_run, value.scenario, value.attempt, user_id, epoch, scope_id),
            ).fetchone()
        if row is None or row["observation_hash"] != expected:
            raise SupplyRuntimeError("OBSERVATION_REPLAY_CONFLICT")
        return UUID(str(row["id"]))

    def read_observations(self, *, user_id: UUID, epoch: int, scope_id: UUID,
                          run: RunV2, resolver: TerminalResolver) -> tuple[ObservationV2, ...]:
        run = checked_model(run, RunV2)
        if run.origin == "real_learner":
            raise SupplyRuntimeError("LEARNER_COLLECTOR_UNAVAILABLE")
        lock_private_namespace(self.conn, user_id, epoch, scope_id)
        stored = self.conn.execute(
            "SELECT run_json FROM tutor_item_supply_private_sandbox_runs "
            "WHERE id=%s AND user_id=%s AND epoch=%s AND scope_id=%s",
            (run.source_run, user_id, epoch, scope_id),
        ).fetchone()
        if stored is None or stored["run_json"] != run.model_dump(mode="json"):
            raise SupplyRuntimeError("SANDBOX_RUN_BINDING_MISMATCH")
        rows = self.conn.execute(
            "SELECT observation_json FROM tutor_item_supply_private_sandbox_observations "
            "WHERE source_run=%s AND user_id=%s AND epoch=%s AND scope_id=%s "
            "ORDER BY scenario,attempt LIMIT 1001",
            (run.source_run, user_id, epoch, scope_id),
        ).fetchall()
        if len(rows) > 1000:
            raise SupplyRuntimeError("SANDBOX_OBSERVATION_READ_BOUND")
        ledger = ObservationLedger(resolver)
        for row in rows:
            value = ObservationV2.model_validate_json(json.dumps(row["observation_json"]))
            if value.run != run:
                raise SupplyRuntimeError("SANDBOX_RUN_BINDING_MISMATCH")
            ledger.record(value)  # Persistence alone is never terminal authority.
        return ledger.observations(run=run)

    def observation_summary(self, *, user_id: UUID, epoch: int, scope_id: UUID,
                            run: RunV2, resolver: TerminalResolver) -> ObservationCountsV2:
        # Derive only after trusted rereads; expose no raw receipts/private source.
        rows = self.read_observations(user_id=user_id, epoch=epoch, scope_id=scope_id,
                                      run=run, resolver=resolver)
        ledger = ObservationLedger(resolver)
        for row in rows:
            ledger.record(row)
        return ledger.aggregate(run=run)
