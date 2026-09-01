"""Tutor persistence 的 run 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class RunPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def create_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        run_id: str | None = None,
        origin: TutorRunOrigin,
        policy_version: str = "tutor_policy_v1",
        policy_fingerprint: str | None = None,
        continuation_kind: TutorContinuationKind | None = None,
        interaction_protocol_version: TutorInteractionProtocolVersion = TutorInteractionProtocolVersion.LEGACY_V1,
        retry_of_turn_id: str | None = None,
        retry_root_turn_id: str | None = None,
        response_to_request_id: str | None = None,
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorRunSnapshot:
        if origin not in {"interactive", "proactive"}:
            raise ValueError("Tutor run origin is invalid")
        protocol_version = TutorInteractionProtocolVersion(str(interaction_protocol_version))
        if retry_of_turn_id is None and retry_root_turn_id is not None:
            raise ValueError("retry root requires retry predecessor")
        _safe_key(policy_version, label="policy version")
        run_id = run_id or str(uuid4())
        policy_payload = _policy_payload(policy)
        fingerprint = policy_fingerprint or _sha256_json(policy_payload)
        if not _SHA256.fullmatch(fingerprint):
            raise ValueError("policy fingerprint must be SHA-256")
        conversation = self._conn.execute(
            "SELECT id FROM tutor_conversations WHERE id = %s AND user_id = %s",
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise TutorRunNotFound("tutor conversation not found")
        catalog = self._conn.execute(
            "SELECT digest FROM tutor_catalog_snapshots WHERE digest = %s",
            (catalog_digest,),
        ).fetchone()
        if catalog is None:
            raise TutorCatalogEvidenceError("catalog snapshot is not persisted")
        row = self._conn.execute(
            """
            INSERT INTO tutor_runs (
              id, user_id, conversation_id, origin, status, policy_json,
              policy_version, policy_fingerprint, catalog_digest, continuation_kind,
              interaction_protocol_version, retry_of_turn_id, retry_root_turn_id,
              response_to_request_id, runtime_kind
            )
            VALUES (%s, %s, %s, %s, 'queued', %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                run_id,
                user_id,
                conversation_id,
                origin,
                _json(self._projector.project(policy_payload)),
                policy_version,
                fingerprint,
                catalog_digest,
                continuation_kind.value if continuation_kind is not None else None,
                protocol_version.value,
                retry_of_turn_id,
                retry_root_turn_id,
                response_to_request_id,
                runtime_kind,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("tutor run insert failed")
        return _snapshot_from_row(row)

    def load_snapshot(self, *, user_id: str, run_id: str) -> TutorRunSnapshot | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None

    def read_run_state(self, *, user_id: str, run_id: str) -> TutorRunReadState:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        terminal_value = row.get("terminal_outcome")
        terminal_outcome = TutorTerminalOutcome(str(terminal_value)) if terminal_value is not None else None
        diagnostic = str(row["terminal_diagnostic_code"]) if row.get("terminal_diagnostic_code") is not None else None
        return TutorRunReadState(
            snapshot=_snapshot_from_row(row),
            terminal_outcome=terminal_outcome,
            diagnostic_code=diagnostic,
            created_at=_as_datetime(row.get("created_at")) or datetime.now(UTC),
            updated_at=_as_datetime(row.get("updated_at")) or datetime.now(UTC),
            interaction_protocol_version=_protocol_version_from_row(row),
            retry_of_turn_id=str(row["retry_of_turn_id"]) if row.get("retry_of_turn_id") is not None else None,
            retry_root_turn_id=str(row["retry_root_turn_id"]) if row.get("retry_root_turn_id") is not None else None,
            response_to_request_id=(
                str(row["response_to_request_id"])
                if row.get("response_to_request_id") is not None
                else None
            ),
            completion_reason=(
                TutorTurnCompletionReason(str(row["completion_reason"]))
                if row.get("completion_reason") is not None
                else None
            ),
        )

    def acquire_lease(
        self,
        *,
        user_id: str,
        run_id: str,
        owner_id: str,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        _safe_key(owner_id, label="lease owner")
        if duration_seconds <= 0:
            raise ValueError("lease duration must be positive")
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=run_id)
            if _is_terminal(run) or run.get("cancelled_at") is not None or run.get("superseded_by_run_id") is not None:
                return None
            expires_at = _as_datetime(run.get("active_lease_expires_at"))
            current_owner = str(run.get("active_lease_owner_id") or "")
            if expires_at is not None and expires_at > now and current_owner and current_owner != owner_id:
                return None
            generation = _as_int(run.get("active_lease_generation"), 0) + 1
            new_expiry = now + timedelta(seconds=duration_seconds)
            row = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'leased', active_lease_owner_id = %s,
                    active_lease_generation = %s, active_lease_expires_at = %s
                WHERE id = %s AND user_id = %s
                RETURNING id, active_lease_owner_id, active_lease_generation, active_lease_expires_at
                """,
                (owner_id, generation, new_expiry, run_id, user_id),
            ).fetchone()
            if row is None:
                return None
            return TutorLease(
                run_id=str(row["id"]),
                owner_id=str(row["active_lease_owner_id"]),
                generation=_as_int(row["active_lease_generation"], 1),
                expires_at=_as_datetime(row["active_lease_expires_at"]) or new_expiry,
            )

    def heartbeat_lease(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        now: datetime,
        duration_seconds: int,
    ) -> TutorLease | None:
        if duration_seconds <= 0:
            raise ValueError("lease duration must be positive")
        new_expiry = now + timedelta(seconds=duration_seconds)
        with self._conn.transaction():
            # Permit a late heartbeat only while the exact owner/generation CAS
            # still matches. A replacement claim increments the generation, so
            # an obsolete worker can never renew after another owner takes over.
            row = self._conn.execute(
                """
                UPDATE tutor_runs
                SET active_lease_expires_at = %s
                WHERE id = %s
                  AND user_id = %s
                  AND active_lease_owner_id = %s
                  AND active_lease_generation = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING id, active_lease_owner_id, active_lease_generation, active_lease_expires_at
                """,
                (new_expiry, lease.run_id, user_id, lease.owner_id, lease.generation),
            ).fetchone()
            if row is None:
                return None
            return TutorLease(
                run_id=str(row["id"]),
                owner_id=str(row["active_lease_owner_id"]),
                generation=_as_int(row["active_lease_generation"], 1),
                expires_at=_as_datetime(row["active_lease_expires_at"]) or new_expiry,
            )

    def current_input_revision(self, *, user_id: str, run_id: str) -> int:
        row = self._conn.execute(
            "SELECT input_revision FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return _as_int(row["input_revision"], 0)

    def is_cancelled(self, *, user_id: str, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT cancelled_at FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row.get("cancelled_at") is not None

    def is_superseded(self, *, user_id: str, run_id: str) -> bool:
        row = self._conn.execute(
            "SELECT superseded_by_run_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row.get("superseded_by_run_id") is not None

    def request_cancellation(
        self, *, user_id: str, run_id: str, now: datetime, diagnostic_code: str = "cancelled",
    ) -> None:
        """Terminally cancel one run without allowing a post-provider public write.

        This uses the same conversation-then-run lock order as normal replacement
        and terminal persistence.  A cancellation therefore cannot slip between
        the stale check and the Tutor-message write of an in-flight run.
        """

        _safe_key(diagnostic_code, label="cancellation diagnostic code")
        with self._conn.transaction():
            conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            if _is_terminal(run):
                return
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'cancelled',
                    cancelled_at = COALESCE(cancelled_at, %s),
                    terminal_outcome = 'cancelled',
                    terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, %s),
                    terminal_at = COALESCE(terminal_at, %s),
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
                RETURNING *
                """,
                (now, diagnostic_code, now, run_id, user_id),
            ).fetchone()
            if updated is None:
                return
            if str(updated.get("origin")) == "interactive" and str(conversation.get("visibility")) == "learner":
                self._freeze_public_process_locked(
                    run=updated,
                    display_state="unavailable",
                    step_key=None,
                    occurred_at=now,
                )
            self._append_event_locked(
                run_id=run_id,
                event_key=f"terminal:cancelled:{_as_int(updated['input_revision'], 0)}",
                kind="terminal_result",
                input_revision=_as_int(updated["input_revision"], 0),
                payload={
                    "kind": "terminal_result",
                    "status": "cancelled",
                    "run_id": run_id,
                    "input_revision": _as_int(updated["input_revision"], 0),
                },
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{run_id}:cancelled",
                occurred_at=now,
            )

    def accept_input(
        self,
        *,
        user_id: str,
        run_id: str,
        idempotency_key: str,
        content: str,
        body_hash: str | None = None,
        source: str = "learner",
        role: str = "learner",
        received_at: datetime | None = None,
        ensure_dispatch: bool = True,
    ) -> TutorInputAcceptance:
        _safe_key(idempotency_key, label="input idempotency key")
        _safe_key(source, label="input source")
        if role not in {"learner", "tutor"} or (role == "tutor" and source not in {"authority_receipt", "retry"}):
            raise ValueError("Tutor input role is invalid")
        raw_content = str(content)
        if not raw_content or len(raw_content) > 16_000:
            raise ValueError("learner message must be non-empty and bounded")
        actual_hash = _sha256_text(raw_content)
        if body_hash is not None and body_hash != actual_hash:
            raise TutorIdempotencyConflict("input body hash does not match learner message")
        accepted_at = received_at or datetime.now(UTC)
        event_key = f"input:{idempotency_key}"
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=run_id,
                learner_only=False,
            )
            existing = self._conn.execute(
                """
                SELECT input_revision, message_id, body_hash
                FROM tutor_run_input_events
                WHERE run_id = %s AND idempotency_key = %s
                """,
                (run_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if str(existing["body_hash"]) != actual_hash:
                    raise TutorIdempotencyConflict("input idempotency key has a different body hash")
                event = self._event_by_key_locked(run_id=run_id, event_key=event_key)
                if event is None:
                    raise RuntimeError("input replay event is missing")
                dispatch = self._conn.execute(
                    "SELECT id FROM tutor_interactive_dispatch_jobs WHERE run_id = %s",
                    (run_id,),
                ).fetchone()
                return TutorInputAcceptance(
                    run_id=run_id,
                    message_id=str(existing["message_id"]),
                    input_revision=_as_int(existing["input_revision"], 0),
                    event=event,
                    replayed=True,
                    dispatch_job_id=str(dispatch["id"]) if dispatch is not None else None,
                )
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            _assert_not_terminal(run)
            message = self._conn.execute(
                """
                INSERT INTO tutor_messages (conversation_id, role, content, created_at)
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (run["conversation_id"], role, raw_content, accepted_at),
            ).fetchone()
            if message is None:
                raise RuntimeError("tutor learner message insert failed")
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET input_revision = input_revision + 1,
                    status = CASE
                      WHEN status = 'waiting_for_input' AND continuation_kind IS NOT NULL THEN 'queued'
                      ELSE status
                    END,
                    continuation_kind = CASE
                      WHEN status = 'waiting_for_input' AND continuation_kind IS NOT NULL THEN NULL
                      ELSE continuation_kind
                    END
                WHERE id = %s AND user_id = %s AND input_revision = %s
                RETURNING *
                """,
                (run_id, user_id, _as_int(run["input_revision"], 0)),
            ).fetchone()
            if updated is None:
                raise TutorIdempotencyConflict("input revision changed before acceptance")
            revision = _as_int(updated["input_revision"], 0)
            self._conn.execute(
                """
                INSERT INTO tutor_run_input_events (
                  run_id, conversation_id, message_id, input_revision,
                  idempotency_key, body_hash, source, accepted_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    run["conversation_id"],
                    message["id"],
                    revision,
                    idempotency_key,
                    actual_hash,
                    source,
                    accepted_at,
                ),
            )
            event = self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind="input_accepted",
                input_revision=revision,
                payload={
                    "kind": "input_accepted",
                    "status": "accepted",
                    "run_id": run_id,
                    "conversation_id": str(run["conversation_id"]),
                    "message_id": str(message["id"]),
                    "input_revision": revision,
                    "request_hash": actual_hash,
                },
            )
            self._touch_conversation_public_activity_locked(
                user_id=user_id,
                conversation_id=str(run["conversation_id"]),
                occurred_at=accepted_at,
            )
            dispatch_job = (
                self._ensure_interactive_dispatch_job_locked(run=updated, available_at=accepted_at)
                if ensure_dispatch
                else None
            )
            self._trip_failpoint("after_interactive_dispatch_job")
            if _protocol_version_from_row(updated) is TutorInteractionProtocolVersion.THREAD_TURN_V2:
                self._append_turn_event_locked(
                    run=updated,
                    kind=(
                        TutorConversationEventKind.TURN_CREATED
                        if revision == 1
                        else TutorConversationEventKind.TURN_UPDATED
                    ),
                    event_key=(
                        f"turn:{run_id}:created"
                        if revision == 1
                        else f"turn:{run_id}:input:{revision}"
                    ),
                    occurred_at=accepted_at,
                )
                self._append_item_reference_event_locked(
                    run=updated,
                    event_key=f"item:message:{message['id']}:added",
                    kind=TutorConversationEventKind.ITEM_ADDED,
                    item_id=str(message["id"]),
                    item_kind="message",
                    occurred_at=accepted_at,
                )
            return TutorInputAcceptance(
                run_id=run_id,
                message_id=str(message["id"]),
                input_revision=revision,
                event=event,
                replayed=False,
                dispatch_job_id=dispatch_job.job_id if dispatch_job is not None else None,
            )

    def append_safe_event(
        self,
        *,
        user_id: str,
        run_id: str,
        event_key: str,
        kind: str,
        input_revision: int,
        payload: Mapping[str, object],
    ) -> TutorDurableEvent:
        _safe_key(event_key, label="event key")
        _safe_key(kind, label="event kind")
        if kind not in _DURABLE_EVENT_KINDS:
            raise ValueError("event kind is not part of the Child 02 durable vocabulary")
        if input_revision < 0:
            raise ValueError("event input revision must be non-negative")
        with self._conn.transaction():
            run = self._lock_run(user_id=user_id, run_id=run_id)
            if (
                _is_terminal(run)
                or run.get("cancelled_at") is not None
                or run.get("superseded_by_run_id") is not None
            ) and kind != "terminal_result":
                raise TutorTerminalStateConflict("terminal, cancelled, or superseded Tutor run cannot append a non-terminal event")
            return self._append_event_locked(
                run_id=run_id,
                event_key=event_key,
                kind=kind,
                input_revision=input_revision,
                payload=payload,
            )

    def events_after(
        self,
        *,
        user_id: str,
        run_id: str,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[TutorDurableEvent, ...]:
        if after_sequence < 0 or limit < 1 or limit > 200:
            raise ValueError("event replay cursor or limit is invalid")
        rows = self._conn.execute(
            """
            SELECT events.*
            FROM tutor_run_events AS events
            JOIN tutor_runs AS runs ON runs.id = events.run_id
            WHERE events.run_id = %s
              AND runs.user_id = %s
              AND events.event_sequence > %s
            ORDER BY events.event_sequence ASC
            LIMIT %s
            """,
            (run_id, user_id, after_sequence, limit),
        ).fetchall()
        return tuple(_event_from_row(row, projector=self._projector) for row in rows)

    def public_tutor_message(
        self,
        *,
        user_id: str,
        run_id: str,
        message_id: str,
    ) -> str | None:
        """Load only a scoped, already-guarded Tutor public message."""

        row = self._conn.execute(
            """
            SELECT messages.content
            FROM tutor_runs AS runs
            JOIN tutor_messages AS messages
              ON messages.conversation_id = runs.conversation_id
            WHERE runs.id = %s
              AND runs.user_id = %s
              AND messages.id = %s
              AND messages.role = 'tutor'
            """,
            (run_id, user_id, message_id),
        ).fetchone()
        if row is None:
            return None
        return sanitize_summary_text(str(row["content"]), max_length=1_200) or None

    def persist_safe_checkpoint(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        envelope: TutorCurationEnvelope,
    ) -> TutorTraceRecord:
        if checkpoint.run_id != lease.run_id or envelope.request.run_id != checkpoint.run_id:
            raise ValueError("lifecycle checkpoint scope is inconsistent")
        if envelope.request.trigger is not TutorCompactionTrigger.SAFE_CHECKPOINT:
            raise ValueError("safe checkpoint requires a safe-checkpoint curation trigger")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=checkpoint.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if checkpoint.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("checkpoint revision is stale")
            return self._persist_checkpoint_and_outbox_locked(run=run, checkpoint=checkpoint, envelope=envelope)

    def persist_context_high_water(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        request: TutorCompactionRequest,
        envelope: TutorCurationEnvelope,
        created_at: datetime,
    ) -> TutorTraceRecord:
        if request.run_id != lease.run_id or envelope.request != request:
            raise ValueError("compaction lifecycle scope is inconsistent")
        if request.trigger is not TutorCompactionTrigger.CONTEXT_HIGH_WATER:
            raise ValueError("context high-water lifecycle requires its matching trigger")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=request.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if request.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("compaction revision is stale")
            event = self._append_event_locked(
                run_id=request.run_id,
                event_key=f"compaction:{request.idempotency_key}",
                kind="compaction_requested",
                input_revision=request.input_revision,
                payload=_compaction_payload(request, status="pending"),
            )
            self._trip_failpoint("after_event")
            trace = self._insert_trace_locked(
                run_id=request.run_id,
                kind="compaction_request",
                event_sequence=event.event_sequence,
                payload=self._projector.compaction(_compaction_payload(request, status="pending")),
                created_at=created_at,
            )
            self._trip_failpoint("after_trace")
            self._upsert_outbox_locked(run=run, envelope=envelope, trace_id=trace.trace_id, event_sequence=event.event_sequence, created_at=created_at)
            self._trip_failpoint("after_outbox")
            return trace

    def complete_run(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        envelope: TutorCurationEnvelope,
    ) -> TutorRunResult:
        if result.run_id != lease.run_id or checkpoint.run_id != lease.run_id or envelope.request.run_id != lease.run_id:
            raise ValueError("terminal lifecycle scope is inconsistent")
        if envelope.request.trigger is not TutorCompactionTrigger.TERMINAL:
            raise ValueError("terminal lifecycle requires a terminal curation trigger")
        if result.terminal_outcome is None:
            raise ValueError("terminal lifecycle requires a terminal result")
        conversation_ref = self._conn.execute(
            "SELECT conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s",
            (result.run_id, user_id),
        ).fetchone()
        if conversation_ref is None:
            raise TutorRunNotFound("tutor run not found")
        with self._conn.transaction():
            conversation = self._lock_conversation(
                user_id=user_id,
                conversation_id=str(conversation_ref["conversation_id"]),
                learner_only=False,
            )
            run = self._lock_run(user_id=user_id, run_id=result.run_id)
            if _is_terminal(run):
                return _result_from_row(run)
            if run.get("cancelled_at") is not None or run.get("superseded_by_run_id") is not None:
                display_state = "superseded" if run.get("superseded_by_run_id") is not None else "unavailable"
                step_key = "replaced_by_newer_input" if display_state == "superseded" else None
                self._freeze_public_process_locked(
                    run=run,
                    display_state=display_state,
                    step_key=step_key,
                    occurred_at=checkpoint.created_at,
                )
                updated = self._conn.execute(
                    """
                    UPDATE tutor_runs
                    SET status = 'cancelled',
                        terminal_outcome = 'cancelled',
                        terminal_diagnostic_code = CASE
                          WHEN superseded_by_run_id IS NULL THEN COALESCE(terminal_diagnostic_code, 'cancelled')
                          ELSE COALESCE(terminal_diagnostic_code, 'superseded')
                        END,
                        terminal_at = COALESCE(terminal_at, %s),
                        active_lease_owner_id = NULL,
                        active_lease_expires_at = NULL
                    WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
                    RETURNING *
                    """,
                    (checkpoint.created_at, result.run_id, user_id),
                ).fetchone()
                if updated is None:
                    latest = self._lock_run(user_id=user_id, run_id=result.run_id)
                    return _result_from_row(latest)
                self._append_event_locked(
                    run_id=result.run_id,
                    event_key=f"terminal:cancelled:{_as_int(updated['input_revision'], 0)}",
                    kind="terminal_result",
                    input_revision=_as_int(updated["input_revision"], 0),
                    payload={
                        "kind": "terminal_result",
                        "status": "cancelled",
                        "run_id": result.run_id,
                        "input_revision": _as_int(updated["input_revision"], 0),
                    },
                )
                self._append_turn_event_locked(
                    run=updated,
                    kind=TutorConversationEventKind.TURN_UPDATED,
                    event_key=f"turn:{result.run_id}:cancelled",
                    occurred_at=checkpoint.created_at,
                )
                return _result_from_row(updated)
            _assert_active_lease(run, lease=lease, now=checkpoint.created_at)
            if checkpoint.input_revision != _as_int(run["input_revision"], 0) or result.input_revision != checkpoint.input_revision:
                raise TutorLeaseConflict("terminal lifecycle revision is stale")
            self._assert_teaching_authority_current_locked(run=run)
            teaching_commit = self._commit_teaching_step_locked(
                run=run, result=result, checkpoint=checkpoint, created_at=checkpoint.created_at,
            )
            terminal_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=checkpoint.created_at,
            )
            self._publish_result_evaluation_artifact_locked(
                run=run,
                terminal_message_id=terminal_message_id,
                occurred_at=checkpoint.created_at,
            )
            if teaching_commit is not None and terminal_message_id is None:
                raise TutorTerminalStateConflict(
                    "teaching step did not produce its required Tutor message"
                )
            self._finalize_teaching_step_locked(
                commit=teaching_commit,
                run=run,
                result=result,
                checkpoint=checkpoint,
                created_at=checkpoint.created_at,
            )
            trace = self._persist_checkpoint_and_outbox_locked(
                run=run,
                checkpoint=checkpoint,
                envelope=envelope,
                terminal_message_id=terminal_message_id,
            )
            self._trip_failpoint("before_terminal_update")
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s,
                    iteration_count = %s,
                    model_call_count = %s,
                    capability_call_count = %s,
                    effect_count = %s,
                    terminal_outcome = %s,
                    terminal_diagnostic_code = %s,
                    terminal_at = %s,
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (
                    result.status.value,
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    result.terminal_outcome.value,
                    result.diagnostic_code,
                    checkpoint.created_at,
                    result.run_id,
                    user_id,
                ),
            ).fetchone()
            if updated is None:
                latest = self._lock_run(user_id=user_id, run_id=result.run_id)
                return _result_from_row(latest)
            if str(run.get("origin")) == "interactive" and str(conversation.get("visibility")) == "learner":
                if result.terminal_outcome is TutorTerminalOutcome.COMPLETED:
                    if terminal_message_id is not None:
                        self._write_conversation_title_once_locked(
                            user_id=user_id,
                            conversation_id=str(run["conversation_id"]),
                            candidate=result.conversation_title,
                        )
                    self._freeze_public_process_locked(
                        run=run,
                        display_state="completed",
                        step_key="learning_reply_generated",
                        occurred_at=checkpoint.created_at,
                        tutor_message_id=terminal_message_id,
                    )
                else:
                    self._freeze_public_process_locked(
                        run=run,
                        display_state="unavailable",
                        step_key=None,
                        occurred_at=checkpoint.created_at,
                    )
            if (
                result.terminal_outcome is TutorTerminalOutcome.COMPLETED
                and terminal_message_id is not None
            ):
                from app.services.tutor.branching import (
                    TutorClarificationBranchService,
                )

                TutorClarificationBranchService(self._conn).complete_turn(
                    user_id=user_id,
                    conversation_id=str(run["conversation_id"]),
                    run_id=result.run_id,
                    response_message_id=terminal_message_id,
                    occurred_at=checkpoint.created_at,
                )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:terminal:{result.terminal_outcome.value}",
                occurred_at=checkpoint.created_at,
            )
            del trace
            return result

    def _publish_result_evaluation_artifact_locked(
        self,
        *,
        run: Mapping[str, object],
        terminal_message_id: str | None,
        occurred_at: datetime,
    ) -> None:
        """Publish the exact result Artifact after its evaluation message, atomically."""

        rows = self._conn.execute(
            """
            SELECT artifacts.id::text AS artifact_id, artifacts.version
            FROM tutor_continuation_intents AS intents
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id = intents.artifact_id
             AND artifacts.user_id = intents.user_id
             AND artifacts.conversation_id = intents.conversation_id
             AND artifacts.teaching_session_id = intents.teaching_session_id
             AND artifacts.learning_track_id = intents.learning_track_id
             AND artifacts.knowledge_key = intents.knowledge_key
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id = artifacts.id
             AND events.id::text = intents.source_id
             AND events.event_sequence = intents.source_version
            WHERE intents.consumed_run_id = %s
              AND intents.user_id = %s
              AND intents.conversation_id = %s
              AND intents.state = 'consumed'
              AND intents.source_kind = 'explicit_artifact_action'
              AND intents.idempotency_key = 'result-evaluation:' || intents.source_id
              AND artifacts.artifact_kind = 'test_result'
              AND artifacts.purpose = 'result'
              AND artifacts.state = 'completed'
              AND NOT artifacts.blocking
              AND artifacts.presentation_kind = 'test_result_v1'
              AND events.event_kind = 'created'
            LIMIT 2
            """,
            (run["id"], run["user_id"], run["conversation_id"]),
        ).fetchall()
        if not rows:
            return
        if len(rows) != 1:
            raise TutorTerminalStateConflict(
                "result-evaluation Artifact publication authority is ambiguous"
            )
        if terminal_message_id is None:
            raise TutorTerminalStateConflict(
                "result-evaluation Turn requires a learner-safe evaluation message"
            )
        artifact_id = str(rows[0]["artifact_id"])
        artifact_version = _as_int(rows[0]["version"], 0)
        if artifact_version < 1:
            raise TutorTerminalStateConflict(
                "result-evaluation Artifact version is invalid"
            )
        self._append_item_reference_event_locked(
            run=run,
            event_key=(
                f"item:artifact:{artifact_id}:item_added:{artifact_version}"
            ),
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=artifact_id,
            item_kind="artifact",
            occurred_at=occurred_at,
        )

    def _lock_run(self, *, user_id: str, run_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s FOR UPDATE",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TutorRunNotFound("tutor run not found")
        return row

    def _append_event_locked(
        self,
        *,
        run_id: str,
        event_key: str,
        kind: str,
        input_revision: int,
        payload: Mapping[str, object],
    ) -> TutorDurableEvent:
        _safe_key(event_key, label="event key")
        _safe_key(kind, label="event kind")
        if kind not in _DURABLE_EVENT_KINDS:
            raise ValueError("event kind is not part of the Child 02 durable vocabulary")
        safe_payload = self._projector.project(payload)
        payload_hash = self._projector.fingerprint(safe_payload)
        existing = self._event_by_key_locked(run_id=run_id, event_key=event_key)
        if existing is not None:
            if existing.kind != kind or existing.input_revision != input_revision or self._projector.fingerprint(existing.payload) != payload_hash:
                raise TutorIdempotencyConflict("event key conflicts with a different safe payload")
            return existing
        sequence = self._conn.execute(
            """
            UPDATE tutor_runs
            SET next_event_sequence = next_event_sequence + 1
            WHERE id = %s
            RETURNING next_event_sequence - 1 AS event_sequence
            """,
            (run_id,),
        ).fetchone()
        if sequence is None:
            raise TutorRunNotFound("tutor run not found")
        row = self._conn.execute(
            """
            INSERT INTO tutor_run_events (
              run_id, event_sequence, event_key, kind, input_revision, payload_json, payload_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING *
            """,
            (
                run_id,
                _as_int(sequence["event_sequence"], 0),
                event_key,
                kind,
                input_revision,
                _json(safe_payload),
                payload_hash,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("tutor event insert failed")
        return _event_from_row(row, projector=self._projector)

    def _event_by_key_locked(self, *, run_id: str, event_key: str) -> TutorDurableEvent | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_run_events WHERE run_id = %s AND event_key = %s",
            (run_id, event_key),
        ).fetchone()
        return _event_from_row(row, projector=self._projector) if row is not None else None

    def _event_by_id(self, event_id: str) -> TutorDurableEvent | None:
        row = self._conn.execute("SELECT * FROM tutor_run_events WHERE id = %s", (event_id,)).fetchone()
        return _event_from_row(row, projector=self._projector) if row is not None else None
