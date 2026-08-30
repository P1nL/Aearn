"""PostgreSQL-authoritative Queue, Steer, Interrupt, Execute, and Retry control."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Final, Literal, cast

from psycopg import Connection

from app.agents.harness.context_budget import build_tutor_context_budget_policy
from app.agents.harness.contracts import TutorPolicySnapshot
from app.core.config import Settings
from app.services.learning.context_references import PostgresTutorContextReferenceRepository
from app.services.learning.contracts import LearningScope, LearningScopeKind, LearningTaskKind
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.learning.teaching_sessions import TeachingSessionConflict, TeachingSessionRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.tutor.conversation_contracts import TutorConversationEventKind, TutorInteractionProtocolVersion
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorIdempotencyConflict,
    TutorInputAcceptance,
    TutorInteractiveTurnAcceptance,
    TutorInteractionRequestConflict,
    TutorQueueAcceptance,
    TutorQueuedInput,
)


QUEUE_MAX_PENDING: Final[int] = 10


class PostgresTutorQueueController:
    """Serialize every conversation control mutation on the conversation row."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        intent_resolution_enabled: bool = True,
    ) -> None:
        self._conn = conn
        self._intent_resolution_enabled = intent_resolution_enabled
        self._repository = PostgresTutorRepository(conn)
        self._tracks = PostgresLearningTrackRepository(conn)
        self._teaching_sessions = TeachingSessionRepository(conn)
        self._references = PostgresTutorContextReferenceRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)

    def accept_or_queue(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        idempotency_key: str,
        content: str,
        metadata: Mapping[str, object],
        received_at: datetime,
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> TutorQueueAcceptance:
        with self._conn.transaction():
            conversation = self._repository._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
            active = self._active(user_id=user_id, conversation_id=conversation_id)
            pending_request = self._pending_request(user_id=user_id, conversation_id=conversation_id)
            if active is None and pending_request is None and not bool(conversation.get("queue_paused")):
                turn = self._repository._create_interactive_turn_locked(
                    conversation=conversation,
                    user_id=user_id,
                    catalog_digest=catalog_digest,
                    policy=policy,
                    idempotency_key=idempotency_key,
                    content=content,
                    received_at=received_at,
                    policy_version="tutor_interactive_policy_v1",
                    runtime_kind=runtime_kind,
                )
                return TutorQueueAcceptance(
                    turn=turn,
                    queued_item=None,
                    control_version=max(1, _integer(conversation.get("control_version"), 1)),
                )
            item = self._enqueue(
                conversation=conversation,
                user_id=user_id,
                idempotency_key=idempotency_key,
                content=content,
                metadata={**dict(metadata), "_server_runtime_kind": runtime_kind},
                received_at=received_at,
            )
            if pending_request is not None:
                self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=True, reason="pending_request")
            control_version = self._repository._increment_control_version_locked(
                user_id=user_id,
                conversation_id=conversation_id,
                event_key=f"control:queue:{item.item_id}:enqueued",
                occurred_at=received_at,
                turn_id=None,
            )
            return TutorQueueAcceptance(turn=None, queued_item=item, control_version=control_version)

    def list_pending(self, *, user_id: str, conversation_id: str) -> tuple[TutorQueuedInput, ...]:
        self._repository.resolve_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        rows = self._conn.execute(
            "SELECT * FROM tutor_queued_inputs WHERE user_id = %s AND conversation_id = %s AND state = 'pending' ORDER BY position, created_at, id",
            (user_id, conversation_id),
        ).fetchall()
        return tuple(_queue_from_row(row) for row in rows)

    def edit(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_control_version: int,
        expected_item_version: int,
        content: str,
        occurred_at: datetime,
    ) -> tuple[TutorQueuedInput, int]:
        normalized = str(content).strip()
        if not normalized or len(normalized) > 16_000:
            raise TutorInteractionRequestConflict("queued input content is invalid")
        with self._conn.transaction():
            conversation = self._lock_control(user_id, conversation_id, expected_control_version)
            del conversation
            current = self._conn.execute(
                """
                SELECT * FROM tutor_queued_inputs
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND state = 'pending' AND version = %s
                FOR UPDATE
                """,
                (item_id, user_id, conversation_id, expected_item_version),
            ).fetchone()
            if current is None:
                raise TutorInteractionRequestConflict("queued input changed before edit")
            content_hash = _json_hash({
                "content": normalized,
                "metadata": _mapping(current.get("input_metadata_json")),
            })
            row = self._conn.execute(
                """
                UPDATE tutor_queued_inputs
                SET content = %s, content_hash = %s, version = version + 1
                WHERE id = %s AND state = 'pending' AND version = %s
                RETURNING *
                """,
                (normalized, content_hash, item_id, expected_item_version),
            ).fetchone()
            if row is None:
                raise TutorInteractionRequestConflict("queued input changed before edit")
            return _queue_from_row(row), self._control_event(
                user_id, conversation_id, f"control:queue:{item_id}:edited:{expected_item_version + 1}", occurred_at
            )

    def delete(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_control_version: int,
        expected_item_version: int,
        occurred_at: datetime,
    ) -> int:
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            row = self._conn.execute(
                """
                UPDATE tutor_queued_inputs
                SET state = 'cancelled', version = version + 1, cancelled_at = %s
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND state = 'pending' AND version = %s
                RETURNING id
                """,
                (occurred_at, item_id, user_id, conversation_id, expected_item_version),
            ).fetchone()
            if row is None:
                raise TutorInteractionRequestConflict("queued input changed before delete")
            self._renumber(conversation_id)
            return self._control_event(
                user_id, conversation_id, f"control:queue:{item_id}:deleted:{expected_item_version + 1}", occurred_at
            )

    def reorder(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_ids: Sequence[str],
        expected_control_version: int,
        occurred_at: datetime,
    ) -> tuple[tuple[TutorQueuedInput, ...], int]:
        if len(item_ids) != len(set(item_ids)):
            raise TutorInteractionRequestConflict("queue reorder contains duplicate items")
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            rows = self._conn.execute(
                "SELECT id FROM tutor_queued_inputs WHERE user_id = %s AND conversation_id = %s AND state = 'pending' ORDER BY position FOR UPDATE",
                (user_id, conversation_id),
            ).fetchall()
            if set(item_ids) != {str(row["id"]) for row in rows}:
                raise TutorInteractionRequestConflict("queue reorder must contain the complete pending set")
            self._conn.execute(
                "UPDATE tutor_queued_inputs SET position = position + 1000 WHERE conversation_id = %s AND state = 'pending'",
                (conversation_id,),
            )
            for position, item_id in enumerate(item_ids, start=1):
                self._conn.execute(
                    "UPDATE tutor_queued_inputs SET position = %s, version = version + 1 WHERE id = %s",
                    (position, item_id),
                )
            version = self._control_event(
                user_id, conversation_id, f"control:queue:reordered:{expected_control_version + 1}", occurred_at
            )
            return self.list_pending(user_id=user_id, conversation_id=conversation_id), version

    def steer(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_control_version: int,
        expected_turn_id: str,
        expected_input_revision: int,
        occurred_at: datetime,
    ) -> tuple[TutorInputAcceptance, TutorQueuedInput, int]:
        with self._conn.transaction():
            conversation = self._lock_control(user_id, conversation_id, expected_control_version)
            if bool(conversation.get("queue_paused")) or self._pending_request(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Steer is blocked by conversation control state")
            run = self._active(user_id=user_id, conversation_id=conversation_id)
            if run is None or str(run["id"]) != expected_turn_id or _integer(run.get("input_revision"), -1) != expected_input_revision:
                raise TutorInteractionRequestConflict("Steer target is stale")
            item = self._pending_item(user_id, conversation_id, item_id)
            acceptance = self._repository.accept_input(
                user_id=user_id,
                run_id=expected_turn_id,
                idempotency_key=f"steer:{item_id}:{expected_input_revision}",
                content=str(item["content"]),
                source="queue_steer",
                received_at=occurred_at,
                ensure_dispatch=False,
            )
            self._apply_metadata(
                user_id=user_id,
                run_id=expected_turn_id,
                acceptance=acceptance,
                metadata=_mapping(item.get("input_metadata_json")),
                inherit_existing_scope=True,
            )
            claimed = self._claim_row(item, expected_turn_id, acceptance.input_revision, "steer", occurred_at)
            self._renumber(conversation_id)
            version = self._control_event(
                user_id, conversation_id, f"control:queue:{item_id}:steered:{acceptance.input_revision}", occurred_at
            )
            return acceptance, claimed, version

    def interrupt(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_control_version: int,
        expected_turn_id: str,
        expected_input_revision: int,
        occurred_at: datetime,
    ) -> int:
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            run = self._active(user_id=user_id, conversation_id=conversation_id)
            if run is None or str(run["id"]) != expected_turn_id or _integer(run.get("input_revision"), -1) != expected_input_revision:
                raise TutorInteractionRequestConflict("Interrupt target is stale")
            self._interrupt_run(run, occurred_at)
            count = self._pending_count(conversation_id)
            self._set_pause(
                user_id=user_id,
                conversation_id=conversation_id,
                paused=count > 0,
                reason="interrupted" if count > 0 else None,
            )
            return self._control_event(
                user_id, conversation_id, f"control:turn:{expected_turn_id}:interrupted:{expected_input_revision}", occurred_at
            )

    def resume(
        self,
        *,
        user_id: str,
        conversation_id: str,
        expected_control_version: int,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        occurred_at: datetime,
    ) -> tuple[TutorInteractiveTurnAcceptance | None, int]:
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            if self._pending_request(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Queue resume is blocked by a pending request")
            if self._active(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Queue resume requires an idle conversation")
            self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=False, reason=None)
            turn = self._claim(
                user_id=user_id, conversation_id=conversation_id, item_id=None, mode="drain",
                catalog_digest=catalog_digest, policy=policy, occurred_at=occurred_at,
            )
            return turn, self._control_event(
                user_id, conversation_id, f"control:queue:resumed:{expected_control_version + 1}", occurred_at
            )

    def execute(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str,
        expected_control_version: int,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        occurred_at: datetime,
    ) -> tuple[TutorInteractiveTurnAcceptance, int]:
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            if self._pending_request(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Queue execute is blocked by a pending request")
            active = self._active(user_id=user_id, conversation_id=conversation_id)
            if active is not None:
                self._interrupt_run(active, occurred_at)
            self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=False, reason=None)
            turn = self._claim(
                user_id=user_id, conversation_id=conversation_id, item_id=item_id, mode="execute",
                catalog_digest=catalog_digest, policy=policy, occurred_at=occurred_at,
            )
            if turn is None:
                raise TutorInteractionRequestConflict("queued input is not pending")
            return turn, self._control_event(
                user_id, conversation_id, f"control:queue:{item_id}:executed:{expected_control_version + 1}", occurred_at
            )

    def retry(
        self,
        *,
        user_id: str,
        conversation_id: str,
        turn_id: str,
        expected_control_version: int,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        occurred_at: datetime,
    ) -> tuple[TutorInteractiveTurnAcceptance, int]:
        with self._conn.transaction():
            self._lock_control(user_id, conversation_id, expected_control_version)
            if self._pending_request(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Retry is blocked by a pending request")
            if self._active(user_id=user_id, conversation_id=conversation_id) is not None:
                raise TutorInteractionRequestConflict("Retry requires an idle conversation")
            failed = self._conn.execute(
                "SELECT * FROM tutor_runs WHERE id = %s AND user_id = %s AND conversation_id = %s FOR UPDATE",
                (turn_id, user_id, conversation_id),
            ).fetchone()
            outcome = str(failed.get("terminal_outcome") or "") if failed is not None else ""
            diagnostic = str(failed.get("terminal_diagnostic_code") or "") if failed is not None else ""
            recoverable = (
                outcome in {"failed", "model_unavailable"}
                or (outcome == "blocked_policy" and diagnostic == "capability_denied")
                or (outcome == "budget_exhausted" and diagnostic == "deadline_exhausted")
            )
            if failed is None or not recoverable:
                raise TutorInteractionRequestConflict("Tutor turn is not recoverable")
            input_row = self._conn.execute(
                """
                SELECT messages.role, messages.content
                FROM tutor_run_input_events AS inputs
                JOIN tutor_messages AS messages ON messages.id = inputs.message_id
                WHERE inputs.run_id = %s AND inputs.input_revision = %s
                """,
                (turn_id, failed["input_revision"]),
            ).fetchone()
            if input_row is None:
                raise TutorInteractionRequestConflict("Retry source input is missing")
            root = _optional(failed.get("retry_root_turn_id")) or turn_id
            run = self._repository.create_run(
                user_id=user_id, conversation_id=conversation_id, catalog_digest=catalog_digest,
                policy=policy, origin="interactive", policy_version="tutor_retry_policy_v1",
                interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
                retry_of_turn_id=turn_id, retry_root_turn_id=root,
                response_to_request_id=_optional(failed.get("response_to_request_id")),
                runtime_kind=cast(
                    Literal["harness_v1", "codex_sidecar_v1"],
                    str(failed.get("runtime_kind") or "harness_v1"),
                ),
            )
            acceptance = self._repository.accept_input(
                user_id=user_id, run_id=run.run_id, idempotency_key=f"retry:{turn_id}",
                content=str(input_row["content"]), source="retry", role=str(input_row["role"]),
                received_at=occurred_at,
            )
            fresh = self._repository._lock_run(user_id=user_id, run_id=run.run_id)
            self._repository._ensure_public_process_locked(run=fresh, occurred_at=occurred_at)
            self._tracks.inherit_run_scope(user_id=user_id, run_id=run.run_id, source_run_id=turn_id)
            self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=False, reason=None)
            version = self._control_event(
                user_id, conversation_id, f"control:turn:{turn_id}:retried:{run.run_id}", occurred_at
            )
            return self._turn_acceptance(run.run_id, acceptance), version

    def drain_completed(
        self,
        *,
        user_id: str,
        conversation_id: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        occurred_at: datetime,
    ) -> TutorInteractiveTurnAcceptance | None:
        with self._conn.transaction():
            conversation = self._repository._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
            if bool(conversation.get("queue_paused")):
                return None
            if self._pending_request(user_id=user_id, conversation_id=conversation_id) is not None:
                self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=True, reason="pending_request")
                return None
            if self._active(user_id=user_id, conversation_id=conversation_id) is not None:
                return None
            turn = self._claim(
                user_id=user_id, conversation_id=conversation_id, item_id=None, mode="drain",
                catalog_digest=catalog_digest, policy=policy, occurred_at=occurred_at,
            )
            if turn is not None:
                self._control_event(
                    user_id, conversation_id, f"control:queue:drained:{turn.run.run_id}", occurred_at
                )
            return turn

    def pause_failed(self, *, user_id: str, conversation_id: str) -> None:
        with self._conn.transaction():
            self._repository._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
            if self._pending_count(conversation_id) > 0:
                self._set_pause(user_id=user_id, conversation_id=conversation_id, paused=True, reason="failed")

    def _claim(
        self,
        *,
        user_id: str,
        conversation_id: str,
        item_id: str | None,
        mode: str,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        occurred_at: datetime,
    ) -> TutorInteractiveTurnAcceptance | None:
        item = (
            self._pending_item(user_id, conversation_id, item_id)
            if item_id is not None
            else self._conn.execute(
                "SELECT * FROM tutor_queued_inputs WHERE user_id = %s AND conversation_id = %s AND state = 'pending' ORDER BY position, created_at, id LIMIT 1 FOR UPDATE",
                (user_id, conversation_id),
            ).fetchone()
        )
        if item is None:
            return None
        metadata = _mapping(item.get("input_metadata_json"))
        runtime_kind = str(metadata.get("_server_runtime_kind") or "harness_v1")
        if runtime_kind not in {"harness_v1", "codex_sidecar_v1"}:
            raise TutorInteractionRequestConflict("queued Tutor Runtime kind is invalid")
        run = self._repository.create_run(
            user_id=user_id, conversation_id=conversation_id, catalog_digest=catalog_digest,
            policy=policy, origin="interactive", policy_version="tutor_queue_claim_policy_v1",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
            runtime_kind=cast(Literal["harness_v1", "codex_sidecar_v1"], runtime_kind),
        )
        acceptance = self._repository.accept_input(
            user_id=user_id, run_id=run.run_id, idempotency_key=f"queue:{item['id']}:{mode}",
            content=str(item["content"]), source=f"queue_{mode}", received_at=occurred_at,
        )
        self._apply_metadata(
            user_id=user_id, run_id=run.run_id, acceptance=acceptance,
            metadata=metadata, inherit_existing_scope=False,
        )
        fresh = self._repository._lock_run(user_id=user_id, run_id=run.run_id)
        self._repository._ensure_public_process_locked(run=fresh, occurred_at=occurred_at)
        self._claim_row(item, run.run_id, acceptance.input_revision, mode, occurred_at)
        self._renumber(conversation_id)
        return self._turn_acceptance(run.run_id, acceptance)

    def _apply_metadata(
        self,
        *,
        user_id: str,
        run_id: str,
        acceptance: TutorInputAcceptance,
        metadata: Mapping[str, object],
        inherit_existing_scope: bool,
    ) -> None:
        raw_scope = metadata.get("learning_scope")
        scope_data = _mapping(raw_scope) if raw_scope is not None else {}
        explicit = (
            LearningScope(
                scope_kind=LearningScopeKind(str(scope_data.get("scope_kind") or "general")),
                learning_track_id=_optional(scope_data.get("learning_track_id")),
                task_kind=LearningTaskKind(str(scope_data.get("task_kind") or "general_tutor")),
                knowledge_key=_optional(scope_data.get("knowledge_key")),
            )
            if scope_data else None
        )
        if inherit_existing_scope:
            scope = self._tracks.read_run_scope(user_id=user_id, run_id=run_id)
            if explicit is not None and (
                scope.scope_kind is not explicit.scope_kind
                or scope.learning_track_id != explicit.learning_track_id
                or scope.task_kind is not (explicit.task_kind or LearningTaskKind.GENERAL_TUTOR)
                or scope.knowledge_key != explicit.knowledge_key
            ):
                raise TutorInteractionRequestConflict("Steer cannot change immutable run scope")
        else:
            scope = self._tracks.snapshot_run_scope(user_id=user_id, run_id=run_id, explicit_scope=explicit)
        raw_references = metadata.get("context_references")
        references = raw_references if isinstance(raw_references, list) else []
        self._references.record_for_input(
            user_id=user_id, scope=scope, message_id=acceptance.message_id,
            input_revision=acceptance.input_revision, references=references,
        )
        if (
            scope.scope_kind is LearningScopeKind.LEARNING_TRACK
            and scope.task_kind is LearningTaskKind.LESSON_TEACHING
            and scope.learning_track_id is not None
            and scope.knowledge_key is not None
        ):
            try:
                self._teaching_sessions.bind_learner_message_run(
                    user_id=user_id, run_id=run_id, conversation_id=scope.conversation_id,
                    track_id=scope.learning_track_id, knowledge_key=scope.knowledge_key,
                    message_id=acceptance.message_id, input_revision=acceptance.input_revision,
                )
            except TeachingSessionConflict as exc:
                raise TutorInteractionRequestConflict("queued teaching-session authority is stale") from exc
        if scope.scope_kind is LearningScopeKind.PLAN_DRAFTING:
            raw_facts = metadata.get("planning_facts")
            raw_reopen = metadata.get("reopen_fact_fields")
            message = self._conn.execute(
                "SELECT content FROM tutor_messages WHERE id = %s", (acceptance.message_id,)
            ).fetchone()
            self._facts.record_input(
                user_id=user_id, run_id=run_id, conversation_id=scope.conversation_id,
                message_id=acceptance.message_id, input_revision=acceptance.input_revision,
                content=str(message["content"] if message is not None else ""),
                explicit_facts=_mapping(raw_facts) if raw_facts is not None else None,
                reopen_fields=tuple(str(item) for item in raw_reopen) if isinstance(raw_reopen, list) else (),
                intent_resolution_enabled=self._intent_resolution_enabled,
            )

    def _turn_acceptance(self, run_id: str, acceptance: TutorInputAcceptance) -> TutorInteractiveTurnAcceptance:
        row = self._conn.execute("SELECT user_id FROM tutor_runs WHERE id = %s", (run_id,)).fetchone()
        if row is None:
            raise TutorInteractionRequestConflict("claimed Tutor turn disappeared")
        snapshot = self._repository.load_snapshot(user_id=str(row["user_id"]), run_id=run_id)
        if snapshot is None:
            raise TutorInteractionRequestConflict("claimed Tutor turn disappeared")
        return TutorInteractiveTurnAcceptance(
            run=snapshot,
            acceptance=acceptance,
            replaced_run_id=None,
            process=self._repository.read_public_process(user_id=snapshot.user_id, run_id=run_id),
            replaced_process=None,
        )

    def _enqueue(
        self,
        *,
        conversation: Mapping[str, object],
        user_id: str,
        idempotency_key: str,
        content: str,
        metadata: Mapping[str, object],
        received_at: datetime,
    ) -> TutorQueuedInput:
        normalized = str(content).strip()
        if not normalized or len(normalized) > 16_000:
            raise TutorInteractionRequestConflict("queued input content is invalid")
        safe_metadata = dict(metadata)
        body_hash = _json_hash({"content": normalized, "metadata": safe_metadata})
        existing = self._conn.execute(
            "SELECT * FROM tutor_queued_inputs WHERE conversation_id = %s AND enqueue_key = %s FOR UPDATE",
            (conversation["id"], idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["content_hash"]) != body_hash:
                raise TutorIdempotencyConflict("queue enqueue key conflicts with a different input")
            return _queue_from_row(existing)
        count = self._pending_count(str(conversation["id"]))
        if count >= QUEUE_MAX_PENDING:
            raise TutorInteractionRequestConflict("Tutor queue is full")
        row = self._conn.execute(
            """
            INSERT INTO tutor_queued_inputs (
              user_id, conversation_id, content, content_hash, position,
              enqueue_key, input_metadata_json, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s) RETURNING *
            """,
            (user_id, conversation["id"], normalized, body_hash, count + 1, idempotency_key,
             json.dumps(safe_metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")), received_at),
        ).fetchone()
        if row is None:
            raise RuntimeError("Tutor queued input insert failed")
        return _queue_from_row(row)

    def _interrupt_run(self, run: Mapping[str, object], occurred_at: datetime) -> None:
        updated = self._conn.execute(
            """
            UPDATE tutor_runs
            SET status = 'cancelled', cancelled_at = COALESCE(cancelled_at, %s),
                terminal_outcome = COALESCE(terminal_outcome, 'cancelled'),
                terminal_diagnostic_code = COALESCE(terminal_diagnostic_code, 'interrupted_by_learner'),
                terminal_at = COALESCE(terminal_at, %s), active_lease_owner_id = NULL,
                active_lease_expires_at = NULL
            WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
              AND cancelled_at IS NULL AND superseded_by_run_id IS NULL RETURNING *
            """,
            (occurred_at, occurred_at, run["id"], run["user_id"]),
        ).fetchone()
        if updated is None:
            raise TutorInteractionRequestConflict("Tutor turn changed before interrupt")
        self._conn.execute(
            """
            UPDATE tutor_interactive_dispatch_jobs
            SET state = 'completed', completed_at = COALESCE(completed_at, %s),
                lease_owner_id = NULL, lease_expires_at = NULL
            WHERE run_id = %s AND state IN ('pending', 'leased', 'retry_wait')
            """,
            (occurred_at, run["id"]),
        )
        revision = _integer(run.get("input_revision"), 0)
        self._repository._append_event_locked(
            run_id=str(run["id"]), event_key=f"terminal:interrupted:{revision}",
            kind="terminal_result", input_revision=revision,
            payload={"kind": "terminal_result", "status": "cancelled", "run_id": str(run["id"]), "input_revision": revision},
        )
        self._repository._freeze_public_process_locked(
            run=updated, display_state="interrupted", step_key=None, occurred_at=occurred_at,
        )
        self._repository._append_turn_event_locked(
            run=updated, kind=TutorConversationEventKind.TURN_UPDATED,
            event_key=f"turn:{run['id']}:interrupted", occurred_at=occurred_at,
        )

    def _claim_row(self, row: Mapping[str, object], turn_id: str, revision: int, mode: str, occurred_at: datetime) -> TutorQueuedInput:
        updated = self._conn.execute(
            """
            UPDATE tutor_queued_inputs
            SET state = 'claimed', version = version + 1, claimed_turn_id = %s,
                claimed_input_revision = %s, claimed_mode = %s, claimed_at = %s
            WHERE id = %s AND state = 'pending' RETURNING *
            """,
            (turn_id, revision, mode, occurred_at, row["id"]),
        ).fetchone()
        if updated is None:
            raise TutorInteractionRequestConflict("queued input changed before claim")
        return _queue_from_row(updated)

    def _active(self, *, user_id: str, conversation_id: str) -> Mapping[str, object] | None:
        return self._conn.execute(
            """
            SELECT * FROM tutor_runs WHERE user_id = %s AND conversation_id = %s
              AND origin = 'interactive' AND terminal_outcome IS NULL AND cancelled_at IS NULL
              AND superseded_by_run_id IS NULL ORDER BY created_at DESC, id DESC LIMIT 1 FOR UPDATE
            """,
            (user_id, conversation_id),
        ).fetchone()

    def _pending_request(self, *, user_id: str, conversation_id: str) -> Mapping[str, object] | None:
        return self._conn.execute(
            "SELECT * FROM tutor_interaction_requests WHERE user_id = %s AND conversation_id = %s AND state = 'pending' FOR UPDATE",
            (user_id, conversation_id),
        ).fetchone()

    def _pending_item(self, user_id: str, conversation_id: str, item_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_queued_inputs WHERE id = %s AND user_id = %s AND conversation_id = %s AND state = 'pending' FOR UPDATE",
            (item_id, user_id, conversation_id),
        ).fetchone()
        if row is None:
            raise TutorInteractionRequestConflict("queued input not found or no longer pending")
        return row

    def _pending_count(self, conversation_id: str) -> int:
        row = self._conn.execute(
            "SELECT count(*) AS count FROM tutor_queued_inputs WHERE conversation_id = %s AND state = 'pending'",
            (conversation_id,),
        ).fetchone()
        return _integer(row.get("count") if row is not None else None, 0)

    def _renumber(self, conversation_id: str) -> None:
        rows = self._conn.execute(
            "SELECT id FROM tutor_queued_inputs WHERE conversation_id = %s AND state = 'pending' ORDER BY position, created_at, id FOR UPDATE",
            (conversation_id,),
        ).fetchall()
        self._conn.execute(
            "UPDATE tutor_queued_inputs SET position = position + 1000 WHERE conversation_id = %s AND state = 'pending'",
            (conversation_id,),
        )
        for position, row in enumerate(rows, start=1):
            self._conn.execute("UPDATE tutor_queued_inputs SET position = %s WHERE id = %s", (position, row["id"]))

    def _lock_control(self, user_id: str, conversation_id: str, expected: int) -> Mapping[str, object]:
        conversation = self._repository._lock_learner_conversation(user_id=user_id, conversation_id=conversation_id)
        if expected < 1 or _integer(conversation.get("control_version"), 0) != expected:
            raise TutorInteractionRequestConflict("conversation control version is stale")
        return conversation

    def _control_event(self, user_id: str, conversation_id: str, key: str, occurred_at: datetime) -> int:
        return self._repository._increment_control_version_locked(
            user_id=user_id, conversation_id=conversation_id, event_key=key,
            occurred_at=occurred_at, turn_id=None,
        )

    def _set_pause(self, *, user_id: str, conversation_id: str, paused: bool, reason: str | None) -> None:
        self._conn.execute(
            "UPDATE tutor_conversations SET queue_paused = %s, queue_pause_reason = %s WHERE id = %s AND user_id = %s",
            (paused, reason if paused else None, conversation_id, user_id),
        )


def _queue_from_row(row: Mapping[str, object]) -> TutorQueuedInput:
    return TutorQueuedInput(
        item_id=str(row["id"]), user_id=str(row["user_id"]), conversation_id=str(row["conversation_id"]),
        content=str(row.get("content") or ""), state=str(row.get("state") or "pending"),
        position=_integer(row.get("position"), 1), version=_integer(row.get("version"), 1),
        claimed_turn_id=_optional(row.get("claimed_turn_id")),
        claimed_input_revision=_integer(row.get("claimed_input_revision"), 0) if row.get("claimed_input_revision") is not None else None,
        claimed_mode=_optional(row.get("claimed_mode")),
        created_at=_datetime(row.get("created_at")), updated_at=_datetime(row.get("updated_at")),
    )


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _optional(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None


def _integer(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _datetime(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.now(UTC)


def _json_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_queue_turn_policy(now: datetime, *, settings: Settings) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=now + timedelta(minutes=5),
        max_iterations=4,
        max_model_calls=3,
        max_capability_calls=2,
        max_effects=2,
        context_token_budget=settings.tutor_context_token_budget,
        lease_duration_seconds=30,
        context_budget_policy=build_tutor_context_budget_policy(settings),
    )
