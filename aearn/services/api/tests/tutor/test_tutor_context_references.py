from __future__ import annotations

from collections.abc import Iterator, Mapping
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
import app.services.learning.lesson_authoring as lesson_authoring
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.grounding.grounding_index_repository import run_and_persist_fixture_grounding_reindex
from app.services.tutor.interactive import PostgresTutorContextLoader, PostgresTutorLearningContextLoader
from app.services.tutor.learner_state import TutorLearnerStateRepository
from app.services.tutor.persistence import PostgresTutorRepository
from tests.support.learning_track_support import sample_plan_payload
from tests.learning.test_lesson_document_authoring import FakeLessonAuthor
from tests.support.tutor_public_api_support import action_payload, assert_error, create_tutor_user, terminal_dispatcher, waiting_dispatcher


@pytest.fixture()
def reference_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    bootstrap_database()
    with connect() as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        conn.commit()
    monkeypatch.setattr(
        lesson_authoring,
        "LESSON_AUTHOR_FACTORY",
        lambda: FakeLessonAuthor(personalized_title="Python 变量：上下文引用版"),
    )
    with TestClient(app) as client:
        yield client


def _create_ready_lesson(client: TestClient, *, user_id: str) -> tuple[str, dict[str, object]]:
    created = client.post(
        "/api/learning-tracks",
        json={
            "user_id": user_id,
            "client_action_id": f"reference-track-{uuid4()}",
            "language_id": "python",
            "goal_text": "Learn Python variables with scoped Tutor references",
            "target_level": "beginner",
            "plan": sample_plan_payload(),
        },
    )
    assert created.status_code == 201
    track_id = str(created.json()["track"]["track_id"])
    path = f"/api/learning-tracks/{track_id}/lessons/python.variables"
    prepared = client.post(
        f"{path}/prepare",
        json={
            "user_id": user_id,
            "client_action_id": f"reference-lesson-{uuid4()}",
            "expected_track_version": 1,
            "expected_progress_version": 1,
        },
    )
    assert prepared.status_code == 202
    ready = client.get(f"{path}?user_id={user_id}")
    assert ready.status_code == 200
    body = ready.json()
    assert body["status"] == "ready"
    return track_id, body


def _lesson_reference(track_id: str, lesson: Mapping[str, object]) -> dict[str, object]:
    assignment = lesson["assignment"]
    document = lesson["document"]
    assert isinstance(assignment, Mapping)
    assert isinstance(document, Mapping)
    blocks = document["blocks"]
    assert isinstance(blocks, list)
    concept = next(item for item in blocks if isinstance(item, dict) and item.get("block_id") == "concept")
    title = str(concept["title"])
    paragraphs = concept["paragraphs"]
    assert isinstance(paragraphs, list)
    canonical = " ".join("\n".join((title, *(str(item) for item in paragraphs))).split())
    excerpt = "自动化目标"
    start = canonical.index(excerpt)
    return {
        "kind": "lesson_selection",
        "learning_track_id": track_id,
        "knowledge_key": "python.variables",
        "document_id": str(assignment["document_id"]),
        "document_content_hash": str(document["content_hash"]),
        "block_id": "concept",
        "start_offset": start,
        "end_offset": start + len(excerpt),
        "excerpt": excerpt,
    }


def _scope(track_id: str) -> dict[str, object]:
    return {
        "scope_kind": "learning_track",
        "learning_track_id": track_id,
        "task_kind": "lesson_teaching",
        "knowledge_key": "python.variables",
    }


