"""Public, feature-gated adapters over the durable Tutor target state.

The service owns route-facing validation, target API idempotency, and
learner-safe projections. It never composes a provider, Graph, worker, or
legacy runtime. Durable input/event/effect semantics remain in the existing
Tutor repositories.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from psycopg import Connection

from app.agents.harness.contracts import TutorPolicySnapshot, TutorTerminalOutcome
from app.core.config import Settings, get_settings
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.services.tutor.learner_state import (
    TutorActivityRecord,
    TutorInboxItem,
    TutorLearnerStateConflict,
    TutorLearnerStateNotFound,
    TutorLearnerStateRepository,
    TutorMemoryEntry,
    TutorMemoryPreference,
    TutorPlanRevision,
)
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorConversationSummary,
    TutorConversationTimelineRecord,
    TutorCursorInvalid,
    TutorPublicForegroundRun,
    TutorDurableEvent,
    TutorInteractiveTurnAcceptance,
    TutorPublicProcessState,
    TutorIdempotencyConflict,
    TutorRunNotFound,
    TutorRunReadState,
    TutorTerminalStateConflict,
)
from app.services.tutor.proactive import TutorProactivePreference
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class TutorPublicApiError(ValueError):
    """Stable public error that route handlers map to the shared envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        recoverable: bool = True,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})


@dataclass(frozen=True)
class TutorPublicSseEvent:
    sequence: int
    event_type: str
    data: dict[str, object]
    terminal: bool = False


