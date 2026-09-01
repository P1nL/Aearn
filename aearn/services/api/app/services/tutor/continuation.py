"""Durable idempotent continuation intents and deterministic single-turn arbitration."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

from app.core.config import Settings, get_settings
from app.services.learning.teaching_contracts import (
    TeachingControlKey,
    TeachingControlStimulus,
    TeachingSessionMode,
)
from app.services.learning.teaching_sessions import (
    TeachingSessionConflict,
    TeachingSessionNotFound,
    TeachingSessionRepository,
)


_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_STABLE_SOURCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_INTENT_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://aearn.local/contracts/tutor-continuation-intent-v1",
)


class ContinuationSourceKind(StrEnum):
    LEARNER_MESSAGE = "learner_message"
    EXPLICIT_ARTIFACT_ACTION = "explicit_artifact_action"
    EXPECTED_INTERACTIVE_EVENT = "expected_interactive_event"
    STATIC_DISPLAY_TIMER = "static_display_timer"
    BACKGROUND_CONTINUATION = "background_continuation"


CONTINUATION_PRIORITY: Mapping[ContinuationSourceKind, int] = {
    ContinuationSourceKind.LEARNER_MESSAGE: 500,
    ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION: 400,
    ContinuationSourceKind.EXPECTED_INTERACTIVE_EVENT: 300,
    ContinuationSourceKind.STATIC_DISPLAY_TIMER: 200,
    ContinuationSourceKind.BACKGROUND_CONTINUATION: 100,
}


class ContinuationIntentState(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"


class ContinuationIntentError(ValueError):
    pass


class ContinuationIntentNotFound(ContinuationIntentError):
    pass


class ContinuationIntentConflict(ContinuationIntentError):
    pass


class ContinuationIntentStale(ContinuationIntentError):
    pass


@dataclass(frozen=True, slots=True)
class ContinuationIntentRecord:
    intent_id: str
    user_id: str
    conversation_id: str
    learning_track_id: str
    knowledge_key: str
    teaching_session_id: str
    checkpoint_id: str
    artifact_id: str
    branch_id: str | None
    source_kind: ContinuationSourceKind
    source_id: str
    source_version: int
    priority: int
    session_version: int
    artifact_version: int
    track_version: int
    progress_version: int
    assignment_version: int
    idempotency_key: str
    request_hash: str
    state: ContinuationIntentState
    version: int
    not_before: datetime
    claimed_by: str | None
    claim_generation: int
    claim_expires_at: datetime | None
    consumed_run_id: str | None
    terminal_reason: str | None
    created_at: datetime
    updated_at: datetime
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class ContinuationDispatchResult:
    intent: ContinuationIntentRecord
    run_id: str
    dispatch_job_id: str | None
    runtime_kind: Literal["harness_v1"] = "harness_v1"


class PostgresTutorContinuationIntentRepository:
    """Persist scheduling facts only; this class never invokes a provider."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def create_pending(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        source_kind: ContinuationSourceKind | str,
        source_id: str,
        source_version: int,
        idempotency_key: str,
        branch_id: str | None = None,
        not_before: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        kind = ContinuationSourceKind(str(source_kind))
        source = _stable(source_id, "source_id")
        key = _idempotency(idempotency_key)
        if source_version < 1:
            raise ValueError("continuation source version must be positive")
        if (kind is ContinuationSourceKind.LEARNER_MESSAGE) != (branch_id is not None):
            raise ValueError("learner-message continuation requires exactly one branch")
        now = _utc(occurred_at or datetime.now(UTC))
        ready_at = _utc(not_before or now)
        request_hash = _hash(
            {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "artifact_id": artifact_id,
                "branch_id": branch_id,
                "source_kind": kind.value,
                "source_id": source,
                "source_version": source_version,
                "not_before": (
                    _utc(not_before).isoformat() if not_before is not None else None
                ),
            }
        )
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (user_id, f"tutor-continuation:{conversation_id}:{key}"),
            )
            existing = self._conn.execute(
                """
                SELECT * FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (user_id, conversation_id, key),
            ).fetchone()
            if existing is not None:
                return self._replay(existing, request_hash=request_hash)
            source_existing = self._conn.execute(
                """
                SELECT * FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s AND artifact_id = %s
                  AND source_kind = %s AND source_id = %s AND source_version = %s
                FOR UPDATE
                """,
                (
                    user_id,
                    conversation_id,
                    artifact_id,
                    kind.value,
                    source,
                    source_version,
                ),
            ).fetchone()
            if source_existing is not None:
                return self._replay(source_existing, request_hash=request_hash)
            scope = self._load_scope(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                for_update=True,
            )
            intent_id = str(
                uuid5(
                    _INTENT_NAMESPACE,
                    f"{user_id}:{conversation_id}:{key}",
                )
            )
            event_id = str(uuid4())
            try:
                row = self._conn.execute(
                    """
                    INSERT INTO tutor_continuation_intents (
                      id, user_id, conversation_id, learning_track_id, knowledge_key,
                      teaching_session_id, checkpoint_id, artifact_id, branch_id,
                      source_kind, source_id, source_version, priority,
                      session_version, artifact_version, track_version, progress_version,
                      assignment_version, idempotency_key, request_hash, state,
                      current_event_id, version, not_before, created_at, updated_at
                    ) VALUES (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, 'pending',
                      %s, 1, %s, %s, %s
                    ) RETURNING *
                    """,
                    (
                        intent_id,
                        user_id,
                        conversation_id,
                        scope["learning_track_id"],
                        scope["knowledge_key"],
                        scope["teaching_session_id"],
                        scope["checkpoint_id"],
                        artifact_id,
                        branch_id,
                        kind.value,
                        source,
                        source_version,
                        CONTINUATION_PRIORITY[kind],
                        scope["session_version"],
                        scope["artifact_version"],
                        scope["track_version"],
                        scope["progress_version"],
                        scope["assignment_version"],
                        key,
                        request_hash,
                        event_id,
                        ready_at,
                        now,
                        now,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Tutor continuation intent insert failed")
                self._insert_event(
                    row=row,
                    event_id=event_id,
                    predecessor_event_id=None,
                    intent_version=1,
                    event_key="created",
                    event_kind="created",
                    state=ContinuationIntentState.PENDING,
                    occurred_at=now,
                )
            except (CheckViolation, ForeignKeyViolation) as exc:
                raise ContinuationIntentStale(
                    "Tutor continuation intent authority is stale or mismatched"
                ) from exc
            except UniqueViolation as exc:
                raise ContinuationIntentConflict(
                    "Tutor continuation intent identity conflicts with durable evidence"
                ) from exc
            return self._record(row)

    def record_learner_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        branch_id: str,
        message_id: str,
        input_revision: int,
        run_id: str,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        now = _utc(occurred_at or datetime.now(UTC))
        with self._conn.transaction():
            record = self.create_pending(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                branch_id=branch_id,
                source_kind=ContinuationSourceKind.LEARNER_MESSAGE,
                source_id=message_id,
                source_version=input_revision,
                idempotency_key=f"learner-message:{message_id}:{input_revision}",
                occurred_at=now,
            )
            if record.state is ContinuationIntentState.CONSUMED:
                if record.consumed_run_id != run_id:
                    raise ContinuationIntentConflict(
                        "learner continuation was consumed by a different Turn"
                    )
                return record
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            claimed = self._conn.execute(
                """
                SELECT * FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s AND state = 'claimed'
                  AND id <> %s
                FOR UPDATE
                """,
                (user_id, conversation_id, record.intent_id),
            ).fetchone()
            if claimed is not None:
                self._transition(
                    claimed,
                    event_kind="released",
                    target_state=ContinuationIntentState.PENDING,
                    event_key=f"released:learner:{message_id}:{input_revision}",
                    occurred_at=now,
                    reason_code="higher_priority_learner_message",
                    claim_generation=_integer(claimed.get("claim_generation")),
                )
            current = self._read_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                intent_id=record.intent_id,
            )
            consumed = self._transition(
                current,
                event_kind="consumed",
                target_state=ContinuationIntentState.CONSUMED,
                event_key=f"consumed:{run_id}",
                occurred_at=now,
                consumed_run_id=run_id,
            )
            return self._record(consumed)

    def claim_next(
        self,
        *,
        user_id: str,
        conversation_id: str,
        claimant_id: str,
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> ContinuationIntentRecord | None:
        claimant = _stable(claimant_id, "claimant_id")
        if lease_seconds < 5 or lease_seconds > 300:
            raise ValueError("continuation claim lease must be within 5..300 seconds")
        current_time = _utc(now or datetime.now(UTC))
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            if self._foreground_exists(
                user_id=user_id, conversation_id=conversation_id
            ):
                return None
            if self._pending_learner_input_exists(
                user_id=user_id,
                conversation_id=conversation_id,
            ):
                return None
            if self._active_branch_exists(
                user_id=user_id,
                conversation_id=conversation_id,
            ):
                return None
            claimed = self._conn.execute(
                """
                SELECT * FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s AND state = 'claimed'
                FOR UPDATE
                """,
                (user_id, conversation_id),
            ).fetchone()
            if (
                claimed is not None
                and _datetime(claimed.get("claim_expires_at")) <= current_time
            ):
                self._transition(
                    claimed,
                    event_kind="released",
                    target_state=ContinuationIntentState.PENDING,
                    event_key=f"released:expired:{_integer(claimed['version']) + 1}",
                    occurred_at=current_time,
                    reason_code="claim_expired",
                    claim_generation=_integer(claimed.get("claim_generation")),
                )
                claimed = None
            candidate = self._next_valid_pending_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                now=current_time,
            )
            if claimed is not None:
                if candidate is not None and _integer(candidate["priority"]) > _integer(
                    claimed["priority"]
                ):
                    self._transition(
                        claimed,
                        event_kind="released",
                        target_state=ContinuationIntentState.PENDING,
                        event_key=f"released:priority:{candidate['id']}:{_integer(claimed['version']) + 1}",
                        occurred_at=current_time,
                        reason_code="higher_priority_intent",
                        claim_generation=_integer(claimed.get("claim_generation")),
                    )
                else:
                    return (
                        self._record(claimed, replayed=True)
                        if str(claimed.get("claimed_by") or "") == claimant
                        else None
                    )
            if candidate is None:
                return None
            expires_at = current_time + timedelta(seconds=lease_seconds)
            updated = self._transition(
                candidate,
                event_kind="claimed",
                target_state=ContinuationIntentState.CLAIMED,
                event_key=f"claimed:{claimant}:{_integer(candidate['version']) + 1}",
                occurred_at=current_time,
                claimed_by=claimant,
                claim_generation=_integer(candidate.get("claim_generation")) + 1,
                claim_expires_at=expires_at,
            )
            return self._record(updated)

    def consume_claim(
        self,
        *,
        user_id: str,
        conversation_id: str,
        intent_id: str,
        claimant_id: str,
        claim_generation: int,
        run_id: str,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        claimant = _stable(claimant_id, "claimant_id")
        now = _utc(occurred_at or datetime.now(UTC))
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            current = self._read_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                intent_id=intent_id,
            )
            if (
                str(current.get("state")) != ContinuationIntentState.CLAIMED.value
                or str(current.get("claimed_by") or "") != claimant
                or _integer(current.get("claim_generation")) != claim_generation
                or _datetime(current.get("claim_expires_at")) <= now
            ):
                raise ContinuationIntentConflict("continuation claim is stale")
            updated = self._transition(
                current,
                event_kind="consumed",
                target_state=ContinuationIntentState.CONSUMED,
                event_key=f"consumed:{run_id}",
                occurred_at=now,
                consumed_run_id=run_id,
                claimed_by=claimant,
                claim_generation=claim_generation,
                claim_expires_at=_datetime(current.get("claim_expires_at")),
            )
            return self._record(updated)

    def cancel(
        self,
        *,
        user_id: str,
        conversation_id: str,
        intent_id: str,
        reason_code: str,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        reason = _stable(reason_code, "reason_code")
        now = _utc(occurred_at or datetime.now(UTC))
        with self._conn.transaction():
            self._lock_conversation(user_id=user_id, conversation_id=conversation_id)
            current = self._read_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                intent_id=intent_id,
            )
            state = ContinuationIntentState(str(current["state"]))
            if state in {
                ContinuationIntentState.CONSUMED,
                ContinuationIntentState.CANCELLED,
                ContinuationIntentState.SUPERSEDED,
            }:
                return self._record(current, replayed=True)
            updated = self._transition(
                current,
                event_kind="cancelled",
                target_state=ContinuationIntentState.CANCELLED,
                event_key=f"cancelled:{reason}:{_integer(current['version']) + 1}",
                occurred_at=now,
                reason_code=reason,
                claim_generation=_integer(current.get("claim_generation")),
            )
            return self._record(updated)

    def read(
        self,
        *,
        user_id: str,
        conversation_id: str,
        intent_id: str,
    ) -> ContinuationIntentRecord:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_continuation_intents
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (intent_id, user_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ContinuationIntentNotFound("Tutor continuation intent was not found")
        return self._record(row)

    def _next_valid_pending_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        now: datetime,
    ) -> Mapping[str, object] | None:
        for _ in range(100):
            row = self._conn.execute(
                """
                SELECT * FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s
                  AND state = 'pending' AND not_before <= %s
                ORDER BY priority DESC, created_at, id
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, conversation_id, now),
            ).fetchone()
            if row is None:
                return None
            if self._authority_current(row):
                return row
            self._transition(
                row,
                event_kind="cancelled",
                target_state=ContinuationIntentState.CANCELLED,
                event_key=f"cancelled:stale:{_integer(row['version']) + 1}",
                occurred_at=now,
                reason_code="authority_stale",
            )
        raise ContinuationIntentConflict("continuation intent scan exceeded its bound")

    def _authority_current(self, row: Mapping[str, object]) -> bool:
        current = self._conn.execute(
            """
            SELECT artifacts.version AS artifact_version, artifacts.state AS artifact_state,
                   sessions.version AS session_version, sessions.status AS session_status,
                   sessions.mode AS session_mode, sessions.current_checkpoint_id,
                   sessions.track_version, sessions.progress_version,
                   sessions.assignment_version
            FROM tutor_learning_artifacts AS artifacts
            JOIN tutor_teaching_sessions AS sessions
              ON sessions.id = artifacts.teaching_session_id
             AND sessions.user_id = artifacts.user_id
             AND sessions.conversation_id = artifacts.conversation_id
            WHERE artifacts.id = %s AND artifacts.user_id = %s
              AND artifacts.conversation_id = %s
            """,
            (row["artifact_id"], row["user_id"], row["conversation_id"]),
        ).fetchone()
        if current is None:
            return False
        kind = ContinuationSourceKind(str(row["source_kind"]))
        if (
            _integer(current["artifact_version"]) != _integer(row["artifact_version"])
            or str(current["session_status"]) not in {"active", "paused"}
            or _integer(current["session_version"]) < _integer(row["session_version"])
            or _integer(current["track_version"]) != _integer(row["track_version"])
            or _integer(current["progress_version"])
            != _integer(row["progress_version"])
            or _integer(current["assignment_version"])
            != _integer(row["assignment_version"])
        ):
            return False
        if kind is ContinuationSourceKind.LEARNER_MESSAGE:
            if _integer(current["session_version"]) != _integer(
                row["session_version"]
            ) or str(current["current_checkpoint_id"]) != str(row["checkpoint_id"]):
                return False
        elif not self._checkpoint_descends_from(
            session_id=str(row["teaching_session_id"]),
            user_id=str(row["user_id"]),
            conversation_id=str(row["conversation_id"]),
            checkpoint_id=str(current["current_checkpoint_id"]),
            ancestor_checkpoint_id=str(row["checkpoint_id"]),
        ):
            return False
        if (
            kind
            in {
                ContinuationSourceKind.STATIC_DISPLAY_TIMER,
                ContinuationSourceKind.BACKGROUND_CONTINUATION,
            }
            and str(current["session_mode"]) != TeachingSessionMode.GUIDED.value
        ):
            return False
        return not (
            kind
            in {
                ContinuationSourceKind.LEARNER_MESSAGE,
                ContinuationSourceKind.STATIC_DISPLAY_TIMER,
                ContinuationSourceKind.BACKGROUND_CONTINUATION,
            }
            and str(current["artifact_state"])
            in {"completed", "failed", "cancelled", "superseded"}
        )

    def _transition(
        self,
        row: Mapping[str, object],
        *,
        event_kind: str,
        target_state: ContinuationIntentState,
        event_key: str,
        occurred_at: datetime,
        claimed_by: str | None = None,
        claim_generation: int | None = None,
        claim_expires_at: datetime | None = None,
        consumed_run_id: str | None = None,
        reason_code: str | None = None,
    ) -> Mapping[str, object]:
        next_version = _integer(row["version"]) + 1
        resolved_claim_generation = (
            _integer(row.get("claim_generation"))
            if claim_generation is None
            else claim_generation
        )
        terminal_reason = (
            reason_code
            if target_state
            in {
                ContinuationIntentState.CANCELLED,
                ContinuationIntentState.SUPERSEDED,
            }
            else None
        )
        event_id = str(uuid4())
        self._insert_event(
            row=row,
            event_id=event_id,
            predecessor_event_id=str(row["current_event_id"]),
            intent_version=next_version,
            event_key=event_key,
            event_kind=event_kind,
            state=target_state,
            occurred_at=occurred_at,
            claimed_by=claimed_by,
            claim_generation=resolved_claim_generation,
            claim_expires_at=claim_expires_at,
            consumed_run_id=consumed_run_id,
            reason_code=reason_code,
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_continuation_intents
            SET state = %s, current_event_id = %s, version = %s,
                claimed_by = %s, claim_generation = %s, claim_expires_at = %s,
                consumed_run_id = %s, terminal_reason = %s, updated_at = %s
            WHERE id = %s AND version = %s AND current_event_id = %s AND state = %s
            RETURNING *
            """,
            (
                target_state.value,
                event_id,
                next_version,
                claimed_by,
                resolved_claim_generation,
                claim_expires_at,
                consumed_run_id,
                terminal_reason,
                occurred_at,
                row["id"],
                row["version"],
                row["current_event_id"],
                row["state"],
            ),
        ).fetchone()
        if updated is None:
            raise ContinuationIntentConflict(
                "Tutor continuation intent changed before CAS"
            )
        return updated

    def _insert_event(
        self,
        *,
        row: Mapping[str, object],
        event_id: str,
        predecessor_event_id: str | None,
        intent_version: int,
        event_key: str,
        event_kind: str,
        state: ContinuationIntentState,
        occurred_at: datetime,
        claimed_by: str | None = None,
        claim_generation: int = 0,
        claim_expires_at: datetime | None = None,
        consumed_run_id: str | None = None,
        reason_code: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_continuation_intent_events (
              id, intent_id, user_id, conversation_id, artifact_id,
              predecessor_event_id, intent_version, event_key, event_kind, state,
              claimed_by, claim_generation, claim_expires_at, consumed_run_id,
              reason_code, created_at
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s
            )
            """,
            (
                event_id,
                row["id"],
                row["user_id"],
                row["conversation_id"],
                row["artifact_id"],
                predecessor_event_id,
                intent_version,
                _stable(event_key, "event_key", max_length=200),
                event_kind,
                state.value,
                claimed_by,
                claim_generation,
                claim_expires_at,
                consumed_run_id,
                reason_code,
                occurred_at,
            ),
        )

    def _load_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        for_update: bool,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT artifacts.learning_track_id, artifacts.knowledge_key,
                   artifacts.teaching_session_id, artifacts.checkpoint_id,
                   artifacts.version AS artifact_version, artifacts.track_version,
                   artifacts.progress_version, artifacts.assignment_version,
                   sessions.version AS session_version
            FROM tutor_learning_artifacts AS artifacts
            JOIN tutor_teaching_sessions AS sessions
              ON sessions.id = artifacts.teaching_session_id
             AND sessions.user_id = artifacts.user_id
             AND sessions.conversation_id = artifacts.conversation_id
            WHERE artifacts.id = %s AND artifacts.user_id = %s
              AND artifacts.conversation_id = %s
            """
            + (" FOR UPDATE OF artifacts, sessions" if for_update else ""),
            (artifact_id, user_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ContinuationIntentNotFound(
                "Tutor continuation Artifact was not found"
            )
        return row

    def _lock_conversation(self, *, user_id: str, conversation_id: str) -> None:
        row = self._conn.execute(
            """
            SELECT id FROM tutor_conversations
            WHERE id = %s AND user_id = %s AND visibility = 'learner'
              AND kind = 'interactive' AND status = 'active'
            FOR UPDATE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise ContinuationIntentNotFound("Tutor conversation was not found")

    def _foreground_exists(self, *, user_id: str, conversation_id: str) -> bool:
        return (
            self._conn.execute(
                """
                SELECT 1 FROM tutor_runs
                WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
                  AND terminal_outcome IS NULL AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                LIMIT 1
                """,
                (user_id, conversation_id),
            ).fetchone()
            is not None
        )

    def _pending_learner_input_exists(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        return (
            self._conn.execute(
                """
                SELECT 1 FROM tutor_queued_inputs
                WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
                LIMIT 1
                """,
                (user_id, conversation_id),
            ).fetchone()
            is not None
        )

    def _active_branch_exists(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> bool:
        return (
            self._conn.execute(
                """
                SELECT 1 FROM tutor_conversation_branches
                WHERE user_id = %s AND conversation_id = %s AND state = 'active'
                LIMIT 1
                """,
                (user_id, conversation_id),
            ).fetchone()
            is not None
        )

    def _checkpoint_descends_from(
        self,
        *,
        session_id: str,
        user_id: str,
        conversation_id: str,
        checkpoint_id: str,
        ancestor_checkpoint_id: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT tutor_teaching_checkpoint_descends_from(
              %s, %s, %s, %s, %s
            ) AS matches
            """,
            (
                checkpoint_id,
                ancestor_checkpoint_id,
                session_id,
                user_id,
                conversation_id,
            ),
        ).fetchone()
        return bool(row is not None and row.get("matches"))

    def _read_locked(
        self,
        *,
        user_id: str,
        conversation_id: str,
        intent_id: str,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_continuation_intents
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            FOR UPDATE
            """,
            (intent_id, user_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ContinuationIntentNotFound("Tutor continuation intent was not found")
        return row

    def _replay(
        self,
        row: Mapping[str, object],
        *,
        request_hash: str,
    ) -> ContinuationIntentRecord:
        if str(row.get("request_hash") or "") != request_hash:
            raise ContinuationIntentConflict(
                "Tutor continuation idempotency identity conflicts with another request"
            )
        return self._record(row, replayed=True)

    @staticmethod
    def _record(
        row: Mapping[str, object],
        *,
        replayed: bool = False,
    ) -> ContinuationIntentRecord:
        return ContinuationIntentRecord(
            intent_id=str(row["id"]),
            user_id=str(row["user_id"]),
            conversation_id=str(row["conversation_id"]),
            learning_track_id=str(row["learning_track_id"]),
            knowledge_key=str(row["knowledge_key"]),
            teaching_session_id=str(row["teaching_session_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            artifact_id=str(row["artifact_id"]),
            branch_id=str(row["branch_id"])
            if row.get("branch_id") is not None
            else None,
            source_kind=ContinuationSourceKind(str(row["source_kind"])),
            source_id=str(row["source_id"]),
            source_version=_integer(row["source_version"]),
            priority=_integer(row["priority"]),
            session_version=_integer(row["session_version"]),
            artifact_version=_integer(row["artifact_version"]),
            track_version=_integer(row["track_version"]),
            progress_version=_integer(row["progress_version"]),
            assignment_version=_integer(row["assignment_version"]),
            idempotency_key=str(row["idempotency_key"]),
            request_hash=str(row["request_hash"]),
            state=ContinuationIntentState(str(row["state"])),
            version=_integer(row["version"]),
            not_before=_datetime(row["not_before"]),
            claimed_by=str(row["claimed_by"])
            if row.get("claimed_by") is not None
            else None,
            claim_generation=_integer(row.get("claim_generation")),
            claim_expires_at=(
                _datetime(row["claim_expires_at"])
                if row.get("claim_expires_at") is not None
                else None
            ),
            consumed_run_id=(
                str(row["consumed_run_id"])
                if row.get("consumed_run_id") is not None
                else None
            ),
            terminal_reason=(
                str(row["terminal_reason"])
                if row.get("terminal_reason") is not None
                else None
            ),
            created_at=_datetime(row["created_at"]),
            updated_at=_datetime(row["updated_at"]),
            replayed=replayed,
        )


class TutorContinuationIntentProducer:
    """Safe producer facade; recording an intent never creates a Turn or calls a provider."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._repository = PostgresTutorContinuationIntentRepository(conn)

    def record_artifact_action(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        artifact_event_id: str,
        artifact_event_sequence: int,
        action_kind: str,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        source_kind = (
            ContinuationSourceKind.EXPECTED_INTERACTIVE_EVENT
            if str(action_kind) == "acknowledge_demo_event"
            else ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION
        )
        return self._repository.create_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            source_kind=source_kind,
            source_id=artifact_event_id,
            source_version=artifact_event_sequence,
            idempotency_key=f"artifact-event:{artifact_event_id}",
            occurred_at=occurred_at,
        )

    def record_static_display_timer(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        timer_id: str,
        timer_version: int,
        not_before: datetime,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        return self._repository.create_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            source_kind=ContinuationSourceKind.STATIC_DISPLAY_TIMER,
            source_id=timer_id,
            source_version=timer_version,
            idempotency_key=(
                "static-timer:"
                + _hash({"timer_id": timer_id, "timer_version": timer_version})[:48]
            ),
            not_before=not_before,
            occurred_at=occurred_at,
        )

    def record_result_evaluation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        result_artifact_id: str,
        result_artifact_event_id: str,
        result_artifact_event_sequence: int,
        attempt_id: str,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        """Record one exact evaluation continuation for a projected terminal result."""

        evidence = self._conn.execute(
            """
            SELECT artifacts.id
            FROM tutor_learning_artifacts AS artifacts
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id = artifacts.id
             AND events.user_id = artifacts.user_id
             AND events.conversation_id = artifacts.conversation_id
             AND events.teaching_session_id = artifacts.teaching_session_id
            WHERE artifacts.id = %s
              AND artifacts.user_id = %s
              AND artifacts.conversation_id = %s
              AND artifacts.artifact_kind = 'test_result'
              AND artifacts.purpose = 'result'
              AND artifacts.state = 'completed'
              AND NOT artifacts.blocking
              AND artifacts.active_attempt_id = %s
              AND artifacts.presentation_kind = 'test_result_v1'
              AND artifacts.presentation_json->>'attempt_id' = %s
              AND events.id = %s
              AND events.event_sequence = %s
              AND events.event_kind = 'created'
            """,
            (
                result_artifact_id,
                user_id,
                conversation_id,
                attempt_id,
                attempt_id,
                result_artifact_event_id,
                result_artifact_event_sequence,
            ),
        ).fetchone()
        if evidence is None:
            raise ContinuationIntentStale(
                "result-evaluation continuation lacks exact projected result evidence"
            )
        return self._repository.create_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=result_artifact_id,
            source_kind=ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION,
            source_id=result_artifact_event_id,
            source_version=result_artifact_event_sequence,
            idempotency_key=f"result-evaluation:{result_artifact_event_id}",
            occurred_at=occurred_at,
        )

    def record_background_continuation(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        source_id: str,
        source_version: int,
        not_before: datetime | None = None,
        occurred_at: datetime | None = None,
    ) -> ContinuationIntentRecord:
        return self._repository.create_pending(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            source_kind=ContinuationSourceKind.BACKGROUND_CONTINUATION,
            source_id=source_id,
            source_version=source_version,
            idempotency_key=(
                "background:"
                + _hash({"source_id": source_id, "source_version": source_version})[:48]
            ),
            not_before=not_before,
            occurred_at=occurred_at,
        )


class TutorContinuationDispatcher:
    """Claim one eligible intent and materialize one mainline teaching Turn."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._repository = PostgresTutorContinuationIntentRepository(conn)
        self._teaching = TeachingSessionRepository(conn, settings=self._settings)

    def dispatch_next(
        self,
        *,
        user_id: str,
        conversation_id: str,
        claimant_id: str,
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> ContinuationDispatchResult | None:
        occurred_at = _utc(now or datetime.now(UTC))
        with self._conn.transaction():
            intent = self._repository.claim_next(
                user_id=user_id,
                conversation_id=conversation_id,
                claimant_id=claimant_id,
                now=occurred_at,
                lease_seconds=lease_seconds,
            )
            if intent is None:
                return None
            try:
                session = self._teaching.read_by_id(
                    user_id=user_id,
                    track_id=intent.learning_track_id,
                    session_id=intent.teaching_session_id,
                    for_update=True,
                )
                if (
                    intent.source_kind
                    in {
                        ContinuationSourceKind.STATIC_DISPLAY_TIMER,
                        ContinuationSourceKind.BACKGROUND_CONTINUATION,
                    }
                    and str(session["mode"]) != TeachingSessionMode.GUIDED.value
                ):
                    self._repository.cancel(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        intent_id=intent.intent_id,
                        reason_code="free_reading_automatic_continuation_denied",
                        occurred_at=occurred_at,
                    )
                    return None
                with self._conn.transaction():
                    authority = self._teaching.resolve_authority(
                        user_id=user_id,
                        track_id=intent.learning_track_id,
                        knowledge_key=intent.knowledge_key,
                        conversation_id=conversation_id,
                        for_update=True,
                    )
                    result_evaluation = self._is_result_evaluation_intent(intent)
                    admitted = self._teaching.admit_control_run(
                        authority=authority,
                        session=session,
                        stimulus=TeachingControlStimulus(
                            control_key=TeachingControlKey.CONTINUE,
                            client_action_id=f"continuation:{intent.intent_id}",
                            expected_session_version=_integer(session["version"]),
                            expected_track_version=authority.track_version,
                            expected_progress_version=authority.progress_version,
                            expected_assignment_version=authority.assignment_version,
                            safe_payload={
                                "reason_code": (
                                    "result_evaluation"
                                    if result_evaluation
                                    else intent.source_kind.value
                                ),
                                "source_handle": f"artifact:{intent.artifact_id}",
                            },
                        ),
                        settings=self._settings,
                    )
            except (TeachingSessionConflict, TeachingSessionNotFound):
                self._repository.cancel(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    intent_id=intent.intent_id,
                    reason_code="authority_stale",
                    occurred_at=occurred_at,
                )
                return None
            run_id = str(admitted["run_id"])
            consumed = self._repository.consume_claim(
                user_id=user_id,
                conversation_id=conversation_id,
                intent_id=intent.intent_id,
                claimant_id=claimant_id,
                claim_generation=intent.claim_generation,
                run_id=run_id,
                occurred_at=occurred_at,
            )
            dispatch_job_id = admitted.get("dispatch_job_id")
            return ContinuationDispatchResult(
                intent=consumed,
                run_id=run_id,
                dispatch_job_id=(
                    str(dispatch_job_id) if dispatch_job_id is not None else None
                ),
            )

    def _is_result_evaluation_intent(
        self,
        intent: ContinuationIntentRecord,
    ) -> bool:
        if intent.source_kind is not ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION:
            return False
        result_evaluation_key = f"result-evaluation:{intent.source_id}"
        if intent.idempotency_key != result_evaluation_key:
            if intent.idempotency_key.startswith("result-evaluation:"):
                raise TeachingSessionConflict(
                    "result-evaluation continuation identity is invalid"
                )
            return False
        row = self._conn.execute(
            """
            SELECT 1
            FROM tutor_learning_artifacts AS artifacts
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id = artifacts.id
             AND events.user_id = artifacts.user_id
             AND events.conversation_id = artifacts.conversation_id
             AND events.teaching_session_id = artifacts.teaching_session_id
            WHERE artifacts.id = %s
              AND artifacts.user_id = %s
              AND artifacts.conversation_id = %s
              AND artifacts.artifact_kind = 'test_result'
              AND artifacts.purpose = 'result'
              AND artifacts.state = 'completed'
              AND NOT artifacts.blocking
              AND artifacts.active_attempt_id IS NOT NULL
              AND artifacts.presentation_kind = 'test_result_v1'
              AND events.id::text = %s
              AND events.event_sequence = %s
              AND events.event_kind = 'created'
            """,
            (
                intent.artifact_id,
                intent.user_id,
                intent.conversation_id,
                intent.source_id,
                intent.source_version,
            ),
        ).fetchone()
        if row is None:
            raise TeachingSessionConflict(
                "result-evaluation continuation evidence is stale"
            )
        return True


class TutorContinuationPriorityArbiter:
    """Thin service facade that preserves the repository's fixed priority order."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._repository = PostgresTutorContinuationIntentRepository(conn)

    def claim_next(
        self,
        *,
        user_id: str,
        conversation_id: str,
        claimant_id: str,
        now: datetime | None = None,
        lease_seconds: int = 30,
    ) -> ContinuationIntentRecord | None:
        return self._repository.claim_next(
            user_id=user_id,
            conversation_id=conversation_id,
            claimant_id=claimant_id,
            now=now,
            lease_seconds=lease_seconds,
        )


def _hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable(value: object, label: str, *, max_length: int = 160) -> str:
    normalized = str(value).strip()
    matcher = (
        _STABLE_SOURCE
        if max_length == 160
        else re.compile(rf"^[A-Za-z0-9][A-Za-z0-9._:@-]{{0,{max_length - 1}}}$")
    )
    if not matcher.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded identifier")
    return normalized


def _idempotency(value: object) -> str:
    normalized = str(value).strip()
    if not _IDEMPOTENCY.fullmatch(normalized):
        raise ValueError("continuation idempotency key is invalid")
    return normalized


def _integer(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("expected integer")
    if isinstance(value, int):
        return value
    return int(str(value or 0))


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("expected datetime")
    return _utc(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = (
    "CONTINUATION_PRIORITY",
    "ContinuationDispatchResult",
    "ContinuationIntentConflict",
    "ContinuationIntentError",
    "ContinuationIntentNotFound",
    "ContinuationIntentRecord",
    "ContinuationIntentStale",
    "ContinuationIntentState",
    "ContinuationSourceKind",
    "PostgresTutorContinuationIntentRepository",
    "TutorContinuationDispatcher",
    "TutorContinuationIntentProducer",
    "TutorContinuationPriorityArbiter",
)