def test_lesson_selection_reference_is_atomic_replayable_and_injected_as_structured_context(
    monkeypatch: pytest.MonkeyPatch,
    reference_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="我会结合你引用的课程片段回答。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(reference_client)["id"])
    track_id, lesson = _create_ready_lesson(reference_client, user_id=user_id)
    reference = _lesson_reference(track_id, lesson)
    request_body = action_payload(
        user_id,
        f"lesson-selection-{uuid4()}",
        content="请解释这段内容为什么重要。",
        learning_scope=_scope(track_id),
        context_references=[reference],
    )

    accepted = reference_client.post("/api/tutor/conversations/first-turn", json=request_body)
    assert accepted.status_code == 202
    body = accepted.json()
    saved = body["context_references"]
    assert len(saved) == 1
    assert saved[0]["kind"] == "lesson_selection"
    assert saved[0]["safe_excerpt"] == reference["excerpt"]
    assert "excerpt" not in saved[0]
    assert isinstance(saved[0]["reference_id"], str)

    replay = reference_client.post("/api/tutor/conversations/first-turn", json=request_body)
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["context_references"] == saved

    conversation_id = str(body["conversation_id"])
    resolved = reference_client.post(
        f"/api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve",
        json={
            "user_id": user_id,
            "knowledge_key": "python.variables",
            "source": {
                "kind": "context_reference",
                "reference_id": saved[0]["reference_id"],
            },
        },
    )
    assert resolved.status_code == 200
    resolved_body = resolved.json()
    assert resolved_body["schema_version"] == "lesson_document_reference_v1"
    assert resolved_body["source_kind"] == "context_reference"
    assert resolved_body["reference_status"] == "current"
    assert resolved_body["target"]["block_id"] == reference["block_id"]
    assert resolved_body["target"]["safe_excerpt"] == reference["excerpt"]
    assert resolved_body["document"]["content_hash"] == reference["document_content_hash"]
    assert resolved_body["sources"]

    other_user = str(create_tutor_user(reference_client)["id"])
    cross_user = reference_client.post(
        f"/api/learning-tracks/{track_id}/lesson-references/{conversation_id}/resolve",
        json={
            "user_id": other_user,
            "knowledge_key": "python.variables",
            "source": {
                "kind": "context_reference",
                "reference_id": saved[0]["reference_id"],
            },
        },
    )
    assert_error(cross_user, "DOCUMENT_REFERENCE_NOT_FOUND", 404)

    history = reference_client.get(
        f"/api/tutor/conversations/{conversation_id}/history?user_id={user_id}&limit=40"
    )
    assert history.status_code == 200
    learner = next(item for item in history.json()["items"] if item.get("role") == "learner")
    assert learner["content"] == "请解释这段内容为什么重要。"
    assert learner["context_references"] == saved

    run_id = str(body["run_id"])
    with connect() as conn:
        row = conn.execute(
            """
            SELECT refs.run_id::text, refs.message_id::text, refs.input_revision,
                   messages.content, refs.safe_payload_json::text AS safe_payload_text
            FROM tutor_message_context_references AS refs
            JOIN tutor_messages AS messages ON messages.id = refs.message_id
            WHERE refs.user_id = %s AND refs.run_id = %s
            """,
            (user_id, run_id),
        ).fetchone()
        assert row is not None
        assert row["content"] == "请解释这段内容为什么重要。"
        assert "请解释这段内容为什么重要" not in str(row["safe_payload_text"])
        assert conn.execute(
            "SELECT count(*) AS count FROM tutor_message_context_references WHERE run_id = %s",
            (run_id,),
        ).fetchone() == {"count": 1}

        repository = PostgresTutorRepository(conn)
        snapshot = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert snapshot is not None
        base_loader = PostgresTutorContextLoader(
            conn=conn,
            learner_state=TutorLearnerStateRepository(conn),
        )
        context = PostgresTutorLearningContextLoader(conn=conn, base_loader=base_loader).load_context(
            snapshot,
            input_revision=int(body["input_revision"]),
        )
        source = next(item for item in context.required_facts if item.source_id.startswith("context-reference:"))
        assert isinstance(source.content, dict)
        assert source.content["kind"] == "lesson_selection"
        assert source.content["safe_excerpt"] == reference["excerpt"]
        assert context.current_input is not None
        assert context.current_input.content == "请解释这段内容为什么重要。"

        with pytest.raises(Exception, match="append-only"):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_message_context_references SET reference_index = 1 WHERE run_id = %s",
                    (run_id,),
                )


