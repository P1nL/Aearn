from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg import Connection

from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.artifacts.contracts import (
    ARTIFACT_PROTECTED_MARKERS,
    TutorArtifactActionKind,
    TutorArtifactActionRequest,
    TutorArtifactCancelAction,
    TutorArtifactCreate,
    TutorArtifactKind,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactOwnerKind,
    TutorArtifactPurpose,
    TutorArtifactState,
    TutorPublicArtifactItem,
)
from app.services.learning.artifacts.conversation_events import (
    ArtifactConversationEventSink,
    ArtifactConversationItemEventKind,
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.owner_adapters import (
    ArtifactMutation,
    ArtifactOwnerAdapterRegistry,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactIdempotencyConflict,
    LearningArtifactNotFound,
    LearningArtifactProjectionError,
    LearningArtifactVersionConflict,
    PostgresLearningArtifactRepository,
)
from app.services.learning.artifacts.service import (
    LearningArtifactService,
    LearningArtifactServiceError,
)
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionService
from tests.support.teaching_session_support import (
    create_teaching_scope,
    database_available,
)


pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)
_NOW = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_artifact_schema() -> None:
    bootstrap_database()


def _open_scope(
    conn: Connection[dict[str, object]],
) -> tuple[dict[str, str | int], dict[str, object]]:
    scope = create_teaching_scope(conn)
    opened = TeachingSessionService(conn).open(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key=str(scope["knowledge_key"]),
        conversation_id=str(scope["conversation_id"]),
        expected_track_version=int(scope["track_version"]),
        expected_progress_version=int(scope["progress_version"]),
        expected_assignment_version=int(scope["assignment_version"]),
        mode=TeachingSessionMode.FREE_READING,
        idempotency_key=f"artifact-session:{uuid4()}",
    )
    session = opened["teaching_session"]
    assert isinstance(session, dict)
    return scope, session


def _create_request(
    scope: dict[str, str | int],
    session: dict[str, object],
    *,
    title: str = "变量绑定检查",
    blocking: bool = False,
) -> TutorArtifactCreate:
    return TutorArtifactCreate(
        user_id=str(scope["user_id"]),
        conversation_id=str(scope["conversation_id"]),
        learning_track_id=str(scope["track_id"]),
        knowledge_key=str(scope["knowledge_key"]),
        teaching_session_id=str(session["session_id"]),
        checkpoint_id=str(session["checkpoint_id"]),
        track_version=int(scope["track_version"]),
        progress_version=int(scope["progress_version"]),
        assignment_version=int(scope["assignment_version"]),
        owner_kind=TutorArtifactOwnerKind.TEACHING_PRACTICE,
        owner_id=str(session["checkpoint_id"]),
        owner_version=int(session["session_version"]),
        owner_context_version=int(session["session_version"]),
        artifact_kind=TutorArtifactKind.KNOWLEDGE_CHECK,
        purpose=TutorArtifactPurpose.KNOWLEDGE_CHECK,
        state=TutorArtifactState.ACTIVE,
        blocking=blocking,
        title=title,
        instruction_markdown="请说明赋值后名称与值的关系。",
        presentation=TutorArtifactKnowledgeCheckPresentationV1(
            response_kind="short_text",
            prompt_markdown="执行 count = 3 后，count 表示什么？",
            maximum_text_length=400,
        ),
        allowed_actions=(
            TutorArtifactActionKind.RESPOND,
            TutorArtifactActionKind.CANCEL,
        ),
    )


def _cancel_request(
    scope: dict[str, str | int],
    session: dict[str, object],
    *,
    client_action_id: str,
    expected_version: int,
) -> TutorArtifactActionRequest:
    return TutorArtifactActionRequest(
        user_id=str(scope["user_id"]),
        learning_track_id=str(scope["track_id"]),
        teaching_session_id=str(session["session_id"]),
        client_action_id=client_action_id,
        expected_artifact_version=expected_version,
        action=TutorArtifactCancelAction(),
    )


def _cancel_mutation(artifact: TutorPublicArtifactItem) -> ArtifactMutation:
    return ArtifactMutation(
        state=TutorArtifactState.CANCELLED,
        owner_version=artifact.owner_version,
        owner_context_version=artifact.owner_version,
        presentation=artifact.presentation,
        allowed_actions=(),
        active_attempt=artifact.active_attempt,
        safe_event_payload={"reason": "learner_cancelled"},
    )


