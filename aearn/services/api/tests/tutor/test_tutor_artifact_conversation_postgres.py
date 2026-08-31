from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.services.learning.artifacts.contracts import (
    ARTIFACT_PROTECTED_MARKERS,
    TutorArtifactCreate,
    TutorArtifactState,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.owner_adapters import ArtifactMutation
from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionRepository
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_api import TutorPublicService
from tests.support.teaching_session_support import (
    connection,
    create_teaching_scope,
    database_available,
)

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")


def _create_request(
    *,
    scope: dict[str, str | int],
    session: dict[str, object],
    turn_id: str | None,
) -> TutorArtifactCreate:
    checkpoint_id = str(session["checkpoint_id"])
    session_version = int(session["session_version"])
    return TutorArtifactCreate.model_validate(
        {
            "user_id": str(scope["user_id"]),
            "conversation_id": str(scope["conversation_id"]),
            "turn_id": turn_id,
            "learning_track_id": str(scope["track_id"]),
            "knowledge_key": str(scope["knowledge_key"]),
            "teaching_session_id": str(session["session_id"]),
            "checkpoint_id": checkpoint_id,
            "track_version": int(scope["track_version"]),
            "progress_version": int(scope["progress_version"]),
            "assignment_version": int(scope["assignment_version"]),
            "owner_kind": "teaching_practice",
            "owner_id": checkpoint_id,
            "owner_version": session_version,
            "owner_context_version": session_version,
            "artifact_kind": "knowledge_check",
            "purpose": "knowledge_check",
            "state": "active",
            "blocking": True,
            "title": "变量赋值检查",
            "instruction_markdown": "选择赋值后变量的值。",
            "difficulty": "D1",
            "presentation": {
                "type": "knowledge_check_v1",
                "response_kind": "single_select",
                "prompt_markdown": "执行 value = 2 后，value 是多少？",
                "options": [
                    {"value": "2", "label": "2"},
                    {"value": "3", "label": "3"},
                ],
                "minimum_selections": 1,
                "maximum_selections": 1,
                "maximum_text_length": 2_000,
            },
            "allowed_actions": ["respond"],
            "source_references": [
                {
                    "kind": "teaching_checkpoint",
                    "reference_id": checkpoint_id,
                    "reference_version": session_version,
                    "content_hash": None,
                    "label": "当前教学检查点",
                }
            ],
            "active_attempt": None,
        }
    )


def test_artifact_snapshot_history_and_sse_recover_from_safe_item_references() -> None:
    with connection() as conn:
        scope = create_teaching_scope(conn)
        teaching = TeachingSessionRepository(conn)
        with conn.transaction():
            authority = teaching.resolve_authority(
                user_id=str(scope["user_id"]),
                track_id=str(scope["track_id"]),
                knowledge_key=str(scope["knowledge_key"]),
                conversation_id=str(scope["conversation_id"]),
                for_update=True,
            )
            session_row, created_session = teaching.open_or_resume(
                authority=authority,
                mode=TeachingSessionMode.GUIDED,
            )
        assert created_session is True
        session = teaching.project_session(session_row)
        assert isinstance(session, dict)

        public = TutorPublicService(conn)
        before = public.read_conversation_snapshot(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            limit=40,
            cursor=None,
        )
        assert before["snapshot_version"] == "tutor_conversation_snapshot_v3"
        assert "active_artifact" not in before

        artifacts = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        created_at = datetime.now(UTC)
        created = artifacts.create_artifact(
            _create_request(
                scope=scope,
                session=session,
                turn_id=None,
            ),
            creation_key="artifact-conversation-projection",
            occurred_at=created_at,
        )

        conversation_activity = conn.execute(
            "SELECT last_public_activity_at FROM tutor_conversations WHERE id = %s",
            (str(scope["conversation_id"]),),
        ).fetchone()
        assert conversation_activity is not None
        assert conversation_activity["last_public_activity_at"] >= created_at

        conversations = public.list_conversations(
            user_id=str(scope["user_id"]),
            limit=40,
            cursor=None,
        )
        assert any(
            item["conversation_id"] == str(scope["conversation_id"])
            for item in conversations["items"]
        )

        after_create = public.read_conversation_snapshot(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            limit=40,
            cursor=None,
        )
        timeline_artifact = next(
            item for item in after_create["timeline"] if item["kind"] == "artifact"
        )
        assert after_create["snapshot_version"] == "tutor_conversation_snapshot_v4"
        assert after_create["active_artifact"] == timeline_artifact
        assert timeline_artifact["id"] == created.artifact.id
        assert timeline_artifact["turn_id"] is None
        assert timeline_artifact["source_references"] == [
            {
                "kind": "teaching_checkpoint",
                "reference_id": str(session["checkpoint_id"]),
                "reference_version": int(session["session_version"]),
                "content_hash": None,
                "label": "当前教学检查点",
            }
        ]

        history = public.read_conversation_history(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            limit=40,
            cursor=None,
        )
        history_artifact = next(
            item for item in history["items"] if item["kind"] == "artifact"
        )
        assert history_artifact == timeline_artifact

        added_events = public.replay_conversation_events(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            cursor=str(before["stream_cursor"]),
        )
        added = next(event for event in added_events if event.event_type == "item_added")
        assert added.data["item_id"] == created.artifact.id
        assert added.data["item_kind"] == "artifact"
        assert added.data["payload"] == {
            "item": {
                "item_id": created.artifact.id,
                "item_kind": "artifact",
            }
        }
        added_serialized = json.dumps(added.data, ensure_ascii=False, sort_keys=True)
        for protected in (
            *ARTIFACT_PROTECTED_MARKERS,
            "instruction_markdown",
            "presentation",
            "allowed_actions",
            "source_references",
        ):
            assert protected not in added_serialized

        activity_before_replay = conn.execute(
            "SELECT last_public_activity_at FROM tutor_conversations WHERE id = %s",
            (str(scope["conversation_id"]),),
        ).fetchone()
        assert activity_before_replay is not None
        replayed_reference = PostgresTutorRepository(conn).append_artifact_item_reference(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=created.artifact.id,
            artifact_version=1,
            turn_id=None,
            kind="item_added",
            occurred_at=created_at + timedelta(seconds=30),
        )
        assert replayed_reference.event_id == added.data["event_id"]
        activity_after_replay = conn.execute(
            "SELECT last_public_activity_at FROM tutor_conversations WHERE id = %s",
            (str(scope["conversation_id"]),),
        ).fetchone()
        assert activity_after_replay == activity_before_replay

        terminal_at = created_at + timedelta(seconds=1)
        updated = artifacts.apply_owner_update(
            artifact_id=created.artifact.id,
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=str(session["session_id"]),
            expected_artifact_version=1,
            event_key="artifact-conversation-terminal",
            event_kind="terminal",
            mutation=ArtifactMutation(
                state=TutorArtifactState.COMPLETED,
                owner_version=int(session["session_version"]),
                owner_context_version=int(session["session_version"]),
                presentation=created.artifact.presentation,
                allowed_actions=(),
                active_attempt=None,
                safe_event_payload={"outcome": "completed"},
            ),
            occurred_at=terminal_at,
        )
        assert updated.artifact.version == 2
        terminal_activity = conn.execute(
            "SELECT last_public_activity_at FROM tutor_conversations WHERE id = %s",
            (str(scope["conversation_id"]),),
        ).fetchone()
        assert terminal_activity is not None
        assert terminal_activity["last_public_activity_at"] >= terminal_at

        updated_events = public.replay_conversation_events(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            cursor=added.cursor,
        )
        item_updated = next(
            event for event in updated_events if event.event_type == "item_updated"
        )
        assert item_updated.data["payload"] == {
            "item": {
                "item_id": created.artifact.id,
                "item_kind": "artifact",
            }
        }

        recovered = public.read_conversation_snapshot(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            limit=40,
            cursor=None,
        )
        recovered_artifact = next(
            item for item in recovered["timeline"] if item["kind"] == "artifact"
        )
        assert recovered["active_artifact"] is None
        assert recovered_artifact["state"] == "completed"
        assert recovered_artifact["version"] == 2

        projection_versions = {
            str(row["projection_version"])
            for row in conn.execute(
                """
                SELECT projection_version
                FROM tutor_conversation_events
                WHERE conversation_id = %s AND item_id = %s
                """,
                (str(scope["conversation_id"]), created.artifact.id),
            ).fetchall()
        }
        assert projection_versions == {"tutor_conversation_event_v3"}
