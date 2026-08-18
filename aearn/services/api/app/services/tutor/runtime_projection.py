"""Durable, safe projection of Codex Runtime events into Tutor public state."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from psycopg import Connection

from app.core.teaching_safety import check_teaching_output
from app.services.tutor.conversation_contracts import TutorConversationEventKind
from app.services.tutor.persistence import PostgresTutorRepository, TutorIdempotencyConflict

_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")
_SAFE_CODE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$")
_TOOL_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TERMINAL_BINDING_STATES: Final[frozenset[str]] = frozenset(
    {"completed", "interrupted", "unavailable", "failed"}
)


class TutorRuntimeKind(StrEnum):
    HARNESS_V1 = "harness_v1"
    CODEX_SIDECAR_V1 = "codex_sidecar_v1"


class TutorRuntimeBindingState(StrEnum):
    THREAD_BOUND = "thread_bound"
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class TutorRuntimeProjectionStatus(StrEnum):
    APPLIED = "applied"
    IGNORED_NONPUBLIC = "ignored_nonpublic"
    IGNORED_STALE = "ignored_stale"
    BLOCKED_UNSAFE = "blocked_unsafe"


@dataclass(frozen=True, slots=True)
class TutorRuntimeProjectionFence:
    input_revision: int
    lease_owner_id: str
    lease_generation: int
    connection_generation: int

    def __post_init__(self) -> None:
        if self.input_revision < 1 or self.lease_generation < 1 or self.connection_generation < 1:
            raise ValueError("runtime projection fence is invalid")
        if not self.lease_owner_id:
            raise ValueError("runtime projection lease owner is required")


@dataclass(frozen=True, slots=True)
class TutorRuntimeProjectionEvent:
    kind: str
    thread_id: str
    sequence: int
    occurred_at: datetime
    turn_id: str | None = None
    item_id: str | None = None
    visible_text: str | None = None
    content_hash: str | None = None
    safe_code: str | None = None
    terminal_status: str | None = None
    tool_name: str | None = None
    input_hash: str | None = None
    result_hash: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {
            "turn_started", "message_delta", "message_completed", "tool_started",
            "tool_completed", "turn_completed", "warning",
        }:
            raise ValueError("runtime projection event kind is invalid")
        if not self.thread_id or self.sequence < 1:
            raise ValueError("runtime projection event identity is invalid")
        for value in (self.content_hash, self.input_hash, self.result_hash):
            if value is not None and _SHA256.fullmatch(value) is None:
                raise ValueError("runtime projection event hash is invalid")
        if self.safe_code is not None and _SAFE_CODE.fullmatch(self.safe_code) is None:
            raise ValueError("runtime projection safe code is invalid")
        if self.tool_name is not None and _TOOL_NAME.fullmatch(self.tool_name) is None:
            raise ValueError("runtime projection tool name is invalid")


@dataclass(frozen=True, slots=True)
class TutorRuntimeBinding:
    binding_id: str
    run_id: str
    user_id: str
    conversation_id: str
    state: TutorRuntimeBindingState
    connection_generation: int


@dataclass(frozen=True, slots=True)
class TutorRuntimeProjectionReceipt:
    receipt_id: str
    binding_id: str
    event_key: str
    event_kind: str
    event_sequence: int
    projection_status: TutorRuntimeProjectionStatus
    public_item_id: str | None
    public_item_kind: str | None
    replayed: bool = False


class TutorRuntimeProjectionError(ValueError):
    """Stable projection conflict that never includes private runtime data."""


class PostgresTutorRuntimeProjectionRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._tutor = PostgresTutorRepository(conn)

    def bind_run(
        self,
        *,
        user_id: str,
        run_id: str,
        fence: TutorRuntimeProjectionFence,
        runtime_version: str,
        protocol_version: str,
        external_thread_id: str,
        occurred_at: datetime,
    ) -> TutorRuntimeBinding:
        if not runtime_version or len(runtime_version) > 120:
            raise ValueError("runtime version is invalid")
        if not protocol_version or len(protocol_version) > 120:
            raise ValueError("runtime protocol version is invalid")
        if not external_thread_id or len(external_thread_id) > 240:
            raise ValueError("runtime thread identity is invalid")
        with self._conn.transaction():
            run = self._conn.execute(
                "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s FOR UPDATE",
                (run_id, user_id),
            ).fetchone()
            if run is None:
                raise TutorRuntimeProjectionError("Tutor run was not found")
            if str(run.get("runtime_kind") or "") != TutorRuntimeKind.CODEX_SIDECAR_V1.value:
                raise TutorRuntimeProjectionError("Tutor run is not assigned to Codex Runtime")
            if str(run.get("origin") or "") != "interactive" or str(
                run.get("interaction_protocol_version") or ""
            ) != "thread_turn_v2":
                raise TutorRuntimeProjectionError("Tutor run is not eligible for public runtime projection")
            if not self._fence_matches(run, fence, occurred_at):
                raise TutorRuntimeProjectionError("Tutor runtime binding fence is stale")
            existing = self._conn.execute(
                "SELECT * FROM tutor_run_runtime_bindings WHERE run_id = %s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["external_thread_id"]) != external_thread_id
                    or _as_int(existing["connection_generation"]) != fence.connection_generation
                    or str(existing["runtime_version"]) != runtime_version
                    or str(existing["protocol_version"]) != protocol_version
                ):
                    raise TutorRuntimeProjectionError("Tutor runtime binding already exists with different identity")
                return self._binding(existing)
            row = self._conn.execute(
                """
                INSERT INTO tutor_run_runtime_bindings (
                  run_id, user_id, conversation_id, runtime_kind, runtime_version,
                  protocol_version, external_thread_id, connection_generation,
                  state, created_at, updated_at
                ) VALUES (%s, %s, %s, 'codex_sidecar_v1', %s, %s, %s, %s, 'thread_bound', %s, %s)
                RETURNING *
                """,
                (
                    run_id, user_id, run["conversation_id"], runtime_version,
                    protocol_version, external_thread_id, fence.connection_generation,
                    occurred_at, occurred_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Tutor runtime binding insert failed")
            return self._binding(row)

    def project(
        self,
        *,
        binding_id: str,
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
    ) -> TutorRuntimeProjectionReceipt:
        event_key = self._event_key(event)
        with self._conn.transaction():
            binding = self._conn.execute(
                """
                SELECT bindings.*, runs.status AS run_status, runs.input_revision,
                       runs.active_lease_owner_id, runs.active_lease_generation,
                       runs.active_lease_expires_at, runs.terminal_outcome,
                       runs.cancelled_at, runs.superseded_by_run_id, runs.origin,
                       runs.interaction_protocol_version
                FROM tutor_run_runtime_bindings AS bindings
                JOIN tutor_runs AS runs ON runs.id = bindings.run_id
                WHERE bindings.id = %s
                FOR UPDATE OF bindings, runs
                """,
                (binding_id,),
            ).fetchone()
            if binding is None:
                raise TutorRuntimeProjectionError("Tutor runtime binding was not found")
            existing = self._conn.execute(
                """
                SELECT * FROM tutor_runtime_item_receipts
                WHERE binding_id = %s
                  AND (event_key = %s OR event_sequence = %s)
                ORDER BY CASE WHEN event_key = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (binding_id, event_key, event.sequence, event_key),
            ).fetchone()
            if existing is not None:
                if str(existing["event_key"]) != event_key:
                    raise TutorIdempotencyConflict(
                        "runtime event sequence conflicts with different safe facts"
                    )
                return self._receipt(existing, replayed=True)
            stale = (
                event.thread_id != str(binding["external_thread_id"])
                or str(binding["state"]) in _TERMINAL_BINDING_STATES
                or not self._fence_matches(binding, fence, event.occurred_at)
                or not self._turn_matches(binding, event)
            )
            if stale:
                return self._insert_receipt(
                    binding=binding,
                    event=event,
                    event_key=event_key,
                    status=TutorRuntimeProjectionStatus.IGNORED_STALE,
                )
            status, public_item_id, public_item_kind = self._apply_event(
                binding=binding,
                fence=fence,
                event=event,
            )
            return self._insert_receipt(
                binding=binding,
                event=event,
                event_key=event_key,
                status=status,
                public_item_id=public_item_id,
                public_item_kind=public_item_kind,
            )

    def receipts_for_run(self, *, user_id: str, run_id: str) -> tuple[TutorRuntimeProjectionReceipt, ...]:
        rows = self._conn.execute(
            """
            SELECT receipts.*
            FROM tutor_runtime_item_receipts AS receipts
            JOIN tutor_run_runtime_bindings AS bindings ON bindings.id = receipts.binding_id
            WHERE bindings.user_id = %s AND bindings.run_id = %s
            ORDER BY receipts.event_sequence, receipts.created_at, receipts.id
            """,
            (user_id, run_id),
        ).fetchall()
        return tuple(self._receipt(row, replayed=False) for row in rows)

    def _apply_event(
        self,
        *,
        binding: Mapping[str, object],
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
    ) -> tuple[TutorRuntimeProjectionStatus, str | None, str | None]:
        run: Mapping[str, object] = self._run_row(binding)
        self._tutor._ensure_public_process_locked(run=run, occurred_at=event.occurred_at)
        if event.kind == "turn_started":
            if event.turn_id is None:
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
            updated = self._conn.execute(
                """
                UPDATE tutor_run_runtime_bindings
                SET external_turn_id = COALESCE(external_turn_id, %s),
                    state = 'running', started_at = COALESCE(started_at, %s)
                WHERE id = %s AND state = 'thread_bound'
                  AND (external_turn_id IS NULL OR external_turn_id = %s)
                RETURNING id
                """,
                (event.turn_id, event.occurred_at, binding["id"], event.turn_id),
            ).fetchone()
            if updated is None:
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
            self._conn.execute(
                "UPDATE tutor_runs SET status = 'running' WHERE id = %s AND status IN ('queued', 'leased', 'running')",
                (binding["run_id"],),
            )
            run = self._locked_run(str(binding["run_id"]), str(binding["user_id"]))
            self._tutor._advance_public_process_locked(
                run=run, step_key="runtime_started", occurred_at=event.occurred_at
            )
            self._tutor._append_turn_event_locked(
                run=run,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{run['id']}:runtime-started",
                occurred_at=event.occurred_at,
            )
            return TutorRuntimeProjectionStatus.APPLIED, str(run["id"]), "process"
        if event.kind == "tool_started":
            self._tutor._advance_public_process_locked(
                run=run, step_key="domain_tool_running", occurred_at=event.occurred_at
            )
            return TutorRuntimeProjectionStatus.APPLIED, str(run["id"]), "process"
        if event.kind == "tool_completed":
            self._tutor._advance_public_process_locked(
                run=run, step_key="domain_tool_completed", occurred_at=event.occurred_at
            )
            return TutorRuntimeProjectionStatus.APPLIED, str(run["id"]), "process"
        if event.kind == "message_completed":
            return self._project_message(binding=binding, run=run, event=event)
        if event.kind == "turn_completed":
            return self._project_terminal(binding=binding, run=run, fence=fence, event=event)
        return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None

    def _project_message(
        self,
        *,
        binding: Mapping[str, object],
        run: Mapping[str, object],
        event: TutorRuntimeProjectionEvent,
    ) -> tuple[TutorRuntimeProjectionStatus, str | None, str | None]:
        text = event.visible_text or ""
        if not text or len(text) > 16_000 or event.content_hash != self._sha256_text(text):
            self._mark_message_blocked(binding, "runtime_final_message_invalid")
            return TutorRuntimeProjectionStatus.BLOCKED_UNSAFE, None, None
        safety = check_teaching_output(text)
        if safety.blocked:
            self._mark_message_blocked(binding, f"runtime_output_{safety.category}")
            return TutorRuntimeProjectionStatus.BLOCKED_UNSAFE, None, None
        current = self._conn.execute(
            "SELECT final_message_id FROM tutor_run_runtime_bindings WHERE id = %s",
            (binding["id"],),
        ).fetchone()
        if current is not None and current.get("final_message_id") is not None:
            return TutorRuntimeProjectionStatus.APPLIED, str(current["final_message_id"]), "message"
        message = self._conn.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content, created_at)
            VALUES (%s, 'tutor', %s, %s)
            RETURNING id
            """,
            (binding["conversation_id"], text, event.occurred_at),
        ).fetchone()
        if message is None:
            raise RuntimeError("Tutor runtime public message insert failed")
        message_id = str(message["id"])
        updated = self._conn.execute(
            """
            UPDATE tutor_run_runtime_bindings
            SET final_message_id = %s
            WHERE id = %s AND final_message_id IS NULL AND final_message_blocked = false
            RETURNING id
            """,
            (message_id, binding["id"]),
        ).fetchone()
        if updated is None:
            raise TutorRuntimeProjectionError("Tutor runtime final message lost its projection fence")
        self._tutor._advance_public_process_locked(
            run=run, step_key="learning_reply_generated", occurred_at=event.occurred_at
        )
        self._tutor._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=event.occurred_at,
        )
        self._tutor._append_item_reference_event_locked(
            run=run,
            event_key=f"item:message:{message_id}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=message_id,
            item_kind="message",
            occurred_at=event.occurred_at,
        )
        return TutorRuntimeProjectionStatus.APPLIED, message_id, "message"

    def _project_terminal(
        self,
        *,
        binding: Mapping[str, object],
        run: Mapping[str, object],
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
    ) -> tuple[TutorRuntimeProjectionStatus, str | None, str | None]:
        requested = event.terminal_status or "failed"
        latest = self._conn.execute(
            "SELECT * FROM tutor_run_runtime_bindings WHERE id = %s FOR UPDATE",
            (binding["id"],),
        ).fetchone()
        if latest is None:
            raise TutorRuntimeProjectionError("Tutor runtime binding was not found")
        final_message_id = latest.get("final_message_id")
        blocked = latest.get("final_message_blocked") is True
        safe_code = str(latest.get("safe_error_code") or event.safe_code or "runtime_failed")
        if requested == "completed" and (final_message_id is None or blocked):
            requested = "failed"
            safe_code = "runtime_final_message_unsafe" if blocked else "runtime_final_message_missing"
        mapping = {
            "completed": ("completed", "completed", "completed", False, None),
            "interrupted": ("cancelled", "cancelled", "interrupted", False, None),
            "unavailable": ("model_unavailable", "model_unavailable", "unavailable", True, "TUTOR_RUNTIME_UNAVAILABLE"),
            "failed": ("failed", "failed", "failed", True, self._public_error_code(safe_code)),
        }
        status, outcome, binding_state, recoverable, public_error_code = mapping.get(
            requested, mapping["failed"]
        )
        cancelled_at = event.occurred_at if requested == "interrupted" else None
        updated = self._conn.execute(
            """
            UPDATE tutor_runs
            SET status = %s, terminal_outcome = %s, terminal_diagnostic_code = %s,
                terminal_at = %s, cancelled_at = COALESCE(cancelled_at, %s),
                active_lease_owner_id = NULL, active_lease_expires_at = NULL
            WHERE id = %s AND user_id = %s AND input_revision = %s
              AND active_lease_owner_id = %s AND active_lease_generation = %s
              AND terminal_outcome IS NULL AND superseded_by_run_id IS NULL
            RETURNING *
            """,
            (
                status, outcome, None if requested == "completed" else safe_code,
                event.occurred_at, cancelled_at, run["id"], run["user_id"],
                fence.input_revision, fence.lease_owner_id, fence.lease_generation,
            ),
        ).fetchone()
        if updated is None:
            return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
        self._conn.execute(
            """
            UPDATE tutor_run_runtime_bindings
            SET state = %s, safe_error_code = %s, terminal_at = %s
            WHERE id = %s
            """,
            (binding_state, None if requested == "completed" else safe_code, event.occurred_at, binding["id"]),
        )
        self._tutor._append_event_locked(
            run_id=str(run["id"]),
            event_key=f"runtime:terminal:{binding['id']}",
            kind="terminal_result",
            input_revision=fence.input_revision,
            payload={
                "kind": "terminal_result", "status": status, "run_id": str(run["id"]),
                "input_revision": fence.input_revision,
            },
        )
        display_state = {
            "completed": "completed", "interrupted": "interrupted",
            "unavailable": "unavailable", "failed": "failed",
        }.get(requested, "failed")
        self._tutor._freeze_public_process_locked(
            run=updated,
            display_state=display_state,
            step_key="learning_reply_generated" if requested == "completed" else None,
            occurred_at=event.occurred_at,
            tutor_message_id=str(final_message_id) if final_message_id is not None else None,
        )
        self._tutor._append_turn_event_locked(
            run=updated,
            kind=TutorConversationEventKind.TURN_UPDATED,
            event_key=f"turn:{run['id']}:runtime-terminal:{outcome}",
            occurred_at=event.occurred_at,
        )
        if public_error_code is None:
            return TutorRuntimeProjectionStatus.APPLIED, str(run["id"]), "process"
        error = self._conn.execute(
            """
            INSERT INTO tutor_runtime_public_errors (
              binding_id, run_id, user_id, conversation_id, code, recoverable, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (binding_id) DO NOTHING
            RETURNING id
            """,
            (
                binding["id"], run["id"], run["user_id"], run["conversation_id"],
                public_error_code, recoverable, event.occurred_at,
            ),
        ).fetchone()
        if error is None:
            raise RuntimeError("Tutor runtime public error insert failed")
        error_id = str(error["id"])
        self._tutor._append_item_reference_event_locked(
            run=run,
            event_key=f"item:error:{error_id}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=error_id,
            item_kind="error",
            occurred_at=event.occurred_at,
        )
        return TutorRuntimeProjectionStatus.APPLIED, error_id, "error"

    def _insert_receipt(
        self,
        *,
        binding: Mapping[str, object],
        event: TutorRuntimeProjectionEvent,
        event_key: str,
        status: TutorRuntimeProjectionStatus,
        public_item_id: str | None = None,
        public_item_kind: str | None = None,
    ) -> TutorRuntimeProjectionReceipt:
        row = self._conn.execute(
            """
            INSERT INTO tutor_runtime_item_receipts (
              binding_id, run_id, user_id, conversation_id, event_key, event_kind,
              external_item_hash, event_sequence, item_kind, item_status, tool_name,
              input_hash, result_hash, content_hash, safe_code, projection_status,
              public_item_id, public_item_kind, occurred_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                binding["id"], binding["run_id"], binding["user_id"], binding["conversation_id"],
                event_key, event.kind, self._hash_optional(event.item_id), event.sequence,
                self._item_kind(event), self._item_status(event),
                event.tool_name, event.input_hash, event.result_hash, event.content_hash,
                event.safe_code, status.value, public_item_id, public_item_kind, event.occurred_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor runtime receipt insert failed")
        return self._receipt(row, replayed=False)

    def _mark_message_blocked(self, binding: Mapping[str, object], safe_code: str) -> None:
        self._conn.execute(
            """
            UPDATE tutor_run_runtime_bindings
            SET final_message_blocked = true, safe_error_code = %s
            WHERE id = %s AND final_message_id IS NULL
            """,
            (safe_code, binding["id"]),
        )

    @staticmethod
    def _fence_matches(row: Mapping[str, object], fence: TutorRuntimeProjectionFence, now: datetime) -> bool:
        expiry = row.get("active_lease_expires_at")
        return (
            _as_int(row.get("input_revision")) == fence.input_revision
            and str(row.get("active_lease_owner_id") or "") == fence.lease_owner_id
            and _as_int(row.get("active_lease_generation")) == fence.lease_generation
            and _as_int(row.get("connection_generation"), fence.connection_generation)
            == fence.connection_generation
            and isinstance(expiry, datetime)
            and expiry > now
            and row.get("terminal_outcome") is None
            and row.get("cancelled_at") is None
            and row.get("superseded_by_run_id") is None
        )

    @staticmethod
    def _turn_matches(binding: Mapping[str, object], event: TutorRuntimeProjectionEvent) -> bool:
        bound_turn = binding.get("external_turn_id")
        if event.kind == "turn_started":
            return event.turn_id is not None and (bound_turn is None or str(bound_turn) == event.turn_id)
        if event.kind == "warning" and event.turn_id is None:
            return True
        return bound_turn is not None and event.turn_id == str(bound_turn)

    @staticmethod
    def _event_key(event: TutorRuntimeProjectionEvent) -> str:
        safe = {
            "kind": event.kind, "thread": hashlib.sha256(event.thread_id.encode()).hexdigest(),
            "turn": PostgresTutorRuntimeProjectionRepository._hash_optional(event.turn_id),
            "item": PostgresTutorRuntimeProjectionRepository._hash_optional(event.item_id),
            "content": event.content_hash, "code": event.safe_code, "terminal": event.terminal_status,
            "tool": event.tool_name, "input": event.input_hash, "result": event.result_hash,
        }
        return hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _hash_optional(value: str | None) -> str | None:
        return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else None

    @staticmethod
    def _sha256_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _item_status(event: TutorRuntimeProjectionEvent) -> str | None:
        if event.kind == "turn_completed":
            return event.terminal_status
        if event.kind in {"tool_started", "tool_completed"} and event.safe_code is not None:
            return event.safe_code if len(event.safe_code) <= 80 else None
        return None

    @staticmethod
    def _item_kind(event: TutorRuntimeProjectionEvent) -> str | None:
        if event.kind.startswith("turn_"):
            return "turn"
        if event.kind.startswith("message_"):
            return "message"
        if event.kind.startswith("tool_"):
            return "tool"
        if event.kind == "warning":
            return "warning"
        return None

    @staticmethod
    def _public_error_code(safe_code: str) -> str:
        if safe_code == "runtime_final_message_missing":
            return "TUTOR_RUNTIME_OUTPUT_MISSING"
        if safe_code.startswith("runtime_final_message_") or safe_code.startswith("runtime_output_"):
            return "TUTOR_RUNTIME_OUTPUT_BLOCKED"
        return "TUTOR_RUNTIME_FAILED"

    @staticmethod
    def _run_row(binding: Mapping[str, object]) -> dict[str, object]:
        return {
            "id": binding["run_id"], "user_id": binding["user_id"],
            "conversation_id": binding["conversation_id"], "origin": binding["origin"],
            "status": binding["run_status"], "input_revision": binding["input_revision"],
            "interaction_protocol_version": binding["interaction_protocol_version"],
        }

    def _locked_run(self, run_id: str, user_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s FOR UPDATE",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRuntimeProjectionError("Tutor run was not found")
        return row

    @staticmethod
    def _binding(row: Mapping[str, object]) -> TutorRuntimeBinding:
        return TutorRuntimeBinding(
            binding_id=str(row["id"]), run_id=str(row["run_id"]),
            user_id=str(row["user_id"]), conversation_id=str(row["conversation_id"]),
            state=TutorRuntimeBindingState(str(row["state"])),
            connection_generation=_as_int(row["connection_generation"]),
        )

    @staticmethod
    def _receipt(row: Mapping[str, object], *, replayed: bool) -> TutorRuntimeProjectionReceipt:
        return TutorRuntimeProjectionReceipt(
            receipt_id=str(row["id"]), binding_id=str(row["binding_id"]),
            event_key=str(row["event_key"]), event_kind=str(row["event_kind"]),
            event_sequence=_as_int(row["event_sequence"]),
            projection_status=TutorRuntimeProjectionStatus(str(row["projection_status"])),
            public_item_id=str(row["public_item_id"]) if row.get("public_item_id") else None,
            public_item_kind=str(row["public_item_kind"]) if row.get("public_item_kind") else None,
            replayed=replayed,
        )


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default
