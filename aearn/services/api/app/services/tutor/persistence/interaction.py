"""Tutor persistence 的 interaction 职责实现。"""
# ruff: noqa: F403, F405
from __future__ import annotations

from ._namespace import *
from ._mixin import PersistenceMixin


class InteractionPersistenceMixin(PersistenceMixin):
    """由 PostgresTutorRepository 组合的内部职责 mixin。"""

    def find_or_create_interactive_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        policy_version: str = "tutor_interactive_policy_v1",
    ) -> tuple[TutorRunSnapshot, bool]:
        """Serialize one learner conversation to at most one reusable run.

        The conversation row lock makes a second input merge into the existing
        non-terminal interactive run rather than creating a competing stream.
        """

        with self._conn.transaction():
            conversation = self._conn.execute(
                """
                SELECT id
                FROM tutor_conversations
                WHERE id = %s
                  AND user_id = %s
                  AND visibility = 'learner'
                  AND kind = 'interactive'
                  AND status = 'active'
                FOR UPDATE
                """,
                (conversation_id, user_id),
            ).fetchone()
            if conversation is None:
                raise TutorRunNotFound("tutor conversation not found")
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_runs
                WHERE user_id = %s
                  AND conversation_id = %s
                  AND origin = 'interactive'
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                FOR UPDATE
                """,
                (user_id, conversation_id),
            ).fetchone()
            if existing is not None:
                return _snapshot_from_row(existing), False
            return (
                self.create_run(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    catalog_digest=catalog_digest,
                    policy=policy,
                    origin="interactive",
                    policy_version=policy_version,
                ),
                True,
            )

    def create_first_interactive_turn(
        self,
        *,
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        conversation_id: str | None = None,
        policy_version: str = "tutor_interactive_policy_v1",
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorInteractiveTurnAcceptance:
        """Create a learner-visible conversation only together with its first turn.

        The caller's enclosing idempotency transaction owns replay.  This method
        still keeps the conversation, fresh run, learner message/input receipt,
        and initial public process in one database transaction so a failed first
        send cannot leave an empty conversation behind.
        """

        with self._conn.transaction():
            resolved_conversation_id = self.create_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            self._trip_failpoint("after_first_turn_conversation")
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=resolved_conversation_id,
            )
            return self._create_interactive_turn_locked(
                conversation=conversation,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                received_at=received_at,
                policy_version=policy_version,
                runtime_kind=runtime_kind,
            )

    def create_interactive_turn(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        policy_version: str = "tutor_interactive_policy_v1",
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorInteractiveTurnAcceptance:
        """Accept one normal message as a fresh finite TurnRun.

        A conversation row lock serializes replacement, and the old foreground
        run is made terminal before the new run is inserted.  The replacement
        audit link is attached after insertion because it is an immediate FK.
        """

        with self._conn.transaction():
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            return self._create_interactive_turn_locked(
                conversation=conversation,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                received_at=received_at,
                policy_version=policy_version,
                runtime_kind=runtime_kind,
            )

    def _create_interactive_turn_locked(
        self,
        *,
        conversation: Mapping[str, object],
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        received_at: datetime,
        policy_version: str,
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorInteractiveTurnAcceptance:
        conversation_id = str(conversation["id"])
        pending_request = self._conn.execute(
            """
            SELECT id FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        if pending_request is not None:
            raise TutorInteractionRequestConflict("Tutor interaction request must be resolved before a normal input")
        foreground = self._conn.execute(
            """
            SELECT *
            FROM tutor_runs
            WHERE user_id = %s
              AND conversation_id = %s
              AND origin = 'interactive'
              AND terminal_outcome IS NULL
              AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        next_run_id = str(uuid4())
        replaced_run_id: str | None = None
        replaced_process: TutorPublicProcessState | None = None
        if foreground is not None:
            replaced_run_id = str(foreground["id"])
            replaced = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'cancelled',
                    cancelled_at = COALESCE(cancelled_at, %s),
                    terminal_outcome = COALESCE(terminal_outcome, 'cancelled'),
                    terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, 'superseded'),
                    terminal_at = COALESCE(terminal_at, %s),
                    active_lease_owner_id = NULL,
                    active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND terminal_outcome IS NULL
                  AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (received_at, received_at, replaced_run_id, user_id),
            ).fetchone()
            if replaced is None:
                raise TutorTerminalStateConflict("foreground Tutor run changed before replacement")
            self._freeze_public_process_locked(
                run=replaced,
                display_state="superseded",
                step_key="replaced_by_newer_input",
                occurred_at=received_at,
            )
            self._append_event_locked(
                run_id=replaced_run_id,
                event_key=f"terminal:superseded:{_as_int(replaced['input_revision'], 0)}",
                kind="terminal_result",
                input_revision=_as_int(replaced["input_revision"], 0),
                payload={
                    "kind": "terminal_result",
                    "status": "cancelled",
                    "run_id": replaced_run_id,
                    "input_revision": _as_int(replaced["input_revision"], 0),
                },
            )
            replaced_process = self.read_public_process(user_id=user_id, run_id=replaced_run_id)

        run = self.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog_digest,
            policy=policy,
            run_id=next_run_id,
            origin="interactive",
            policy_version=policy_version,
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
            runtime_kind=runtime_kind,
        )
        self._trip_failpoint("after_fresh_turn_run")
        if replaced_run_id is not None:
            linked = self._conn.execute(
                """
                UPDATE tutor_runs
                SET superseded_by_run_id = %s
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (run.run_id, replaced_run_id, user_id),
            ).fetchone()
            if linked is None:
                raise TutorRunNotFound("superseded Tutor run disappeared")
        acceptance = self.accept_input(
            user_id=user_id,
            run_id=run.run_id,
            idempotency_key=idempotency_key,
            content=content,
            received_at=received_at,
        )
        fresh_run = self._lock_run(user_id=user_id, run_id=run.run_id)
        self._ensure_public_process_locked(run=fresh_run, occurred_at=received_at)
        self._trip_failpoint("after_fresh_turn_input")
        process = self.read_public_process(user_id=user_id, run_id=run.run_id)
        return TutorInteractiveTurnAcceptance(
            run=self.load_snapshot(user_id=user_id, run_id=run.run_id) or run,
            acceptance=acceptance,
            replaced_run_id=replaced_run_id,
            process=process,
            replaced_process=replaced_process,
        )

    def read_interaction_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
    ) -> TutorInteractionRequestRecord:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND item_id = %s
            """,
            (user_id, conversation_id, item_id),
        ).fetchone()
        if row is None:
            raise TutorInteractionRequestNotFound("Tutor interaction request not found")
        return _interaction_request_from_row(row)

    def read_pending_interaction_requests(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> tuple[TutorInteractionRequestRecord, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM tutor_interaction_requests
            WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
            ORDER BY created_at, item_id
            """,
            (user_id, conversation_id),
        ).fetchall()
        return tuple(_interaction_request_from_row(row) for row in rows)

    def respond_to_interaction_request(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_version: int,
        response: Mapping[str, object],
        idempotency_key: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        received_at: datetime,
    ) -> TutorInteractionResponseAcceptance:
        if expected_version < 1:
            raise TutorInteractionRequestConflict("Tutor interaction request version is invalid")
        with self._conn.transaction():
            conversation = self._lock_learner_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
            request_row = self._conn.execute(
                """
                SELECT * FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND item_id = %s
                FOR UPDATE
                """,
                (user_id, conversation_id, item_id),
            ).fetchone()
            if request_row is None:
                raise TutorInteractionRequestNotFound("Tutor interaction request not found")
            kind = TutorInteractionRequestKind(str(request_row["kind"]))
            if TutorInteractionRequestActor(str(request_row["actor"])) is not TutorInteractionRequestActor.LEARNER:
                raise TutorInteractionRequestConflict("authority request has no learner mutation")
            normalized, content, planning_facts, denied = self._normalize_learner_request_response(
                request_row=request_row,
                response=response,
            )
            response_hash = canonical_payload_hash(normalized)
            if str(request_row["state"]) != TutorInteractionRequestState.PENDING.value:
                if (
                    str(request_row.get("response_hash") or "") == response_hash
                    and request_row.get("answer_turn_id") is not None
                ):
                    return TutorInteractionResponseAcceptance(
                        request=_interaction_request_from_row(request_row),
                        turn=self._resolved_request_turn_locked(request_row=request_row),
                        planning_facts=planning_facts,
                        replayed=True,
                    )
                raise TutorInteractionRequestConflict("Tutor interaction request is already resolved")
            if _as_int(request_row.get("version"), 0) != expected_version:
                raise TutorInteractionRequestConflict("Tutor interaction request version is stale")
            descriptor = _as_mapping(request_row.get("descriptor_json"))
            if canonical_payload_hash(descriptor) != str(request_row["descriptor_hash"]):
                raise TutorInteractionRequestConflict("Tutor interaction request authority changed")
            turn = self._create_response_turn_locked(
                conversation=conversation,
                request_row=request_row,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=idempotency_key,
                content=content,
                source="interaction_request_response",
                role="learner",
                received_at=received_at,
            )
            next_state = (
                TutorInteractionRequestState.DENIED.value
                if denied and kind is TutorInteractionRequestKind.APPROVAL
                else TutorInteractionRequestState.ANSWERED.value
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_interaction_requests
                SET state = %s, version = version + 1, response_hash = %s,
                    answer_turn_id = %s, answer_message_id = %s, resolved_at = %s
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND state = 'pending' AND version = %s
                RETURNING *
                """,
                (
                    next_state,
                    response_hash,
                    turn.run.run_id,
                    turn.acceptance.message_id,
                    received_at,
                    request_row["id"],
                    user_id,
                    conversation_id,
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise TutorInteractionRequestConflict("Tutor interaction request changed before response")
            source_run = self._lock_run(user_id=user_id, run_id=str(request_row["source_turn_id"]))
            self._append_item_reference_event_locked(
                run=source_run,
                event_key=f"item:request:{item_id}:resolved:{expected_version + 1}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=item_id,
                item_kind=public_item_kind(kind),
                occurred_at=received_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:request:{item_id}:resolved:{expected_version + 1}",
                occurred_at=received_at,
                turn_id=turn.run.run_id,
            )
            return TutorInteractionResponseAcceptance(
                request=_interaction_request_from_row(updated),
                turn=turn,
                planning_facts=planning_facts,
                replayed=False,
            )

    def accept_authority_receipt(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_version: int,
        issuer: str,
        subject: str,
        scope: Mapping[str, object],
        request_hash: str,
        result_hash: str,
        verification_result: str,
        receipt_identity: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        received_at: datetime,
    ) -> TutorInteractionResponseAcceptance:
        _safe_key(issuer, label="authority issuer")
        _safe_key(subject, label="authority subject")
        _safe_key(receipt_identity, label="authority receipt identity")
        if not _SHA256.fullmatch(request_hash) or not _SHA256.fullmatch(result_hash):
            raise TutorInteractionRequestConflict("authority receipt hashes are invalid")
        if verification_result not in {"verified", "ambiguous", "rejected"}:
            raise TutorInteractionRequestConflict("authority receipt verification result is invalid")
        with self._conn.transaction():
            conversation = self._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
            request_row = self._conn.execute(
                """
                SELECT * FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND item_id = %s
                FOR UPDATE
                """,
                (user_id, conversation_id, item_id),
            ).fetchone()
            if request_row is None:
                raise TutorInteractionRequestNotFound("Tutor interaction request not found")
            if TutorInteractionRequestActor(str(request_row["actor"])) is not TutorInteractionRequestActor.AUTHORITY:
                raise TutorInteractionRequestConflict("learner request cannot accept an authority receipt")
            expected_scope = _as_mapping(request_row.get("authority_scope_json"))
            if canonical_payload_hash(scope) != canonical_payload_hash(expected_scope):
                raise TutorInteractionRequestConflict("authority receipt scope does not match the request")
            if subject != str(request_row["id"]) or request_hash != str(request_row["authority_request_hash"]):
                raise TutorInteractionRequestConflict("authority receipt identity does not match the request")
            receipt_body = {
                "schema_version": TUTOR_AUTHORITY_RECEIPT_SCHEMA_VERSION,
                "issuer": issuer,
                "subject": subject,
                "scope": dict(scope),
                "request_hash": request_hash,
                "result_hash": result_hash,
                "verification_result": verification_result,
            }
            receipt_hash = canonical_payload_hash(receipt_body)
            if str(request_row["state"]) != TutorInteractionRequestState.PENDING.value:
                if (
                    str(request_row.get("receipt_identity") or "") == receipt_identity
                    and str(request_row.get("receipt_hash") or "") == receipt_hash
                    and request_row.get("answer_turn_id") is not None
                ):
                    return TutorInteractionResponseAcceptance(
                        request=_interaction_request_from_row(request_row),
                        turn=self._resolved_request_turn_locked(request_row=request_row),
                        planning_facts={},
                        replayed=True,
                    )
                raise TutorInteractionRequestConflict("authority request is already resolved")
            if _as_int(request_row.get("version"), 0) != expected_version:
                raise TutorInteractionRequestConflict("authority request version is stale")
            if verification_result != "verified":
                updated = self._conn.execute(
                    """
                    UPDATE tutor_interaction_requests
                    SET version = version + 1, authority_issuer = %s, authority_subject = %s,
                        authority_result_hash = %s, authority_verification_result = %s
                    WHERE id = %s AND state = 'pending' AND version = %s
                    RETURNING *
                    """,
                    (issuer, subject, result_hash, verification_result, request_row["id"], expected_version),
                ).fetchone()
                if updated is None:
                    raise TutorInteractionRequestConflict("authority request changed before verification")
                return TutorInteractionResponseAcceptance(
                    request=_interaction_request_from_row(updated),
                    turn=None,
                    planning_facts={},
                    replayed=False,
                )
            turn = self._create_response_turn_locked(
                conversation=conversation,
                request_row=request_row,
                user_id=user_id,
                catalog_digest=catalog_digest,
                policy=policy,
                idempotency_key=f"authority:{receipt_identity}",
                content="已接收并验证受信结果。",
                source="authority_receipt",
                role="tutor",
                received_at=received_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_interaction_requests
                SET state = 'answered', version = version + 1,
                    authority_issuer = %s, authority_subject = %s,
                    authority_result_hash = %s, authority_verification_result = 'verified',
                    receipt_identity = %s, receipt_hash = %s,
                    answer_turn_id = %s, answer_message_id = %s, resolved_at = %s
                WHERE id = %s AND state = 'pending' AND version = %s
                RETURNING *
                """,
                (
                    issuer,
                    subject,
                    result_hash,
                    receipt_identity,
                    receipt_hash,
                    turn.run.run_id,
                    turn.acceptance.message_id,
                    received_at,
                    request_row["id"],
                    expected_version,
                ),
            ).fetchone()
            if updated is None:
                raise TutorInteractionRequestConflict("authority request changed before receipt commit")
            source_run = self._lock_run(user_id=user_id, run_id=str(request_row["source_turn_id"]))
            request_kind = TutorInteractionRequestKind(str(request_row["kind"]))
            self._append_item_reference_event_locked(
                run=source_run,
                event_key=f"item:request:{item_id}:authority:{expected_version + 1}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=item_id,
                item_kind=public_item_kind(request_kind),
                occurred_at=received_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:request:{item_id}:authority:{expected_version + 1}",
                occurred_at=received_at,
                turn_id=turn.run.run_id,
            )
            return TutorInteractionResponseAcceptance(
                request=_interaction_request_from_row(updated),
                turn=turn,
                planning_facts={},
                replayed=False,
            )

    def _normalize_learner_request_response(
        self,
        *,
        request_row: Mapping[str, object],
        response: Mapping[str, object],
    ) -> tuple[dict[str, object], str, dict[str, object], bool]:
        kind = TutorInteractionRequestKind(str(request_row["kind"]))
        response_kind = str(response.get("kind") or "")
        if response_kind != kind.value:
            raise TutorInteractionRequestConflict("Tutor response kind does not match the request")
        if kind is TutorInteractionRequestKind.CLARIFICATION:
            answer = str(response.get("answer_text") or "").strip()
            if not answer or len(answer) > 16_000:
                raise TutorInteractionRequestConflict("clarification answer is invalid")
            return {"kind": kind.value, "answer_text": answer}, answer, {}, False
        if kind is TutorInteractionRequestKind.PLANNING_INPUT:
            question_key = str(response.get("question_key") or "")
            catalog_version = str(response.get("catalog_version") or "")
            if question_key != str(request_row.get("question_key") or ""):
                raise TutorInteractionRequestConflict("planning response question key does not match")
            normalized = validate_planning_question_value(
                self._conn,
                question_key=question_key,
                catalog_version=catalog_version,
                value=response.get("value"),
                presentation=_as_mapping(request_row.get("presentation_json")),
            )
            safe = {
                "kind": kind.value,
                "question_key": question_key,
                "catalog_version": catalog_version,
                "value": normalized,
            }
            content = format_planning_question_value(
                presentation=_as_mapping(request_row.get("presentation_json")),
                value=normalized,
            )
            return safe, content, {question_key: normalized}, False
        if kind is TutorInteractionRequestKind.APPROVAL:
            decision = str(response.get("decision") or "")
            proposal_identity = str(response.get("proposal_identity") or "")
            if decision not in {"approve", "deny"}:
                raise TutorInteractionRequestConflict("approval decision is invalid")
            if proposal_identity != str(request_row.get("proposal_identity") or ""):
                raise TutorInteractionRequestConflict("approval proposal identity does not match")
            reason = " ".join(str(response.get("reason") or "").split())
            if len(reason) > 400:
                raise TutorInteractionRequestConflict("approval reason is too long")
            safe = {
                "kind": kind.value,
                "proposal_identity": proposal_identity,
                "decision": decision,
                "reason": reason or None,
            }
            content = "已批准该操作。" if decision == "approve" else "已拒绝该操作。"
            if reason:
                content = f"{content} 原因：{reason}"
            return safe, content, {}, decision == "deny"
        raise TutorInteractionRequestConflict("authority request has no learner response")

    def _create_response_turn_locked(
        self,
        *,
        conversation: Mapping[str, object],
        request_row: Mapping[str, object],
        user_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        source: str,
        role: str,
        received_at: datetime,
    ) -> TutorInteractiveTurnAcceptance:
        conversation_id = str(conversation["id"])
        self._conn.execute(
            "UPDATE tutor_conversations SET queue_paused = false, queue_pause_reason = NULL WHERE id = %s AND user_id = %s AND queue_pause_reason = 'pending_request'",
            (conversation_id, user_id),
        )
        foreground = self._conn.execute(
            """
            SELECT id FROM tutor_runs
            WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
            FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()
        if foreground is not None:
            raise TutorInteractionRequestConflict("conversation already has an active Tutor turn")
        source_run = self._conn.execute(
            "SELECT runtime_kind FROM tutor_runs WHERE id = %s AND user_id = %s AND conversation_id = %s",
            (request_row["source_turn_id"], user_id, conversation_id),
        ).fetchone()
        if source_run is None:
            raise TutorInteractionRequestConflict("interaction request source turn is missing")
        run = self.create_run(
            user_id=user_id,
            conversation_id=conversation_id,
            catalog_digest=catalog_digest,
            policy=policy,
            origin="interactive",
            policy_version="tutor_interaction_response_policy_v1",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
            response_to_request_id=str(request_row["id"]),
            runtime_kind=cast(
                Literal["harness_v1", "codex_sidecar_v1"],
                str(source_run.get("runtime_kind") or "harness_v1"),
            ),
        )
        acceptance = self.accept_input(
            user_id=user_id,
            run_id=run.run_id,
            idempotency_key=idempotency_key,
            content=content,
            source=source,
            role=role,
            received_at=received_at,
        )
        fresh = self._lock_run(user_id=user_id, run_id=run.run_id)
        self._ensure_public_process_locked(run=fresh, occurred_at=received_at)
        return TutorInteractiveTurnAcceptance(
            run=self.load_snapshot(user_id=user_id, run_id=run.run_id) or run,
            acceptance=acceptance,
            replaced_run_id=None,
            process=self.read_public_process(user_id=user_id, run_id=run.run_id),
            replaced_process=None,
        )

    def _resolved_request_turn_locked(
        self,
        *,
        request_row: Mapping[str, object],
    ) -> TutorInteractiveTurnAcceptance:
        run_id = str(request_row.get("answer_turn_id") or "")
        message_id = str(request_row.get("answer_message_id") or "")
        run_row = self._conn.execute("SELECT * FROM tutor_runs WHERE id = %s", (run_id,)).fetchone()
        input_row = self._conn.execute(
            """
            SELECT * FROM tutor_run_input_events
            WHERE run_id = %s AND message_id = %s
            """,
            (run_id, message_id),
        ).fetchone()
        if run_row is None or input_row is None:
            raise TutorInteractionRequestConflict("resolved request answer turn is missing")
        event = self._event_by_key_locked(
            run_id=run_id,
            event_key=f"input:{input_row['idempotency_key']}",
        )
        if event is None:
            raise TutorInteractionRequestConflict("resolved request input event is missing")
        dispatch = self._conn.execute(
            "SELECT id FROM tutor_interactive_dispatch_jobs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        acceptance = TutorInputAcceptance(
            run_id=run_id,
            message_id=message_id,
            input_revision=_as_int(input_row.get("input_revision"), 1),
            event=event,
            replayed=True,
            dispatch_job_id=str(dispatch["id"]) if dispatch is not None else None,
        )
        snapshot = _snapshot_from_row(run_row)
        return TutorInteractiveTurnAcceptance(
            run=snapshot,
            acceptance=acceptance,
            replaced_run_id=None,
            process=self.read_public_process(user_id=str(run_row["user_id"]), run_id=run_id),
            replaced_process=None,
        )

    def record_interaction_request(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        decision: "TutorDecision",
        result: TutorRunResult,
        created_at: datetime,
        intent_resolution_enabled: bool = True,
    ) -> TutorRunResult:
        if decision.continuation_kind is None:
            raise ValueError("typed request requires a continuation kind")
        if (
            result.status is not TutorRunStatus.COMPLETED
            or result.terminal_outcome is not TutorTerminalOutcome.COMPLETED
            or result.completion_reason is None
        ):
            raise ValueError("typed request must complete its source turn")
        kind = TutorInteractionRequestKind(decision.continuation_kind.value)
        actor = actor_for_request(kind)
        expected_reason = completion_reason_for_request(kind)
        if result.completion_reason is not expected_reason:
            raise ValueError("typed request completion reason does not match request kind")
        prompt = sanitize_summary_text(decision.public_message or "", max_length=1_200)
        if not prompt:
            raise TutorInteractionRequestConflict("typed request requires a learner-safe prompt")
        with self._conn.transaction():
            conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=result.run_id,
                learner_only=False,
            )
            if _protocol_version_from_row(run) is not TutorInteractionProtocolVersion.THREAD_TURN_V2:
                raise TutorInteractionRequestConflict("typed request requires thread_turn_v2")
            existing = self._conn.execute(
                "SELECT * FROM tutor_interaction_requests WHERE source_turn_id = %s FOR UPDATE",
                (result.run_id,),
            ).fetchone()
            if existing is not None:
                return _result_from_row(run)
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if result.input_revision != _as_int(run.get("input_revision"), 0):
                raise TutorLeaseConflict("typed request result revision is stale")
            pending = self._conn.execute(
                """
                SELECT id FROM tutor_interaction_requests
                WHERE user_id = %s AND conversation_id = %s AND state = 'pending'
                FOR UPDATE
                """,
                (user_id, run["conversation_id"]),
            ).fetchone()
            if pending is not None:
                raise TutorInteractionRequestConflict("conversation already has a pending request")
            public_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=created_at,
            )
            if public_message_id is None:
                raise TutorInteractionRequestConflict("typed request requires a learner-safe public message")
            request_id = str(uuid4())
            item_id = str(uuid4())
            catalog_version: str | None = None
            question_key: str | None = None
            proposal_identity: str | None = None
            authority_key: str | None = None
            risk_level: str | None = None
            authority_request_hash: str | None = None
            authority_scope: dict[str, object] | None = None
            descriptor: dict[str, object] = {
                "prompt": prompt,
                "public_thinking_text": result.public_thinking_text,
                "required": True,
                "kind": kind.value,
                "actor": actor.value,
                "source_turn_id": result.run_id,
            }
            if kind is TutorInteractionRequestKind.PLANNING_INPUT:
                question_key = str(decision.question_key or "")
                descriptor["prompt"] = planning_question_prompt(question_key)
                model_hint = (
                    decision.planning_intent_hint.as_mapping()
                    if decision.planning_intent_hint is not None
                    else None
                )
                language_intent = PlanningIntentResolver(self._conn).resolve_for_run(
                    user_id=user_id,
                    run_id=result.run_id,
                    enabled=intent_resolution_enabled,
                    model_hint=model_hint,
                    expected_input_revision=result.input_revision,
                )
                if question_key == "language_id" and language_intent.resolution in {
                    "auto_confirm",
                    "clarification_required",
                    "unsupported",
                }:
                    raise TutorInteractionRequestConflict(
                        "language planning request requires a current deterministic or semantic shortlist"
                    )
                if (
                    question_key == "language_id"
                    and decision.planning_intent_hint is not None
                    and not language_intent.semantic_language_ids
                ):
                    raise TutorInteractionRequestConflict(
                        "language planning request semantic hint is stale or invalid"
                    )
                presentation = build_planning_question_presentation(
                    self._conn,
                    question_key=question_key,
                    language_intent=(language_intent if question_key == "language_id" else None),
                )
                catalog_version = PLANNING_QUESTION_CATALOG_VERSION
                descriptor.update(
                    {"question_key": question_key, "catalog_version": catalog_version}
                )
            elif kind is TutorInteractionRequestKind.CLARIFICATION:
                presentation = {
                    "type": "text",
                    "field_key": None,
                    "minimum_length": 1,
                    "maximum_length": 16_000,
                    "multiline": True,
                }
            elif kind is TutorInteractionRequestKind.APPROVAL:
                proposal_identity = f"proposal:{canonical_payload_hash({'run_id': result.run_id, 'input_revision': result.input_revision, 'model_call_count': result.model_call_count, 'prompt': prompt})}"
                authority_key = "tutor.approval"
                risk_level = "medium"
                descriptor.update(
                    {
                        "proposal_identity": proposal_identity,
                        "authority_key": authority_key,
                        "risk_level": risk_level,
                    }
                )
                presentation = {
                    "type": "approval",
                    "proposal_id": proposal_identity,
                    "authority_key": authority_key,
                    "risk_level": risk_level,
                    "summary": prompt,
                }
            else:
                authority_key = f"tutor.{kind.value}"
                authority_scope = {
                    "conversation_id": str(run["conversation_id"]),
                    "source_turn_id": result.run_id,
                    "kind": kind.value,
                }
                authority_request_hash = canonical_payload_hash(
                    {
                        "request_id": request_id,
                        "kind": kind.value,
                        "scope": authority_scope,
                    }
                )
                descriptor.update(
                    {
                        "authority_key": authority_key,
                        "authority_subject": request_id,
                        "request_hash": authority_request_hash,
                    }
                )
                presentation = {
                    "type": "text",
                    "field_key": None,
                    "minimum_length": 1,
                    "maximum_length": 1,
                    "multiline": False,
                }
            descriptor_hash = canonical_payload_hash(descriptor)
            request_row = self._conn.execute(
                """
                INSERT INTO tutor_interaction_requests (
                  id, item_id, user_id, conversation_id, source_turn_id,
                  kind, actor, schema_version, catalog_version, question_key,
                  descriptor_json, presentation_json, descriptor_hash,
                  proposal_identity, authority_key, risk_level,
                  authority_subject, authority_scope_json, authority_request_hash,
                  state, version, created_at
                ) VALUES (
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s::jsonb, %s::jsonb, %s,
                  %s, %s, %s,
                  %s, %s::jsonb, %s,
                  'pending', 1, %s
                )
                RETURNING *
                """,
                (
                    request_id,
                    item_id,
                    user_id,
                    run["conversation_id"],
                    result.run_id,
                    kind.value,
                    actor.value,
                    TUTOR_INTERACTION_REQUEST_SCHEMA_VERSION,
                    catalog_version,
                    question_key,
                    _json(descriptor),
                    _json(presentation),
                    descriptor_hash,
                    proposal_identity,
                    authority_key,
                    risk_level,
                    request_id if actor is TutorInteractionRequestActor.AUTHORITY else None,
                    _json(authority_scope) if authority_scope is not None else None,
                    authority_request_hash,
                    created_at,
                ),
            ).fetchone()
            if request_row is None:
                raise RuntimeError("Tutor interaction request insert failed")
            self._conn.execute(
                "UPDATE tutor_conversations SET queue_paused = true, queue_pause_reason = 'pending_request' WHERE id = %s AND user_id = %s",
                (run["conversation_id"], user_id),
            )
            request_event = self._append_event_locked(
                run_id=result.run_id,
                event_key=f"interaction-request:{request_id}",
                kind="interaction_request",
                input_revision=result.input_revision,
                payload={
                    "kind": "interaction_request",
                    "request_id": request_id,
                    "item_id": item_id,
                    "request_kind": kind.value,
                    "actor": actor.value,
                    "input_revision": result.input_revision,
                },
            )
            self._append_event_locked(
                run_id=result.run_id,
                event_key=f"terminal:request:{request_id}",
                kind="terminal_result",
                input_revision=result.input_revision,
                payload={
                    "kind": "terminal_result",
                    "status": "completed",
                    "run_id": result.run_id,
                    "input_revision": result.input_revision,
                    "request_id": request_id,
                    "item_id": item_id,
                },
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = 'completed', iteration_count = %s, model_call_count = %s,
                    capability_call_count = %s, effect_count = %s,
                    terminal_outcome = 'completed', terminal_at = %s,
                    completion_reason = %s, continuation_kind = NULL,
                    active_lease_owner_id = NULL, active_lease_expires_at = NULL
                WHERE id = %s AND user_id = %s
                  AND active_lease_owner_id = %s AND active_lease_generation = %s
                  AND terminal_outcome IS NULL AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                RETURNING *
                """,
                (
                    result.iteration_count,
                    result.model_call_count,
                    result.capability_call_count,
                    result.effect_count,
                    created_at,
                    result.completion_reason.value,
                    result.run_id,
                    user_id,
                    lease.owner_id,
                    lease.generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLeaseConflict("typed request result lease was lost")
            self._freeze_public_process_locked(
                run=updated,
                display_state="completed",
                step_key="learning_reply_generated",
                occurred_at=created_at,
                tutor_message_id=public_message_id,
            )
            self._append_item_reference_event_locked(
                run=updated,
                event_key=f"item:request:{item_id}:added",
                kind=TutorConversationEventKind.ITEM_ADDED,
                item_id=item_id,
                item_kind=public_item_kind(kind),
                occurred_at=created_at,
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:request:{request_id}",
                occurred_at=created_at,
            )
            self._increment_control_version_locked(
                user_id=user_id,
                conversation_id=str(conversation["id"]),
                event_key=f"control:request:{item_id}:pending",
                occurred_at=created_at,
                turn_id=result.run_id,
            )
            self._write_conversation_title_once_locked(
                user_id=user_id,
                conversation_id=str(conversation["id"]),
                candidate=result.conversation_title,
            )
            del request_event
            return result

    def record_waiting_result(
        self,
        *,
        user_id: str,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        if result.status is not TutorRunStatus.WAITING_FOR_INPUT:
            raise ValueError("only waiting-for-input result may use this lifecycle operation")
        with self._conn.transaction():
            _conversation, run = self._lock_run_with_conversation(
                user_id=user_id,
                run_id=result.run_id,
                learner_only=False,
            )
            _assert_active_lease(run, lease=lease, now=created_at)
            _assert_not_terminal(run)
            _assert_not_cancelled(run)
            _assert_not_superseded(run)
            if result.continuation_kind is None:
                raise TutorTerminalStateConflict("waiting input requires a persisted continuation kind")
            persisted_kind = run.get("continuation_kind")
            if persisted_kind is not None and str(persisted_kind) != result.continuation_kind.value:
                raise TutorTerminalStateConflict("waiting continuation kind conflicts with persisted run state")
            if result.input_revision != _as_int(run["input_revision"], 0):
                raise TutorLeaseConflict("waiting result revision is stale")
            self._assert_teaching_authority_current_locked(run=run)
            public_message_id = self._record_public_message_locked(
                run=run,
                result=result,
                created_at=created_at,
            )
            event_payload: dict[str, object] = {
                "kind": "waiting_for_input",
                "status": result.status.value,
                "run_id": result.run_id,
                "input_revision": result.input_revision,
                "count": result.iteration_count,
            }
            if public_message_id is not None:
                event_payload["message_id"] = public_message_id
            event = self._append_event_locked(
                run_id=result.run_id,
                event_key=f"waiting:{result.input_revision}:{result.iteration_count}:{result.model_call_count}",
                kind="waiting_for_input",
                input_revision=result.input_revision,
                payload=event_payload,
            )
            self._insert_trace_locked(
                run_id=result.run_id,
                kind="waiting_result",
                event_sequence=event.event_sequence,
                payload={
                    "kind": "waiting_result",
                    "status": result.status.value,
                    "input_revision": result.input_revision,
                },
                created_at=created_at,
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_runs
                SET status = %s, iteration_count = %s, model_call_count = %s,
                    capability_call_count = %s, effect_count = %s,
                    continuation_kind = COALESCE(continuation_kind, %s),
                    active_lease_owner_id = NULL, active_lease_expires_at = NULL
                WHERE id = %s
                  AND user_id = %s
                  AND active_lease_owner_id = %s
                  AND active_lease_generation = %s
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
                    result.continuation_kind.value,
                    result.run_id,
                    user_id,
                    lease.owner_id,
                    lease.generation,
                ),
            ).fetchone()
            if updated is None:
                raise TutorLeaseConflict("waiting result lease was lost")
            self._conn.execute(
                """
                UPDATE tutor_run_public_processes
                SET display_state = 'waiting_input',
                    last_public_activity_at = GREATEST(last_public_activity_at, %s)
                WHERE run_id = %s AND display_state IN (
                  'thinking', 'waiting_input', 'waiting_approval', 'waiting_authority'
                )
                """,
                (created_at, result.run_id),
            )
            self._append_item_reference_event_locked(
                run=updated,
                event_key=f"item:process:{result.run_id}:waiting:{result.input_revision}",
                kind=TutorConversationEventKind.ITEM_UPDATED,
                item_id=result.run_id,
                item_kind="process",
                occurred_at=created_at,
            )
            self._append_turn_event_locked(
                run=updated,
                kind=TutorConversationEventKind.TURN_UPDATED,
                event_key=f"turn:{result.run_id}:waiting:{result.input_revision}",
                occurred_at=created_at,
            )
            return result
