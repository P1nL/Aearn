"""Global Tutor thread/turn v2 protocol cutover authority."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Literal

from psycopg import Connection

from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.services.tutor.cutover import CutoverError

THREAD_TURN_CUTOVER_VERSION = "tutor_thread_turn_v2_global_v1"
THREAD_TURN_CAPABILITY_VERSION = "tutor_thread_turn_v2_capability_v1"
THREAD_TURN_DESKTOP_CONTRACT_VERSION = "tutor_thread_turn_v2_desktop_v1"
_ADVISORY_LOCK_KEY = "aearn:tutor-thread-turn-v2-cutover"
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_ACTIVE_LEGACY_STATUSES = ("queued", "leased", "running", "waiting_for_capability")


class TutorThreadTurnCutoverService:
    """Own the global protocol generation, migration inventory, and effective gate."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def status(self, *, settings: Settings | None = None) -> dict[str, object]:
        record = self._ensure_record()
        env_allowed = (settings or get_settings()).tutor_thread_turn_v2_enabled
        state = str(record["state"])
        return {
            "schema_version": THREAD_TURN_CAPABILITY_VERSION,
            "cutover_version": THREAD_TURN_CUTOVER_VERSION,
            "desktop_contract_version": THREAD_TURN_DESKTOP_CONTRACT_VERSION,
            "env_allowed": env_allowed,
            "state": state,
            "generation": _int_value(record["generation"]),
            "summary_hash": _optional_text(record.get("summary_hash")),
            "block_code": _optional_text(record.get("block_code")),
            "effective_enabled": env_allowed and state == "enabled",
            "counts": _mapping(record.get("counts_json")),
            "prepared_at": _iso(record.get("prepared_at")),
            "enabled_at": _iso(record.get("enabled_at")),
            "updated_at": _iso(record.get("updated_at")),
        }

    def dry_run(self) -> dict[str, object]:
        inventory = self._inventory()
        summary = self._summary(inventory=inventory, migrated={})
        return {
            "cutover_version": THREAD_TURN_CUTOVER_VERSION,
            "state": "dry_run",
            "generation": _int_value(self._ensure_record()["generation"]),
            "summary": summary,
            "summary_hash": _hash(summary),
            "would_block": _int_value(summary["ambiguous_effects"]) > 0,
            "block_code": "TUTOR_CUTOVER_AMBIGUOUS_EFFECT" if _int_value(summary["ambiguous_effects"]) > 0 else None,
        }

    def prepare(
        self,
        *,
        expected_generation: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        key = _key(idempotency_key)
        request_hash = _hash({"operation": "prepare", "expected_generation": expected_generation})
        with self._conn.transaction():
            self._lock()
            record = self._ensure_record(for_update=True)
            replay = self._replay(record, operation="prepare", key=key, request_hash=request_hash)
            if replay:
                return self.status()
            self._expected(record, expected_generation)
            if str(record["state"]) == "enabled":
                raise CutoverError(
                    "TUTOR_CUTOVER_ALREADY_ENABLED",
                    "Tutor thread/turn v2 已启用；不能重新执行 prepare。",
                    status_code=409,
                    recoverable=False,
                )
            generation = _int_value(record["generation"]) + 1
            now = datetime.now(UTC)
            self._conn.execute(
                """
                UPDATE tutor_thread_turn_cutovers
                SET state = 'preparing', generation = %s, summary_hash = NULL,
                    counts_json = '{}'::jsonb, block_code = NULL, prepared_at = %s,
                    ready_at = NULL, enabled_at = NULL, last_operation = 'prepare',
                    last_idempotency_key = %s, last_request_hash = %s
                WHERE cutover_version = %s
                """,
                (generation, now, key, request_hash, THREAD_TURN_CUTOVER_VERSION),
            )
            self._audit(generation=generation, kind="preparing", state="preparing", counts={}, block_code=None, occurred_at=now)
        return self._converge(generation=generation)

    def enable(
        self,
        *,
        expected_generation: int,
        summary_hash: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        key = _key(idempotency_key)
        request_hash = _hash({"operation": "enable", "generation": expected_generation, "summary_hash": summary_hash})
        with self._conn.transaction():
            self._lock()
            record = self._ensure_record(for_update=True)
            if self._replay(record, operation="enable", key=key, request_hash=request_hash):
                return self.status()
            self._expected(record, expected_generation)
            if str(record["state"]) != "ready" or str(record.get("summary_hash") or "") != summary_hash:
                raise CutoverError(
                    "TUTOR_CUTOVER_NOT_READY",
                    "当前 preflight 摘要不是可启用状态。",
                    status_code=409,
                    details={"generation": expected_generation},
                )
            inventory = self._inventory()
            summary = self._summary(inventory=inventory, migrated={})
            if any(_int_value(summary[name]) for name in ("legacy_nonterminal", "active_legacy_leases", "ambiguous_effects")):
                raise CutoverError(
                    "TUTOR_CUTOVER_SUMMARY_STALE",
                    "legacy inventory 已变化，请重新 prepare。",
                    status_code=409,
                    details={"generation": expected_generation},
                )
            now = datetime.now(UTC)
            self._conn.execute(
                """
                UPDATE tutor_thread_turn_cutovers
                SET state = 'enabled', enabled_at = %s, block_code = NULL,
                    last_operation = 'enable', last_idempotency_key = %s, last_request_hash = %s
                WHERE cutover_version = %s AND generation = %s AND state = 'ready'
                """,
                (now, key, request_hash, THREAD_TURN_CUTOVER_VERSION, expected_generation),
            )
            self._audit(generation=expected_generation, kind="enabled", state="enabled", counts=summary, block_code=None, occurred_at=now)
        return self.status()

    def rollback(self, *, expected_generation: int, idempotency_key: str) -> dict[str, object]:
        key = _key(idempotency_key)
        request_hash = _hash({"operation": "rollback", "generation": expected_generation})
        with self._conn.transaction():
            self._lock()
            record = self._ensure_record(for_update=True)
            if self._replay(record, operation="rollback", key=key, request_hash=request_hash):
                return self.status()
            self._expected(record, expected_generation)
            if str(record["state"]) != "enabled":
                raise CutoverError("TUTOR_CUTOVER_NOT_ENABLED", "当前 v2 authority 未启用。", status_code=409)
            generation = expected_generation + 1
            now = datetime.now(UTC)
            self._conn.execute(
                """
                UPDATE tutor_thread_turn_cutovers
                SET state = 'ready', generation = %s, enabled_at = NULL,
                    last_operation = 'rollback', last_idempotency_key = %s, last_request_hash = %s
                WHERE cutover_version = %s AND generation = %s
                """,
                (generation, key, request_hash, THREAD_TURN_CUTOVER_VERSION, expected_generation),
            )
            self._audit(generation=generation, kind="rollback", state="ready", counts=_mapping(record.get("counts_json")), block_code=None, occurred_at=now)
        return self.status()

    def assert_mutation_allowed(self, *, settings: Settings | None = None) -> None:
        capability = self.status(settings=settings)
        if capability["effective_enabled"] is True:
            return
        state = str(capability["state"])
        code = {
            "preparing": "TUTOR_THREAD_TURN_V2_PREPARING",
            "blocked": "TUTOR_THREAD_TURN_V2_BLOCKED",
        }.get(state, "TUTOR_THREAD_TURN_V2_UNAVAILABLE")
        raise CutoverError(
            code,
            "Tutor thread/turn v2 mutation 当前不可用；历史读取仍可继续。",
            status_code=503,
            recoverable=True,
            details={
                "cutover_version": THREAD_TURN_CUTOVER_VERSION,
                "state": state,
                "generation": capability["generation"],
                "block_code": capability["block_code"],
            },
        )

    def _converge(self, *, generation: int) -> dict[str, object]:
        with self._conn.transaction():
            self._lock()
            record = self._ensure_record(for_update=True)
            if _int_value(record["generation"]) != generation or str(record["state"]) != "preparing":
                return self.status()
            before = self._inventory()
            migrated = self._terminalize_safe_legacy(generation=generation, ambiguous_ids=_string_set(before["ambiguous_run_ids"]))
            after = self._inventory()
            summary = self._summary(inventory=after, migrated=migrated)
            summary_hash = _hash(summary)
            blocked = _int_value(summary["ambiguous_effects"]) > 0
            state: Literal["blocked", "ready"] = "blocked" if blocked else "ready"
            block_code = "TUTOR_CUTOVER_AMBIGUOUS_EFFECT" if blocked else None
            now = datetime.now(UTC)
            self._conn.execute(
                """
                UPDATE tutor_thread_turn_cutovers
                SET state = %s, summary_hash = %s, counts_json = %s::jsonb,
                    block_code = %s, ready_at = CASE WHEN %s = 'ready' THEN %s ELSE NULL END
                WHERE cutover_version = %s AND generation = %s AND state = 'preparing'
                """,
                (state, summary_hash, json.dumps(summary, sort_keys=True), block_code, state, now, THREAD_TURN_CUTOVER_VERSION, generation),
            )
            self._audit(generation=generation, kind="preflight", state=state, counts=summary, block_code=block_code, occurred_at=now)
        return self.status()

    def _inventory(self) -> dict[str, object]:
        rows = self._conn.execute(
            """
            SELECT id::text, status, active_lease_owner_id
            FROM tutor_runs
            WHERE interaction_protocol_version = 'legacy_v1' AND terminal_outcome IS NULL
            ORDER BY conversation_id, created_at, id
            """
        ).fetchall()
        proposed = self._conn.execute(
            """
            SELECT DISTINCT runs.id::text
            FROM tutor_runs AS runs
            LEFT JOIN tutor_effects AS effects ON effects.run_id = runs.id AND effects.status = 'proposed'
            LEFT JOIN tutor_action_invocations AS actions ON actions.run_id = runs.id
              AND actions.status NOT IN ('verified','retryable_failed','permanent_failed','denied','cancelled','timed_out','superseded')
            WHERE runs.interaction_protocol_version = 'legacy_v1'
              AND runs.terminal_outcome IS NULL
              AND (runs.status = 'awaiting_effect_commit' OR effects.id IS NOT NULL OR actions.id IS NOT NULL)
            """
        ).fetchall()
        ambiguous_ids = tuple(str(row["id"]) for row in proposed)
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row["status"])
            counts[status] = counts.get(status, 0) + 1
        return {
            "status_counts": counts,
            "legacy_nonterminal": len(rows),
            "active_legacy_leases": sum(1 for row in rows if row.get("active_lease_owner_id") is not None),
            "ambiguous_effects": len(ambiguous_ids),
            "ambiguous_run_ids": ambiguous_ids,
        }

    def _terminalize_safe_legacy(self, *, generation: int, ambiguous_ids: set[str]) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT * FROM tutor_runs
            WHERE interaction_protocol_version = 'legacy_v1' AND terminal_outcome IS NULL
            ORDER BY conversation_id, created_at, id
            FOR UPDATE
            """
        ).fetchall()
        migrated = {"waiting_failed": 0, "active_cancelled": 0}
        now = datetime.now(UTC)
        for row in rows:
            run_id = str(row["id"])
            if run_id in ambiguous_ids:
                continue
            status = str(row["status"])
            if status == "waiting_for_input":
                outcome, new_status, diagnostic, display = "failed", "failed", "legacy_continuation_requires_new_turn", "failed"
                migrated["waiting_failed"] += 1
            elif status in _ACTIVE_LEGACY_STATUSES:
                outcome, new_status, diagnostic, display = "cancelled", "cancelled", "legacy_protocol_cutover", "interrupted"
                migrated["active_cancelled"] += 1
            else:
                continue
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s, cancelled_at = CASE WHEN %s = 'cancelled' THEN COALESCE(cancelled_at, %s) ELSE cancelled_at END,
                    terminal_outcome = %s, terminal_diagnostic_code = %s, terminal_at = %s,
                    active_lease_owner_id = NULL, active_lease_expires_at = NULL
                WHERE id = %s AND terminal_outcome IS NULL
                RETURNING *
                """,
                (new_status, outcome, now, outcome, diagnostic, now, run_id),
            ).fetchone()
            if updated is None:
                continue
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET display_state = %s, finished_at = COALESCE(finished_at, %s), updated_at = %s
                WHERE run_id = %s AND finished_at IS NULL
                """,
                (display, now, now, run_id),
            )
            self._conn.execute(
                """
                UPDATE tutor_interactive_dispatch_jobs
                SET state = 'dead', lease_owner_id = NULL, lease_expires_at = NULL,
                    last_error_code = %s, dead_at = COALESCE(dead_at, %s), completed_at = NULL
                WHERE run_id = %s AND state IN ('pending','leased','retry_wait')
                """,
                (diagnostic, now, run_id),
            )
            self._append_terminal_event(run=updated, generation=generation, diagnostic=diagnostic, outcome=outcome, occurred_at=now)
        return migrated

    def _append_terminal_event(self, *, run: Mapping[str, object], generation: int, diagnostic: str, outcome: str, occurred_at: datetime) -> None:
        run_id = str(run["id"])
        event_key = f"protocol-cutover:{generation}:{run_id}"
        if self._conn.execute("SELECT 1 FROM tutor_run_events WHERE run_id = %s AND event_key = %s", (run_id, event_key)).fetchone():
            return
        sequence = _int_value(run.get("next_event_sequence"), default=1)
        payload = {"kind": "terminal_result", "status": outcome, "run_id": run_id, "input_revision": _int_value(run.get("input_revision")), "diagnostic_code": diagnostic}
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._conn.execute(
            """
            INSERT INTO tutor_run_events (run_id, event_sequence, event_key, kind, input_revision, payload_json, payload_hash, created_at)
            VALUES (%s, %s, %s, 'terminal_result', %s, %s::jsonb, %s, %s)
            """,
            (run_id, sequence, event_key, _int_value(run.get("input_revision")), payload_json, hashlib.sha256(payload_json.encode()).hexdigest(), occurred_at),
        )
        self._conn.execute("UPDATE tutor_runs SET next_event_sequence = GREATEST(next_event_sequence, %s) WHERE id = %s", (sequence + 1, run_id))

    def _summary(self, *, inventory: Mapping[str, object], migrated: Mapping[str, int]) -> dict[str, object]:
        return {
            "schema_ready": self._table_exists("tutor_thread_turn_cutovers") and self._table_exists("tutor_conversation_events"),
            "worker_import_ready": importlib.util.find_spec("aearn_worker.worker_app") is not None,
            "legacy_post_tombstone": True,
            "snapshot_history_readable": self._table_exists("tutor_runs") and self._table_exists("tutor_messages"),
            "desktop_contract_version": THREAD_TURN_DESKTOP_CONTRACT_VERSION,
            "legacy_nonterminal": _int_value(inventory["legacy_nonterminal"]),
            "active_legacy_leases": _int_value(inventory["active_legacy_leases"]),
            "ambiguous_effects": _int_value(inventory["ambiguous_effects"]),
            "legacy_status_counts": _mapping(inventory["status_counts"]),
            "migrated_waiting_failed": int(migrated.get("waiting_failed", 0)),
            "migrated_active_cancelled": int(migrated.get("active_cancelled", 0)),
        }

    def _table_exists(self, name: str) -> bool:
        row = self._conn.execute("SELECT to_regclass(%s) IS NOT NULL AS present", (f"public.{name}",)).fetchone()
        return bool(row and row["present"])

    def _ensure_record(self, *, for_update: bool = False) -> Mapping[str, object]:
        self._conn.execute(
            "INSERT INTO tutor_thread_turn_cutovers (cutover_version) VALUES (%s) ON CONFLICT DO NOTHING",
            (THREAD_TURN_CUTOVER_VERSION,),
        )
        suffix = " FOR UPDATE" if for_update else ""
        row = self._conn.execute(
            f"SELECT * FROM tutor_thread_turn_cutovers WHERE cutover_version = %s{suffix}",
            (THREAD_TURN_CUTOVER_VERSION,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor thread/turn cutover singleton is missing")
        return row

    def _lock(self) -> None:
        self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_ADVISORY_LOCK_KEY,))

    def _expected(self, record: Mapping[str, object], expected: int) -> None:
        actual = _int_value(record["generation"])
        if expected != actual:
            raise CutoverError(
                "TUTOR_CUTOVER_GENERATION_CONFLICT",
                "cutover generation 已变化，请刷新状态。",
                status_code=409,
                details={"expected_generation": expected, "actual_generation": actual},
            )

    def _replay(self, record: Mapping[str, object], *, operation: str, key: str, request_hash: str) -> bool:
        if str(record.get("last_idempotency_key") or "") != key:
            return False
        if str(record.get("last_operation") or "") != operation or str(record.get("last_request_hash") or "") != request_hash:
            raise CutoverError("TUTOR_CUTOVER_IDEMPOTENCY_CONFLICT", "cutover idempotency key 与原请求不一致。", status_code=409, recoverable=False)
        return True

    def _audit(self, *, generation: int, kind: str, state: str, counts: Mapping[str, object], block_code: str | None, occurred_at: datetime) -> None:
        event_key = f"{generation}:{kind}"
        self._conn.execute(
            """
            INSERT INTO tutor_thread_turn_cutover_events (
              cutover_version, generation, event_key, kind, state, counts_json, block_code, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            ON CONFLICT (cutover_version, event_key) DO NOTHING
            """,
            (THREAD_TURN_CUTOVER_VERSION, generation, event_key, kind, state, json.dumps(dict(counts), sort_keys=True), block_code, occurred_at),
        )


def thread_turn_v2_gate_error(*, settings: Settings | None = None) -> CutoverError | None:
    with connect() as conn:
        try:
            TutorThreadTurnCutoverService(conn).assert_mutation_allowed(settings=settings)
        except CutoverError as exc:
            conn.rollback()
            return exc
    return None


def _key(value: str) -> str:
    normalized = value.strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise CutoverError("VALIDATION_ERROR", "cutover idempotency key 格式不合法。", status_code=400)
    return normalized


def _hash(value: Mapping[str, object]) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional_text(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat()


def _int_value(value: object, *, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _string_set(value: object) -> set[str]:
    if not isinstance(value, tuple | list | set):
        return set()
    return {str(item) for item in value}