def test_repository_read_list_replay_scope_and_safe_projection() -> None:
    with connect() as conn:
        scope, session = _open_scope(conn)
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        first = repository.create_artifact(
            _create_request(scope, session, title="第一项"),
            creation_key="teaching:first",
            occurred_at=_NOW,
        )
        second = repository.create_artifact(
            _create_request(scope, session, title="第二项"),
            creation_key="teaching:second",
            occurred_at=_NOW + timedelta(minutes=1),
        )

        assert first.artifact.version == 1
        assert second.artifact.version == 1
        exact = repository.read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=first.artifact.id,
        )
        assert exact == first.artifact
        listed = repository.list_conversation_artifacts(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
        )
        assert [item.id for item in listed] == [
            first.artifact.id,
            second.artifact.id,
        ]
        assert [item.title for item in listed] == ["第一项", "第二项"]

        replay = repository.create_artifact(
            _create_request(scope, session, title="第一项"),
            creation_key="teaching:first",
            occurred_at=_NOW + timedelta(minutes=2),
        )
        assert replay.idempotent_replayed is True
        assert replay.artifact.id == first.artifact.id
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE conversation_id = %s AND item_id = %s
            """,
            (scope["conversation_id"], first.artifact.id),
        ).fetchone() == {"count": 1}

        with pytest.raises(LearningArtifactIdempotencyConflict):
            repository.create_artifact(
                _create_request(scope, session, title="冲突标题"),
                creation_key="teaching:first",
                occurred_at=_NOW + timedelta(minutes=3),
            )
        with pytest.raises(LearningArtifactNotFound):
            repository.read_artifact(
                user_id=str(scope["user_id"]),
                conversation_id=str(uuid4()),
                artifact_id=first.artifact.id,
            )

        protected = ARTIFACT_PROTECTED_MARKERS[0]
        with pytest.raises(LearningArtifactProjectionError):
            repository.create_artifact(
                _create_request(scope, session, title=protected),
                creation_key="teaching:protected",
                occurred_at=_NOW + timedelta(minutes=4),
            )
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_learning_artifacts
            WHERE user_id = %s AND title = %s
            """,
            (scope["user_id"], protected),
        ).fetchone() == {"count": 0}


def test_action_cas_and_idempotency_delegate_once() -> None:
    with connect() as conn:
        scope, session = _open_scope(conn)
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        created = repository.create_artifact(
            _create_request(scope, session),
            creation_key="teaching:action",
            occurred_at=_NOW,
        )
        calls = 0

        def cancel(artifact: TutorPublicArtifactItem) -> ArtifactMutation:
            nonlocal calls
            calls += 1
            return _cancel_mutation(artifact)

        request = _cancel_request(
            scope,
            session,
            client_action_id="artifact-cancel-1",
            expected_version=1,
        )
        cancelled = repository.apply_action(
            artifact_id=created.artifact.id,
            request=request,
            owner_callback=cancel,
            occurred_at=_NOW + timedelta(minutes=1),
        )
        assert cancelled.artifact.state is TutorArtifactState.CANCELLED
        assert cancelled.artifact.version == 2
        assert cancelled.owner_callback_invoked is True
        assert calls == 1

        replay = repository.apply_action(
            artifact_id=created.artifact.id,
            request=request,
            owner_callback=cancel,
            occurred_at=_NOW + timedelta(minutes=2),
        )
        assert replay.idempotent_replayed is True
        assert replay.owner_callback_invoked is False
        assert replay.artifact.version == 2
        assert calls == 1

        conflicting = request.model_copy(update={"expected_artifact_version": 2})
        with pytest.raises(LearningArtifactIdempotencyConflict):
            repository.apply_action(
                artifact_id=created.artifact.id,
                request=conflicting,
                owner_callback=cancel,
                occurred_at=_NOW + timedelta(minutes=3),
            )
        with pytest.raises(LearningArtifactVersionConflict):
            repository.apply_action(
                artifact_id=created.artifact.id,
                request=_cancel_request(
                    scope,
                    session,
                    client_action_id="artifact-cancel-stale",
                    expected_version=1,
                ),
                owner_callback=cancel,
                occurred_at=_NOW + timedelta(minutes=4),
            )
        assert calls == 1
        assert conn.execute(
            """
            SELECT array_agg(event_sequence ORDER BY event_sequence) AS sequences
            FROM tutor_learning_artifact_events
            WHERE artifact_id = %s
            """,
            (created.artifact.id,),
        ).fetchone() == {"sequences": [1, 2]}
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE conversation_id = %s AND item_id = %s
            """,
            (scope["conversation_id"], created.artifact.id),
        ).fetchone() == {"count": 2}


class _FailAfterUpdateEventSink:
    def __init__(self, delegate: ArtifactConversationEventSink) -> None:
        self._delegate = delegate

    def append_item_reference(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        artifact_version: int,
        turn_id: str | None,
        kind: ArtifactConversationItemEventKind,
        occurred_at: datetime,
    ) -> object:
        result = self._delegate.append_item_reference(
            user_id=user_id,
            conversation_id=conversation_id,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            turn_id=turn_id,
            kind=kind,
            occurred_at=occurred_at,
        )
        if kind == "item_updated":
            raise RuntimeError("forced artifact conversation event failure")
        return result


def test_owner_callback_artifact_event_and_conversation_event_roll_back_together() -> (
    None
):
    with connect() as conn:
        scope, session = _open_scope(conn)
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=_FailAfterUpdateEventSink(
                PostgresTutorArtifactConversationEventSink(conn)
            ),
        )
        created = repository.create_artifact(
            _create_request(scope, session),
            creation_key="teaching:rollback",
            occurred_at=_NOW,
        )
        original_name = conn.execute(
            "SELECT display_name FROM users WHERE id = %s",
            (scope["user_id"],),
        ).fetchone()
        assert original_name is not None
        conn.commit()

        def mutate_owner(artifact: TutorPublicArtifactItem) -> ArtifactMutation:
            conn.execute(
                "UPDATE users SET display_name = %s WHERE id = %s",
                ("should-roll-back", scope["user_id"]),
            )
            return _cancel_mutation(artifact)

        with pytest.raises(
            RuntimeError, match="forced artifact conversation event failure"
        ):
            repository.apply_action(
                artifact_id=created.artifact.id,
                request=_cancel_request(
                    scope,
                    session,
                    client_action_id="artifact-rollback-1",
                    expected_version=1,
                ),
                owner_callback=mutate_owner,
                occurred_at=_NOW + timedelta(minutes=1),
            )

        assert conn.execute(
            "SELECT version, state FROM tutor_learning_artifacts WHERE id = %s",
            (created.artifact.id,),
        ).fetchone() == {"version": 1, "state": "active"}
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_artifact_events WHERE artifact_id = %s",
            (created.artifact.id,),
        ).fetchone() == {"count": 1}
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE conversation_id = %s AND item_id = %s
            """,
            (scope["conversation_id"], created.artifact.id),
        ).fetchone() == {"count": 1}
        assert (
            conn.execute(
                "SELECT display_name FROM users WHERE id = %s",
                (scope["user_id"],),
            ).fetchone()
            == original_name
        )


