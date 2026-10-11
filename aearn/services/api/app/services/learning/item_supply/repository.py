"""Caller-transaction P3 item-supply root, job, lease and checkpoint repository."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1,
    CoverageBlueprintV1,
    SupplyScopeV1,
)
from app.services.learning.item_supply.jobs import (
    CheckpointV1,
    JobLeaseV1,
    first_missing_stage,
)
from app.services.learning.item_supply.parameter_profiles import (
    ExecutionParameterProfileV1,
    FrozenProfileSnapshot,
    freeze_profile,
)
from app.services.learning.item_supply.policies import (
    CoverageObligationV1,
    FailureClass,
    PoolClass,
    RetryPolicyV1,
    SupplyRuntimeError,
    derive_runtime_contract_hash,
)
from app.services.learning.item_supply.storage_contracts import checked_model


def _key(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()


def aware_time(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise SupplyRuntimeError("AWARE_TIME_REQUIRED")


def server_clock(conn: Connection[dict[str, Any]], now: datetime) -> datetime:
    """Caller timestamps never authorize future budget windows or stale leases."""
    aware_time(now)
    row = conn.execute("SELECT clock_timestamp() AS now").fetchone()
    assert row is not None
    return row["now"]


def lock_private_namespace(
    conn: Connection[dict[str, Any]],
    user_id: UUID | None,
    epoch: int | None,
    scope_id: UUID | None = None,
) -> None:
    """Match reset's user -> epoch -> active-plan order before locking children."""
    if user_id is None or type(epoch) is not int or epoch < 1:
        raise SupplyRuntimeError("PRIVATE_OWNER_REQUIRED")
    user = conn.execute(
        "SELECT id FROM users WHERE id=%s AND deleted_at IS NULL FOR SHARE", (user_id,)
    ).fetchone()
    row = conn.execute(
        "SELECT epoch,enabled FROM tutor_item_supply_user_epochs WHERE user_id=%s FOR SHARE",
        (user_id,),
    ).fetchone()
    if user is None or row is None or row["epoch"] != epoch or not row["enabled"]:
        raise SupplyRuntimeError("PRIVATE_EPOCH_STALE")
    if scope_id is not None:
        scope = conn.execute(
            "SELECT s.id FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p "
            "ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id "
            "WHERE s.id=%s AND s.user_id=%s AND s.epoch=%s FOR SHARE OF s,p",
            (scope_id, user_id, epoch),
        ).fetchone()
        if scope is None:
            raise SupplyRuntimeError("PRIVATE_SCOPE_STALE")


class ItemSupplyRuntimeRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def register_profile(self, profile: ExecutionParameterProfileV1) -> UUID:
        value = checked_model(profile, ExecutionParameterProfileV1)
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_parameter_profiles(profile_key_hash,profile_version,profile_hash,state,profile_json) "
            "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(profile_key_hash,profile_version) DO NOTHING RETURNING id",
            (
                value.profile_key.key_hash,
                value.version,
                value.profile_hash,
                value.state,
                Jsonb(value.model_dump(mode="json")),
            ),
        ).fetchone()
        if row is not None:
            return UUID(str(row["id"]))
        row = self.conn.execute(
            "SELECT id,profile_hash FROM tutor_item_supply_parameter_profiles WHERE profile_key_hash=%s AND profile_version=%s",
            (value.profile_key.key_hash, value.version),
        ).fetchone()
        if row is None or row["profile_hash"] != value.profile_hash:
            raise SupplyRuntimeError("PROFILE_CONFLICT")
        return UUID(str(row["id"]))

    def ensure_shared_root(
        self,
        *,
        blueprint_id: UUID,
        obligation: CoverageObligationV1,
        pool: PoolClass,
        provider_key: str,
    ) -> UUID:
        supplied = checked_model(obligation, CoverageObligationV1)
        row = self.conn.execute(
            "SELECT blueprint_hash,objective_hash,policy_version,snapshot_json FROM tutor_item_supply_shared_blueprints WHERE id=%s FOR SHARE",
            (blueprint_id,),
        ).fetchone()
        if row is None:
            raise SupplyRuntimeError("BLUEPRINT_MISMATCH")
        blueprint = CoverageBlueprintV1.model_validate_json(
            json.dumps(row["snapshot_json"], default=str)
        )
        expected = CoverageObligationV1(
            blueprint_hash=blueprint.blueprint_hash,
            scope_hash=blueprint.scope.scope_hash,
            objective_hash=blueprint.objective_hash,
            purpose=blueprint.scope.purpose.value,
            runtime_contract_hash=derive_runtime_contract_hash(blueprint.scope),
            visibility="public",
            policy_version=blueprint.policy_version,
        )
        if (
            supplied != expected
            or row["blueprint_hash"] != expected.blueprint_hash
            or row["objective_hash"] != expected.objective_hash
            or row["policy_version"] != expected.policy_version
        ):
            raise SupplyRuntimeError("OBLIGATION_AUTHORITY_MISMATCH")
        value = expected
        self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_budget_roots(blueprint_id,canonical_key,policy_class) VALUES(%s,%s,%s) ON CONFLICT(canonical_key) DO NOTHING",
            (blueprint_id, value.canonical_key, value.policy_version),
        )
        root = self.conn.execute(
            "SELECT id,blueprint_id,policy_class FROM tutor_item_supply_shared_budget_roots WHERE canonical_key=%s",
            (value.canonical_key,),
        ).fetchone()
        if (
            root is None
            or root["blueprint_id"] != blueprint_id
            or root["policy_class"] not in {value.policy_version, pool}
        ):
            raise SupplyRuntimeError("ROOT_CONFLICT")
        self.conn.execute(
            "INSERT INTO tutor_item_supply_shared_obligations(root_id,canonical_key,obligation_json,runtime_contract_hash,pool_class,provider_key) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(root_id) DO NOTHING",
            (
                root["id"],
                value.canonical_key,
                Jsonb(value.model_dump(mode="json")),
                value.runtime_contract_hash,
                pool,
                provider_key,
            ),
        )
        exact = self.conn.execute(
            "SELECT canonical_key,pool_class,provider_key,obligation_json FROM tutor_item_supply_shared_obligations WHERE root_id=%s",
            (root["id"],),
        ).fetchone()
        if (
            exact is None
            or exact["canonical_key"] != value.canonical_key
            or exact["pool_class"] != pool
            or exact["provider_key"] != provider_key
            or exact["obligation_json"] != value.model_dump(mode="json")
        ):
            raise SupplyRuntimeError("ROOT_CONFLICT")
        return UUID(str(root["id"]))

    def ensure_private_root(
        self,
        *,
        user_id: UUID,
        epoch: int,
        scope_id: UUID,
        demand_id: UUID,
        obligation: CoverageObligationV1,
        pool: PoolClass,
        provider_key: str,
    ) -> UUID:
        lock_private_namespace(self.conn, user_id, epoch, scope_id)
        supplied = checked_model(obligation, CoverageObligationV1)
        row = self.conn.execute(
            "SELECT s.scope_hash,s.objective_hash,s.snapshot_json,s.track_id,s.revision_id,s.knowledge_key,d.snapshot_json AS demand_json,d.demand_hash "
            "FROM tutor_item_supply_private_scopes s JOIN tutor_item_supply_private_demands d ON d.scope_id=s.id AND d.user_id=s.user_id AND d.epoch=s.epoch "
            "WHERE s.id=%s AND s.user_id=%s AND s.epoch=%s AND d.id=%s FOR SHARE OF s,d",
            (scope_id, user_id, epoch, demand_id),
        ).fetchone()
        if row is None:
            raise SupplyRuntimeError("PRIVATE_AUTHORITY_MISSING")
        scope = SupplyScopeV1.model_validate_json(
            json.dumps(row["snapshot_json"], default=str)
        )
        demand = AssessmentSupplyDemandV1.model_validate_json(
            json.dumps(row["demand_json"], default=str)
        )
        node = self.conn.execute(
            "SELECT n.id,n.title,n.description,n.required_capabilities_json,n.prerequisite_keys_json,t.language_id FROM tutor_track_plan_nodes n "
            "JOIN tutor_track_active_plans p ON p.revision_id=n.revision_id AND p.track_id=n.track_id AND p.user_id=n.user_id "
            "JOIN tutor_learning_tracks t ON t.id=n.track_id AND t.user_id=n.user_id "
            "WHERE n.user_id=%s AND n.track_id=%s AND n.revision_id=%s AND n.knowledge_key=%s FOR SHARE OF n,p",
            (user_id, row["track_id"], row["revision_id"], row["knowledge_key"]),
        ).fetchone()
        if node is None:
            raise SupplyRuntimeError("PRIVATE_AUTHORITY_MISSING")
        bound_hash = canonical_hash(
            {
                "contract": scope.model_dump(mode="json"),
                "track_id": str(row["track_id"]),
                "revision_id": str(row["revision_id"]),
                "node_id": str(node["id"]),
            }
        )
        objective_hash = canonical_hash(
            {
                key: str(value) if isinstance(value, UUID) else value
                for key, value in node.items()
            }
        )
        if (
            demand.scope != scope
            or bound_hash != row["scope_hash"]
            or objective_hash != row["objective_hash"]
            or demand.demand_hash != row["demand_hash"]
            or demand.objective_hash != row["objective_hash"]
        ):
            raise SupplyRuntimeError("PRIVATE_AUTHORITY_MISMATCH")
        expected = CoverageObligationV1(
            blueprint_hash=demand.blueprint_hash,
            scope_hash=str(row["scope_hash"]),
            objective_hash=str(row["objective_hash"]),
            purpose=scope.purpose.value,
            runtime_contract_hash=derive_runtime_contract_hash(scope),
            visibility="private",
            policy_version=demand.policy_version,
            owner_id=user_id,
        )
        if supplied != expected:
            raise SupplyRuntimeError("OBLIGATION_AUTHORITY_MISMATCH")
        value = expected
        self.conn.execute(
            "INSERT INTO tutor_item_supply_private_budget_roots(user_id,epoch,scope_id,canonical_key,policy_class) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,canonical_key) DO NOTHING",
            (user_id, epoch, scope_id, value.canonical_key, value.policy_version),
        )
        root = self.conn.execute(
            "SELECT id,scope_id,policy_class FROM tutor_item_supply_private_budget_roots WHERE user_id=%s AND epoch=%s AND canonical_key=%s",
            (user_id, epoch, value.canonical_key),
        ).fetchone()
        if (
            root is None
            or root["scope_id"] != scope_id
            or root["policy_class"] not in {value.policy_version, pool}
        ):
            raise SupplyRuntimeError("ROOT_CONFLICT")
        self.conn.execute(
            "INSERT INTO tutor_item_supply_private_obligations(user_id,epoch,scope_id,root_id,canonical_key,obligation_json,runtime_contract_hash,pool_class,provider_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,canonical_key) DO NOTHING",
            (
                user_id,
                epoch,
                scope_id,
                root["id"],
                value.canonical_key,
                Jsonb(value.model_dump(mode="json")),
                value.runtime_contract_hash,
                pool,
                provider_key,
            ),
        )
        exact = self.conn.execute(
            "SELECT obligation_json,pool_class,provider_key FROM tutor_item_supply_private_obligations WHERE root_id=%s AND user_id=%s AND epoch=%s",
            (root["id"], user_id, epoch),
        ).fetchone()
        if (
            exact is None
            or exact["obligation_json"] != value.model_dump(mode="json")
            or exact["pool_class"] != pool
            or exact["provider_key"] != provider_key
        ):
            raise SupplyRuntimeError("ROOT_CONFLICT")
        return UUID(str(root["id"]))

    def enqueue(
        self,
        *,
        root_id: UUID,
        stage_key: str,
        profile: ExecutionParameterProfileV1,
        now: datetime,
        priority: int,
        aging_seconds: int,
        visibility: Literal["public", "private"],
        user_id: UUID | None = None,
        epoch: int | None = None,
        scope_id: UUID | None = None,
        parent_job_id: UUID | None = None,
        retry_policy: RetryPolicyV1 | None = None,
    ) -> UUID:
        now = server_clock(self.conn, now)
        profile = checked_model(profile, ExecutionParameterProfileV1)
        retry = (
            None if retry_policy is None else checked_model(retry_policy, RetryPolicyV1)
        )
        if (
            visibility not in {"public", "private"}
            or type(priority) is not int
            or not 0 <= priority <= 1000
            or type(aging_seconds) is not int
            or not 1 <= aging_seconds <= 86400
        ):
            raise SupplyRuntimeError("INVALID_JOB")
        if visibility == "private":
            lock_private_namespace(self.conn, user_id, epoch, scope_id)
        elif any(value is not None for value in (user_id, epoch, scope_id)):
            raise SupplyRuntimeError("PUBLIC_OWNER_FORBIDDEN")
        namespace = "shared" if visibility == "public" else "private"
        root_table = f"tutor_item_supply_{namespace}_obligations"
        params: tuple[Any, ...] = (root_id,)
        owner_sql = ""
        if visibility == "private":
            owner_sql = " AND user_id=%s AND epoch=%s AND scope_id=%s"
            params += (user_id, epoch, scope_id)
        authority = self.conn.execute(
            f"SELECT provider_key FROM {root_table} WHERE root_id=%s" + owner_sql,
            params,
        ).fetchone()
        if authority is None:
            raise SupplyRuntimeError("ROOT_AUTHORITY_MISSING")
        if profile.profile_key.provider != authority["provider_key"]:
            raise SupplyRuntimeError("PROFILE_PROVIDER_MISMATCH")
        if profile.state in {"blocked", "proposed"}:
            raise SupplyRuntimeError("PROFILE_NOT_EXECUTABLE")
        profile_id = self.register_profile(profile)
        snapshot = freeze_profile(profile, bound_at=now)
        envelope = {
            "schema_version": "item_supply_job_snapshot_v1",
            "profile": snapshot.model_dump(mode="json"),
            "retry_policy": None if retry is None else retry.model_dump(mode="json"),
        }
        job_key = _key(root_id, stage_key)
        deadline = now + timedelta(milliseconds=snapshot.values.parent_deadline_ms)
        table = f"tutor_item_supply_{namespace}_jobs"
        controls = f"tutor_item_supply_{namespace}_job_controls"
        if parent_job_id is not None:
            parent = self.conn.execute(
                f"SELECT c.parent_deadline FROM {controls} c JOIN {table} j ON j.id=c.job_id WHERE j.id=%s AND j.root_id=%s",
                (parent_job_id, root_id),
            ).fetchone()
            if parent is None:
                raise SupplyRuntimeError("PARENT_LINEAGE_MISMATCH")
            deadline = min(deadline, parent["parent_deadline"])
        if deadline <= now:
            raise SupplyRuntimeError("PARENT_DEADLINE_EXPIRED")
        snapshot = freeze_profile(profile, bound_at=now, ancestor_deadline=deadline)
        envelope["profile"] = snapshot.model_dump(mode="json")
        state = (
            "queued"
            if profile.state not in {"blocked", "proposed"}
            and retry is not None
            and deadline > now
            else "preparing"
        )
        if visibility == "public":
            self.conn.execute(
                f"INSERT INTO {table}(root_id,parent_job_id,job_key) VALUES(%s,%s,%s) ON CONFLICT(root_id,job_key) DO NOTHING",
                (root_id, parent_job_id, job_key),
            )
        else:
            self.conn.execute(
                f"INSERT INTO {table}(user_id,epoch,scope_id,root_id,parent_job_id,job_key) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(root_id,job_key) DO NOTHING",
                (user_id, epoch, scope_id, root_id, parent_job_id, job_key),
            )
        job = self.conn.execute(
            f"SELECT * FROM {table} WHERE root_id=%s AND job_key=%s", (root_id, job_key)
        ).fetchone()
        if job is None or job["parent_job_id"] != parent_job_id:
            raise SupplyRuntimeError("JOB_CONFLICT")
        if visibility == "private" and (
            job["user_id"],
            job["epoch"],
            job["scope_id"],
        ) != (user_id, epoch, scope_id):
            raise SupplyRuntimeError("PRIVATE_OWNER_CONFLICT")
        if visibility == "public":
            self.conn.execute(
                f"INSERT INTO {controls}(job_id,profile_id,state,priority,aging_seconds,available_at,parent_deadline,profile_snapshot_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(job_id) DO NOTHING",
                (
                    job["id"],
                    profile_id,
                    state,
                    priority,
                    aging_seconds,
                    now,
                    deadline,
                    Jsonb(envelope),
                ),
            )
        else:
            self.conn.execute(
                f"INSERT INTO {controls}(user_id,epoch,scope_id,job_id,profile_id,state,priority,aging_seconds,available_at,parent_deadline,profile_snapshot_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(job_id,user_id,epoch,scope_id) DO NOTHING",
                (
                    user_id,
                    epoch,
                    scope_id,
                    job["id"],
                    profile_id,
                    state,
                    priority,
                    aging_seconds,
                    now,
                    deadline,
                    Jsonb(envelope),
                ),
            )
        # Idempotent enqueue preserves the ORIGINAL in-flight profile/deadline.
        return UUID(str(job["id"]))

    @staticmethod
    def _snapshot(
        row: dict[str, Any],
    ) -> tuple[FrozenProfileSnapshot, RetryPolicyV1 | None]:
        value = row["profile_snapshot_json"]
        try:
            if value.get("schema_version") == "item_supply_job_snapshot_v1":
                if set(value) != {"schema_version", "profile", "retry_policy"}:
                    raise ValueError("invalid snapshot")
                profile = FrozenProfileSnapshot.model_validate_json(
                    json.dumps(value["profile"])
                )
                retry = (
                    None
                    if value["retry_policy"] is None
                    else RetryPolicyV1.model_validate_json(
                        json.dumps(value["retry_policy"])
                    )
                )
            else:
                profile = FrozenProfileSnapshot.model_validate_json(json.dumps(value))
                retry = None
        except (ValueError, TypeError, KeyError):
            raise SupplyRuntimeError("PROFILE_SNAPSHOT_INVALID") from None
        return profile, retry

    def _lease(
        self, row: dict[str, Any], visibility: Literal["public", "private"]
    ) -> JobLeaseV1:
        profile, retry = self._snapshot(row)
        return JobLeaseV1(
            job_id=UUID(str(row["job_id"])),
            visibility=visibility,
            owner_id=row.get("user_id"),
            owner_epoch=row.get("epoch"),
            lease_owner=row["lease_owner"],
            generation=row["lease_generation"],
            state_version=row["state_version"],
            expires_at=row["lease_expires_at"],
            parent_deadline=row["parent_deadline"],
            profile=profile,
            retry_policy=retry,
        )

    def claim(
        self,
        *,
        root_id: UUID,
        lease_owner: str,
        now: datetime,
        lease_seconds: int,
        visibility: Literal["public", "private"],
        user_id: UUID | None = None,
        epoch: int | None = None,
    ) -> JobLeaseV1 | None:
        now = server_clock(self.conn, now)
        if (
            type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 3600
            or visibility not in {"public", "private"}
        ):
            raise SupplyRuntimeError("INVALID_CLAIM")
        import re

        if (
            not isinstance(lease_owner, str)
            or re.fullmatch(r"[A-Za-z0-9._:-]{3,160}", lease_owner) is None
        ):
            raise SupplyRuntimeError("INVALID_WORKER")
        if visibility == "private":
            authority = self.conn.execute(
                "SELECT scope_id FROM tutor_item_supply_private_obligations WHERE root_id=%s AND user_id=%s AND epoch=%s",
                (root_id, user_id, epoch),
            ).fetchone()
            lock_private_namespace(
                self.conn,
                user_id,
                epoch,
                None if authority is None else UUID(str(authority["scope_id"])),
            )
            if authority is None:
                return None
        elif user_id is not None or epoch is not None:
            raise SupplyRuntimeError("PUBLIC_OWNER_FORBIDDEN")
        namespace = "shared" if visibility == "public" else "private"
        table = f"tutor_item_supply_{namespace}_job_controls"
        now = server_clock(self.conn, now)
        owner_sql = (
            " AND c.user_id=%s AND c.epoch=%s" if visibility == "private" else ""
        )
        params: tuple[Any, ...] = (
            (root_id,)
            + ((user_id, epoch) if visibility == "private" else ())
            + (now, now, now, now)
        )
        row = self.conn.execute(
            f"SELECT c.* FROM {table} c JOIN tutor_item_supply_{namespace}_jobs j ON j.id=c.job_id "
            "WHERE j.root_id=%s"
            + owner_sql
            + " AND (c.state IN ('queued','retry_wait') OR (c.state='leased' AND c.lease_expires_at<=%s)) "
            "AND c.available_at<=%s AND c.parent_deadline>%s AND NOT c.breaker_open "
            "ORDER BY (c.priority + LEAST(1000,FLOOR(EXTRACT(EPOCH FROM (%s-c.available_at))/c.aging_seconds))) DESC,c.available_at,c.id FOR UPDATE OF c SKIP LOCKED LIMIT 1",
            params,
        ).fetchone()
        if row is None:
            return None
        if visibility == "private":
            lock_private_namespace(
                self.conn, user_id, epoch, UUID(str(row["scope_id"]))
            )
        snapshot, retry = self._snapshot(row)
        if retry is None:
            self.conn.execute(
                f"UPDATE {table} SET state='preparing',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL WHERE id=%s",
                (row["id"],),
            )
            return None
        if row["attempt_count"] >= retry.max_transient_attempts:
            self.conn.execute(
                f"UPDATE {table} SET state='blocked',breaker_open=true,state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL WHERE id=%s",
                (row["id"],),
            )
            return None
        # Validate frozen identity BEFORE mutating control, never use a new profile.
        expires = min(row["parent_deadline"], now + timedelta(seconds=lease_seconds))
        updated = self.conn.execute(
            f"UPDATE {table} SET state='leased',state_version=state_version+1,lease_generation=lease_generation+1,lease_owner=%s,lease_expires_at=%s,attempt_count=attempt_count+1,updated_at=%s WHERE id=%s AND state_version=%s RETURNING *",
            (lease_owner, expires, now, row["id"], row["state_version"]),
        ).fetchone()
        return None if updated is None else self._lease(updated, visibility)

    def _control(
        self, lease: JobLeaseV1, *, now: datetime, compare_version: bool = True
    ) -> dict[str, Any]:
        checked_model(lease, JobLeaseV1)
        now = server_clock(self.conn, now)
        namespace = "shared" if lease.visibility == "public" else "private"
        table = f"tutor_item_supply_{namespace}_job_controls"
        if lease.visibility == "private":
            meta = self.conn.execute(
                f"SELECT scope_id FROM {table} WHERE job_id=%s AND user_id=%s AND epoch=%s",
                (lease.job_id, lease.owner_id, lease.owner_epoch),
            ).fetchone()
            if meta is None:
                raise SupplyRuntimeError("LEASE_STALE")
            lock_private_namespace(
                self.conn,
                lease.owner_id,
                lease.owner_epoch,
                UUID(str(meta["scope_id"])),
            )
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE job_id=%s FOR UPDATE", (lease.job_id,)
        ).fetchone()
        # Waiting for the owner/control locks may cross expiry. The pre-lock
        # clock cannot authorize a heartbeat or stage effect after that wait.
        now = server_clock(self.conn, now)
        if (
            row is None
            or row["state"] != "leased"
            or row["lease_owner"] != lease.lease_owner
            or row["lease_generation"] != lease.generation
            or row["lease_expires_at"] <= now
            or row["parent_deadline"] <= now
        ):
            raise SupplyRuntimeError("LEASE_STALE")
        profile, retry = self._snapshot(row)
        if (
            lease.profile != profile
            or lease.retry_policy != retry
            or lease.parent_deadline != row["parent_deadline"]
        ):
            raise SupplyRuntimeError("LEASE_IDENTITY_MISMATCH")
        if compare_version and row["state_version"] != lease.state_version:
            raise SupplyRuntimeError("STATE_VERSION_STALE")
        return row

    def refresh_lease(self, lease: JobLeaseV1, *, now: datetime) -> JobLeaseV1:
        return self._lease(
            self._control(lease, now=now, compare_version=False), lease.visibility
        )

    def heartbeat(
        self, lease: JobLeaseV1, *, now: datetime, lease_seconds: int
    ) -> JobLeaseV1:
        now = server_clock(self.conn, now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise SupplyRuntimeError("INVALID_HEARTBEAT")
        row = self._control(lease, now=now)
        now = server_clock(self.conn, now)
        expires = min(
            row["parent_deadline"],
            max(row["lease_expires_at"], now + timedelta(seconds=lease_seconds)),
        )
        table = (
            "tutor_item_supply_shared_job_controls"
            if lease.visibility == "public"
            else "tutor_item_supply_private_job_controls"
        )
        updated = self.conn.execute(
            f"UPDATE {table} SET lease_expires_at=%s,updated_at=%s WHERE id=%s AND state_version=%s RETURNING *",
            (expires, now, row["id"], lease.state_version),
        ).fetchone()
        assert updated is not None
        return self._lease(updated, lease.visibility)

    def checkpoint(
        self, lease: JobLeaseV1, checkpoint: CheckpointV1, *, now: datetime
    ) -> str | None:
        value = checked_model(checkpoint, CheckpointV1)
        row = self._control(lease, now=now, compare_version=False)
        namespace = "shared" if lease.visibility == "public" else "private"
        table = f"tutor_item_supply_{namespace}_checkpoints"
        existing = self.conn.execute(
            f"SELECT * FROM {table} WHERE job_id=%s AND stage=%s AND attempt=%s",
            (lease.job_id, value.stage, value.attempt),
        ).fetchone()
        if existing is not None:
            if (
                existing["status"],
                existing["receipt_hash"],
                existing["safe_reason"],
                existing["lease_generation"],
            ) != (
                value.status,
                value.receipt_hash,
                value.safe_reason,
                lease.generation,
            ):
                raise SupplyRuntimeError("CHECKPOINT_CONFLICT")
            return self.next_stage(lease)
        if row["state_version"] != lease.state_version:
            raise SupplyRuntimeError("STATE_VERSION_STALE")
        if self.next_stage(lease) != value.stage:
            raise SupplyRuntimeError("STAGE_ORDER_MISMATCH")
        if value.attempt != row["attempt_count"]:
            raise SupplyRuntimeError("ATTEMPT_MISMATCH")
        if lease.visibility == "public":
            self.conn.execute(
                f"INSERT INTO {table}(job_id,stage,attempt,status,lease_generation,receipt_hash,safe_reason) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    lease.job_id,
                    value.stage,
                    value.attempt,
                    value.status,
                    lease.generation,
                    value.receipt_hash,
                    value.safe_reason,
                ),
            )
        else:
            self.conn.execute(
                f"INSERT INTO {table}(user_id,epoch,scope_id,job_id,stage,attempt,status,lease_generation,receipt_hash,safe_reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    lease.owner_id,
                    lease.owner_epoch,
                    row["scope_id"],
                    lease.job_id,
                    value.stage,
                    value.attempt,
                    value.status,
                    lease.generation,
                    value.receipt_hash,
                    value.safe_reason,
                ),
            )
        controls = f"tutor_item_supply_{namespace}_job_controls"
        self.conn.execute(
            f"UPDATE {controls} SET state_version=state_version+1,updated_at=%s WHERE id=%s AND state_version=%s",
            (now, row["id"], lease.state_version),
        )
        return self.next_stage(lease)

    def next_stage(self, lease: JobLeaseV1) -> str | None:
        checked_model(lease, JobLeaseV1)
        table = (
            "tutor_item_supply_shared_checkpoints"
            if lease.visibility == "public"
            else "tutor_item_supply_private_checkpoints"
        )
        owner_sql = (
            " AND user_id=%s AND epoch=%s" if lease.visibility == "private" else ""
        )
        params = (lease.job_id,) + (
            (lease.owner_id, lease.owner_epoch) if lease.visibility == "private" else ()
        )
        rows = self.conn.execute(
            f"SELECT stage FROM {table} WHERE job_id=%s AND status='completed'"
            + owner_sql,
            params,
        ).fetchall()
        completed = {str(row["stage"]) for row in rows}
        if lease.visibility == "public" and "generating" not in completed:
            # 491's immutable same-root adoption may satisfy the generation DATA
            # prerequisite, never execution/admission or a stored checkpoint.
            # This is scheduling only: stage owners still resolve through the
            # concrete continuation/C owner before any current stage effect.
            installed = self.conn.execute(
                "SELECT to_regprocedure('item_supply_internal.shared_continuation_generation_inherited(uuid)') IS NOT NULL AS installed"
            ).fetchone()
            if installed is not None and installed["installed"]:
                inherited = self.conn.execute(
                    "SELECT item_supply_internal.shared_continuation_generation_inherited(%s) AS inherited", (lease.job_id,),
                ).fetchone()
                if inherited is not None and inherited["inherited"] is True:
                    completed.add("generating")
        return first_missing_stage(completed)

    def _transition(
        self,
        lease: JobLeaseV1,
        *,
        state: str,
        reason: str,
        now: datetime,
        available_at: datetime | None = None,
        breaker: bool = False,
    ) -> None:
        import re

        if re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,159}", reason) is None:
            raise SupplyRuntimeError("INVALID_REASON")
        row = self._control(lease, now=now)
        namespace = "shared" if lease.visibility == "public" else "private"
        table = f"tutor_item_supply_{namespace}_job_controls"
        updated = self.conn.execute(
            f"UPDATE {table} SET state=%s,state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL,available_at=%s,breaker_open=%s,updated_at=%s WHERE id=%s AND state_version=%s RETURNING state_version",
            (
                state,
                available_at or row["available_at"],
                breaker,
                now,
                row["id"],
                lease.state_version,
            ),
        ).fetchone()
        assert updated is not None
        event_table = f"tutor_item_supply_{namespace}_job_events"
        key = _key(lease.job_id, lease.generation, lease.state_version, state, reason)
        if lease.visibility == "public":
            self.conn.execute(
                f"INSERT INTO {event_table}(job_id,event_key,event_kind,lease_generation,state_version,safe_reason) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    lease.job_id,
                    key,
                    state,
                    lease.generation,
                    updated["state_version"],
                    reason,
                ),
            )
        else:
            self.conn.execute(
                f"INSERT INTO {event_table}(user_id,epoch,scope_id,job_id,event_key,event_kind,lease_generation,state_version,safe_reason) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    lease.owner_id,
                    lease.owner_epoch,
                    row["scope_id"],
                    lease.job_id,
                    key,
                    state,
                    lease.generation,
                    updated["state_version"],
                    reason,
                ),
            )

    def mark_preparing(self, lease: JobLeaseV1, *, reason: str, now: datetime) -> None:
        self._transition(lease, state="preparing", reason=reason, now=now)

    def fail(
        self,
        lease: JobLeaseV1,
        *,
        failure: FailureClass,
        now: datetime,
        retry_after_seconds: int | None = None,
    ) -> str:
        now = server_clock(self.conn, now)
        row = self._control(lease, now=now)
        retry = lease.retry_policy
        retry_at = (
            None
            if retry is None
            else retry.next_retry_at(
                failure=failure,
                attempt=int(row["attempt_count"]),
                now=now,
                parent_deadline=row["parent_deadline"],
                retry_after_seconds=retry_after_seconds,
            )
        )
        state = "retry_wait" if retry_at is not None else "blocked"
        deterministic = failure in {
            FailureClass.DETERMINISTIC,
            FailureClass.SAFETY,
            FailureClass.SCORING,
        }
        self._transition(
            lease,
            state=state,
            reason=f"failure.{failure.value}",
            now=now,
            available_at=retry_at,
            breaker=deterministic or retry_at is None,
        )
        return state

    def complete(self, lease: JobLeaseV1, *, now: datetime) -> None:
        self._control(lease, now=now)
        if self.next_stage(lease) is not None:
            raise SupplyRuntimeError("STAGES_INCOMPLETE")
        # Checkpoints are trusted internal receipts, not production evidence.
        self._transition(
            lease,
            state="completed",
            reason="all_internal_checkpoints_complete",
            now=now,
        )

    def recover_controlled_unspent_setup(self, *, prior_job_id: UUID, root_id: UUID,
            candidate_id: UUID, item_key: str, profile: ExecutionParameterProfileV1,
            window_id: UUID, global_limit_ids: tuple[UUID, ...], prior_intent_hash: str,
            now: datetime, enabled: bool = False) -> tuple[UUID, JobLeaseV1, dict[str, Any]]:
        """ONE default-off B1d pre-author recovery; JSON locators mint no seals.

        Caller transaction includes every check, original cancel, new enqueue and
        exact claim. Existing spend/UNKNOWN or a second recovery is never revived.
        """
        import re
        from psycopg.pq import TransactionStatus
        from app.core.config import DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
        from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository

        if (enabled is not True or type(self) is not ItemSupplyRuntimeRepository
                or self.conn.info.transaction_status != TransactionStatus.INTRANS
                or prior_job_id != UUID("366339e4-bd5b-493c-afe0-65654799fea2")
                or root_id != UUID("7d4b85ba-a0ec-4348-ac11-3401c6bded47")
                or candidate_id != UUID("b3c3a38a-e6d4-49e9-97b0-dec8705f3035")
                or item_key != "native.multi.round.kc."+candidate_id.hex
                or re.fullmatch(r"[0-9a-f]{64}",prior_intent_hash) is None):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_SCOPE_DENIED")
        self.conn.execute("SELECT pg_advisory_xact_lock(hashtextextended('native-v3-canonical-period',0))")
        now = server_clock(self.conn,now)
        if self.conn.execute("SELECT current_database() AS n").fetchone()["n"] != "aearn_b1d_sandbox_20261001":
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_DATABASE_DENIED")
        guard = self.conn.execute("SELECT pg_get_functiondef(to_regprocedure("
            "'item_supply_internal.enforce_controlled_counterexample_insert()')) AS body").fetchone()
        if (guard is None or guard["body"] is None or "OR control_row.root_id IS DISTINCT FROM NEW.root_id" in guard["body"]
                or "shared_jobs sj WHERE sj.id=NEW.job_id AND sj.root_id=NEW.root_id" not in guard["body"]):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_512_REQUIRED")
        row = self.conn.execute("SELECT c.*,j.root_id AS original_root_id,j.job_key,j.parent_job_id "
            "FROM tutor_item_supply_shared_job_controls c JOIN tutor_item_supply_shared_jobs j ON j.id=c.job_id "
            "WHERE j.id=%s FOR UPDATE OF c,j",(prior_job_id,)).fetchone()
        if (row is None or row["original_root_id"]!=root_id or row["parent_job_id"] is not None
                or row["job_key"]!=_key(root_id,"native.multi.round.author."+candidate_id.hex)
                or row["state"]!="leased" or row["lease_owner"]!="native.multi.round."+candidate_id.hex
                or row["lease_generation"]!=1 or row["breaker_open"]):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_ORIGINAL_JOB_DENIED")
        prior_lease = self._lease(row,"public")  # Fresh original DB owner view, NOT JSON hydration.
        self._control(prior_lease,now=now)
        if self.next_stage(prior_lease)!="generating":
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_STAGE_DENIED")
        stage_key = "native.controlled.pre.author.setup.recovery.v1"
        if self.conn.execute("SELECT id FROM tutor_item_supply_shared_jobs WHERE root_id=%s AND job_key=%s",
                (root_id,_key(root_id,stage_key))).fetchone() is not None:
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_ALREADY_ISSUED")
        checks = {
            "reservations":("SELECT count(*) AS n FROM tutor_item_supply_shared_reservations WHERE job_id=%s",(prior_job_id,)),
            "artifacts":("SELECT count(*) AS n FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=%s OR candidate_id=%s",(prior_job_id,candidate_id)),
            "markers":("SELECT count(*) AS n FROM tutor_item_supply_shared_controlled_counterexample_preparations WHERE job_id=%s OR candidate_id=%s",(prior_job_id,candidate_id)),
            "inputs":("SELECT count(*) AS n FROM tutor_item_supply_shared_controlled_counterexample_receipts WHERE job_id=%s OR candidate_id=%s",(prior_job_id,candidate_id)),
            "policy_bindings":("SELECT count(*) AS n FROM tutor_item_supply_shared_generation_policy_bindings WHERE job_id=%s OR candidate_id=%s",(prior_job_id,candidate_id)),
            "pipeline_receipts":("SELECT count(*) AS n FROM tutor_item_supply_shared_pipeline_receipts WHERE job_id=%s",(prior_job_id,)),
            "settlements":("SELECT count(*) AS n FROM tutor_item_supply_shared_runtime_settlements s JOIN tutor_item_supply_shared_reservations r ON r.id=s.reservation_id WHERE r.job_id=%s",(prior_job_id,)),
            "checkpoints":("SELECT count(*) AS n FROM tutor_item_supply_shared_checkpoints WHERE job_id=%s",(prior_job_id,)),
        }
        counts = {name:self.conn.execute(sql,params).fetchone()["n"] for name,(sql,params) in checks.items()}
        if any(n!=0 for n in counts.values()):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_SPEND_OR_EVIDENCE_DENIED")
        old_profile_row = self.conn.execute("SELECT profile_json FROM tutor_item_supply_parameter_profiles WHERE id=%s FOR SHARE",
            (row["profile_id"],)).fetchone()
        if old_profile_row is None:
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_PROFILE_DENIED")
        old_profile = ExecutionParameterProfileV1.model_validate_json(json.dumps(old_profile_row["profile_json"]))
        profile = checked_model(profile,ExecutionParameterProfileV1)
        if (old_profile.profile_hash!=prior_lease.profile.profile_hash or profile.profile_key!=old_profile.profile_key
                or profile.state!=old_profile.state or profile.version<=old_profile.version
                or any(getattr(profile,k)!=getattr(old_profile,k) for k in
                    ("initial","current","last_stable","floor","ceiling","trusted_initial_evidence"))
                or profile.profile_key.provider!="deepseek" or profile.profile_key.model_version!="deepseek-flash"
                or self.conn.execute("SELECT id FROM tutor_item_supply_parameter_profiles WHERE profile_key_hash=%s AND profile_version=%s",
                    (profile.profile_key.key_hash,profile.version)).fetchone() is not None):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_PROFILE_DENIED")
        original_deadline = min(prior_lease.expires_at,prior_lease.parent_deadline,prior_lease.profile.parent_deadline_at,
            prior_lease.profile.bound_at+timedelta(milliseconds=prior_lease.profile.values.stage_deadline_ms))
        if (profile.current.parent_deadline_ms!=3600000 or profile.current.stage_deadline_ms!=3600000):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_TIME_DENIED")
        # New, still-unfunded job gets its own original 3600s profile. No field
        # of the cancelled old job/profile or the existing window is extended.
        deadline = now+timedelta(seconds=3600)
        caps = dict(requests=17,input_tokens=4194304,output_tokens=17*DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
            execution_seconds=1,fetches=1,candidates=2,revision_rounds=1,investigation_rounds=1)
        dimensions = {("system","item-supply"),("window","item-supply"),("pool","base"),("provider","deepseek")}
        limits = self.conn.execute("SELECT * FROM tutor_item_supply_runtime_global_limits WHERE window_start<=%s AND window_end>%s "
            "AND ((dimension_kind='system' AND dimension_key='item-supply') OR (dimension_kind='window' AND dimension_key='item-supply') "
            "OR (dimension_kind='pool' AND dimension_key='base') OR (dimension_kind='provider' AND dimension_key='deepseek')) FOR UPDATE",
            (now,now)).fetchall()
        budget = ItemSupplyBudgetRepository(self.conn)
        windows = self.conn.execute("SELECT * FROM tutor_item_supply_shared_budget_windows WHERE window_start<=%s AND window_end>%s FOR UPDATE",
            (now,now)).fetchall()
        if (len(limits)!=32 or len(global_limit_ids)!=32 or {r["id"] for r in limits}!=set(global_limit_ids)
                or {(r["dimension_kind"],r["dimension_key"],r["resource_kind"]) for r in limits}
                    != {(d,k,t) for d,k in dimensions for t in caps}
                or any(r["cap_amount"]!=caps[r["resource_kind"]] or budget._global_used(r["id"],r["resource_kind"])!=0
                    or r["window_end"]<deadline for r in limits)
                or len(windows)!=1 or windows[0]["id"]!=window_id or windows[0]["root_id"]!=root_id
                or windows[0]["pool_key"]!="base" or windows[0]["provider_key"]!="deepseek"
                or windows[0]["request_cap"]!=17 or windows[0]["token_cap"]!=caps["input_tokens"]+caps["output_tokens"]
                or windows[0]["resource_cap"]!=1 or windows[0]["window_end"]<deadline
                or any(budget._root_used("shared",root_id,window_id).values())):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_UNUSED_WINDOW_DENIED")
        self.cancel(prior_lease,now=now)  # Original transition and immutable cancellation event.
        new_job = self.enqueue(root_id=root_id,stage_key=stage_key,profile=profile,now=now,
            priority=row["priority"],aging_seconds=row["aging_seconds"],visibility="public",
            retry_policy=prior_lease.retry_policy)
        lease = self.claim(root_id=root_id,lease_owner="native.controlled.setup.recovery."+candidate_id.hex,
            now=now,lease_seconds=3600,visibility="public")
        if lease is None or lease.job_id!=new_job:
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_EXACT_CLAIM_ROLLBACK_REQUIRED")
        if lease.parent_deadline>windows[0]["window_end"] or any(lease.parent_deadline>r["window_end"] for r in limits):
            raise SupplyRuntimeError("CONTROLLED_SETUP_RECOVERY_TIME_DENIED")
        self.conn.execute("INSERT INTO tutor_item_supply_shared_job_events "
            "(job_id,event_key,event_kind,lease_generation,state_version,safe_reason) VALUES(%s,%s,%s,%s,%s,%s)",
            (new_job,_key(prior_intent_hash,prior_job_id,"controlled.setup.recovery.v1"),"setup_recovery_claimed",
                lease.generation,lease.state_version,"controlled_unspent_setup_recovery"))
        return new_job,lease,dict(schema_version="controlled_unspent_setup_recovery_db_v1",prior_job_id=str(prior_job_id),
            new_job_id=str(new_job),candidate_id=str(candidate_id),root_id=str(root_id),prior_intent_hash=prior_intent_hash,
            verified_original_counts=counts,original_deadline=original_deadline.isoformat(),new_parent_deadline=lease.parent_deadline.isoformat(),
            old_deadline_modified=False,new_unfunded_profile_parent_ms=3600000,
            account_billing_zero_asserted=False,json_capability_restored=False,new_budget_window_created=False)

    def cancel(self, lease: JobLeaseV1, *, now: datetime) -> None:
        self._control(lease, now=now)
        if lease.visibility == "public":
            active = self.conn.execute(
                "SELECT id FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=%s AND state='active' LIMIT 1",
                (lease.job_id,),
            ).fetchone()
            if active is not None:
                raise SupplyRuntimeError("SHARED_CONSUMERS_ACTIVE")
        self._transition(lease, state="cancelled", reason="owner_cancelled", now=now)

    def cancel_shared_subscription(
        self, *, subscription_id: UUID, user_id: UUID, epoch: int, now: datetime
    ) -> bool:
        now = server_clock(self.conn, now)
        row = self.conn.execute(
            "SELECT scope_id,shared_job_id FROM tutor_item_supply_private_subscriptions WHERE id=%s AND user_id=%s AND epoch=%s",
            (subscription_id, user_id, epoch),
        ).fetchone()
        if row is None:
            return False
        lock_private_namespace(self.conn, user_id, epoch, UUID(str(row["scope_id"])))
        self.conn.execute(
            "UPDATE tutor_item_supply_private_subscriptions SET state='cancelled',state_version=state_version+1,updated_at=%s WHERE id=%s AND user_id=%s AND epoch=%s AND state='active'",
            (now, subscription_id, user_id, epoch),
        )
        # Consumer cancellation NEVER implicitly cancels the shared producer.
        remaining = self.conn.execute(
            "SELECT count(*)::int AS n FROM tutor_item_supply_private_subscriptions WHERE shared_job_id=%s AND state='active'",
            (row["shared_job_id"],),
        ).fetchone()
        return bool(remaining and remaining["n"] > 0)
