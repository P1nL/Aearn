"""Atomic multi-dimensional P3 reservations and append-only usage settlement."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from psycopg import Connection
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import (
    RESOURCE_KINDS,
    ResourceAmounts,
    ResourceKind,
    SupplyRuntimeError,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.repository import (
    ItemSupplyRuntimeRepository,
    server_clock,
    lock_private_namespace,
)


@dataclass(frozen=True)
class ReservationResult:
    allowed: bool
    reason: str
    reservation_id: UUID | None = None


@dataclass(frozen=True)
class SettlementResult:
    state: str
    sequence: int


class ItemSupplyBudgetRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def register_global_limit(
        self,
        *,
        dimension_kind: Literal["system", "provider", "window", "pool"],
        dimension_key: str,
        resource_kind: ResourceKind,
        window_start: datetime,
        window_end: datetime,
        cap_amount: int,
    ) -> UUID:
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_runtime_global_limits(dimension_kind,dimension_key,resource_kind,window_start,window_end,cap_amount) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(dimension_kind,dimension_key,resource_kind,window_start) DO NOTHING RETURNING id",
            (
                dimension_kind,
                dimension_key,
                resource_kind,
                window_start,
                window_end,
                cap_amount,
            ),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id,window_end,cap_amount FROM tutor_item_supply_runtime_global_limits WHERE dimension_kind=%s AND dimension_key=%s AND resource_kind=%s AND window_start=%s",
                (dimension_kind, dimension_key, resource_kind, window_start),
            ).fetchone()
            if (
                row is None
                or row["window_end"] != window_end
                or row["cap_amount"] != cap_amount
            ):
                raise SupplyRuntimeError("LIMIT_CONFLICT")
        return UUID(str(row["id"]))

    def register_user_limit(
        self,
        *,
        user_id: UUID,
        epoch: int,
        resource_kind: ResourceKind,
        window_start: datetime,
        window_end: datetime,
        cap_amount: int,
    ) -> UUID:
        row = self.conn.execute(
            "INSERT INTO tutor_item_supply_private_runtime_user_limits(user_id,epoch,resource_kind,window_start,window_end,cap_amount) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(user_id,epoch,resource_kind,window_start) DO NOTHING RETURNING id",
            (user_id, epoch, resource_kind, window_start, window_end, cap_amount),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id,window_end,cap_amount FROM tutor_item_supply_private_runtime_user_limits WHERE user_id=%s AND epoch=%s AND resource_kind=%s AND window_start=%s",
                (user_id, epoch, resource_kind, window_start),
            ).fetchone()
            if (
                row is None
                or row["window_end"] != window_end
                or row["cap_amount"] != cap_amount
            ):
                raise SupplyRuntimeError("LIMIT_CONFLICT")
        return UUID(str(row["id"]))

    def reserve(
        self,
        *,
        lease: JobLeaseV1,
        reservation_key: str,
        amounts: ResourceAmounts,
        now: datetime,
    ) -> ReservationResult:
        now = server_clock(self.conn, now)
        self._validate_key(reservation_key)
        requested = checked_model(amounts, ResourceAmounts)
        if not requested.positive():
            return ReservationResult(False, "EMPTY_RESERVATION")
        # P2's legacy envelope cannot encode execution-only yet. Never invent
        # request/token consumption just to satisfy its CHECK constraints.
        if (
            requested.requests <= 0
            or requested.input_tokens + requested.output_tokens <= 0
        ):
            return ReservationResult(
                False, "LEGACY_ENVELOPE_REQUIRES_REQUEST_AND_TOKEN"
            )
        return self._reserve_budget(lease=lease, reservation_key=reservation_key,
                                    requested=requested, now=now)

    def reserve_execution(
        self, *, lease: JobLeaseV1, intent_id: UUID, now: datetime,
    ) -> ReservationResult:
        """Trusted private P6 entry; never fabricate provider requests or tokens."""
        from app.services.learning.item_supply.sandbox.repository import SandboxRepository

        repository = SandboxRepository(self.conn)
        intent = repository.get_intent(lease=lease, intent_id=intent_id, now=now)
        return self._reserve_budget(lease=lease, reservation_key=intent.reservation_key,
                                    requested=intent.resources, now=now, intent_id=intent_id)

    def _reserve_budget(
        self, *, lease: JobLeaseV1, reservation_key: str,
        requested: ResourceAmounts, now: datetime, intent_id: UUID | None = None,
    ) -> ReservationResult:
        # Both entrances share exactly the original cumulative locking/accounting.
        now = server_clock(self.conn, now)
        meta = self._job_meta(lease, now=now)
        # Replays are checked BEFORE current-window/cap tests: an exhausted or
        # expired window must not turn the same reservation into new spending.
        replay = self._reservation_by_key(lease, reservation_key)
        if replay is not None:
            if (
                replay["lease_generation"] != lease.generation
                or self._reservation_amounts(lease, UUID(str(replay["id"])))
                != requested.as_dict()
            ):
                raise SupplyRuntimeError("RESERVATION_CONFLICT")
            return ReservationResult(True, "REPLAY", UUID(str(replay["id"])))
        rows, user_rows = self._active_limits(meta, lease, now)
        if rows is None:
            return ReservationResult(False, "BUDGET_CONFIGURATION_MISSING")
        if user_rows is None:
            return ReservationResult(False, "USER_BUDGET_CONFIGURATION_MISSING")
        namespace = "shared" if lease.visibility == "public" else "private"
        root_table = f"tutor_item_supply_{namespace}_budget_roots"
        self.conn.execute(
            f"SELECT id FROM {root_table} WHERE id=%s FOR UPDATE", (meta["root_id"],)
        ).fetchone()
        windows = self.conn.execute(
            f"SELECT * FROM tutor_item_supply_{namespace}_budget_windows WHERE root_id=%s AND pool_key=%s AND provider_key=%s AND window_start<=%s AND window_end>%s ORDER BY window_start,id FOR UPDATE",
            (meta["root_id"], meta["pool_class"], meta["provider_key"], now, now),
        ).fetchall()
        if len(windows) != 1:
            return ReservationResult(
                False, "ROOT_WINDOW_MISSING" if not windows else "ROOT_WINDOW_AMBIGUOUS"
            )
        window = windows[0]
        now = server_clock(self.conn, now)
        # All limits and the root window were locked after the live control.
        # Recheck both time fences AFTER waiting for cumulative-budget locks.
        self._job_meta(lease, now=now)
        if intent_id is not None:
            from app.services.learning.item_supply.sandbox.repository import SandboxRepository

            SandboxRepository(self.conn).get_intent(lease=lease, intent_id=intent_id, now=now)
        if any(
            not limit["window_start"] <= now < limit["window_end"]
            for limit in rows + user_rows
        ):
            return ReservationResult(False, "BUDGET_CONFIGURATION_MISSING")
        if not window["window_start"] <= now < window["window_end"]:
            return ReservationResult(False, "ROOT_WINDOW_MISSING")
        root_used = self._root_used(
            namespace, UUID(str(meta["root_id"])), UUID(str(window["id"]))
        )
        if (
            root_used["requests"] + requested.requests > window["request_cap"]
            or root_used["input_tokens"]
            + root_used["output_tokens"]
            + requested.input_tokens
            + requested.output_tokens
            > window["token_cap"]
        ):
            return ReservationResult(False, "ROOT_CAP_EXHAUSTED")
        amount_map = requested.as_dict()
        # All active cumulative windows are enforced, not just the newest one.
        for limit in rows:
            if (
                self._global_used(UUID(str(limit["id"])), str(limit["resource_kind"]))
                + amount_map[limit["resource_kind"]]
                > limit["cap_amount"]
            ):
                return ReservationResult(
                    False, f"{str(limit['dimension_kind']).upper()}_CAP_EXHAUSTED"
                )
        for limit in user_rows:
            if (
                self._user_used(UUID(str(limit["id"])), str(limit["resource_kind"]))
                + amount_map[limit["resource_kind"]]
                > limit["cap_amount"]
            ):
                return ReservationResult(False, "USER_CAP_EXHAUSTED")
        if lease.visibility == "public":
            reservation = self.conn.execute(
                "INSERT INTO tutor_item_supply_shared_reservations(root_id,window_id,job_id,lease_generation,reservation_key,requests,tokens,resources) VALUES(%s,%s,%s,%s,%s,%s,%s,0) RETURNING id",
                (
                    meta["root_id"],
                    window["id"],
                    lease.job_id,
                    lease.generation,
                    reservation_key,
                    requested.requests,
                    requested.input_tokens + requested.output_tokens,
                ),
            ).fetchone()
        else:
            reservation = self.conn.execute(
                "INSERT INTO tutor_item_supply_private_reservations(user_id,epoch,scope_id,root_id,window_id,job_id,lease_generation,reservation_key,requests,tokens,resources) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0) RETURNING id",
                (
                    lease.owner_id,
                    lease.owner_epoch,
                    meta["scope_id"],
                    meta["root_id"],
                    window["id"],
                    lease.job_id,
                    lease.generation,
                    reservation_key,
                    requested.requests,
                    requested.input_tokens + requested.output_tokens,
                ),
            ).fetchone()
        assert reservation is not None
        rid = UUID(str(reservation["id"]))
        for limit in rows:
            self.conn.execute(
                "INSERT INTO tutor_item_supply_runtime_global_reservation_amounts(reservation_namespace,reservation_id,limit_id,resource_kind,reserved_amount) VALUES(%s,%s,%s,%s,%s)",
                (
                    namespace,
                    rid,
                    limit["id"],
                    limit["resource_kind"],
                    amount_map[limit["resource_kind"]],
                ),
            )
        for limit in user_rows:
            self.conn.execute(
                "INSERT INTO tutor_item_supply_private_runtime_reservation_amounts(user_id,epoch,scope_id,reservation_id,limit_id,resource_kind,reserved_amount) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    lease.owner_id,
                    lease.owner_epoch,
                    meta["scope_id"],
                    rid,
                    limit["id"],
                    limit["resource_kind"],
                    amount_map[limit["resource_kind"]],
                ),
            )
        return ReservationResult(True, "RESERVED", rid)

    def _active_limits(
        self, meta: dict[str, Any], lease: JobLeaseV1, now: datetime
    ) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None]:
        # Universal lock order: owner/active plan -> control (reserve only) ->
        # GLOBAL sorted dimension/key/resource/id -> USER sorted resource/id ->
        # root -> root-window -> reservation. Settlement uses the same order.
        keys = {
            "system": "item-supply",
            "provider": str(meta["provider_key"]),
            "window": "item-supply",
            "pool": str(meta["pool_class"]),
        }
        rows = self.conn.execute(
            "SELECT * FROM tutor_item_supply_runtime_global_limits WHERE window_start<=%s AND window_end>%s AND ((dimension_kind='system' AND dimension_key=%s) OR (dimension_kind='provider' AND dimension_key=%s) OR (dimension_kind='window' AND dimension_key=%s) OR (dimension_kind='pool' AND dimension_key=%s)) ORDER BY dimension_kind,dimension_key,resource_kind,id FOR UPDATE",
            (now, now, keys["system"], keys["provider"], keys["window"], keys["pool"]),
        ).fetchall()
        covered = {(r["dimension_kind"], r["resource_kind"]) for r in rows}
        if covered != {
            (dimension, kind) for dimension in keys for kind in RESOURCE_KINDS
        }:
            return None, []
        user_rows: list[dict[str, Any]] = []
        if lease.visibility == "private":
            user_rows = self.conn.execute(
                "SELECT * FROM tutor_item_supply_private_runtime_user_limits WHERE user_id=%s AND epoch=%s AND window_start<=%s AND window_end>%s ORDER BY resource_kind,id FOR UPDATE",
                (lease.owner_id, lease.owner_epoch, now, now),
            ).fetchall()
            if {r["resource_kind"] for r in user_rows} != set(RESOURCE_KINDS):
                return rows, None
        return rows, user_rows

    def settle(
        self,
        *,
        lease: JobLeaseV1,
        reservation_id: UUID,
        settlement_key: str,
        usage_state: Literal["known", "unknown"],
        actual: ResourceAmounts | None,
        cost_amount: Decimal | None,
        receipt_hash: str | None,
        reconcile: bool = False,
    ) -> SettlementResult:
        self._validate_key(settlement_key)
        if type(reconcile) is not bool:
            raise SupplyRuntimeError("INVALID_RECONCILIATION")
        if usage_state not in {"known", "unknown"}:
            raise SupplyRuntimeError("INVALID_USAGE_STATE")
        if usage_state == "unknown" and (
            actual is not None or receipt_hash is not None
        ):
            raise SupplyRuntimeError("UNKNOWN_USAGE_SHAPE")
        if usage_state == "known" and (actual is None or receipt_hash is None):
            raise SupplyRuntimeError("KNOWN_USAGE_SHAPE")
        import re

        if (
            receipt_hash is not None
            and re.fullmatch(r"[0-9a-f]{64}", receipt_hash) is None
        ):
            raise SupplyRuntimeError("INVALID_RECEIPT")
        if cost_amount is not None and (
            not isinstance(cost_amount, Decimal)
            or not cost_amount.is_finite()
            or cost_amount < 0
        ):
            raise SupplyRuntimeError("INVALID_COST")
        meta = self._job_meta(lease, require_live=False)
        namespace = "shared" if lease.visibility == "public" else "private"
        reservation_table = f"tutor_item_supply_{namespace}_reservations"
        # Ownership/generation check BEFORE looking up allocations. Lost workers
        # may settle only THEIR original reservation, never a new generation's.
        reservation = self.conn.execute(
            f"SELECT * FROM {reservation_table} WHERE id=%s AND job_id=%s",
            (reservation_id, lease.job_id),
        ).fetchone()
        if reservation is None or reservation["lease_generation"] != lease.generation:
            raise SupplyRuntimeError("RESERVATION_UNAVAILABLE")
        self._lock_allocations(namespace, reservation_id)
        self.conn.execute(
            f"SELECT id FROM tutor_item_supply_{namespace}_budget_roots WHERE id=%s FOR UPDATE",
            (meta["root_id"],),
        ).fetchone()
        self.conn.execute(
            f"SELECT id FROM tutor_item_supply_{namespace}_budget_windows WHERE id=%s FOR UPDATE",
            (reservation["window_id"],),
        ).fetchone()
        self.conn.execute(
            f"SELECT id FROM {reservation_table} WHERE id=%s FOR UPDATE",
            (reservation_id,),
        ).fetchone()
        table = f"tutor_item_supply_{namespace}_runtime_settlements"
        amount_table = f"tutor_item_supply_{namespace}_runtime_settlement_amounts"
        expected: dict[str, int] = (
            {}
            if actual is None
            else {
                str(kind): value
                for kind, value in checked_model(actual, ResourceAmounts)
                .as_dict()
                .items()
            }
        )
        # Recheck replay AFTER locks: concurrent equal callbacks serialize.
        replay = self.conn.execute(
            f"SELECT * FROM {table} WHERE reservation_id=%s AND settlement_key=%s",
            (reservation_id, settlement_key),
        ).fetchone()
        if replay is not None:
            stored = self._settlement_amounts(namespace, UUID(str(replay["id"])))
            if (
                replay["usage_state"],
                replay["cost_amount"],
                replay["receipt_hash"],
                stored,
            ) != (usage_state, cost_amount, receipt_hash, expected):
                raise SupplyRuntimeError("SETTLEMENT_CONFLICT")
            return SettlementResult(str(replay["usage_state"]), int(replay["sequence"]))
        latest = self.conn.execute(
            f"SELECT * FROM {table} WHERE reservation_id=%s ORDER BY sequence DESC LIMIT 1",
            (reservation_id,),
        ).fetchone()
        known = self.conn.execute(
            f"SELECT * FROM {table} WHERE reservation_id=%s AND usage_state='known' ORDER BY sequence DESC LIMIT 1",
            (reservation_id,),
        ).fetchone()
        if known is not None:
            stored = self._settlement_amounts(namespace, UUID(str(known["id"])))
            if usage_state == "known" and not reconcile:
                if any(
                    expected.get(kind, 0) < amount for kind, amount in stored.items()
                ) or (
                    known["cost_amount"] is not None
                    and (cost_amount is None or cost_amount < known["cost_amount"])
                ):
                    raise SupplyRuntimeError("RECONCILIATION_REQUIRED")
        sequence = 1 if latest is None else int(latest["sequence"]) + 1
        if lease.visibility == "public":
            row = self.conn.execute(
                f"INSERT INTO {table}(reservation_id,sequence,settlement_key,usage_state,cost_amount,receipt_hash) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    reservation_id,
                    sequence,
                    settlement_key,
                    usage_state,
                    cost_amount,
                    receipt_hash,
                ),
            ).fetchone()
        else:
            row = self.conn.execute(
                f"INSERT INTO {table}(user_id,epoch,scope_id,reservation_id,sequence,settlement_key,usage_state,cost_amount,receipt_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (
                    lease.owner_id,
                    lease.owner_epoch,
                    meta["scope_id"],
                    reservation_id,
                    sequence,
                    settlement_key,
                    usage_state,
                    cost_amount,
                    receipt_hash,
                ),
            ).fetchone()
        assert row is not None
        for kind, amount in expected.items():
            if lease.visibility == "public":
                self.conn.execute(
                    f"INSERT INTO {amount_table}(settlement_id,resource_kind,actual_amount) VALUES(%s,%s,%s)",
                    (row["id"], kind, amount),
                )
            else:
                self.conn.execute(
                    f"INSERT INTO {amount_table}(user_id,epoch,scope_id,settlement_id,resource_kind,actual_amount) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        lease.owner_id,
                        lease.owner_epoch,
                        meta["scope_id"],
                        row["id"],
                        kind,
                        amount,
                    ),
                )
        # Retained anonymous facts are independent of private payload purge.
        # They carry no owner/scope/content/receipt/client keys. Same transaction
        # as detailed settlement; a failure rolls back BOTH ledgers.
        for kind in RESOURCE_KINDS:
            self.conn.execute(
                "INSERT INTO tutor_item_supply_runtime_global_usage_facts(reservation_namespace,reservation_id,settlement_id,sequence,resource_kind,usage_state,actual_amount) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    namespace,
                    reservation_id,
                    row["id"],
                    sequence,
                    kind,
                    usage_state,
                    None if usage_state == "unknown" else expected[kind],
                ),
            )
        # Actual overage is deliberately NOT checked against cap on settlement:
        # it is immutable truth and consumes capacity before further work.
        return SettlementResult(usage_state, sequence)

    def _lock_allocations(self, namespace: str, rid: UUID) -> None:
        self.conn.execute(
            "SELECT l.id FROM tutor_item_supply_runtime_global_limits l JOIN tutor_item_supply_runtime_global_reservation_amounts a ON a.limit_id=l.id WHERE a.reservation_namespace=%s AND a.reservation_id=%s ORDER BY l.dimension_kind,l.dimension_key,l.resource_kind,l.id FOR UPDATE OF l",
            (namespace, rid),
        ).fetchall()
        if namespace == "private":
            self.conn.execute(
                "SELECT l.id FROM tutor_item_supply_private_runtime_user_limits l JOIN tutor_item_supply_private_runtime_reservation_amounts a ON a.limit_id=l.id WHERE a.reservation_id=%s ORDER BY l.resource_kind,l.id FOR UPDATE OF l",
                (rid,),
            ).fetchall()

    def _job_meta(
        self, lease: JobLeaseV1, require_live: bool = True, now: datetime | None = None
    ) -> dict[str, Any]:
        checked_model(lease, JobLeaseV1)
        namespace = "shared" if lease.visibility == "public" else "private"
        if require_live:
            if now is None:
                raise SupplyRuntimeError("AWARE_TIME_REQUIRED")
            ItemSupplyRuntimeRepository(self.conn)._control(lease, now=now)
        if lease.visibility == "private":
            scope = self.conn.execute(
                "SELECT scope_id FROM tutor_item_supply_private_jobs WHERE id=%s AND user_id=%s AND epoch=%s",
                (lease.job_id, lease.owner_id, lease.owner_epoch),
            ).fetchone()
            if scope is None:
                raise SupplyRuntimeError("JOB_UNAVAILABLE")
            lock_private_namespace(
                self.conn,
                lease.owner_id,
                lease.owner_epoch,
                UUID(str(scope["scope_id"])),
            )
        owner_sql = (
            " AND j.user_id=%s AND j.epoch=%s" if lease.visibility == "private" else ""
        )
        params = (lease.job_id,) + (
            (lease.owner_id, lease.owner_epoch) if lease.visibility == "private" else ()
        )
        row = self.conn.execute(
            "SELECT j.root_id,o.pool_class,o.provider_key,"
            + ("j.scope_id" if namespace == "private" else "NULL::uuid AS scope_id")
            + f" FROM tutor_item_supply_{namespace}_jobs j JOIN tutor_item_supply_{namespace}_obligations o ON o.root_id=j.root_id WHERE j.id=%s"
            + owner_sql,
            params,
        ).fetchone()
        if row is None:
            raise SupplyRuntimeError("JOB_UNAVAILABLE")
        return row

    @staticmethod
    def _validate_key(key: str) -> None:
        import re

        if (
            not isinstance(key, str)
            or re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,159}", key) is None
        ):
            raise SupplyRuntimeError("INVALID_IDEMPOTENCY_KEY")

    def _reservation_by_key(self, lease: JobLeaseV1, key: str) -> dict[str, Any] | None:
        namespace = "shared" if lease.visibility == "public" else "private"
        return self.conn.execute(
            f"SELECT * FROM tutor_item_supply_{namespace}_reservations WHERE job_id=%s AND reservation_key=%s",
            (lease.job_id, key),
        ).fetchone()

    def _reservation_amounts(self, lease: JobLeaseV1, rid: UUID) -> dict[str, int]:
        namespace = "shared" if lease.visibility == "public" else "private"
        rows = self.conn.execute(
            "SELECT DISTINCT resource_kind,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts WHERE reservation_namespace=%s AND reservation_id=%s",
            (namespace, rid),
        ).fetchall()
        return {str(row["resource_kind"]): int(row["reserved_amount"]) for row in rows}

    def _settlement_amounts(self, namespace: str, sid: UUID) -> dict[str, int]:
        namespace = "shared" if namespace == "public" else namespace
        rows = self.conn.execute(
            f"SELECT resource_kind,actual_amount FROM tutor_item_supply_{namespace}_runtime_settlement_amounts WHERE settlement_id=%s",
            (sid,),
        ).fetchall()
        return {str(row["resource_kind"]): int(row["actual_amount"]) for row in rows}

    def _root_used(
        self, namespace: str, root_id: UUID, window_id: UUID
    ) -> dict[str, int]:
        rows = self.conn.execute(
            f"SELECT id FROM tutor_item_supply_{namespace}_reservations WHERE root_id=%s AND window_id=%s",
            (root_id, window_id),
        ).fetchall()
        totals: dict[str, int] = {kind: 0 for kind in RESOURCE_KINDS}
        for row in rows:
            rid = UUID(str(row["id"]))
            allocations = self.conn.execute(
                "SELECT DISTINCT resource_kind,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts WHERE reservation_namespace=%s AND reservation_id=%s",
                (namespace, rid),
            ).fetchall()
            for item in allocations:
                kind = str(item["resource_kind"])
                totals[kind] += self._effective(
                    namespace, rid, kind, int(item["reserved_amount"])
                )
        return totals

    def _global_used(self, limit_id: UUID, kind: str) -> int:
        rows = self.conn.execute(
            "SELECT reservation_namespace,reservation_id,reserved_amount FROM tutor_item_supply_runtime_global_reservation_amounts WHERE limit_id=%s AND resource_kind=%s",
            (limit_id, kind),
        ).fetchall()
        return sum(
            self._effective(
                str(row["reservation_namespace"]),
                UUID(str(row["reservation_id"])),
                kind,
                int(row["reserved_amount"]),
            )
            for row in rows
        )

    def _user_used(self, limit_id: UUID, kind: str) -> int:
        rows = self.conn.execute(
            "SELECT reservation_id,reserved_amount FROM tutor_item_supply_private_runtime_reservation_amounts WHERE limit_id=%s AND resource_kind=%s",
            (limit_id, kind),
        ).fetchall()
        return sum(
            self._effective(
                "private",
                UUID(str(row["reservation_id"])),
                kind,
                int(row["reserved_amount"]),
            )
            for row in rows
        )

    def _effective(self, namespace: str, rid: UUID, kind: str, reserved: int) -> int:
        visibility = "shared" if namespace in {"public", "shared"} else "private"
        facts = self.conn.execute(
            "SELECT sequence,resource_kind,usage_state,actual_amount FROM tutor_item_supply_runtime_global_usage_facts WHERE reservation_namespace=%s AND reservation_id=%s ORDER BY sequence DESC,resource_kind",
            (visibility, rid),
        ).fetchall()
        known_peak = max(
            (
                int(row["actual_amount"])
                for row in facts
                if row["resource_kind"] == kind
                and row["usage_state"] == "known"
                and row["actual_amount"] is not None
            ),
            default=0,
        )
        if not facts:
            # Legacy allocations without retained facts remain conservatively
            # occupied; schema owner's additive backfill preserves old actuals.
            return reserved
        latest_sequence = facts[0]["sequence"]
        latest = {
            str(row["resource_kind"]): row
            for row in facts
            if row["sequence"] == latest_sequence
        }
        if set(latest) != set(RESOURCE_KINDS):
            return max(reserved, known_peak)
        fact = latest[kind]
        if fact["usage_state"] != "known" or fact["actual_amount"] is None:
            return max(reserved, known_peak)
        # Only a full explicit known receipt may release conservative capacity.
        return int(fact["actual_amount"])
