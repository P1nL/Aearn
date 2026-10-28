"""Durable, safe projection of Codex Runtime events into Tutor public state."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from psycopg import Connection

from app.core.teaching_safety import check_teaching_output
from app.services.tutor.conversation_contracts import (
    TUTOR_RUNTIME_ITEM_STREAM_VERSION,
    TutorConversationEventKind,
)
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
    projection_sequence: int | None = None
    source_sequence_start: int | None = None
    source_sequence_end: int | None = None
    source_delta_count: int = 1
    source_content_hash: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    visible_text: str | None = None
    content_hash: str | None = None
    safe_code: str | None = None
    terminal_status: str | None = None
    tool_name: str | None = None
    input_hash: str | None = None
    result_hash: str | None = None
    item_type: str | None = None
    phase: str | None = None
    defer_public_message: bool = False

    def __post_init__(self) -> None:
        if self.kind not in {
            "turn_started",
            "reasoning_started", "reasoning_delta", "reasoning_completed",
            "reasoning_summary_started", "reasoning_summary_delta", "reasoning_summary_completed",
            "message_started", "message_delta", "message_completed",
            "context_compaction_started", "context_compaction_completed",
            "tool_started", "tool_completed", "turn_completed", "warning",
        }:
            raise ValueError("runtime projection event kind is invalid")
        projection_sequence = self.projection_sequence or self.sequence
        if not self.thread_id or self.sequence < 1 or projection_sequence < 1:
            raise ValueError("runtime projection event identity is invalid")
        if projection_sequence != self.sequence:
            raise ValueError("runtime projection sequence must match the compatibility sequence")
        object.__setattr__(self, "projection_sequence", projection_sequence)
        source_values = (self.source_sequence_start, self.source_sequence_end)
        if any(value is not None for value in source_values):
            if (
                self.source_sequence_start is None
                or self.source_sequence_end is None
                or self.source_sequence_start < 1
                or self.source_sequence_end < self.source_sequence_start
                or self.source_delta_count < 1
                or self.source_delta_count
                != self.source_sequence_end - self.source_sequence_start + 1
                or self.source_content_hash is None
            ):
                raise ValueError("runtime projection source range is invalid")
        elif self.source_delta_count != 1 or self.source_content_hash is not None:
            raise ValueError("runtime projection source metadata is incomplete")
        for value in (
            self.content_hash,
            self.input_hash,
            self.result_hash,
            self.source_content_hash,
        ):
            if value is not None and _SHA256.fullmatch(value) is None:
                raise ValueError("runtime projection event hash is invalid")
        if self.safe_code is not None and _SAFE_CODE.fullmatch(self.safe_code) is None:
            raise ValueError("runtime projection safe code is invalid")
        if self.tool_name is not None and _TOOL_NAME.fullmatch(self.tool_name) is None:
            raise ValueError("runtime projection tool name is invalid")


@dataclass(frozen=True, slots=True)
class TutorConversationRuntimeThread:
    thread_binding_id: str
    user_id: str
    conversation_id: str
    external_thread_id: str
    state: str
    migration_mode: str


@dataclass(frozen=True, slots=True)
class TutorRuntimeBinding:
    binding_id: str
    run_id: str
    user_id: str
    conversation_id: str
    state: TutorRuntimeBindingState
    connection_generation: int
    step_attempt_id: str | None = None


@dataclass(frozen=True, slots=True)
class TutorRuntimeProjectionReceipt:
    receipt_id: str
    binding_id: str
    event_key: str
    event_kind: str
    event_sequence: int
    projection_sequence: int
    source_sequence_start: int | None
    source_sequence_end: int | None
    source_delta_count: int | None
    source_content_hash: str | None
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

    def active_conversation_thread(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> TutorConversationRuntimeThread | None:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_conversation_runtime_threads
            WHERE user_id = %s AND conversation_id = %s
              AND runtime_kind = 'codex_sidecar_v1' AND state = 'active'
            """,
            (user_id, conversation_id),
        ).fetchone()
        return self._conversation_thread(row) if row is not None else None

    def create_conversation_thread(
        self,
        *,
        user_id: str,
        conversation_id: str,
        runtime_version: str,
        protocol_version: str,
        external_thread_id: str,
        migration_mode: str,
        occurred_at: datetime,
    ) -> TutorConversationRuntimeThread:
        if migration_mode not in {"native", "legacy_reseed"}:
            raise ValueError("runtime thread migration mode is invalid")
        with self._conn.transaction():
            conversation = self._conn.execute(
                "SELECT id FROM tutor_conversations WHERE id = %s AND user_id = %s FOR UPDATE",
                (conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                raise TutorRuntimeProjectionError("Tutor conversation was not found")
            existing = self._conn.execute(
                """
                SELECT * FROM tutor_conversation_runtime_threads
                WHERE user_id = %s AND conversation_id = %s
                  AND runtime_kind = 'codex_sidecar_v1' AND state = 'active'
                FOR UPDATE
                """,
                (user_id, conversation_id),
            ).fetchone()
            if existing is not None:
                if str(existing["external_thread_id"]) != external_thread_id:
                    raise TutorRuntimeProjectionError("Tutor conversation already owns another Runtime thread")
                return self._conversation_thread(existing)
            row = self._conn.execute(
                """
                INSERT INTO tutor_conversation_runtime_threads (
                  user_id, conversation_id, runtime_kind, runtime_version,
                  protocol_version, model, model_provider, external_thread_id,
                  state, migration_mode, created_at, updated_at, last_resumed_at
                ) VALUES (
                  %s, %s, 'codex_sidecar_v1', %s, %s,
                  'deepseek-flash', 'aearn_deepseek', %s,
                  'active', %s, %s, %s, %s
                )
                RETURNING *
                """,
                (
                    user_id, conversation_id, runtime_version, protocol_version,
                    external_thread_id, migration_mode, occurred_at, occurred_at, occurred_at,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Tutor conversation Runtime thread insert failed")
            return self._conversation_thread(row)

    def mark_conversation_thread_resumed(
        self,
        *,
        thread_binding_id: str,
        user_id: str,
        occurred_at: datetime,
    ) -> None:
        row = self._conn.execute(
            """
            UPDATE tutor_conversation_runtime_threads
            SET last_resumed_at = %s
            WHERE id = %s AND user_id = %s AND state = 'active'
            RETURNING id
            """,
            (occurred_at, thread_binding_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRuntimeProjectionError("Tutor conversation Runtime thread is unavailable")

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
        conversation_runtime_thread_id: str | None = None,
        step_attempt_id: str | None = None,
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
            if step_attempt_id is not None:
                step = self._conn.execute(
                    "SELECT * FROM tutor_run_step_attempts WHERE id = %s AND run_id = %s "
                    "AND user_id = %s AND conversation_id = %s FOR UPDATE",
                    (step_attempt_id, run_id, user_id, run["conversation_id"]),
                ).fetchone()
                if (
                    step is None or step.get("state") != "prepared" or step.get("kind") != "sidecar_turn"
                    or step.get("input_revision") != fence.input_revision
                    or step.get("owner_id") != fence.lease_owner_id
                    or step.get("owner_generation") != fence.lease_generation
                ):
                    raise TutorRuntimeProjectionError("Tutor runtime step binding fence is stale")
            thread_row = None
            if conversation_runtime_thread_id is not None:
                thread_row = self._conn.execute(
                    """
                    SELECT * FROM tutor_conversation_runtime_threads
                    WHERE id = %s AND user_id = %s AND conversation_id = %s
                      AND runtime_kind = 'codex_sidecar_v1' AND state = 'active'
                    FOR UPDATE
                    """,
                    (conversation_runtime_thread_id, user_id, run["conversation_id"]),
                ).fetchone()
                if thread_row is None or str(thread_row["external_thread_id"]) != external_thread_id:
                    raise TutorRuntimeProjectionError("Tutor conversation Runtime thread identity is invalid")
            else:
                thread_row = self._conn.execute(
                    """
                    SELECT * FROM tutor_conversation_runtime_threads
                    WHERE user_id = %s AND conversation_id = %s
                      AND runtime_kind = 'codex_sidecar_v1' AND state = 'active'
                      AND external_thread_id = %s
                    FOR UPDATE
                    """,
                    (user_id, run["conversation_id"], external_thread_id),
                ).fetchone()
                if thread_row is None:
                    thread_row = self._conn.execute(
                        """
                        INSERT INTO tutor_conversation_runtime_threads (
                          user_id, conversation_id, runtime_kind, runtime_version,
                          protocol_version, model, model_provider, external_thread_id,
                          state, migration_mode, created_at, updated_at, last_resumed_at
                        ) VALUES (
                          %s, %s, 'codex_sidecar_v1', %s, %s,
                          'deepseek-flash', 'aearn_deepseek', %s,
                          'active', 'native', %s, %s, %s
                        )
                        RETURNING *
                        """,
                        (
                            user_id, run["conversation_id"], runtime_version,
                            protocol_version, external_thread_id, occurred_at,
                            occurred_at, occurred_at,
                        ),
                    ).fetchone()
            if thread_row is None:
                raise RuntimeError("Tutor conversation Runtime thread is missing")
            conversation_runtime_thread_id = str(thread_row["id"])
            existing = self._conn.execute(
                "SELECT * FROM tutor_run_runtime_bindings WHERE run_id = %s "
                "AND step_attempt_id IS NOT DISTINCT FROM %s::uuid FOR UPDATE",
                (run_id, step_attempt_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["external_thread_id"]) != external_thread_id
                    or str(existing.get("conversation_runtime_thread_id") or "") != conversation_runtime_thread_id
                    or _as_int(existing["connection_generation"]) != fence.connection_generation
                    or str(existing["runtime_version"]) != runtime_version
                    or str(existing["protocol_version"]) != protocol_version
                ):
                    raise TutorRuntimeProjectionError("Tutor runtime binding already exists with different identity")
                return self._binding(existing)
            row = self._conn.execute(
                """
                INSERT INTO tutor_run_runtime_bindings (
                  run_id, conversation_runtime_thread_id, user_id, conversation_id, step_attempt_id,
                  runtime_kind, runtime_version, protocol_version,
                  external_thread_id, connection_generation,
                  state, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, 'codex_sidecar_v1', %s, %s, %s, %s, 'thread_bound', %s, %s)
                RETURNING *
                """,
                (
                    run_id, conversation_runtime_thread_id, user_id, run["conversation_id"],
                    step_attempt_id,
                    runtime_version, protocol_version, external_thread_id,
                    fence.connection_generation, occurred_at, occurred_at,
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
        complete_business_run: bool = False,
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
                  AND (event_key = %s OR projection_sequence = %s)
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
                if (
                    binding.get("step_attempt_id") is not None
                    and event.kind == "message_completed" and event.phase in {None, "final_answer"}
                    and not event.defer_public_message and binding.get("final_message_id") is None
                    and str(binding["state"]) not in _TERMINAL_BINDING_STATES
                    and self._fence_matches(binding, fence, event.occurred_at)
                    and self._turn_matches(binding, event)
                ):
                    self._require_accepted_message_step(binding, fence)
                    # The immutable stream receipt is reused; formal publication
                    # occurs only now, inside the original owner's acceptance txn.
                    self._project_message(binding=binding, run=self._run_row(binding), event=event)
                return self._receipt(existing, replayed=True)
            if complete_business_run:
                step = self._conn.execute(
                    "SELECT state, accepted_owner_id, accepted_owner_generation, input_revision "
                    "FROM tutor_run_step_attempts WHERE id = %s AND run_id = %s "
                    "AND user_id = %s AND conversation_id = %s FOR UPDATE",
                    (binding.get("step_attempt_id"), binding["run_id"], binding["user_id"], binding["conversation_id"]),
                ).fetchone()
                if (
                    event.kind != "turn_completed" or step is None or step.get("state") != "accepted"
                    or step.get("accepted_owner_id") != fence.lease_owner_id
                    or step.get("accepted_owner_generation") != fence.lease_generation
                    or step.get("input_revision") != fence.input_revision
                    or event.thread_id != str(binding["external_thread_id"])
                    or not self._turn_matches(binding, event)
                    or _as_int(binding["connection_generation"]) != fence.connection_generation
                ):
                    raise TutorRuntimeProjectionError("Tutor business completion requires accepted current step")
                # Typed input acceptance has already atomically committed its
                # public message and terminal binding in this same owner txn.
                if (
                    binding.get("state") == "completed" and binding.get("final_message_id") is not None
                    and binding.get("terminal_outcome") == "completed"
                    and binding.get("input_revision") == fence.input_revision
                ):
                    return self._insert_receipt(
                        binding=binding, event=event, event_key=event_key,
                        status=TutorRuntimeProjectionStatus.APPLIED,
                    )
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
            if complete_business_run:
                status, public_item_id, public_item_kind = self._project_terminal(
                    binding=binding, run=self._run_row(binding), fence=fence, event=event,
                    complete_business_run=True,
                )
            else:
                if (
                    binding.get("step_attempt_id") is not None
                    and event.kind == "message_completed" and event.phase in {None, "final_answer"}
                    and not event.defer_public_message
                ):
                    self._require_accepted_message_step(binding, fence)
                status, public_item_id, public_item_kind = self._apply_event(
                    binding=binding, fence=fence, event=event,
                )
            return self._insert_receipt(
                binding=binding,
                event=event,
                event_key=event_key,
                status=status,
                public_item_id=public_item_id,
                public_item_kind=public_item_kind,
            )

    def next_event_sequence(self, *, binding_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(max(projection_sequence), 0)::int + 1 AS next_sequence
            FROM tutor_runtime_item_receipts
            WHERE binding_id = %s
            """,
            (binding_id,),
        ).fetchone()
        return _as_int(row.get("next_sequence"), 1) if row is not None else 1

    def receipts_for_run(self, *, user_id: str, run_id: str) -> tuple[TutorRuntimeProjectionReceipt, ...]:
        rows = self._conn.execute(
            """
            SELECT receipts.*
            FROM tutor_runtime_item_receipts AS receipts
            JOIN tutor_run_runtime_bindings AS bindings ON bindings.id = receipts.binding_id
            WHERE bindings.user_id = %s AND bindings.run_id = %s
            ORDER BY receipts.projection_sequence, receipts.created_at, receipts.id
            """,
            (user_id, run_id),
        ).fetchall()
        return tuple(self._receipt(row, replayed=False) for row in rows)

    def runtime_output_for_run(self, *, user_id: str, run_id: str) -> dict[str, object] | None:
        rows = self._conn.execute(
            """
            SELECT items.*, runs.input_revision AS run_input_revision
            FROM tutor_runtime_text_items AS items
            JOIN tutor_runs AS runs ON runs.id = items.run_id
            WHERE items.user_id = %s AND items.run_id = %s
              AND runs.user_id = %s AND items.state IN ('streaming', 'completed')
            ORDER BY items.created_at, items.id
            """,
            (user_id, run_id, user_id),
        ).fetchall()
        return self._runtime_output_payload(rows) if rows else None

    def runtime_output_for_message(self, *, user_id: str, message_id: str) -> dict[str, object] | None:
        rows = self._conn.execute(
            """
            SELECT items.*, runs.input_revision AS run_input_revision
            FROM tutor_runtime_text_items AS items
            JOIN tutor_runs AS runs ON runs.id = items.run_id
            JOIN tutor_conversations AS conversations ON conversations.id = items.conversation_id
            WHERE items.user_id = %s AND items.public_message_id = %s
              AND conversations.user_id = %s AND items.state = 'completed'
            ORDER BY items.created_at, items.id
            """,
            (user_id, message_id, user_id),
        ).fetchall()
        return self._runtime_output_payload(rows) if rows else None

    def link_completed_text_items_to_message(
        self,
        *,
        binding_id: str,
        message_id: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE tutor_runtime_text_items
            SET public_message_id = %s
            WHERE binding_id = %s AND state = 'completed' AND public_message_id IS NULL
            """,
            (message_id, binding_id),
        )

    def discard_streaming_text_items_for_server_terminalization(
        self,
        *,
        binding_id: str,
        fence: TutorRuntimeProjectionFence,
        thread_id: str,
        turn_id: str | None,
        sequence: int,
        occurred_at: datetime,
    ) -> None:
        event = TutorRuntimeProjectionEvent(
            kind="turn_completed",
            thread_id=thread_id,
            turn_id=turn_id,
            sequence=sequence,
            occurred_at=occurred_at,
        )
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
            stale = (
                event.thread_id != str(binding["external_thread_id"])
                or str(binding["state"]) in _TERMINAL_BINDING_STATES
                or not self._fence_matches(binding, fence, event.occurred_at)
                or not self._turn_matches(binding, event)
            )
            if stale:
                raise TutorRuntimeProjectionError(
                    "Tutor runtime server terminal cleanup fence is stale"
                )
            self._discard_streaming_text_items(
                binding=binding,
                fence=fence,
                event=event,
            )

    def finalize_typed_request_binding(
        self,
        *,
        binding_id: str,
        user_id: str,
        message_id: str,
        occurred_at: datetime,
    ) -> None:
        with self._conn.transaction():
            row = self._conn.execute(
                """
                UPDATE tutor_run_runtime_bindings
                SET final_message_id = COALESCE(final_message_id, %s),
                    state = 'completed', terminal_at = COALESCE(terminal_at, %s)
                WHERE id = %s AND user_id = %s
                  AND state IN ('thread_bound', 'running', 'completed')
                  AND (final_message_id IS NULL OR final_message_id = %s)
                RETURNING id
                """,
                (message_id, occurred_at, binding_id, user_id, message_id),
            ).fetchone()
            if row is None:
                raise TutorRuntimeProjectionError("Tutor runtime typed request binding is stale")
            self.link_completed_text_items_to_message(
                binding_id=binding_id,
                message_id=message_id,
            )

    def _project_text_item(
        self,
        *,
        binding: Mapping[str, object],
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
        channel: str,
        operation: str,
    ) -> tuple[TutorRuntimeProjectionStatus, str | None, str | None]:
        if event.item_id is None:
            return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None
        item_hash = self._hash_optional(event.item_id)
        if item_hash is None:
            return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None
        supplied_text = event.visible_text
        text = supplied_text or ""
        if operation == "append":
            if supplied_text is None or event.content_hash != self._sha256_text(text):
                return TutorRuntimeProjectionStatus.BLOCKED_UNSAFE, None, None
            if not text:
                return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None
        elif operation == "complete" and supplied_text is not None:
            if event.content_hash != self._sha256_text(text):
                return TutorRuntimeProjectionStatus.BLOCKED_UNSAFE, None, None
        current = self._conn.execute(
            """
            SELECT * FROM tutor_runtime_text_items
            WHERE binding_id = %s AND external_item_hash = %s AND channel = %s
            FOR UPDATE
            """,
            (binding["id"], item_hash, channel),
        ).fetchone()
        if current is None:
            if operation == "discard":
                return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None
            initial_state = "completed" if operation == "complete" else "streaming"
            initial_text = text if operation == "complete" else (text if operation == "append" else "")
            row = self._conn.execute(
                """
                INSERT INTO tutor_runtime_text_items (
                  binding_id, conversation_runtime_thread_id, run_id, user_id,
                  conversation_id, external_item_hash, channel, state, text,
                  last_event_sequence, content_hash, connection_generation,
                  created_at, updated_at, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    binding["id"], binding["conversation_runtime_thread_id"],
                    binding["run_id"], binding["user_id"], binding["conversation_id"],
                    item_hash, channel, initial_state, initial_text, event.sequence,
                    self._sha256_text(initial_text) if initial_text else None,
                    fence.connection_generation, event.occurred_at, event.occurred_at,
                    event.occurred_at if initial_state == "completed" else None,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Tutor runtime text item insert failed")
            current = row
        elif operation == "append":
            if str(current["state"]) != "streaming":
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
            cumulative = str(current.get("text") or "") + text
            if len(cumulative) > 1_000_000:
                self._conn.execute(
                    "UPDATE tutor_runtime_text_items SET state = 'blocked', completed_at = %s WHERE id = %s",
                    (event.occurred_at, current["id"]),
                )
                return TutorRuntimeProjectionStatus.BLOCKED_UNSAFE, None, None
            current = self._conn.execute(
                """
                UPDATE tutor_runtime_text_items
                SET text = %s, last_event_sequence = %s, content_hash = %s, updated_at = %s
                WHERE id = %s AND state = 'streaming' AND last_event_sequence < %s
                RETURNING *
                """,
                (
                    cumulative, event.sequence, self._sha256_text(cumulative),
                    event.occurred_at, current["id"], event.sequence,
                ),
            ).fetchone()
            if current is None:
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
        elif operation == "complete":
            if str(current["state"]) == "completed":
                if supplied_text is not None and str(current.get("text") or "") != text:
                    raise TutorIdempotencyConflict("runtime completed text conflicts with stored authority")
            elif str(current["state"]) != "streaming":
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
            else:
                completed_text = text if supplied_text is not None else str(current.get("text") or "")
                current = self._conn.execute(
                    """
                    UPDATE tutor_runtime_text_items
                    SET text = %s, state = 'completed', last_event_sequence = %s,
                        content_hash = %s, completed_at = %s, updated_at = %s
                    WHERE id = %s AND state = 'streaming'
                    RETURNING *
                    """,
                    (
                        completed_text, event.sequence, self._sha256_text(completed_text), event.occurred_at,
                        event.occurred_at, current["id"],
                    ),
                ).fetchone()
                if current is None:
                    return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
        elif operation == "discard":
            if str(current["state"]) != "streaming":
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
            current = self._conn.execute(
                """
                UPDATE tutor_runtime_text_items
                SET text = '', state = 'discarded', last_event_sequence = %s,
                    content_hash = NULL, completed_at = %s, updated_at = %s
                WHERE id = %s AND state = 'streaming'
                RETURNING *
                """,
                (event.sequence, event.occurred_at, event.occurred_at, current["id"]),
            ).fetchone()
            if current is None:
                return TutorRuntimeProjectionStatus.IGNORED_STALE, None, None
        payload: dict[str, object] = {
            "output_version": TUTOR_RUNTIME_ITEM_STREAM_VERSION,
            "input_revision": fence.input_revision,
            "generation": fence.connection_generation,
            "operation": "reset" if operation == "started" else operation,
            "chunk_sequence": event.sequence,
            "item_id": str(current["id"]),
            "channel": channel,
        }
        if operation == "append":
            payload["text"] = text
        elif operation == "complete":
            payload["text"] = str(current.get("text") or "")
        self._tutor._append_conversation_event_locked(
            user_id=str(binding["user_id"]),
            conversation_id=str(binding["conversation_id"]),
            event_key=f"runtime-output:{binding['id']}:{event.sequence}:{operation}",
            kind=TutorConversationEventKind.TURN_OUTPUT,
            turn_id=str(binding["run_id"]),
            payload=payload,
            occurred_at=event.occurred_at,
        )
        return TutorRuntimeProjectionStatus.APPLIED, str(current["id"]), "runtime_output"

    @staticmethod
    def _runtime_output_payload(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
        reasoning: list[dict[str, object]] = []
        final_answer: dict[str, object] | None = None
        for row in rows:
            item = {
                "item_id": str(row["id"]),
                "text": str(row.get("text") or ""),
                "state": str(row.get("state") or "streaming"),
                "last_sequence": _as_int(row.get("last_event_sequence"), 0),
            }
            if str(row.get("channel")) == "reasoning":
                reasoning.append(item)
            else:
                final_answer = item
        first = rows[0]
        return {
            "output_version": "tutor_runtime_output_v1",
            "input_revision": _as_int(first.get("run_input_revision"), 0),
            "generation": _as_int(first.get("connection_generation"), 1),
            "reasoning_items": reasoning,
            "final_answer_item": final_answer,
        }

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
        if event.kind in {"reasoning_started", "reasoning_delta", "reasoning_completed"}:
            operation = {
                "reasoning_started": "started",
                "reasoning_delta": "append",
                "reasoning_completed": "complete",
            }[event.kind]
            return self._project_text_item(
                binding=binding, fence=fence, event=event,
                channel="reasoning", operation=operation,
            )
        if event.kind in {"message_started", "message_delta"}:
            if event.phase != "final_answer":
                return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None
            operation = "started" if event.kind == "message_started" else "append"
            return self._project_text_item(
                binding=binding, fence=fence, event=event,
                channel="final_answer", operation=operation,
            )
        if event.kind == "message_completed":
            if event.phase not in {None, "final_answer"}:
                return self._project_text_item(
                    binding=binding, fence=fence, event=event,
                    channel="final_answer", operation="discard",
                )
            text_status = self._project_text_item(
                binding=binding, fence=fence, event=event,
                channel="final_answer", operation="complete",
            )
            if event.defer_public_message:
                return text_status
            return self._project_message(binding=binding, run=run, event=event)
        if event.kind == "context_compaction_completed":
            self._conn.execute(
                "UPDATE tutor_conversation_runtime_threads SET last_compacted_at = %s WHERE id = %s",
                (event.occurred_at, binding["conversation_runtime_thread_id"]),
            )
            return TutorRuntimeProjectionStatus.APPLIED, None, None
        if event.kind == "turn_completed":
            return self._project_terminal(binding=binding, run=run, fence=fence, event=event)
        return TutorRuntimeProjectionStatus.IGNORED_NONPUBLIC, None, None

    def _require_accepted_message_step(
        self, binding: Mapping[str, object], fence: TutorRuntimeProjectionFence,
    ) -> None:
        accepted = self._conn.execute(
            "SELECT id FROM tutor_run_step_attempts WHERE id=%s AND run_id=%s "
            "AND user_id=%s AND conversation_id=%s AND input_revision=%s "
            "AND state='accepted' AND accepted_owner_id=%s AND accepted_owner_generation=%s FOR UPDATE",
            (binding["step_attempt_id"], binding["run_id"], binding["user_id"], binding["conversation_id"],
             fence.input_revision, fence.lease_owner_id, fence.lease_generation),
        ).fetchone()
        if accepted is None:
            raise TutorRuntimeProjectionError("Deferred runtime message requires accepted current step")

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
        self.link_completed_text_items_to_message(
            binding_id=str(binding["id"]),
            message_id=message_id,
        )
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

    def _discard_streaming_text_items(
        self,
        *,
        binding: Mapping[str, object],
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
    ) -> None:
        rows = self._conn.execute(
            """
            UPDATE tutor_runtime_text_items
            SET text = '', state = 'discarded', last_event_sequence = %s,
                content_hash = NULL, completed_at = %s, updated_at = %s
            WHERE binding_id = %s AND state = 'streaming'
            RETURNING id, channel
            """,
            (event.sequence, event.occurred_at, event.occurred_at, binding["id"]),
        ).fetchall()
        for row in rows:
            item_id = str(row["id"])
            self._tutor._append_conversation_event_locked(
                user_id=str(binding["user_id"]),
                conversation_id=str(binding["conversation_id"]),
                event_key=(
                    f"runtime-output:{binding['id']}:{event.sequence}:discard:{item_id}"
                ),
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=str(binding["run_id"]),
                payload={
                    "output_version": TUTOR_RUNTIME_ITEM_STREAM_VERSION,
                    "input_revision": fence.input_revision,
                    "generation": fence.connection_generation,
                    "operation": "discard",
                    "chunk_sequence": event.sequence,
                    "item_id": item_id,
                    "channel": str(row["channel"]),
                },
                occurred_at=event.occurred_at,
            )

    def _project_terminal(
        self,
        *,
        binding: Mapping[str, object],
        run: Mapping[str, object],
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
        complete_business_run: bool = False,
    ) -> tuple[TutorRuntimeProjectionStatus, str | None, str | None]:
        requested = event.terminal_status or "failed"
        latest = self._conn.execute(
            "SELECT * FROM tutor_run_runtime_bindings WHERE id = %s FOR UPDATE",
            (binding["id"],),
        ).fetchone()
        if latest is None:
            raise TutorRuntimeProjectionError("Tutor runtime binding was not found")
        self._discard_streaming_text_items(
            binding=latest,
            fence=fence,
            event=event,
        )
        final_message_id = latest.get("final_message_id")
        blocked = latest.get("final_message_blocked") is True
        safe_code = str(latest.get("safe_error_code") or event.safe_code or "runtime_failed")
        if latest.get("step_attempt_id") is not None and not complete_business_run:
            # A native work turn is not the original plan's acceptance boundary.
            # The dispatcher records its durable attempt result separately before
            # any next step. No run terminal, lease release or public completion.
            state = {
                "completed": "completed", "interrupted": "interrupted",
                "failed": "failed", "unavailable": "unavailable",
            }.get(requested, "failed")
            self._conn.execute(
                "UPDATE tutor_run_runtime_bindings SET state = %s, safe_error_code = %s, "
                "terminal_at = %s WHERE id = %s",
                (state, None if requested == "completed" else safe_code, event.occurred_at, binding["id"]),
            )
            return TutorRuntimeProjectionStatus.APPLIED, None, None
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
              external_item_hash, event_sequence, projection_sequence,
              source_sequence_start, source_sequence_end, source_delta_count,
              source_content_hash, item_kind, item_status, tool_name,
              input_hash, result_hash, content_hash, safe_code, projection_status,
              public_item_id, public_item_kind, occurred_at
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                binding["id"], binding["run_id"], binding["user_id"], binding["conversation_id"],
                event_key, event.kind, self._hash_optional(event.item_id), event.sequence,
                event.projection_sequence, event.source_sequence_start,
                event.source_sequence_end,
                event.source_delta_count if event.source_sequence_start is not None else None,
                event.source_content_hash, self._item_kind(event), self._item_status(event),
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
        if event.kind == "turn_completed" and bound_turn is None:
            return event.turn_id is None
        return bound_turn is not None and event.turn_id == str(bound_turn)

    @staticmethod
    def _event_key(event: TutorRuntimeProjectionEvent) -> str:
        safe = {
            "kind": event.kind, "thread": hashlib.sha256(event.thread_id.encode()).hexdigest(),
            "turn": PostgresTutorRuntimeProjectionRepository._hash_optional(event.turn_id),
            "item": PostgresTutorRuntimeProjectionRepository._hash_optional(event.item_id),
            "content": event.content_hash, "code": event.safe_code, "terminal": event.terminal_status,
            "tool": event.tool_name, "input": event.input_hash, "result": event.result_hash,
            "item_type": event.item_type, "phase": event.phase,
            "projection_sequence": event.projection_sequence,
            "source_sequence_start": event.source_sequence_start,
            "source_sequence_end": event.source_sequence_end,
            "source_delta_count": event.source_delta_count,
            "source_content_hash": event.source_content_hash,
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
        if event.kind.startswith("reasoning_summary_"):
            return "reasoning_summary"
        if event.kind.startswith("reasoning_"):
            return "reasoning"
        if event.kind.startswith("message_"):
            return "message"
        if event.kind.startswith("context_compaction_"):
            return "context_compaction"
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
    def _conversation_thread(row: Mapping[str, object]) -> TutorConversationRuntimeThread:
        return TutorConversationRuntimeThread(
            thread_binding_id=str(row["id"]),
            user_id=str(row["user_id"]),
            conversation_id=str(row["conversation_id"]),
            external_thread_id=str(row["external_thread_id"]),
            state=str(row["state"]),
            migration_mode=str(row["migration_mode"]),
        )

    @staticmethod
    def _binding(row: Mapping[str, object]) -> TutorRuntimeBinding:
        return TutorRuntimeBinding(
            binding_id=str(row["id"]), run_id=str(row["run_id"]),
            user_id=str(row["user_id"]), conversation_id=str(row["conversation_id"]),
            state=TutorRuntimeBindingState(str(row["state"])),
            connection_generation=_as_int(row["connection_generation"]),
            step_attempt_id=str(row["step_attempt_id"]) if row.get("step_attempt_id") is not None else None,
        )

    @staticmethod
    def _receipt(row: Mapping[str, object], *, replayed: bool) -> TutorRuntimeProjectionReceipt:
        return TutorRuntimeProjectionReceipt(
            receipt_id=str(row["id"]), binding_id=str(row["binding_id"]),
            event_key=str(row["event_key"]), event_kind=str(row["event_kind"]),
            event_sequence=_as_int(row["event_sequence"]),
            projection_sequence=_as_int(
                row.get("projection_sequence"), _as_int(row["event_sequence"])
            ),
            source_sequence_start=(
                _as_int(row.get("source_sequence_start"))
                if row.get("source_sequence_start") is not None
                else None
            ),
            source_sequence_end=(
                _as_int(row.get("source_sequence_end"))
                if row.get("source_sequence_end") is not None
                else None
            ),
            source_delta_count=(
                _as_int(row.get("source_delta_count"))
                if row.get("source_delta_count") is not None
                else None
            ),
            source_content_hash=(
                str(row["source_content_hash"])
                if row.get("source_content_hash")
                else None
            ),
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