class TutorPublicService:
    """Route-facing target API service with no provider or worker dependency."""

    def __init__(self, conn: Connection[dict[str, object]], *, settings: Settings | None = None) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._repository = PostgresTutorRepository(conn)
        self._learner_state = TutorLearnerStateRepository(conn)
        self._proactive = PostgresTutorProactiveRepository(conn)

    def create_or_resume_conversation(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_conversation_id = (
            _uuid_identifier(conversation_id, label="conversation_id") if conversation_id is not None else None
        )
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.conversation.create_or_resume",
            idempotency_key=idempotency_key,
            request_body={"conversation_id": normalized_conversation_id},
            action=lambda: self._create_or_resume_conversation(
                user_id=normalized_user_id,
                conversation_id=normalized_conversation_id,
            ),
        )

    def accept_first_turn(
        self,
        *,
        user_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.conversation.first_turn",
            idempotency_key=idempotency_key,
            request_body={"content": content},
            action=lambda: self._accept_first_turn(
                user_id=normalized_user_id,
                content=content,
                idempotency_key=idempotency_key,
            ),
        )

    def accept_conversation_input(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_conversation_id = _uuid_identifier(conversation_id, label="conversation_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.conversation.input",
            idempotency_key=idempotency_key,
            request_body={"conversation_id": normalized_conversation_id, "content": content},
            action=lambda: self._accept_conversation_input(
                user_id=normalized_user_id,
                conversation_id=normalized_conversation_id,
                content=content,
                idempotency_key=idempotency_key,
            ),
        )

    def accept_run_input(
        self,
        *,
        user_id: str,
        run_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_run_id = _uuid_identifier(run_id, label="run_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.run.input",
            idempotency_key=idempotency_key,
            request_body={"run_id": normalized_run_id, "content": content},
            action=lambda: self._accept_existing_run_input(
                user_id=normalized_user_id,
                run_id=normalized_run_id,
                content=content,
                idempotency_key=idempotency_key,
            ),
        )

    def read_run(self, *, user_id: str, run_id: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_run_id = _uuid_identifier(run_id, label="run_id")
        self._assert_user_exists(normalized_user_id)
        try:
            return _run_payload(self._repository.read_run_state(user_id=normalized_user_id, run_id=normalized_run_id))
        except TutorRunNotFound as exc:
            raise _run_not_found(normalized_run_id) from exc

    def list_conversations(
        self,
        *,
        user_id: str,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        try:
            items, next_cursor, has_more = self._repository.list_public_conversations(
                user_id=normalized_user_id,
                limit=limit,
                cursor=cursor,
            )
        except TutorCursorInvalid as exc:
            raise _cursor_invalid() from exc
        return {
            "items": [_conversation_summary_payload(item) for item in items],
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    def read_conversation_history(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_conversation_id = _uuid_identifier(conversation_id, label="conversation_id")
        self._assert_user_exists(normalized_user_id)
        try:
            items, next_cursor, has_more = self._repository.read_public_history(
                user_id=normalized_user_id,
                conversation_id=normalized_conversation_id,
                limit=limit,
                cursor=cursor,
                now=datetime.now(UTC),
            )
            active_run = self._repository.read_public_foreground_run(
                user_id=normalized_user_id,
                conversation_id=normalized_conversation_id,
            )
        except TutorCursorInvalid as exc:
            raise _cursor_invalid() from exc
        except TutorRunNotFound as exc:
            raise TutorPublicApiError(
                "TUTOR_CONVERSATION_NOT_FOUND",
                "Tutor conversation was not found for the current learner.",
                status_code=404,
                details={"conversation_id": normalized_conversation_id},
            ) from exc
        return {
            "items": [_timeline_payload(item) for item in items],
            "next_cursor": next_cursor,
            "has_more": has_more,
            "active_run": _foreground_run_payload(active_run),
        }

    def replay_events(
        self,
        *,
        user_id: str,
        run_id: str,
        after_sequence: int,
        limit: int = 100,
    ) -> tuple[TutorPublicSseEvent, ...]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_run_id = _uuid_identifier(run_id, label="run_id")
        if after_sequence < 0:
            raise TutorPublicApiError(
                "SSE_CURSOR_INVALID",
                "SSE cursor must be a non-negative run-local sequence.",
                status_code=400,
                recoverable=True,
            )
        self._assert_user_exists(normalized_user_id)
        try:
            state = self._repository.read_run_state(user_id=normalized_user_id, run_id=normalized_run_id)
            events = self._repository.events_after(
                user_id=normalized_user_id,
                run_id=normalized_run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except TutorRunNotFound as exc:
            raise _run_not_found(normalized_run_id) from exc
        return tuple(
            self._public_sse_event(user_id=normalized_user_id, state=state, event=event)
            for event in events
        )

    def list_activity(self, *, user_id: str, limit: int) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        return {
            "items": [
                _activity_payload(item)
                for item in self._learner_state.list_activity_records(user_id=normalized_user_id, limit=limit)
            ]
        }

    def list_inbox(self, *, user_id: str, include_dismissed: bool, limit: int) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        return {
            "items": [
                _inbox_payload(item)
                for item in self._learner_state.list_inbox_items(
                    user_id=normalized_user_id,
                    include_dismissed=include_dismissed,
                    limit=limit,
                )
            ]
        }

    def mark_inbox_read(self, *, user_id: str, inbox_id: str, idempotency_key: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_inbox_id = _uuid_identifier(inbox_id, label="inbox_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.inbox.read",
            idempotency_key=idempotency_key,
            request_body={"inbox_id": normalized_inbox_id},
            action=lambda: {"inbox": _inbox_payload(self._mark_inbox_read(normalized_user_id, normalized_inbox_id))},
        )

    def dismiss_inbox(self, *, user_id: str, inbox_id: str, idempotency_key: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_inbox_id = _uuid_identifier(inbox_id, label="inbox_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.inbox.dismiss",
            idempotency_key=idempotency_key,
            request_body={"inbox_id": normalized_inbox_id},
            action=lambda: {"inbox": _inbox_payload(self._dismiss_inbox(normalized_user_id, normalized_inbox_id))},
        )

    def list_memory(self, *, user_id: str, include_inactive: bool, limit: int) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        return {
            "items": [
                _memory_payload(item)
                for item in self._learner_state.list_memory_entries(
                    user_id=normalized_user_id,
                    include_inactive=include_inactive,
                    limit=limit,
                )
            ]
        }

    def correct_memory(
        self,
        *,
        user_id: str,
        entry_id: str,
        statement: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_entry_id = _uuid_identifier(entry_id, label="entry_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.memory.correct",
            idempotency_key=idempotency_key,
            request_body={"entry_id": normalized_entry_id, "statement": statement},
            action=lambda: self._correct_memory(
                user_id=normalized_user_id,
                entry_id=normalized_entry_id,
                statement=statement,
                request_hash=_request_hash({"entry_id": normalized_entry_id, "statement": statement}),
            ),
        )

    def delete_memory(self, *, user_id: str, entry_id: str, idempotency_key: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        normalized_entry_id = _uuid_identifier(entry_id, label="entry_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.memory.delete",
            idempotency_key=idempotency_key,
            request_body={"entry_id": normalized_entry_id},
            action=lambda: self._delete_memory(normalized_user_id, normalized_entry_id),
        )

    def list_plan_revisions(self, *, user_id: str, limit: int) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        active = self._learner_state.active_plan_for_user(user_id=normalized_user_id)
        return {
            "active_revision_id": active.revision_id if active is not None else None,
            "items": [
                _plan_revision_payload(item)
                for item in self._learner_state.list_plan_revisions(user_id=normalized_user_id, limit=limit)
            ],
        }

    def rollback_plan(self, *, user_id: str, idempotency_key: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.plan.rollback",
            idempotency_key=idempotency_key,
            request_body={},
            action=lambda: self._rollback_plan(normalized_user_id, idempotency_key),
        )

    def read_preferences(self, *, user_id: str) -> dict[str, object]:
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        self._assert_user_exists(normalized_user_id)
        return self._preferences_payload(normalized_user_id)

    def update_preferences(
        self,
        *,
        user_id: str,
        inferred_memory_enabled: bool | None,
        expected_memory_setting_version: str | None,
        proactive_paused: bool | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        if inferred_memory_enabled is None and proactive_paused is None:
            raise TutorPublicApiError(
                "VALIDATION_ERROR",
                "At least one Tutor preference must be supplied.",
                status_code=400,
                recoverable=True,
            )
        normalized_user_id = _uuid_identifier(user_id, label="user_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation="tutor.preferences.update",
            idempotency_key=idempotency_key,
            request_body={
                "inferred_memory_enabled": inferred_memory_enabled,
                "expected_memory_setting_version": expected_memory_setting_version,
                "proactive_paused": proactive_paused,
            },
            action=lambda: self._update_preferences(
                user_id=normalized_user_id,
                inferred_memory_enabled=inferred_memory_enabled,
                expected_memory_setting_version=expected_memory_setting_version,
                proactive_paused=proactive_paused,
                idempotency_key=idempotency_key,
            ),
        )

    def _create_or_resume_conversation(self, *, user_id: str, conversation_id: str | None) -> dict[str, object]:
        self._assert_user_exists(user_id)
        try:
            resolved, created = self._repository.create_or_resume_learner_conversation(
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except TutorRunNotFound as exc:
            raise TutorPublicApiError(
                "TUTOR_CONVERSATION_NOT_FOUND",
                "Tutor conversation was not found for the current learner.",
                status_code=404,
                details={"conversation_id": conversation_id},
            ) from exc
        return {"conversation_id": resolved, "created": created}

    def _accept_first_turn(
        self,
        *,
        user_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        self._assert_user_exists(user_id)
        now = datetime.now(UTC)
        try:
            catalog = compile_published_skill_catalog()
            self._repository.record_catalog_snapshot(catalog)
            accepted = self._repository.create_first_interactive_turn(
                user_id=user_id,
                catalog_digest=catalog.digest,
                policy=_interactive_policy(now, settings=self._settings),
                idempotency_key=idempotency_key,
                content=content,
                received_at=now,
            )
            state = self._repository.read_run_state(user_id=user_id, run_id=accepted.run.run_id)
        except TutorIdempotencyConflict as exc:
            raise _idempotency_conflict() from exc
        except TutorTerminalStateConflict as exc:
            raise _run_not_active() from exc
        return _turn_acceptance_payload(accepted, state=state, first_turn=True)

    def _accept_conversation_input(
        self,
        *,
        user_id: str,
        conversation_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        self._assert_user_exists(user_id)
        now = datetime.now(UTC)
        try:
            catalog = compile_published_skill_catalog()
            self._repository.record_catalog_snapshot(catalog)
            accepted = self._repository.create_interactive_turn(
                user_id=user_id,
                conversation_id=conversation_id,
                catalog_digest=catalog.digest,
                policy=_interactive_policy(now, settings=self._settings),
                idempotency_key=idempotency_key,
                content=content,
                received_at=now,
            )
            state = self._repository.read_run_state(user_id=user_id, run_id=accepted.run.run_id)
        except TutorRunNotFound as exc:
            raise TutorPublicApiError(
                "TUTOR_CONVERSATION_NOT_FOUND",
                "Tutor conversation was not found for the current learner.",
                status_code=404,
                details={"conversation_id": conversation_id},
            ) from exc
        except TutorIdempotencyConflict as exc:
            raise _idempotency_conflict() from exc
        except TutorTerminalStateConflict as exc:
            raise _run_not_active(conversation_id=conversation_id) from exc
        return _turn_acceptance_payload(accepted, state=state, first_turn=False)

    def _accept_existing_run_input(
        self,
        *,
        user_id: str,
        run_id: str,
        content: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        self._assert_user_exists(user_id)
        try:
            state = self._repository.read_run_state(user_id=user_id, run_id=run_id)
            if (
                state.snapshot.origin != "interactive"
                or state.snapshot.cancelled
                or state.terminal_outcome is not None
                or state.snapshot.status.value != "waiting_for_input"
                or state.snapshot.continuation_kind is None
            ):
                raise _run_not_active(run_id=run_id)
            acceptance = self._repository.accept_input(
                user_id=user_id,
                run_id=run_id,
                idempotency_key=idempotency_key,
                content=content,
                received_at=datetime.now(UTC),
            )
            updated = self._repository.read_run_state(user_id=user_id, run_id=run_id)
        except TutorRunNotFound as exc:
            raise _run_not_found(run_id) from exc
        except TutorIdempotencyConflict as exc:
            raise _idempotency_conflict() from exc
        except TutorTerminalStateConflict as exc:
            raise _run_not_active(run_id=run_id) from exc
        process = self._repository.read_public_process(user_id=user_id, run_id=run_id)
        return {
            "conversation_id": updated.snapshot.conversation_id,
            "run_id": run_id,
            "input_revision": acceptance.input_revision,
            "message_id": acceptance.message_id,
            "event_cursor": acceptance.event.event_sequence,
            "merged": True,
            "input_replayed": acceptance.replayed,
            "run": _run_payload(updated),
            "process": _public_process_payload(process) if process is not None else None,
            "replaced_run_id": None,
            "replaced_process": None,
        }

    def _mark_inbox_read(self, user_id: str, inbox_id: str) -> TutorInboxItem:
        try:
            return self._learner_state.mark_inbox_read(user_id=user_id, inbox_id=inbox_id)
        except TutorLearnerStateNotFound as exc:
            raise TutorPublicApiError("INBOX_ITEM_NOT_FOUND", "Tutor inbox item was not found.", status_code=404) from exc
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "INBOX_ITEM_NOT_UNREAD",
                "Tutor inbox item is no longer unread.",
                status_code=409,
                details={"inbox_id": inbox_id},
            ) from exc

    def _dismiss_inbox(self, user_id: str, inbox_id: str) -> TutorInboxItem:
        try:
            return self._learner_state.dismiss_inbox_item(user_id=user_id, inbox_id=inbox_id)
        except TutorLearnerStateNotFound as exc:
            raise TutorPublicApiError("INBOX_ITEM_NOT_FOUND", "Tutor inbox item was not found.", status_code=404) from exc
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "INBOX_ITEM_NOT_UNREAD",
                "Tutor inbox item is no longer unread.",
                status_code=409,
                details={"inbox_id": inbox_id},
            ) from exc

    def _correct_memory(
        self,
        *,
        user_id: str,
        entry_id: str,
        statement: str,
        request_hash: str,
    ) -> dict[str, object]:
        evidence_id = f"learner-control:{request_hash[:24]}"
        try:
            corrected_id = self._learner_state.correct_memory_entry(
                user_id=user_id,
                entry_id=entry_id,
                statement=statement,
                evidence_ids=(evidence_id,),
                evidence_hashes=(request_hash,),
            )
            entry = self._learner_state.memory_entry_for_user(user_id=user_id, entry_id=corrected_id)
            return {"memory": _memory_payload(entry)}
        except TutorLearnerStateNotFound as exc:
            raise TutorPublicApiError("MEMORY_ENTRY_NOT_FOUND", "Tutor memory entry was not found.", status_code=404) from exc
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "MEMORY_ENTRY_NOT_ACTIVE",
                "Tutor memory entry is no longer active.",
                status_code=409,
                details={"entry_id": entry_id},
            ) from exc

    def _delete_memory(self, user_id: str, entry_id: str) -> dict[str, object]:
        try:
            self._learner_state.delete_memory_entry(user_id=user_id, entry_id=entry_id)
            return {"entry_id": entry_id, "state": "deleted"}
        except TutorLearnerStateNotFound as exc:
            raise TutorPublicApiError("MEMORY_ENTRY_NOT_FOUND", "Tutor memory entry was not found.", status_code=404) from exc
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "MEMORY_ENTRY_NOT_ACTIVE",
                "Tutor memory entry is no longer active.",
                status_code=409,
                details={"entry_id": entry_id},
            ) from exc

    def _rollback_plan(self, user_id: str, idempotency_key: str) -> dict[str, object]:
        try:
            revision_id = self._learner_state.rollback_plan_from_user_action(
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            active = self._learner_state.active_plan_for_user(user_id=user_id)
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "PLAN_ROLLBACK_UNAVAILABLE",
                "No earlier Tutor plan revision is available for rollback.",
                status_code=409,
                recoverable=False,
            ) from exc
        return {
            "revision_id": revision_id,
            "active_plan": _plan_revision_payload(active) if active is not None else None,
        }

    def _preferences_payload(self, user_id: str) -> dict[str, object]:
        memory = self._learner_state.memory_preference_for_user(user_id=user_id)
        proactive = self._proactive.preference_for_user(user_id=user_id)
        return _preferences_payload(memory=memory, proactive=proactive)

    def _update_preferences(
        self,
        *,
        user_id: str,
        inferred_memory_enabled: bool | None,
        expected_memory_setting_version: str | None,
        proactive_paused: bool | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        try:
            if inferred_memory_enabled is not None:
                self._learner_state.set_inferred_memory_preference(
                    user_id=user_id,
                    enabled=inferred_memory_enabled,
                    expected_setting_version=expected_memory_setting_version,
                )
        except TutorLearnerStateConflict as exc:
            raise TutorPublicApiError(
                "MEMORY_SETTING_VERSION_CONFLICT",
                "Tutor memory preference changed; refresh before saving again.",
                status_code=409,
                details={"expected_setting_version": expected_memory_setting_version},
            ) from exc
        if proactive_paused is not None:
            current = self._proactive.preference_for_user(user_id=user_id)
            version_hash = _request_hash(
                {"prior": current.setting_version, "paused": proactive_paused, "key": idempotency_key}
            )
            self._proactive.upsert_preference(
                preference=TutorProactivePreference(
                    user_id=user_id,
                    enabled=True if not proactive_paused else current.enabled,
                    hard_paused=proactive_paused,
                    policy_version=current.policy_version,
                    setting_version=f"tutor_proactive_setting:{version_hash[:20]}",
                ),
                now=datetime.now(UTC),
            )
        return self._preferences_payload(user_id)

    def _public_sse_event(
        self,
        *,
        user_id: str,
        state: TutorRunReadState,
        event: TutorDurableEvent,
    ) -> TutorPublicSseEvent:
        base = {
            "run_id": event.run_id,
            "input_revision": event.input_revision,
            "event_sequence": event.event_sequence,
        }
        payload = event.payload
        if event.kind == "input_accepted":
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="input_accepted",
                data={
                    **base,
                    "message_id": _safe_text(payload.get("message_id")),
                    "status": "accepted",
                },
            )
        if event.kind == "skill_selected":
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="tool_status",
                data={
                    **base,
                    "status": "completed",
                    "tool": "public_process",
                    "label": "已整理最近的对话与学习目标",
                    "message": "已整理最近的对话与学习目标",
                },
            )
        if event.kind == "capability_invoked":
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="tool_status",
                data={
                    **base,
                    "status": "completed",
                    "tool": "public_process",
                    "label": "已查阅已授权的学习资料",
                    "message": "已查阅已授权的学习资料",
                },
            )
        if event.kind == "effect_result":
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="activity",
                data={
                    **base,
                    "category": "public_process",
                    "status": _safe_text(payload.get("status")) or "completed",
                    "label": "已完成一次受控学习建议生成",
                },
            )
        if event.kind == "waiting_for_input":
            message_id = _safe_text(payload.get("message_id"))
            public_message = (
                self._repository.public_tutor_message(
                    user_id=user_id,
                    run_id=event.run_id,
                    message_id=message_id,
                )
                if message_id
                else None
            )
            data: dict[str, object] = {
                **base,
                "status": "waiting_for_input",
                "terminal_outcome": None,
            }
            if public_message is not None:
                data["public_message"] = public_message
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="run_state",
                data=data,
            )
        if event.kind == "terminal_result":
            terminal = state.terminal_outcome
            message_id = _safe_text(payload.get("message_id"))
            public_message = (
                self._repository.public_tutor_message(
                    user_id=user_id,
                    run_id=event.run_id,
                    message_id=message_id,
                )
                if message_id
                else None
            )
            if terminal is TutorTerminalOutcome.COMPLETED:
                return TutorPublicSseEvent(
                    sequence=event.event_sequence,
                    event_type="done",
                    terminal=True,
                    data={
                        **base,
                        "result_ref": {"type": "TutorRun", "id": event.run_id},
                        "public_message": public_message,
                    },
                )
            code = _terminal_error_code(terminal)
            return TutorPublicSseEvent(
                sequence=event.event_sequence,
                event_type="error",
                terminal=True,
                data={
                    "error": {
                        "code": code,
                        "message": _terminal_error_message(code),
                        "details": {"run_id": event.run_id},
                        "recoverable": code in {"MODEL_UNAVAILABLE", "TUTOR_RUN_UNAVAILABLE"},
                    },
                    "public_message": public_message,
                },
            )
        return TutorPublicSseEvent(
            sequence=event.event_sequence,
            event_type="run_state",
            data={
                **base,
                "status": state.snapshot.status.value,
                "terminal_outcome": state.terminal_outcome.value if state.terminal_outcome is not None else None,
            },
            terminal=state.terminal_outcome is not None,
        )

    def _mutate(
        self,
        *,
        user_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, object],
        action: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        key = _idempotency_key(idempotency_key)
        request_hash = _request_hash(request_body)
        with self._conn.transaction():
            self._assert_user_exists(user_id)
            existing = self._conn.execute(
                """
                SELECT request_hash, response_json
                FROM tutor_api_idempotency_records
                WHERE user_id = %s AND operation = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (user_id, operation, key),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise _idempotency_conflict()
                response = _mapping(existing["response_json"])
                response["idempotent_replayed"] = True
                return response
            response = _json_response(action())
            response["idempotent_replayed"] = False
            self._conn.execute(
                """
                INSERT INTO tutor_api_idempotency_records (
                  user_id, operation, idempotency_key, request_hash, response_json
                )
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (user_id, operation, key, request_hash, _json(response)),
            )
            return response

    def _assert_user_exists(self, user_id: str) -> None:
        row = self._conn.execute("SELECT id FROM users WHERE id = %s", (user_id,)).fetchone()
        if row is None:
            raise TutorPublicApiError(
                "USER_NOT_FOUND",
                "Current learner was not found.",
                status_code=404,
                details={"user_id": user_id},
            )


def _interactive_policy(now: datetime, *, settings: Settings) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=now + timedelta(minutes=5),
        max_iterations=4,
        max_model_calls=3,
        max_capability_calls=2,
        max_effects=2,
        context_token_budget=settings.tutor_context_token_budget,
        lease_duration_seconds=30,
    )


def _run_payload(state: TutorRunReadState) -> dict[str, object]:
    snapshot = state.snapshot
    continuation_kind = (
        snapshot.continuation_kind.value
        if snapshot.status.value == "waiting_for_input" and state.terminal_outcome is None and snapshot.continuation_kind is not None
        else None
    )
    return {
        "run_id": snapshot.run_id,
        "conversation_id": snapshot.conversation_id,
        "origin": snapshot.origin,
        "status": snapshot.status.value,
        "input_revision": snapshot.input_revision,
        "cancelled": snapshot.cancelled,
        "iteration_count": snapshot.iteration_count,
        "model_call_count": snapshot.model_call_count,
        "capability_call_count": snapshot.capability_call_count,
        "effect_count": snapshot.effect_count,
        "terminal_outcome": state.terminal_outcome.value if state.terminal_outcome is not None else None,
        "continuation_kind": continuation_kind,
        "created_at": _iso(state.created_at),
        "updated_at": _iso(state.updated_at),
    }


def _turn_acceptance_payload(
    accepted: TutorInteractiveTurnAcceptance,
    *,
    state: TutorRunReadState,
    first_turn: bool,
) -> dict[str, object]:
    del first_turn
    return {
        "conversation_id": accepted.run.conversation_id,
        "run_id": accepted.run.run_id,
        "input_revision": accepted.acceptance.input_revision,
        "message_id": accepted.acceptance.message_id,
        "event_cursor": accepted.acceptance.event.event_sequence,
        "merged": False,
        "input_replayed": accepted.acceptance.replayed,
        "run": _run_payload(state),
        "process": _public_process_payload(accepted.process) if accepted.process is not None else None,
        "replaced_run_id": accepted.replaced_run_id,
        "replaced_process": _public_process_payload(accepted.replaced_process)
        if accepted.replaced_process is not None
        else None,
    }


def _foreground_run_payload(item: TutorPublicForegroundRun | None) -> dict[str, object] | None:
    if item is None:
        return None
    return {
        "run_id": item.run_id,
        "status": item.status,
        "continuation_kind": item.continuation_kind.value if item.continuation_kind is not None else None,
    }


def _conversation_summary_payload(item: TutorConversationSummary) -> dict[str, object]:
    active_run: dict[str, object] | None = None
    if item.active_run_id is not None and item.active_run_status is not None:
        active_run = {
            "run_id": item.active_run_id,
            "status": item.active_run_status,
            "continuation_kind": item.active_run_continuation_kind.value if item.active_run_continuation_kind is not None else None,
        }
    return {
        "conversation_id": item.conversation_id,
        "title": item.title or "新对话",
        "last_public_activity_at": _iso(item.last_public_activity_at),
        "active_run": active_run,
    }


def _public_process_payload(item: TutorPublicProcessState) -> dict[str, object]:
    return {
        "kind": "process",
        "id": item.run_id,
        "run_id": item.run_id,
        "display_state": item.display_state,
        "steps": [dict(step) for step in item.steps],
        "elapsed_seconds": item.elapsed_seconds,
        "created_at": _iso(item.created_at),
        "finished_at": _iso(item.finished_at),
    }


def _timeline_payload(item: TutorConversationTimelineRecord) -> dict[str, object]:
    if item.kind == "process" and item.process is not None:
        return _public_process_payload(item.process)
    return {
        "kind": "message",
        "id": item.item_id,
        "role": item.role,
        "content": item.content or "",
        "created_at": _iso(item.created_at),
    }


def _plan_revision_payload(item: TutorPlanRevision) -> dict[str, object]:
    return {
        "revision_id": item.revision_id,
        "predecessor_revision_id": item.predecessor_revision_id,
        "title": item.title,
        "outline": list(item.outline),
        "diff": list(item.diff),
        "learner_reason": item.learner_reason,
        "evidence": list(item.evidence_ids),
        "policy_version": item.policy_version,
        "created_at": _iso(item.created_at),
    }


def _memory_payload(item: TutorMemoryEntry) -> dict[str, object]:
    return {
        "entry_id": item.entry_id,
        "memory_kind": item.memory_kind,
        "state": item.state,
        "category": item.category,
        "statement": item.statement,
        "confidence": item.confidence,
        "provenance": item.provenance_kind,
        "replaced_entry_id": item.replaced_entry_id,
        "evidence": list(item.evidence_ids),
        "retention_until": _iso(item.retention_until),
        "stale_after": _iso(item.stale_after),
        "created_at": _iso(item.created_at),
    }


def _activity_payload(item: TutorActivityRecord) -> dict[str, object]:
    return {
        "activity_id": item.activity_id,
        "category": item.category,
        "reason": item.learner_reason,
        "evidence": list(item.evidence_ids),
        "created_at": _iso(item.created_at),
    }


def _inbox_payload(item: TutorInboxItem) -> dict[str, object]:
    return {
        "inbox_id": item.inbox_id,
        "activity_id": item.activity_id,
        "message": item.message,
        "state": item.state,
        "read_at": _iso(item.read_at),
        "dismissed_at": _iso(item.dismissed_at),
        "created_at": _iso(item.created_at),
    }


def _preferences_payload(*, memory: TutorMemoryPreference, proactive: TutorProactivePreference) -> dict[str, object]:
    return {
        "inferred_memory_enabled": memory.inferred_memory_enabled,
        "memory_setting_version": memory.setting_version,
        "proactive_paused": proactive.hard_paused,
        "proactive_enabled": proactive.enabled,
    }


def _terminal_error_code(outcome: TutorTerminalOutcome | None) -> str:
    if outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE:
        return "MODEL_UNAVAILABLE"
    if outcome is TutorTerminalOutcome.BLOCKED_POLICY:
        return "CAPABILITY_DENIED"
    if outcome is TutorTerminalOutcome.CANCELLED:
        return "RUN_NOT_ACTIVE"
    if outcome is TutorTerminalOutcome.BUDGET_EXHAUSTED:
        return "TUTOR_RUN_UNAVAILABLE"
    return "TUTOR_RUN_FAILED"


def _terminal_error_message(code: str) -> str:
    return {
        "MODEL_UNAVAILABLE": "Tutor model service is unavailable; retry later.",
        "CAPABILITY_DENIED": "Tutor policy did not allow this action.",
        "RUN_NOT_ACTIVE": "Tutor run is no longer active.",
        "TUTOR_RUN_UNAVAILABLE": "Tutor run reached a temporary limit.",
        "TUTOR_RUN_FAILED": "Tutor run could not complete safely.",
    }[code]


def _idempotency_conflict() -> TutorPublicApiError:
    return TutorPublicApiError(
        "IDEMPOTENCY_CONFLICT",
        "Idempotency key was already used with a different request.",
        status_code=409,
        recoverable=False,
    )


def _cursor_invalid() -> TutorPublicApiError:
    return TutorPublicApiError(
        "CURSOR_INVALID",
        "The requested Tutor history cursor is invalid or no longer available.",
        status_code=400,
        recoverable=True,
    )


def _run_not_found(run_id: str) -> TutorPublicApiError:
    return TutorPublicApiError(
        "TUTOR_RUN_NOT_FOUND",
        "Tutor run was not found for the current learner.",
        status_code=404,
        details={"run_id": run_id},
    )


def _run_not_active(*, run_id: str | None = None, conversation_id: str | None = None) -> TutorPublicApiError:
    details: dict[str, object] = {}
    if run_id is not None:
        details["run_id"] = run_id
    if conversation_id is not None:
        details["conversation_id"] = conversation_id
    return TutorPublicApiError(
        "RUN_NOT_ACTIVE",
        "Tutor run is not active for this input.",
        status_code=409,
        details=details,
    )


def _uuid_identifier(value: str, *, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise TutorPublicApiError(
            "VALIDATION_ERROR",
            f"{label} must be a UUID.",
            status_code=400,
            details={"field": label},
        ) from exc


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise TutorPublicApiError(
            "VALIDATION_ERROR",
            "Idempotency-Key must use the documented bounded identifier format.",
            status_code=400,
            details={"field": "Idempotency-Key"},
        )
    return normalized


def _request_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_response(value: Mapping[str, object]) -> dict[str, object]:
    normalized = _json_value(value)
    return _mapping(normalized)


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text if text and len(text) <= 160 else None


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None
