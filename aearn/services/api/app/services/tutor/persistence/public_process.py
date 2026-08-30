"""Tutor persistence 的 public_process 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class PublicProcessPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def _ensure_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        occurred_at: datetime,
    ) -> None:
        if str(run.get("origin")) != "interactive":
            return
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_run_public_processes (
              run_id, user_id, conversation_id, projection_version,
              display_state, current_step_key, started_at, last_public_activity_at
            )
            VALUES (%s, %s, %s, %s, 'thinking', 'input_received', %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            RETURNING run_id
            """,
            (
                run["id"],
                run["user_id"],
                run["conversation_id"],
                _PUBLIC_PROCESS_VERSION,
                occurred_at,
                occurred_at,
            ),
        ).fetchone()
        if inserted is None:
            return
        self._conn.execute(
            """
            INSERT INTO tutor_run_public_process_steps (run_id, ordinal, step_key, state, occurred_at)
            VALUES (%s, 1, 'input_received', 'completed', %s)
            ON CONFLICT (run_id, ordinal) DO NOTHING
            """,
            (run["id"], occurred_at),
        )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def _append_public_process_step_locked(
        self,
        *,
        run_id: str,
        step_key: str,
        state: str,
        occurred_at: datetime,
    ) -> bool:
        if step_key not in _PUBLIC_PROCESS_STEP_KEYS or state not in _PUBLIC_PROCESS_STEP_STATES:
            raise ValueError("public process step is not allowlisted")
        existing = self._conn.execute(
            """
            SELECT id
            FROM tutor_run_public_process_steps
            WHERE run_id = %s AND step_key = %s
            ORDER BY ordinal DESC
            LIMIT 1
            """,
            (run_id, step_key),
        ).fetchone()
        if existing is not None:
            return False
        ordinal_row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) + 1 AS ordinal FROM tutor_run_public_process_steps WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        ordinal = _as_int(ordinal_row["ordinal"] if ordinal_row is not None else 1, 1)
        self._conn.execute(
            """
            INSERT INTO tutor_run_public_process_steps (run_id, ordinal, step_key, state, occurred_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (run_id, ordinal, step_key, state, occurred_at),
        )
        return True

    def _advance_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        step_key: str,
        occurred_at: datetime,
    ) -> None:
        if step_key not in _PUBLIC_PROCESS_STEP_KEYS:
            raise ValueError("public process step is not allowlisted")
        process = self._conn.execute(
            "SELECT * FROM tutor_run_public_processes WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        if process is None or str(process["display_state"]) != "thinking":
            return
        self._append_public_process_step_locked(
            run_id=str(run["id"]),
            step_key=step_key,
            state="completed",
            occurred_at=occurred_at,
        )
        self._conn.execute(
            """
            UPDATE tutor_run_public_processes
            SET current_step_key = %s,
                last_public_activity_at = GREATEST(last_public_activity_at, %s)
            WHERE run_id = %s
            """,
            (step_key, occurred_at, run["id"]),
        )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:step:{step_key}",
            kind=TutorConversationEventKind.ITEM_UPDATED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def _freeze_public_process_locked(
        self,
        *,
        run: Mapping[str, object],
        display_state: str,
        step_key: str | None,
        occurred_at: datetime,
        tutor_message_id: str | None = None,
    ) -> None:
        if display_state not in _PUBLIC_PROCESS_STATES or display_state == "thinking":
            raise ValueError("public process terminal state is invalid")
        if step_key is not None and step_key not in _PUBLIC_PROCESS_STEP_KEYS:
            raise ValueError("public process step is not allowlisted")
        process = self._conn.execute(
            "SELECT * FROM tutor_run_public_processes WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        # Older records must remain message-only history; do not manufacture a card.
        if process is None:
            return
        if str(process["display_state"]) == "thinking":
            if step_key is not None:
                self._append_public_process_step_locked(
                    run_id=str(run["id"]),
                    step_key=step_key,
                    state="completed",
                    occurred_at=occurred_at,
                )
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET display_state = %s,
                    current_step_key = COALESCE(%s, current_step_key),
                    tutor_message_id = COALESCE(%s, tutor_message_id),
                    last_public_activity_at = GREATEST(last_public_activity_at, %s),
                    finished_at = %s
                WHERE run_id = %s
                """,
                (display_state, step_key, tutor_message_id, occurred_at, occurred_at, run["id"]),
            )
        elif tutor_message_id is not None:
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET tutor_message_id = COALESCE(tutor_message_id, %s)
                WHERE run_id = %s
                """,
                (tutor_message_id, run["id"]),
            )
        self._touch_conversation_public_activity_locked(
            user_id=str(run["user_id"]),
            conversation_id=str(run["conversation_id"]),
            occurred_at=occurred_at,
        )
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:process:{run['id']}:state:{display_state}",
            kind=TutorConversationEventKind.ITEM_UPDATED,
            item_id=str(run["id"]),
            item_kind="process",
            occurred_at=occurred_at,
        )

    def read_public_process(self, *, user_id: str, run_id: str, now: datetime | None = None) -> TutorPublicProcessState | None:
        row = self._conn.execute(
            """
            SELECT processes.*
            FROM tutor_run_public_processes AS processes
            JOIN tutor_runs AS runs ON runs.id = processes.run_id
            WHERE processes.run_id = %s AND runs.user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        return self._public_process_state_from_row(row, now=now) if row is not None else None

    def _public_process_state_from_row(
        self,
        row: Mapping[str, object],
        *,
        now: datetime | None = None,
    ) -> TutorPublicProcessState:
        run_id = str(row["run_id"])
        started_at = _as_datetime(row.get("started_at")) or datetime.now(UTC)
        finished_at = _as_datetime(row.get("finished_at"))
        effective_end = finished_at or now or datetime.now(UTC)
        elapsed_seconds = max(0, min(_MAX_PUBLIC_PROCESS_ELAPSED_SECONDS, int((effective_end - started_at).total_seconds())))
        steps = self._conn.execute(
            """
            SELECT step_key, state, occurred_at
            FROM tutor_run_public_process_steps
            WHERE run_id = %s
            ORDER BY ordinal ASC
            """,
            (run_id,),
        ).fetchall()
        public_steps: list[dict[str, object]] = []
        for step in steps:
            key = str(step.get("step_key") or "")
            if key not in _PUBLIC_PROCESS_STEP_KEYS:
                continue
            state = str(step.get("state") or "completed")
            public_steps.append(
                {
                    "key": key,
                    "state": state if state in _PUBLIC_PROCESS_STEP_STATES else "completed",
                    "label": _PUBLIC_PROCESS_STEP_LABELS[key],
                }
            )
        display_state = str(row.get("display_state") or "unavailable")
        return TutorPublicProcessState(
            run_id=run_id,
            conversation_id=str(row["conversation_id"]),
            display_state=display_state if display_state in _PUBLIC_PROCESS_STATES else "unavailable",
            steps=tuple(public_steps),
            elapsed_seconds=elapsed_seconds,
            created_at=started_at,
            finished_at=finished_at,
        )

    def begin_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        if decision_iteration < 1 or generation < 1 or provider_attempt < 1:
            raise ValueError("public thinking stream identity is invalid")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id,
                run_id=snapshot.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            existing = self._conn.execute(
                "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
                (snapshot.run_id,),
            ).fetchone()
            if existing is not None and generation <= _as_int(existing.get("generation"), 0):
                raise TutorIdempotencyConflict("public thinking generation did not advance")
            if existing is None:
                self._conn.execute(
                    """
                    INSERT INTO tutor_turn_public_thinking_streams (
                      run_id, user_id, conversation_id, input_revision, decision_iteration,
                      generation, provider_attempt, state, thinking_text, next_chunk_sequence,
                      created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', '', 1, %s, %s)
                    """,
                    (
                        snapshot.run_id, snapshot.user_id, snapshot.conversation_id,
                        snapshot.input_revision, decision_iteration, generation,
                        provider_attempt, occurred_at, occurred_at,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE tutor_turn_public_thinking_streams
                    SET input_revision = %s, decision_iteration = %s, generation = %s,
                        provider_attempt = %s, state = 'active', thinking_text = '',
                        next_chunk_sequence = 1, last_public_event_sequence = NULL,
                        completed_at = NULL, discarded_at = NULL, accepted_at = NULL,
                        updated_at = %s
                    WHERE run_id = %s
                    """,
                    (
                        snapshot.input_revision, decision_iteration, generation,
                        provider_attempt, occurred_at, snapshot.run_id,
                    ),
                )
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:reset",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": "reset",
                    "chunk_sequence": 0,
                },
                occurred_at=occurred_at,
            )
            self._conn.execute(
                "UPDATE tutor_turn_public_thinking_streams SET last_public_event_sequence = %s WHERE run_id = %s",
                (event.sequence, snapshot.run_id),
            )

    def append_public_thinking_text(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        text: str,
        occurred_at: datetime,
    ) -> None:
        if not text or len(text) > PUBLIC_THINKING_CHUNK_MAX_LENGTH:
            raise ValueError("public thinking chunk is empty or oversized")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id, run_id=snapshot.run_id, learner_only=False
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            stream = self._lock_public_thinking_stream(
                snapshot=snapshot, generation=generation, provider_attempt=provider_attempt
            )
            if str(stream.get("state")) != "active":
                raise TutorTerminalStateConflict("public thinking stream is not active")
            current_text = str(stream.get("thinking_text") or "")
            cumulative = current_text + text
            if len(cumulative) > MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH:
                raise TutorTerminalStateConflict("public thinking stream exceeded its bound")
            if check_teaching_output(cumulative).blocked:
                raise TutorTerminalStateConflict("public thinking stream failed teaching safety")
            chunk_sequence = _as_int(stream.get("next_chunk_sequence"), 1)
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:{chunk_sequence}:append",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": "append",
                    "chunk_sequence": chunk_sequence,
                    "text": text,
                },
                occurred_at=occurred_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_turn_public_thinking_streams
                SET thinking_text = %s, next_chunk_sequence = %s,
                    last_public_event_sequence = %s, updated_at = %s
                WHERE run_id = %s AND generation = %s AND state = 'active'
                RETURNING run_id
                """,
                (
                    cumulative, chunk_sequence + 1, event.sequence, occurred_at,
                    snapshot.run_id, generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLifecycleConflict("public thinking append lost generation ownership")

    def complete_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        self._finish_public_thinking_stream(
            snapshot=snapshot, lease=lease, generation=generation,
            provider_attempt=provider_attempt, state="complete", operation="complete",
            occurred_at=occurred_at,
        )

    def discard_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        occurred_at: datetime,
    ) -> None:
        self._finish_public_thinking_stream(
            snapshot=snapshot, lease=lease, generation=generation,
            provider_attempt=provider_attempt, state="discarded", operation="discard",
            occurred_at=occurred_at,
        )

    def _finish_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        generation: int,
        provider_attempt: int,
        state: Literal["complete", "discarded"],
        operation: Literal["complete", "discard"],
        occurred_at: datetime,
    ) -> None:
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=snapshot.user_id, run_id=snapshot.run_id, learner_only=False
            )
            _assert_active_lease(run, lease=lease, now=occurred_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if snapshot.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("public thinking stream revision is stale")
            stream = self._lock_public_thinking_stream(
                snapshot=snapshot, generation=generation, provider_attempt=provider_attempt
            )
            current_state = str(stream.get("state") or "")
            if current_state == state:
                return
            allowed_states = {"active", "complete"} if state == "discarded" else {"active"}
            if current_state not in allowed_states:
                raise TutorTerminalStateConflict("public thinking stream transition is invalid")
            if state == "complete" and not str(stream.get("thinking_text") or "").strip():
                raise TutorTerminalStateConflict("public thinking stream cannot complete empty")
            chunk_sequence = _as_int(stream.get("next_chunk_sequence"), 1)
            event = self._append_conversation_event_locked(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                event_key=f"turn-output:{snapshot.run_id}:{generation}:{chunk_sequence}:{operation}",
                kind=TutorConversationEventKind.TURN_OUTPUT,
                turn_id=snapshot.run_id,
                payload={
                    "output_version": TUTOR_PUBLIC_THINKING_STREAM_VERSION,
                    "input_revision": snapshot.input_revision,
                    "generation": generation,
                    "operation": operation,
                    "chunk_sequence": chunk_sequence,
                },
                occurred_at=occurred_at,
            )
            completed_at = occurred_at if state == "complete" else None
            discarded_at = occurred_at if state == "discarded" else None
            updated = self._conn.execute(
                """
                UPDATE tutor_turn_public_thinking_streams
                SET state = %s, next_chunk_sequence = %s, last_public_event_sequence = %s,
                    completed_at = COALESCE(completed_at, %s), discarded_at = %s,
                    accepted_at = NULL, updated_at = %s
                WHERE run_id = %s AND generation = %s
                RETURNING run_id
                """,
                (
                    state, chunk_sequence + 1, event.sequence, completed_at, discarded_at,
                    occurred_at, snapshot.run_id, generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLifecycleConflict("public thinking completion lost generation ownership")

    def _lock_public_thinking_stream(
        self,
        *,
        snapshot: TutorRunSnapshot,
        generation: int,
        provider_attempt: int,
    ) -> Mapping[str, object]:
        stream = self._conn.execute(
            "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
            (snapshot.run_id,),
        ).fetchone()
        if stream is None:
            raise TutorLifecycleConflict("public thinking stream row is missing")
        if (
            str(stream.get("user_id")) != snapshot.user_id
            or str(stream.get("conversation_id")) != snapshot.conversation_id
            or _as_int(stream.get("input_revision"), -1) != snapshot.input_revision
            or _as_int(stream.get("generation"), -1) != generation
            or _as_int(stream.get("provider_attempt"), -1) != provider_attempt
        ):
            raise TutorLifecycleConflict("public thinking stream scope or generation is stale")
        return stream

    def _public_active_thinking_from_row(
        self,
        run: Mapping[str, object],
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_turn_public_thinking_streams
            WHERE run_id = %s AND user_id = %s AND conversation_id = %s
              AND input_revision = %s AND state IN ('active', 'complete')
            """,
            (run["id"], run["user_id"], run["conversation_id"], run["input_revision"]),
        ).fetchone()
        if row is None:
            return None
        return {
            "turn_id": str(row["run_id"]),
            "input_revision": _as_int(row.get("input_revision"), 0),
            "generation": _as_int(row.get("generation"), 1),
            "state": str(row.get("state") or "active"),
            "text": str(row.get("thinking_text") or ""),
            "complete": str(row.get("state") or "") == "complete",
            "last_event_sequence": _as_int(row.get("last_public_event_sequence"), 0),
        }

    def _accept_public_thinking_stream_locked(
        self,
        *,
        run: Mapping[str, object],
        result: TutorRunResult,
        accepted_at: datetime,
    ) -> None:
        stream = self._conn.execute(
            "SELECT * FROM tutor_turn_public_thinking_streams WHERE run_id = %s FOR UPDATE",
            (run["id"],),
        ).fetchone()
        if stream is None:
            return
        if (
            str(stream.get("state") or "") != "complete"
            or _as_int(stream.get("input_revision"), -1) != result.input_revision
            or _as_int(stream.get("decision_iteration"), -1) != result.model_call_count
            or str(stream.get("thinking_text") or "") != result.public_thinking_text
        ):
            raise TutorTerminalStateConflict(
                "public thinking stream does not match the authoritative Tutor result"
            )
        updated = self._conn.execute(
            """
            UPDATE tutor_turn_public_thinking_streams
            SET state = 'accepted', accepted_at = %s, updated_at = %s
            WHERE run_id = %s AND state = 'complete'
            RETURNING run_id
            """,
            (accepted_at, accepted_at, run["id"]),
        ).fetchone()
        if updated is None:
            raise TutorLifecycleConflict("public thinking stream acceptance lost ownership")

    def _record_public_message_locked(
        self,
        *,
        run: Mapping[str, object],
        result: TutorRunResult,
        created_at: datetime,
    ) -> str | None:
        public_message = sanitize_summary_text(result.public_message or "", max_length=1_200)
        if not public_message:
            return None
        self._accept_public_thinking_stream_locked(
            run=run,
            result=result,
            accepted_at=created_at,
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_messages (
              conversation_id, role, content, public_thinking_text,
              public_thinking_steps_json, created_at
            )
            VALUES (%s, 'tutor', %s, %s, '[]'::jsonb, %s)
            RETURNING id
            """,
            (
                run["conversation_id"],
                public_message,
                result.public_thinking_text,
                created_at,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor public message insert failed")
        message_id = str(row["id"])
        self._append_item_reference_event_locked(
            run=run,
            event_key=f"item:message:{message_id}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=message_id,
            item_kind="message",
            occurred_at=created_at,
        )
        return message_id
