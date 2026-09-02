"""PostgreSQL authority and learner-safe projection for Learning Artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from psycopg import Connection
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation
from pydantic import TypeAdapter, ValidationError

from aearn_shared.execution import (
    SafeExecutionResultV1,
    SafeExecutionResultV2,
    parse_safe_execution_result,
)
from .contracts import (
    TUTOR_LEARNING_ARTIFACT_POLICY_VERSION,
    TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION,
    TutorArtifactActionKind,
    TutorArtifactActionRequest,
    TutorArtifactAttemptDetailV2,
    TutorArtifactAttemptResultV2,
    TutorArtifactAttemptSummaryV1,
    TutorArtifactBranchSummaryV1,
    TutorArtifactDifficulty,
    TutorArtifactKind,
    TutorArtifactOwnerKind,
    TutorArtifactPresentationV1,
    TutorArtifactPurpose,
    TutorArtifactSourceReferenceV1,
    TutorArtifactState,
    TutorArtifactCreate,
    TutorPublicArtifactItem,
    assert_public_artifact_safe,
    canonical_hash,
    presentation_kind,
    validate_public_artifact,
)
from .conversation_events import ArtifactConversationEventSink
from .owner_adapters import ArtifactMutation


ArtifactOwnerEventKind = Literal["state_changed", "attempt_linked", "terminal"]
ArtifactActionCallback = Callable[[TutorPublicArtifactItem], ArtifactMutation]

_PRESENTATION_ADAPTER: TypeAdapter[TutorArtifactPresentationV1] = TypeAdapter(
    TutorArtifactPresentationV1
)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_ARTIFACT_ID_NAMESPACE = uuid5(
    NAMESPACE_URL,
    "https://aearn.local/contracts/tutor-learning-artifact-v1",
)
_ACTIVE_STATES = frozenset(
    {
        TutorArtifactState.PENDING,
        TutorArtifactState.READY,
        TutorArtifactState.ACTIVE,
        TutorArtifactState.RUNNING,
    }
)
_MAX_SAFE_EVENT_PAYLOAD_BYTES = 7_500


class LearningArtifactRepositoryError(ValueError):
    pass


class LearningArtifactNotFound(LearningArtifactRepositoryError):
    pass


class LearningArtifactVersionConflict(LearningArtifactRepositoryError):
    pass


class LearningArtifactIdempotencyConflict(LearningArtifactRepositoryError):
    pass


class LearningArtifactStateConflict(LearningArtifactRepositoryError):
    pass


class LearningArtifactProjectionError(LearningArtifactRepositoryError):
    pass


class LearningArtifactEventSinkUnavailable(LearningArtifactRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class LearningArtifactWriteResult:
    artifact: TutorPublicArtifactItem
    artifact_event_id: str
    artifact_event_sequence: int
    idempotent_replayed: bool
    owner_callback_invoked: bool


@dataclass(frozen=True, slots=True)
class ExecutionResultProjectionSource:
    artifact: TutorPublicArtifactItem
    attempt: TutorArtifactAttemptDetailV2
    track_version: int
    progress_version: int
    assignment_version: int
    owner_context_version: int | None


class PostgresLearningArtifactRepository:
    """The only database-row to learner-safe Artifact DTO boundary.

    Every write owns one short transaction and appends the Artifact evidence row
    plus a Tutor conversation item reference before that transaction exits. Owner
    callbacks execute only after replay/CAS checks and receive the same connection
    through the service's registered adapter.
    """

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        conversation_events: ArtifactConversationEventSink | None = None,
    ) -> None:
        self._conn = conn
        self._conversation_events = conversation_events

    def read_artifact(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
    ) -> TutorPublicArtifactItem:
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        artifact = _uuid(artifact_id, "artifact_id")
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (artifact, user, conversation),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound("learning artifact was not found")
        return self._project_row(row)

    def list_conversation_artifacts(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int = 100,
    ) -> tuple[TutorPublicArtifactItem, ...]:
        if limit < 1 or limit > 200:
            raise ValueError("learning artifact list limit must be within 1..200")
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        rows = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE user_id = %s AND conversation_id = %s
            ORDER BY created_at ASC, id ASC
            LIMIT %s
            """,
            (user, conversation, limit),
        ).fetchall()
        return tuple(self._project_row(row) for row in rows)

    def read_attempt_detail(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        attempt_id: str,
    ) -> TutorArtifactAttemptDetailV2:
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        artifact = _uuid(artifact_id, "artifact_id")
        attempt = _uuid(attempt_id, "attempt_id")
        row = self._conn.execute(
            """
            SELECT artifacts.id AS artifact_id,
                   artifacts.version AS artifact_version,
                   artifacts.conversation_id,
                   artifacts.learning_track_id,
                   artifacts.knowledge_key,
                   artifacts.teaching_session_id,
                   attempts.id AS attempt_id,
                   attempts.attempt_type,
                   attempts.exercise_version_id,
                   attempts.submission_hash,
                   attempts.independence,
                   attempts.assistance_kind,
                   attempts.accepted_at,
                   results.outcome,
                   results.score,
                   results.safe_feedback_json,
                   results.capability_scores_json,
                   results.policy_version AS result_policy_version,
                   results.result_hash,
                   results.terminal_at,
                   jobs.state AS execution_job_state,
                   jobs.result_json AS execution_result_json
            FROM tutor_learning_artifact_attempt_links AS artifact_links
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id = artifact_links.artifact_id
             AND artifacts.user_id = artifact_links.user_id
             AND artifacts.conversation_id = artifact_links.conversation_id
             AND artifacts.teaching_session_id = artifact_links.teaching_session_id
             AND artifacts.learning_track_id = artifact_links.learning_track_id
            JOIN tutor_exercise_attempts AS attempts
              ON attempts.id = artifact_links.attempt_id
             AND attempts.user_id = artifact_links.user_id
             AND attempts.track_id = artifact_links.learning_track_id
             AND attempts.knowledge_key = artifacts.knowledge_key
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id = attempts.id
             AND results.user_id = attempts.user_id
            LEFT JOIN tutor_exercise_execution_links AS execution_links
              ON execution_links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs
              ON jobs.id = execution_links.execution_job_id
            WHERE artifact_links.artifact_id = %s
              AND artifact_links.attempt_id = %s
              AND artifact_links.user_id = %s
              AND artifact_links.conversation_id = %s
              AND tutor_learning_artifact_attempt_owner_matches(
                artifacts.user_id,
                artifacts.conversation_id,
                artifacts.learning_track_id,
                artifacts.knowledge_key,
                artifacts.teaching_session_id,
                artifacts.owner_kind,
                artifacts.owner_id,
                attempts.id
              )
            """,
            (artifact, attempt, user, conversation),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound(
                "learning artifact Attempt was not found"
            )
        return self._project_attempt_detail(row)

    def read_execution_result_projection_source(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        attempt_id: str,
    ) -> ExecutionResultProjectionSource:
        """Lock and read the exact source Artifact plus terminal Attempt authority.

        The caller must own the surrounding transaction. The Artifact lock serializes
        concurrent projectors while Attempt/result evidence remains append-only.
        """

        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        artifact = _uuid(artifact_id, "artifact_id")
        attempt = _uuid(attempt_id, "attempt_id")
        self._lock_conversation_scope(
            user_id=user,
            conversation_id=conversation,
        )
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            FOR UPDATE
            """,
            (artifact, user, conversation),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound(
                "learning artifact was not found"
            )
        detail = self.read_attempt_detail(
            user_id=user,
            conversation_id=conversation,
            artifact_id=artifact,
            attempt_id=attempt,
        )
        if detail.result is None:
            raise LearningArtifactStateConflict(
                "execution result projection requires a terminal Attempt"
            )
        return ExecutionResultProjectionSource(
            artifact=self._project_row(row, allow_stale_attempt=True),
            attempt=detail,
            track_version=_int(row.get("track_version"), "track_version"),
            progress_version=_int(
                row.get("progress_version"),
                "progress_version",
            ),
            assignment_version=_int(
                row.get("assignment_version"),
                "assignment_version",
            ),
            owner_context_version=(
                _int(
                    row.get("owner_context_version"),
                    "owner_context_version",
                )
                if row.get("owner_context_version") is not None
                else None
            ),
        )

    def read_owner_update_result(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        event_key: str,
        event_kind: ArtifactOwnerEventKind,
        expected_owner_result: Mapping[str, object] | None = None,
    ) -> LearningArtifactWriteResult | None:
        artifact = _uuid(artifact_id, "artifact_id")
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        key = _stable_key(event_key, "event_key")
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (artifact, user, conversation),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound(
                "learning artifact was not found"
            )
        event = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifact_events
            WHERE artifact_id = %s AND event_key = %s AND event_kind = %s
            """,
            (artifact, key, event_kind),
        ).fetchone()
        if event is None:
            return None
        if expected_owner_result is not None:
            safe_payload = _mapping(
                event.get("safe_payload_json"),
                "safe_payload_json",
            )
            owner_result = _mapping(
                safe_payload.get("owner_result"),
                "owner_result",
            )
            if owner_result != dict(expected_owner_result):
                raise LearningArtifactIdempotencyConflict(
                    "learning artifact owner event conflicts with Attempt result"
                )
        return self._write_result(
            row,
            event,
            replayed=True,
            owner_callback_invoked=False,
        )

    def read_current_artifact_write(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
    ) -> LearningArtifactWriteResult:
        """Return the current Artifact with the event owning its exact version."""

        artifact = _uuid(artifact_id, "artifact_id")
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s AND conversation_id = %s
            """,
            (artifact, user, conversation),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound("learning artifact was not found")
        event = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifact_events
            WHERE artifact_id = %s AND event_sequence = %s AND to_version = %s
            """,
            (artifact, row["version"], row["version"]),
        ).fetchone()
        if event is None:
            raise LearningArtifactProjectionError(
                "learning artifact current version is missing its owning event"
            )
        return self._write_result(
            row,
            event,
            replayed=True,
            owner_callback_invoked=False,
        )

    def read_result_artifact_for_attempt(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_artifact_id: str,
        attempt_id: str,
        result_hash: str,
    ) -> LearningArtifactWriteResult | None:
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        source_artifact = _uuid(source_artifact_id, "source_artifact_id")
        attempt = _uuid(attempt_id, "attempt_id")
        if not re.fullmatch(r"[0-9a-f]{64}", result_hash):
            raise ValueError("result_hash must be a SHA-256 digest")
        rows = self._conn.execute(
            """
            SELECT artifacts.*
            FROM tutor_learning_artifacts AS artifacts
            JOIN tutor_learning_artifact_references AS source_refs
              ON source_refs.artifact_id = artifacts.id
             AND source_refs.reference_kind = 'artifact'
             AND source_refs.reference_id = %s
            JOIN tutor_learning_artifact_references AS attempt_refs
              ON attempt_refs.artifact_id = artifacts.id
             AND attempt_refs.reference_kind = 'attempt_result'
             AND attempt_refs.reference_id = %s
             AND attempt_refs.content_hash = %s
            WHERE artifacts.user_id = %s
              AND artifacts.conversation_id = %s
              AND artifacts.artifact_kind = 'test_result'
              AND artifacts.purpose = 'result'
              AND artifacts.state = 'completed'
              AND NOT artifacts.blocking
              AND artifacts.active_attempt_id = %s
              AND artifacts.presentation_json->>'result_hash' = %s
            ORDER BY artifacts.created_at ASC, artifacts.id ASC
            LIMIT 2
            """,
            (
                source_artifact,
                attempt,
                result_hash,
                user,
                conversation,
                attempt,
                result_hash,
            ),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise LearningArtifactProjectionError(
                "multiple result artifacts exist for one Attempt"
            )
        row = rows[0]
        event = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifact_events
            WHERE artifact_id = %s AND event_sequence = 1 AND event_kind = 'created'
            """,
            (str(row["id"]),),
        ).fetchone()
        if event is None:
            raise LearningArtifactProjectionError(
                "result artifact is missing its immutable creation evidence"
            )
        return self._write_result(
            row,
            event,
            replayed=True,
            owner_callback_invoked=False,
        )

    def create_artifact(
        self,
        request: TutorArtifactCreate,
        *,
        creation_key: str,
        publish_item: bool = True,
        occurred_at: datetime | None = None,
    ) -> LearningArtifactWriteResult:
        events = self._require_events()
        create = _canonical_create(request)
        key = _stable_key(creation_key, "creation_key")
        now = _utc(occurred_at or datetime.now(UTC))
        create_payload = create.model_dump(mode="json", exclude_none=False)
        try:
            assert_public_artifact_safe(create_payload)
        except ValueError as exc:
            raise LearningArtifactProjectionError(
                "learning artifact create payload contains protected content"
            ) from exc
        request_hash = canonical_hash({"creation_key": key, "artifact": create_payload})
        artifact_id = str(
            uuid5(
                _ARTIFACT_ID_NAMESPACE,
                f"{create.user_id}:{create.conversation_id}:{key}",
            )
        )
        with self._conn.transaction():
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (
                    create.user_id,
                    f"learning-artifact:create:{create.conversation_id}:{key}",
                ),
            )
            self._lock_conversation_scope(
                user_id=create.user_id,
                conversation_id=create.conversation_id,
            )
            existing = self._conn.execute(
                "SELECT * FROM tutor_learning_artifacts WHERE id = %s",
                (artifact_id,),
            ).fetchone()
            if existing is not None:
                created_event = self._conn.execute(
                    """
                    SELECT * FROM tutor_learning_artifact_events
                    WHERE artifact_id = %s AND event_sequence = 1
                    """,
                    (artifact_id,),
                ).fetchone()
                if (
                    str(existing.get("user_id") or "") != create.user_id
                    or str(existing.get("conversation_id") or "")
                    != create.conversation_id
                    or created_event is None
                    or str(created_event.get("request_hash") or "") != request_hash
                    or str(created_event.get("event_kind") or "") != "created"
                ):
                    raise LearningArtifactIdempotencyConflict(
                        "learning artifact creation key conflicts with durable evidence"
                    )
                return self._write_result(
                    existing,
                    created_event,
                    replayed=True,
                    owner_callback_invoked=False,
                )
            if create.active_attempt is not None:
                self._assert_attempt_summary_matches_authority(
                    user_id=create.user_id,
                    conversation_id=create.conversation_id,
                    learning_track_id=create.learning_track_id,
                    knowledge_key=create.knowledge_key,
                    teaching_session_id=create.teaching_session_id,
                    owner_kind=create.owner_kind,
                    owner_id=create.owner_id,
                    summary=create.active_attempt,
                )
            if create.blocking:
                active = self._conn.execute(
                    """
                    SELECT id
                    FROM tutor_learning_artifacts
                    WHERE blocking
                      AND state IN ('pending', 'ready', 'active', 'running')
                      AND (conversation_id = %s OR teaching_session_id = %s)
                    LIMIT 1
                    FOR UPDATE
                    """,
                    (create.conversation_id, create.teaching_session_id),
                ).fetchone()
                if active is not None:
                    raise LearningArtifactStateConflict(
                        "a blocking learning artifact is already active"
                    )
            presentation_payload = create.presentation.model_dump(mode="json")
            active_attempt_payload = (
                create.active_attempt.model_dump(mode="json")
                if create.active_attempt is not None
                else None
            )
            try:
                row = self._conn.execute(
                    """
                    INSERT INTO tutor_learning_artifacts (
                      id, user_id, conversation_id, turn_id, learning_track_id,
                      knowledge_key, teaching_session_id, checkpoint_id,
                      track_version, progress_version, assignment_version,
                      owner_kind, owner_id, owner_version, owner_context_version,
                      artifact_schema_version, artifact_kind, purpose, state,
                      blocking, title, instruction_markdown, difficulty,
                      presentation_kind, presentation_json, presentation_hash,
                      allowed_actions_json, active_attempt_id,
                      active_attempt_summary_json, version, created_at, updated_at,
                      terminal_at
                    )
                    VALUES (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s::jsonb, %s,
                      %s::jsonb, %s,
                      %s::jsonb, 1, %s, %s,
                      %s
                    )
                    RETURNING *
                    """,
                    (
                        artifact_id,
                        create.user_id,
                        create.conversation_id,
                        create.turn_id,
                        create.learning_track_id,
                        create.knowledge_key,
                        create.teaching_session_id,
                        create.checkpoint_id,
                        create.track_version,
                        create.progress_version,
                        create.assignment_version,
                        create.owner_kind.value,
                        create.owner_id,
                        create.owner_version,
                        create.owner_context_version,
                        TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION,
                        create.artifact_kind.value,
                        create.purpose.value,
                        create.state.value,
                        create.blocking,
                        create.title,
                        create.instruction_markdown,
                        create.difficulty.value
                        if create.difficulty is not None
                        else None,
                        presentation_kind(create.presentation),
                        _json(presentation_payload),
                        canonical_hash(presentation_payload),
                        _json([item.value for item in create.allowed_actions]),
                        create.active_attempt.attempt_id
                        if create.active_attempt is not None
                        else None,
                        _json(active_attempt_payload)
                        if active_attempt_payload is not None
                        else None,
                        now,
                        now,
                        now if create.state.terminal else None,
                    ),
                ).fetchone()
            except ForeignKeyViolation as exc:
                raise LearningArtifactNotFound(
                    "learning artifact authority scope was not found"
                ) from exc
            except CheckViolation as exc:
                raise LearningArtifactVersionConflict(
                    "learning artifact owner or teaching authority is stale"
                ) from exc
            except UniqueViolation as exc:
                raise LearningArtifactStateConflict(
                    "learning artifact active authority conflicts with an existing row"
                ) from exc
            if row is None:
                raise RuntimeError("learning artifact insert failed")
            for index, reference in enumerate(create.source_references):
                self._conn.execute(
                    """
                    INSERT INTO tutor_learning_artifact_references (
                      artifact_id, user_id, conversation_id, teaching_session_id,
                      reference_index, reference_kind, reference_id,
                      reference_version, content_hash, label, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        artifact_id,
                        create.user_id,
                        create.conversation_id,
                        create.teaching_session_id,
                        index,
                        reference.kind,
                        reference.reference_id,
                        reference.reference_version,
                        reference.content_hash,
                        reference.label,
                        now,
                    ),
                )
            if create.active_attempt is not None:
                self._link_attempt(
                    row=row,
                    attempt=create.active_attempt,
                    artifact_version=1,
                    occurred_at=now,
                )
            safe_payload = _safe_event_payload(
                {
                    "artifact_version": 1,
                    "artifact_kind": create.artifact_kind.value,
                    "owner_kind": create.owner_kind.value,
                    "owner_id": create.owner_id,
                    "owner_version": create.owner_version,
                    "state": create.state.value,
                    "policy_version": TUTOR_LEARNING_ARTIFACT_POLICY_VERSION,
                }
            )
            event = self._insert_event(
                row=row,
                event_sequence=1,
                event_key="created",
                event_kind="created",
                from_version=None,
                to_version=1,
                state=create.state,
                action_kind=None,
                client_action_id=None,
                request_hash=request_hash,
                safe_payload=safe_payload,
                occurred_at=now,
            )
            projected = self._project_row(row)
            if publish_item:
                events.append_item_reference(
                    user_id=create.user_id,
                    conversation_id=create.conversation_id,
                    artifact_id=artifact_id,
                    artifact_version=1,
                    turn_id=create.turn_id,
                    kind="item_added",
                    occurred_at=now,
                )
            return LearningArtifactWriteResult(
                artifact=projected,
                artifact_event_id=str(event["id"]),
                artifact_event_sequence=1,
                idempotent_replayed=False,
                owner_callback_invoked=False,
            )

    def apply_action(
        self,
        *,
        artifact_id: str,
        request: TutorArtifactActionRequest,
        owner_callback: ArtifactActionCallback,
        conversation_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> LearningArtifactWriteResult:
        events = self._require_events()
        artifact = _uuid(artifact_id, "artifact_id")
        action_request = _canonical_action_request(request)
        scoped_conversation = (
            _uuid(conversation_id, "conversation_id")
            if conversation_id is not None
            else None
        )
        now = _utc(occurred_at or datetime.now(UTC))
        request_hash = canonical_hash(
            action_request.model_dump(mode="json", exclude_none=False)
        )
        with self._conn.transaction():
            resolved_conversation = scoped_conversation or self._locate_scoped_conversation(
                artifact_id=artifact,
                user_id=action_request.user_id,
                learning_track_id=action_request.learning_track_id,
                teaching_session_id=action_request.teaching_session_id,
            )
            self._lock_conversation_scope(
                user_id=action_request.user_id,
                conversation_id=resolved_conversation,
            )
            row = self._read_scoped_row(
                artifact_id=artifact,
                user_id=action_request.user_id,
                learning_track_id=action_request.learning_track_id,
                teaching_session_id=action_request.teaching_session_id,
                conversation_id=resolved_conversation,
                for_update=True,
            )
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_learning_artifact_events
                WHERE artifact_id = %s AND client_action_id = %s
                """,
                (artifact, action_request.client_action_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing.get("request_hash") or "") != request_hash
                    or str(existing.get("action_kind") or "")
                    != action_request.action.action
                    or str(existing.get("event_kind") or "") != "action"
                ):
                    raise LearningArtifactIdempotencyConflict(
                        "learning artifact client action conflicts with durable evidence"
                    )
                return self._write_result(
                    row,
                    existing,
                    replayed=True,
                    owner_callback_invoked=False,
                )
            current = self._project_row(row)
            if current.version != action_request.expected_artifact_version:
                raise LearningArtifactVersionConflict(
                    "learning artifact version changed before action admission"
                )
            if current.state.terminal:
                raise LearningArtifactStateConflict(
                    "terminal learning artifact cannot accept actions"
                )
            action_kind = TutorArtifactActionKind(action_request.action.action)
            if action_kind not in current.allowed_actions:
                raise LearningArtifactStateConflict(
                    "learning artifact action is not currently allowed"
                )
            mutation = owner_callback(current)
            self._validate_mutation(
                user_id=str(row["user_id"]),
                current=current,
                mutation=mutation,
            )
            updated, event = self._persist_mutation(
                row=row,
                current=current,
                mutation=mutation,
                event_key=f"action:{action_request.client_action_id}",
                event_kind="action",
                action_kind=action_kind,
                client_action_id=action_request.client_action_id,
                request_hash=request_hash,
                occurred_at=now,
            )
            projected = self._project_row(updated)
            events.append_item_reference(
                user_id=action_request.user_id,
                conversation_id=projected.conversation_id,
                artifact_id=projected.id,
                artifact_version=projected.version,
                turn_id=projected.turn_id,
                kind="item_updated",
                occurred_at=now,
            )
            return LearningArtifactWriteResult(
                artifact=projected,
                artifact_event_id=str(event["id"]),
                artifact_event_sequence=projected.version,
                idempotent_replayed=False,
                owner_callback_invoked=True,
            )

    def apply_owner_update(
        self,
        *,
        artifact_id: str,
        user_id: str,
        conversation_id: str,
        learning_track_id: str,
        teaching_session_id: str,
        expected_artifact_version: int,
        event_key: str,
        event_kind: ArtifactOwnerEventKind,
        mutation: ArtifactMutation,
        occurred_at: datetime | None = None,
    ) -> LearningArtifactWriteResult:
        events = self._require_events()
        artifact = _uuid(artifact_id, "artifact_id")
        user = _uuid(user_id, "user_id")
        conversation = _uuid(conversation_id, "conversation_id")
        track = _uuid(learning_track_id, "learning_track_id")
        session = _uuid(teaching_session_id, "teaching_session_id")
        key = _stable_key(event_key, "event_key")
        if expected_artifact_version < 1:
            raise ValueError("expected artifact version must be positive")
        if event_kind == "terminal" and not mutation.state.terminal:
            raise LearningArtifactStateConflict(
                "terminal artifact event requires a terminal state"
            )
        if event_kind == "attempt_linked" and mutation.active_attempt is None:
            raise LearningArtifactStateConflict(
                "attempt-linked artifact event requires an Attempt summary"
            )
        now = _utc(occurred_at or datetime.now(UTC))
        request_hash = canonical_hash(
            {
                "artifact_id": artifact,
                "expected_artifact_version": expected_artifact_version,
                "event_key": key,
                "event_kind": event_kind,
                "mutation": _mutation_identity(mutation),
            }
        )
        with self._conn.transaction():
            self._lock_conversation_scope(
                user_id=user,
                conversation_id=conversation,
            )
            row = self._read_scoped_row(
                artifact_id=artifact,
                user_id=user,
                learning_track_id=track,
                teaching_session_id=session,
                conversation_id=conversation,
                for_update=True,
            )
            existing = self._conn.execute(
                """
                SELECT *
                FROM tutor_learning_artifact_events
                WHERE artifact_id = %s AND event_key = %s
                """,
                (artifact, key),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing.get("request_hash") or "") != request_hash
                    or str(existing.get("event_kind") or "") != event_kind
                ):
                    raise LearningArtifactIdempotencyConflict(
                        "learning artifact owner event conflicts with durable evidence"
                    )
                return self._write_result(
                    row,
                    existing,
                    replayed=True,
                    owner_callback_invoked=False,
                )
            current = self._project_row(row, allow_stale_attempt=True)
            if current.version != expected_artifact_version:
                raise LearningArtifactVersionConflict(
                    "learning artifact version changed before owner update"
                )
            self._validate_mutation(
                user_id=str(row["user_id"]),
                current=current,
                mutation=mutation,
            )
            updated, event = self._persist_mutation(
                row=row,
                current=current,
                mutation=mutation,
                event_key=key,
                event_kind=event_kind,
                action_kind=None,
                client_action_id=None,
                request_hash=request_hash,
                occurred_at=now,
            )
            projected = self._project_row(updated)
            events.append_item_reference(
                user_id=user,
                conversation_id=conversation,
                artifact_id=artifact,
                artifact_version=projected.version,
                turn_id=projected.turn_id,
                kind="item_updated",
                occurred_at=now,
            )
            return LearningArtifactWriteResult(
                artifact=projected,
                artifact_event_id=str(event["id"]),
                artifact_event_sequence=projected.version,
                idempotent_replayed=False,
                owner_callback_invoked=False,
            )

    def _require_events(self) -> ArtifactConversationEventSink:
        if self._conversation_events is None:
            raise LearningArtifactEventSinkUnavailable(
                "learning artifact writes require a conversation event sink"
            )
        return self._conversation_events

    def _lock_conversation_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
    ) -> None:
        row = self._conn.execute(
            """
            SELECT id
            FROM tutor_conversations
            WHERE id = %s AND user_id = %s
              AND visibility = 'learner'
              AND kind = 'interactive'
              AND status = 'active'
            FOR UPDATE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound(
                "learning artifact conversation authority was not found"
            )

    def _locate_scoped_conversation(
        self,
        *,
        artifact_id: str,
        user_id: str,
        learning_track_id: str,
        teaching_session_id: str,
    ) -> str:
        row = self._conn.execute(
            """
            SELECT conversation_id
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s
              AND learning_track_id = %s AND teaching_session_id = %s
            """,
            (artifact_id, user_id, learning_track_id, teaching_session_id),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound("learning artifact was not found")
        return str(row["conversation_id"])

    def _read_scoped_row(
        self,
        *,
        artifact_id: str,
        user_id: str,
        learning_track_id: str,
        teaching_session_id: str,
        conversation_id: str,
        for_update: bool,
    ) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT *
            FROM tutor_learning_artifacts
            WHERE id = %s AND user_id = %s AND conversation_id = %s
              AND learning_track_id = %s AND teaching_session_id = %s
            """
            + (" FOR UPDATE" if for_update else ""),
            (
                artifact_id,
                user_id,
                conversation_id,
                learning_track_id,
                teaching_session_id,
            ),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound("learning artifact was not found")
        return row

    def _validate_mutation(
        self,
        *,
        user_id: str,
        current: TutorPublicArtifactItem,
        mutation: ArtifactMutation,
    ) -> None:
        if not isinstance(mutation, ArtifactMutation):
            raise LearningArtifactProjectionError(
                "artifact owner callback returned an invalid mutation"
            )
        if mutation.owner_version < current.owner_version:
            raise LearningArtifactVersionConflict(
                "artifact owner version cannot move backwards"
            )
        if current.state.terminal:
            raise LearningArtifactStateConflict(
                "terminal learning artifact is immutable"
            )
        if not _transition_allowed(current.state, mutation.state):
            raise LearningArtifactStateConflict(
                "learning artifact lifecycle transition is invalid"
            )
        if not _presentation_matches_kind(
            current.artifact_kind,
            presentation_kind(mutation.presentation),
        ):
            raise LearningArtifactProjectionError(
                "learning artifact kind does not match owner presentation"
            )
        if current.active_attempt is not None and mutation.active_attempt is None:
            raise LearningArtifactStateConflict(
                "learning artifact Attempt authority cannot be silently cleared"
            )
        try:
            assert_public_artifact_safe(_mutation_identity(mutation))
        except ValueError as exc:
            raise LearningArtifactProjectionError(
                "learning artifact owner mutation contains protected content"
            ) from exc
        if mutation.active_attempt is not None:
            self._assert_attempt_summary_matches_authority(
                user_id=user_id,
                conversation_id=current.conversation_id,
                learning_track_id=current.learning_track_id,
                knowledge_key=current.knowledge_key,
                teaching_session_id=current.teaching_session_id,
                owner_kind=current.owner_kind,
                owner_id=current.owner_id,
                summary=mutation.active_attempt,
            )

    def _assert_attempt_summary_matches_authority(
        self,
        *,
        user_id: str,
        conversation_id: str,
        learning_track_id: str,
        knowledge_key: str,
        teaching_session_id: str,
        owner_kind: TutorArtifactOwnerKind,
        owner_id: str,
        summary: TutorArtifactAttemptSummaryV1,
    ) -> None:
        authoritative = self._authoritative_attempt_summary(
            user_id=user_id,
            conversation_id=conversation_id,
            learning_track_id=learning_track_id,
            knowledge_key=knowledge_key,
            teaching_session_id=teaching_session_id,
            owner_kind=owner_kind,
            owner_id=owner_id,
            attempt_id=summary.attempt_id,
        )
        if _attempt_summary_identity(authoritative) != _attempt_summary_identity(summary):
            raise LearningArtifactVersionConflict(
                "learning artifact Attempt summary differs from owner authority"
            )

    def _authoritative_attempt_summary(
        self,
        *,
        user_id: str,
        conversation_id: str,
        learning_track_id: str,
        knowledge_key: str,
        teaching_session_id: str,
        owner_kind: TutorArtifactOwnerKind,
        owner_id: str,
        attempt_id: str,
    ) -> TutorArtifactAttemptSummaryV1:
        row = self._conn.execute(
            """
            SELECT attempts.id, attempts.attempt_type, attempts.accepted_at,
                   results.outcome, results.score, results.result_hash,
                   results.terminal_at
            FROM tutor_exercise_attempts AS attempts
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id = attempts.id
             AND results.user_id = attempts.user_id
            WHERE attempts.id = %s
              AND attempts.user_id = %s
              AND attempts.track_id = %s
              AND attempts.knowledge_key = %s
              AND tutor_learning_artifact_attempt_owner_matches(
                %s, %s, %s, %s, %s, %s, %s, attempts.id
              )
            """,
            (
                attempt_id,
                user_id,
                learning_track_id,
                knowledge_key,
                user_id,
                conversation_id,
                learning_track_id,
                knowledge_key,
                teaching_session_id,
                owner_kind.value,
                owner_id,
            ),
        ).fetchone()
        if row is None:
            raise LearningArtifactNotFound(
                "learning artifact Attempt owner authority was not found"
            )
        terminal = row.get("outcome") is not None
        try:
            return TutorArtifactAttemptSummaryV1.model_validate(
                {
                    "attempt_id": str(row["id"]),
                    "attempt_type": str(row["attempt_type"]),
                    "status": "terminal" if terminal else "pending",
                    "outcome": str(row["outcome"]) if terminal else None,
                    "score": float(str(row["score"])) if terminal else None,
                    "result_hash": str(row["result_hash"]) if terminal else None,
                    "accepted_at": _iso(row.get("accepted_at"), "accepted_at"),
                    "terminal_at": (
                        _iso(row.get("terminal_at"), "terminal_at")
                        if terminal
                        else None
                    ),
                }
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise LearningArtifactProjectionError(
                "learning artifact Attempt authority cannot be projected safely"
            ) from exc

    def _persist_mutation(
        self,
        *,
        row: Mapping[str, object],
        current: TutorPublicArtifactItem,
        mutation: ArtifactMutation,
        event_key: str,
        event_kind: str,
        action_kind: TutorArtifactActionKind | None,
        client_action_id: str | None,
        request_hash: str,
        occurred_at: datetime,
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        next_version = current.version + 1
        presentation_payload = mutation.presentation.model_dump(mode="json")
        active_attempt_payload = (
            mutation.active_attempt.model_dump(mode="json")
            if mutation.active_attempt is not None
            else None
        )
        try:
            updated = self._conn.execute(
                """
                UPDATE tutor_learning_artifacts
                SET owner_version = %s,
                    owner_context_version = %s,
                    state = %s,
                    presentation_kind = %s,
                    presentation_json = %s::jsonb,
                    presentation_hash = %s,
                    allowed_actions_json = %s::jsonb,
                    active_attempt_id = %s,
                    active_attempt_summary_json = %s::jsonb,
                    version = version + 1,
                    terminal_at = %s
                WHERE id = %s AND user_id = %s AND conversation_id = %s
                  AND teaching_session_id = %s AND learning_track_id = %s
                  AND version = %s
                RETURNING *
                """,
                (
                    mutation.owner_version,
                    mutation.owner_context_version,
                    mutation.state.value,
                    presentation_kind(mutation.presentation),
                    _json(presentation_payload),
                    canonical_hash(presentation_payload),
                    _json([item.value for item in mutation.allowed_actions]),
                    mutation.active_attempt.attempt_id
                    if mutation.active_attempt is not None
                    else None,
                    _json(active_attempt_payload)
                    if active_attempt_payload is not None
                    else None,
                    occurred_at if mutation.state.terminal else None,
                    current.id,
                    str(row["user_id"]),
                    current.conversation_id,
                    current.teaching_session_id,
                    current.learning_track_id,
                    current.version,
                ),
            ).fetchone()
        except ForeignKeyViolation as exc:
            raise LearningArtifactNotFound(
                "learning artifact owner Attempt or authority scope was not found"
            ) from exc
        except CheckViolation as exc:
            raise LearningArtifactVersionConflict(
                "learning artifact owner or teaching authority is stale"
            ) from exc
        except UniqueViolation as exc:
            raise LearningArtifactStateConflict(
                "learning artifact active authority conflicts with an existing row"
            ) from exc
        if updated is None:
            raise LearningArtifactVersionConflict(
                "learning artifact version changed before mutation commit"
            )
        if mutation.active_attempt is not None:
            self._link_attempt(
                row=updated,
                attempt=mutation.active_attempt,
                artifact_version=next_version,
                occurred_at=occurred_at,
            )
        safe_payload = _safe_event_payload(
            {
                "artifact_version": next_version,
                "owner_kind": current.owner_kind.value,
                "owner_id": current.owner_id,
                "owner_version": mutation.owner_version,
                "state": mutation.state.value,
                "active_attempt_id": mutation.active_attempt.attempt_id
                if mutation.active_attempt is not None
                else None,
                "owner_result": dict(mutation.safe_event_payload),
                "policy_version": TUTOR_LEARNING_ARTIFACT_POLICY_VERSION,
            }
        )
        event = self._insert_event(
            row=updated,
            event_sequence=next_version,
            event_key=event_key,
            event_kind=event_kind,
            from_version=current.version,
            to_version=next_version,
            state=mutation.state,
            action_kind=action_kind,
            client_action_id=client_action_id,
            request_hash=request_hash,
            safe_payload=safe_payload,
            occurred_at=occurred_at,
        )
        return updated, event

    def _link_attempt(
        self,
        *,
        row: Mapping[str, object],
        attempt: TutorArtifactAttemptSummaryV1,
        artifact_version: int,
        occurred_at: datetime,
    ) -> None:
        existing = self._conn.execute(
            """
            SELECT artifact_version, user_id, conversation_id, teaching_session_id,
                   learning_track_id
            FROM tutor_learning_artifact_attempt_links
            WHERE artifact_id = %s AND attempt_id = %s
            """,
            (str(row["id"]), attempt.attempt_id),
        ).fetchone()
        if existing is not None:
            if (
                str(existing.get("user_id") or "") != str(row["user_id"])
                or str(existing.get("conversation_id") or "")
                != str(row["conversation_id"])
                or str(existing.get("teaching_session_id") or "")
                != str(row["teaching_session_id"])
                or str(existing.get("learning_track_id") or "")
                != str(row["learning_track_id"])
            ):
                raise LearningArtifactIdempotencyConflict(
                    "learning artifact Attempt link conflicts with durable scope"
                )
            return
        try:
            self._conn.execute(
                """
                INSERT INTO tutor_learning_artifact_attempt_links (
                  artifact_id, user_id, conversation_id, teaching_session_id,
                  learning_track_id, attempt_id, artifact_version, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(row["id"]),
                    str(row["user_id"]),
                    str(row["conversation_id"]),
                    str(row["teaching_session_id"]),
                    str(row["learning_track_id"]),
                    attempt.attempt_id,
                    artifact_version,
                    occurred_at,
                ),
            )
        except ForeignKeyViolation as exc:
            raise LearningArtifactNotFound(
                "learning artifact Attempt authority was not found"
            ) from exc
        except UniqueViolation as exc:
            raise LearningArtifactIdempotencyConflict(
                "learning artifact Attempt link conflicts with durable evidence"
            ) from exc

    def _insert_event(
        self,
        *,
        row: Mapping[str, object],
        event_sequence: int,
        event_key: str,
        event_kind: str,
        from_version: int | None,
        to_version: int,
        state: TutorArtifactState,
        action_kind: TutorArtifactActionKind | None,
        client_action_id: str | None,
        request_hash: str,
        safe_payload: Mapping[str, object],
        occurred_at: datetime,
    ) -> Mapping[str, object]:
        try:
            event = self._conn.execute(
                """
                INSERT INTO tutor_learning_artifact_events (
                  artifact_id, user_id, conversation_id, teaching_session_id,
                  event_sequence, event_key, event_kind, from_version, to_version,
                  state, action_kind, client_action_id, request_hash,
                  safe_payload_json, payload_hash, created_at
                )
                VALUES (
                  %s, %s, %s, %s,
                  %s, %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s::jsonb, %s, %s
                )
                RETURNING *
                """,
                (
                    str(row["id"]),
                    str(row["user_id"]),
                    str(row["conversation_id"]),
                    str(row["teaching_session_id"]),
                    event_sequence,
                    event_key,
                    event_kind,
                    from_version,
                    to_version,
                    state.value,
                    action_kind.value if action_kind is not None else None,
                    client_action_id,
                    request_hash,
                    _json(safe_payload),
                    canonical_hash(safe_payload),
                    occurred_at,
                ),
            ).fetchone()
        except (CheckViolation, UniqueViolation) as exc:
            raise LearningArtifactIdempotencyConflict(
                "learning artifact event conflicts with durable evidence"
            ) from exc
        if event is None:
            raise RuntimeError("learning artifact event insert failed")
        return event

    def _write_result(
        self,
        row: Mapping[str, object],
        event: Mapping[str, object],
        *,
        replayed: bool,
        owner_callback_invoked: bool,
    ) -> LearningArtifactWriteResult:
        return LearningArtifactWriteResult(
            artifact=self._project_row(row),
            artifact_event_id=str(event["id"]),
            artifact_event_sequence=_int(event.get("event_sequence"), "event_sequence"),
            idempotent_replayed=replayed,
            owner_callback_invoked=owner_callback_invoked,
        )

    def _project_row(
        self,
        row: Mapping[str, object],
        *,
        allow_stale_attempt: bool = False,
    ) -> TutorPublicArtifactItem:
        try:
            if (
                str(row.get("artifact_schema_version") or "")
                != TUTOR_LEARNING_ARTIFACT_SCHEMA_VERSION
            ):
                raise ValueError("unsupported learning artifact schema version")
            presentation_payload = _mapping(
                row.get("presentation_json"),
                "presentation_json",
            )
            if canonical_hash(presentation_payload) != str(
                row.get("presentation_hash") or ""
            ):
                raise ValueError("learning artifact presentation hash mismatch")
            presentation = _PRESENTATION_ADAPTER.validate_python(presentation_payload)
            actions = tuple(
                TutorArtifactActionKind(str(item))
                for item in _sequence(
                    row.get("allowed_actions_json"),
                    "allowed_actions_json",
                )
            )
            active_attempt_id = _optional_string(row.get("active_attempt_id"))
            active_attempt_payload = row.get("active_attempt_summary_json")
            active_attempt = (
                TutorArtifactAttemptSummaryV1.model_validate(
                    _mapping(
                        active_attempt_payload,
                        "active_attempt_summary_json",
                    )
                )
                if active_attempt_payload is not None
                else None
            )
            if (active_attempt is None) != (active_attempt_id is None):
                raise ValueError("learning artifact active Attempt shape is invalid")
            if (
                active_attempt is not None
                and active_attempt.attempt_id != active_attempt_id
            ):
                raise ValueError("learning artifact active Attempt identity mismatch")
            if active_attempt is not None and not allow_stale_attempt:
                authoritative_attempt = self._authoritative_attempt_summary(
                    user_id=str(row["user_id"]),
                    conversation_id=str(row["conversation_id"]),
                    learning_track_id=str(row["learning_track_id"]),
                    knowledge_key=str(row["knowledge_key"]),
                    teaching_session_id=str(row["teaching_session_id"]),
                    owner_kind=TutorArtifactOwnerKind(str(row["owner_kind"])),
                    owner_id=str(row["owner_id"]),
                    attempt_id=active_attempt.attempt_id,
                )
                if _attempt_summary_identity(authoritative_attempt) != _attempt_summary_identity(
                    active_attempt
                ):
                    raise ValueError(
                        "learning artifact active Attempt summary is stale or mismatched"
                    )
            item = TutorPublicArtifactItem(
                id=str(row["id"]),
                conversation_id=str(row["conversation_id"]),
                turn_id=_optional_string(row.get("turn_id")),
                learning_track_id=str(row["learning_track_id"]),
                knowledge_key=str(row["knowledge_key"]),
                teaching_session_id=str(row["teaching_session_id"]),
                checkpoint_id=str(row["checkpoint_id"]),
                artifact_kind=TutorArtifactKind(str(row["artifact_kind"])),
                purpose=TutorArtifactPurpose(str(row["purpose"])),
                owner_kind=TutorArtifactOwnerKind(str(row["owner_kind"])),
                owner_id=str(row["owner_id"]),
                owner_version=_int(row.get("owner_version"), "owner_version"),
                state=TutorArtifactState(str(row["state"])),
                blocking=bool(row["blocking"]),
                title=str(row["title"]),
                instruction_markdown=str(row["instruction_markdown"]),
                difficulty=(
                    TutorArtifactDifficulty(str(row["difficulty"]))
                    if row.get("difficulty") is not None
                    else None
                ),
                presentation=presentation,
                allowed_actions=actions,
                source_references=self._read_references(artifact_id=str(row["id"])),
                active_attempt=active_attempt,
                branch_summary=self._read_branch_summary(
                    user_id=str(row["user_id"]),
                    conversation_id=str(row["conversation_id"]),
                    artifact_id=str(row["id"]),
                ),
                version=_int(row.get("version"), "version"),
                created_at=_iso(row.get("created_at"), "created_at"),
                updated_at=_iso(row.get("updated_at"), "updated_at"),
                terminal_at=(
                    _iso(row.get("terminal_at"), "terminal_at")
                    if row.get("terminal_at") is not None
                    else None
                ),
            )
            return TutorPublicArtifactItem.model_validate(
                validate_public_artifact(item)
            )
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise LearningArtifactProjectionError(
                "stored learning artifact cannot be projected safely"
            ) from exc

    def _read_branch_summary(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
    ) -> TutorArtifactBranchSummaryV1 | None:
        row = self._conn.execute(
            """
            SELECT branches.id, branches.state, branches.latest_disposition,
                   branches.round_count,
                   count(items.id)::int AS item_count
            FROM tutor_conversation_branches AS branches
            LEFT JOIN tutor_conversation_branch_items AS items
              ON items.branch_id = branches.id
             AND items.user_id = branches.user_id
             AND items.conversation_id = branches.conversation_id
             AND items.artifact_id = branches.artifact_id
            WHERE branches.user_id = %s AND branches.conversation_id = %s
              AND branches.artifact_id = %s
            GROUP BY branches.id
            ORDER BY branches.created_at DESC, branches.id DESC
            LIMIT 1
            """,
            (user_id, conversation_id, artifact_id),
        ).fetchone()
        if row is None:
            return None
        item_count = _int(row.get("item_count"), "item_count")
        if item_count < 1:
            raise LearningArtifactProjectionError(
                "stored learning artifact branch has no item membership"
            )
        state = str(row["state"])
        return TutorArtifactBranchSummaryV1.model_validate(
            {
                "branch_id": str(row["id"]),
                "state": state,
                "disposition": row.get("latest_disposition"),
                "round_count": _int(row.get("round_count"), "round_count"),
                "item_count": item_count,
                "collapsed": state == "resolved",
            }
        )

    def _project_attempt_detail(
        self,
        row: Mapping[str, object],
    ) -> TutorArtifactAttemptDetailV2:
        try:
            result = (
                TutorArtifactAttemptResultV2.model_validate(
                    {
                        "outcome": row["outcome"],
                        "score": row["score"],
                        "execution_result": _project_execution_result(row),
                        "capability_scores": _mapping(
                            row.get("capability_scores_json"),
                            "capability_scores_json",
                        ),
                        "policy_version": row["result_policy_version"],
                        "result_hash": row["result_hash"],
                        "terminal_at": _iso(
                            row.get("terminal_at"),
                            "terminal_at",
                        ),
                    }
                )
                if row.get("outcome") is not None
                else None
            )
            detail = TutorArtifactAttemptDetailV2.model_validate(
                {
                    "artifact_id": str(row["artifact_id"]),
                    "artifact_version": _int(
                        row.get("artifact_version"),
                        "artifact_version",
                    ),
                    "conversation_id": str(row["conversation_id"]),
                    "learning_track_id": str(row["learning_track_id"]),
                    "knowledge_key": str(row["knowledge_key"]),
                    "teaching_session_id": str(row["teaching_session_id"]),
                    "attempt_id": str(row["attempt_id"]),
                    "attempt_type": str(row["attempt_type"]),
                    "exercise_version_id": str(row["exercise_version_id"]),
                    "submission_hash": str(row["submission_hash"]),
                    "independence": str(row["independence"]),
                    "assistance_kind": str(
                        row.get("assistance_kind") or row["independence"]
                    ),
                    "status": "terminal" if result is not None else "pending",
                    "execution_job_state": _optional_string(
                        row.get("execution_job_state")
                    ),
                    "accepted_at": _iso(row.get("accepted_at"), "accepted_at"),
                    "result": result,
                }
            )
            assert_public_artifact_safe(detail.model_dump(mode="json"))
            return detail
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise LearningArtifactProjectionError(
                "stored learning artifact Attempt cannot be projected safely"
            ) from exc

    def _read_references(
        self,
        *,
        artifact_id: str,
    ) -> tuple[TutorArtifactSourceReferenceV1, ...]:
        rows = self._conn.execute(
            """
            SELECT reference_kind, reference_id, reference_version,
                   content_hash, label
            FROM tutor_learning_artifact_references
            WHERE artifact_id = %s
            ORDER BY reference_index ASC
            """,
            (artifact_id,),
        ).fetchall()
        return tuple(
            TutorArtifactSourceReferenceV1.model_validate(
                {
                    "kind": str(row["reference_kind"]),
                    "reference_id": str(row["reference_id"]),
                    "reference_version": (
                        _int(row.get("reference_version"), "reference_version")
                        if row.get("reference_version") is not None
                        else None
                    ),
                    "content_hash": _optional_string(row.get("content_hash")),
                    "label": str(row["label"]),
                }
            )
            for row in rows
        )


def _project_execution_result(
    row: Mapping[str, object],
) -> SafeExecutionResultV2 | None:
    job_payload = row.get("execution_result_json")
    job_result = (
        _parse_execution_result_payload(
            job_payload,
            label="execution job result",
        )
        if isinstance(job_payload, Mapping)
        else None
    )
    feedback_result = _execution_result_from_safe_feedback(
        row.get("safe_feedback_json")
    )
    if (
        job_result is not None
        and feedback_result is not None
        and canonical_hash(job_result.model_dump(mode="json"))
        != canonical_hash(feedback_result.model_dump(mode="json"))
    ):
        raise ValueError(
            "execution job result differs from authoritative Attempt feedback"
        )
    return job_result or feedback_result


def _execution_result_from_safe_feedback(
    value: object,
) -> SafeExecutionResultV2 | None:
    if not isinstance(value, Mapping):
        return None
    payload = dict(value)
    schema_version = payload.get("schema_version")
    if schema_version is not None:
        if schema_version != "safe-execution-result-v2":
            if str(schema_version).startswith("safe-execution-result"):
                raise ValueError(
                    "Attempt feedback execution result version is unsupported"
                )
            return None
        return _parse_execution_result_payload(
            payload,
            label="Attempt feedback execution result",
        )
    v1_fields = frozenset(SafeExecutionResultV1.model_fields)
    if "status" not in payload or not set(payload).issubset(v1_fields):
        return None
    return _parse_execution_result_payload(
        payload,
        label="historical Attempt feedback execution result",
    )


def _parse_execution_result_payload(
    value: object,
    *,
    label: str,
) -> SafeExecutionResultV2:
    try:
        return parse_safe_execution_result(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid") from exc


def _canonical_create(request: TutorArtifactCreate) -> TutorArtifactCreate:
    create = TutorArtifactCreate.model_validate(request)
    return create.model_copy(
        update={
            "user_id": _uuid(create.user_id, "user_id"),
            "conversation_id": _uuid(create.conversation_id, "conversation_id"),
            "turn_id": _uuid(create.turn_id, "turn_id")
            if create.turn_id is not None
            else None,
            "learning_track_id": _uuid(
                create.learning_track_id,
                "learning_track_id",
            ),
            "teaching_session_id": _uuid(
                create.teaching_session_id,
                "teaching_session_id",
            ),
            "checkpoint_id": _uuid(create.checkpoint_id, "checkpoint_id"),
            "owner_id": _uuid(create.owner_id, "owner_id"),
        }
    )


def _canonical_action_request(
    request: TutorArtifactActionRequest,
) -> TutorArtifactActionRequest:
    action = TutorArtifactActionRequest.model_validate(request)
    return action.model_copy(
        update={
            "user_id": _uuid(action.user_id, "user_id"),
            "learning_track_id": _uuid(
                action.learning_track_id,
                "learning_track_id",
            ),
            "teaching_session_id": _uuid(
                action.teaching_session_id,
                "teaching_session_id",
            ),
        }
    )


def _mutation_identity(mutation: ArtifactMutation) -> dict[str, object]:
    return {
        "state": mutation.state.value,
        "owner_version": mutation.owner_version,
        "owner_context_version": mutation.owner_context_version,
        "presentation": mutation.presentation.model_dump(mode="json"),
        "allowed_actions": [item.value for item in mutation.allowed_actions],
        "active_attempt": mutation.active_attempt.model_dump(mode="json")
        if mutation.active_attempt is not None
        else None,
        "safe_event_payload": dict(mutation.safe_event_payload),
    }


def _attempt_summary_identity(
    summary: TutorArtifactAttemptSummaryV1,
) -> dict[str, object]:
    payload = summary.model_dump(mode="json", exclude_none=False)
    payload["accepted_at"] = _canonical_iso_text(summary.accepted_at)
    payload["terminal_at"] = (
        _canonical_iso_text(summary.terminal_at)
        if summary.terminal_at is not None
        else None
    )
    return payload


def _canonical_iso_text(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("artifact Attempt timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise ValueError("artifact Attempt timestamp must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def _safe_event_payload(payload: Mapping[str, object]) -> dict[str, object]:
    safe = dict(payload)
    try:
        assert_public_artifact_safe(safe)
        encoded = _json(safe).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LearningArtifactProjectionError(
            "learning artifact event payload is not learner-safe JSON"
        ) from exc
    if len(encoded) > _MAX_SAFE_EVENT_PAYLOAD_BYTES:
        raise LearningArtifactProjectionError(
            "learning artifact event payload exceeds its safe bound"
        )
    return safe


def _transition_allowed(
    current: TutorArtifactState,
    target: TutorArtifactState,
) -> bool:
    if current == target:
        return True
    transitions = {
        TutorArtifactState.PENDING: {
            TutorArtifactState.READY,
            TutorArtifactState.FAILED,
            TutorArtifactState.CANCELLED,
            TutorArtifactState.SUPERSEDED,
        },
        TutorArtifactState.READY: {
            TutorArtifactState.ACTIVE,
            TutorArtifactState.RUNNING,
            TutorArtifactState.COMPLETED,
            TutorArtifactState.FAILED,
            TutorArtifactState.CANCELLED,
            TutorArtifactState.SUPERSEDED,
        },
        TutorArtifactState.ACTIVE: {
            TutorArtifactState.RUNNING,
            TutorArtifactState.COMPLETED,
            TutorArtifactState.FAILED,
            TutorArtifactState.CANCELLED,
            TutorArtifactState.SUPERSEDED,
        },
        TutorArtifactState.RUNNING: {
            TutorArtifactState.ACTIVE,
            TutorArtifactState.COMPLETED,
            TutorArtifactState.FAILED,
            TutorArtifactState.CANCELLED,
            TutorArtifactState.SUPERSEDED,
        },
    }
    return target in transitions.get(current, set())


def _presentation_matches_kind(kind: TutorArtifactKind, presentation: str) -> bool:
    expected = {
        TutorArtifactKind.EXERCISE_WORKSPACE: frozenset({"exercise_workspace_v1"}),
        TutorArtifactKind.BROWSER_PREVIEW: frozenset({"browser_preview_v1"}),
        TutorArtifactKind.TEST_RESULT: frozenset({"test_result_v1"}),
        TutorArtifactKind.KNOWLEDGE_CHECK: frozenset({"knowledge_check_v1"}),
        TutorArtifactKind.MODEL_CODE_REVIEW: frozenset(
            {"model_code_review_v1", "model_code_review_v2"}
        ),
        TutorArtifactKind.SQL_WORKSPACE: frozenset({"sql_workspace_v1", "sql_workspace_v2"}),
        TutorArtifactKind.DEMONSTRATION: frozenset(
            {"demonstration_v1", "demonstration_v2"}
        ),
        TutorArtifactKind.SOURCE_INSPECTOR: frozenset({"source_inspector_v1"}),
    }[kind]
    return presentation in expected


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a UUID") from exc


def _stable_key(value: str, label: str) -> str:
    normalized = str(value).strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise ValueError(f"{label} must be a stable bounded identifier")
    return normalized


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return dict(value)


def _sequence(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, Sequence) or isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise ValueError(f"{label} must be a JSON array")
    return tuple(value)


def _int(value: object, label: str) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{label} must be positive")
    return parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    return normalized if normalized else None


def _iso(value: object, label: str) -> str:
    if not isinstance(value, datetime):
        raise ValueError(f"{label} must be a timestamp")
    return _utc(value).isoformat()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = (
    "ArtifactActionCallback",
    "ArtifactOwnerEventKind",
    "ExecutionResultProjectionSource",
    "LearningArtifactEventSinkUnavailable",
    "LearningArtifactIdempotencyConflict",
    "LearningArtifactNotFound",
    "LearningArtifactProjectionError",
    "LearningArtifactRepositoryError",
    "LearningArtifactStateConflict",
    "LearningArtifactVersionConflict",
    "LearningArtifactWriteResult",
    "PostgresLearningArtifactRepository",
)