def test_teaching_session_message_reference_uses_exact_session_and_message_authority(
    monkeypatch: pytest.MonkeyPatch,
    reference_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = terminal_dispatcher(
        settings=tutor_api_settings,
        message="已完成当前自由阅读问题。",
        public_thinking_text="",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(reference_client)["id"])
    track_id, lesson = _create_ready_lesson(reference_client, user_id=user_id)
    assignment = lesson["assignment"]
    assert isinstance(assignment, Mapping)

    conversation = reference_client.post(
        "/api/tutor/conversations",
        json=action_payload(
            user_id,
            f"history-reference-conversation-{uuid4()}",
            learning_scope={"scope_kind": "learning_track", "learning_track_id": track_id},
        ),
    )
    assert conversation.status_code in {200, 201}
    conversation_id = str(conversation.json()["conversation_id"])
    opened = reference_client.post(
        f"/api/learning-tracks/{track_id}/teaching-sessions/python.variables/open",
        json=action_payload(
            user_id,
            f"history-reference-session-{uuid4()}",
            conversation_id=conversation_id,
            expected_track_version=1,
            expected_progress_version=1,
            expected_assignment_version=int(assignment["assignment_version"]),
            mode="free_reading",
        ),
    )
    assert opened.status_code == 201
    session_id = str(opened.json()["teaching_session"]["session_id"])

    source = reference_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            f"history-reference-source-{uuid4()}",
            content="请先说明变量绑定。",
            learning_scope=_scope(track_id),
        ),
    )
    assert source.status_code == 202
    source_message_id = str(source.json()["message_id"])

    reference = {
        "kind": "teaching_session_message",
        "learning_track_id": track_id,
        "knowledge_key": "python.variables",
        "teaching_session_id": session_id,
        "message_id": source_message_id,
    }
    accepted = reference_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            f"history-reference-use-{uuid4()}",
            content="沿用上一条消息的上下文继续解释。",
            learning_scope=_scope(track_id),
            context_references=[reference],
        ),
    )
    assert accepted.status_code == 202
    saved = accepted.json()["context_references"]
    assert len(saved) == 1
    assert saved[0]["kind"] == "teaching_session_message"
    assert saved[0]["teaching_session_id"] == session_id
    assert saved[0]["message_id"] == source_message_id
    assert saved[0]["turn_id"] == source.json()["run_id"]
    assert saved[0]["role"] == "learner"
    assert saved[0]["message_summary"] == "历史提问（exact session/message reference）"
    assert "content" not in saved[0]
    assert "请先说明变量绑定" not in str(saved[0])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        snapshot = repository.load_snapshot(user_id=user_id, run_id=str(accepted.json()["run_id"]))
        assert snapshot is not None
        base_loader = PostgresTutorContextLoader(
            conn=conn,
            learner_state=TutorLearnerStateRepository(conn),
        )
        context = PostgresTutorLearningContextLoader(conn=conn, base_loader=base_loader).load_context(
            snapshot,
            input_revision=int(accepted.json()["input_revision"]),
        )
        source_fact = next(item for item in context.required_facts if item.source_id.startswith("context-reference:"))
        assert isinstance(source_fact.content, dict)
        assert source_fact.content["message_content"] == "请先说明变量绑定。"

    rejected = reference_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            f"history-reference-stale-{uuid4()}",
            content="这次引用必须 fail closed。",
            learning_scope=_scope(track_id),
            context_references=[{**reference, "teaching_session_id": str(uuid4())}],
        ),
    )
    assert_error(rejected, "CONTEXT_REFERENCE_NOT_FOUND", 404)


def test_stale_reference_rolls_back_the_entire_first_turn(
    monkeypatch: pytest.MonkeyPatch,
    reference_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="不会执行到这里。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(reference_client)["id"])
    track_id, lesson = _create_ready_lesson(reference_client, user_id=user_id)
    reference = _lesson_reference(track_id, lesson)
    reference["document_content_hash"] = "f" * 64

    with connect() as conn:
        before = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM tutor_conversations WHERE user_id = %s) AS conversations,
              (SELECT count(*) FROM tutor_runs WHERE user_id = %s) AS runs,
              (SELECT count(*) FROM tutor_messages WHERE conversation_id IN (
                 SELECT id FROM tutor_conversations WHERE user_id = %s
              )) AS messages,
              (SELECT count(*) FROM tutor_message_context_references WHERE user_id = %s) AS references
            """,
            (user_id, user_id, user_id, user_id),
        ).fetchone()
    assert before is not None

    rejected = reference_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(
            user_id,
            f"stale-reference-{uuid4()}",
            content="这条消息必须和失效引用一起回滚。",
            learning_scope=_scope(track_id),
            context_references=[reference],
        ),
    )
    assert_error(rejected, "CONTEXT_REFERENCE_STALE", 409)

    with connect() as conn:
        after = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM tutor_conversations WHERE user_id = %s) AS conversations,
              (SELECT count(*) FROM tutor_runs WHERE user_id = %s) AS runs,
              (SELECT count(*) FROM tutor_messages WHERE conversation_id IN (
                 SELECT id FROM tutor_conversations WHERE user_id = %s
              )) AS messages,
              (SELECT count(*) FROM tutor_message_context_references WHERE user_id = %s) AS references
            """,
            (user_id, user_id, user_id, user_id),
        ).fetchone()
    assert after == before


def test_context_reference_input_rejects_unknown_fields(reference_client: TestClient) -> None:
    user_id = str(create_tutor_user(reference_client)["id"])
    response = reference_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(
            user_id,
            f"invalid-reference-shape-{uuid4()}",
            content="引用输入必须严格。",
            context_references=[
                {
                    "kind": "exercise_feedback",
                    "learning_track_id": str(uuid4()),
                    "knowledge_key": "python.variables",
                    "attempt_id": str(uuid4()),
                    "raw_submission": "绝不能接受该字段",
                }
            ],
        ),
    )
    assert_error(response, "VALIDATION_ERROR", 400)