class _CancellingTeachingAdapter:
    owner_kind = TutorArtifactOwnerKind.TEACHING_PRACTICE

    def __init__(self) -> None:
        self.calls = 0
        self.connections: list[Connection[dict[str, object]]] = []

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation:
        assert request.action.action == "cancel"
        self.calls += 1
        self.connections.append(conn)
        return _cancel_mutation(artifact)


def test_service_is_read_only_when_disabled_and_registry_has_no_fallback() -> None:
    with connect() as conn:
        scope, session = _open_scope(conn)
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        created = repository.create_artifact(
            _create_request(scope, session),
            creation_key="teaching:service",
            occurred_at=_NOW,
        )
        disabled = LearningArtifactService(
            conn,
            repository=repository,
            enabled=lambda: False,
        )
        assert (
            disabled.read_artifact(
                user_id=str(scope["user_id"]),
                conversation_id=str(scope["conversation_id"]),
                artifact_id=created.artifact.id,
            )
            == created.artifact
        )
        with pytest.raises(LearningArtifactServiceError) as feature_off:
            disabled.act(
                artifact_id=created.artifact.id,
                request=_cancel_request(
                    scope,
                    session,
                    client_action_id="artifact-disabled-1",
                    expected_version=1,
                ),
            )
        assert feature_off.value.code == "LEARNING_ARTIFACT_DISABLED"
        assert conn.execute(
            "SELECT version FROM tutor_learning_artifacts WHERE id = %s",
            (created.artifact.id,),
        ).fetchone() == {"version": 1}

        missing = LearningArtifactService(
            conn,
            repository=repository,
            enabled=lambda: True,
        )
        with pytest.raises(LearningArtifactServiceError) as unavailable:
            missing.act(
                artifact_id=created.artifact.id,
                request=_cancel_request(
                    scope,
                    session,
                    client_action_id="artifact-missing-owner-1",
                    expected_version=1,
                ),
            )
        assert unavailable.value.code == "LEARNING_ARTIFACT_OWNER_UNAVAILABLE"

        adapter = _CancellingTeachingAdapter()
        enabled = LearningArtifactService(
            conn,
            repository=repository,
            owner_adapters=ArtifactOwnerAdapterRegistry((adapter,)),
            enabled=lambda: True,
            clock=lambda: _NOW + timedelta(minutes=1),
        )
        request = _cancel_request(
            scope,
            session,
            client_action_id="artifact-service-cancel-1",
            expected_version=1,
        )
        result = enabled.act(
            artifact_id=created.artifact.id,
            request=request,
        )
        replay = enabled.act(
            artifact_id=created.artifact.id,
            request=request,
        )
        assert result.artifact.state is TutorArtifactState.CANCELLED
        assert replay.idempotent_replayed is True
        assert adapter.calls == 1
        assert adapter.connections == [conn]

        with pytest.raises(ValueError, match="duplicate artifact owner adapter"):
            ArtifactOwnerAdapterRegistry((adapter, adapter))
