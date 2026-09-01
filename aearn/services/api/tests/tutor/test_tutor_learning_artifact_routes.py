from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Mapping
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection

import app.routes.learning_artifacts as artifact_routes
from app.agents.harness.contracts import TutorProviderResult, TutorTerminalOutcome
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.learning.artifacts.contracts import (
    ARTIFACT_PROTECTED_MARKERS,
    TutorArtifactActionKind,
    TutorArtifactActionRequest,
    TutorArtifactAttemptSummaryV1,
    TutorArtifactCreate,
    TutorArtifactKind,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactOwnerKind,
    TutorArtifactPurpose,
    TutorArtifactState,
    TutorPublicArtifactItem,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.owner_adapters import (
    ArtifactMutation,
    ArtifactOwnerAdapterRegistry,
    ArtifactOwnerUnavailable,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactVersionConflict,
    PostgresLearningArtifactRepository,
)
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_candidates import project_teaching_provider_context
from app.services.learning.teaching_sessions import (
    TeachingSessionRepository,
    TeachingSessionService,
)
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.ports import SequenceTutorProvider
from app.services.repositories.local_user_data_repository import reset_user_data
from tests.support.teaching_session_support import (
    connection as teaching_connection,
    create_teaching_scope,
    database_available,
)


pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)
_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
_PRIVATE_SUBMISSION = ARTIFACT_PROTECTED_MARKERS[0]


@dataclass(frozen=True, slots=True)
class _ArtifactRouteFixture:
    user_id: str
    conversation_id: str
    learning_track_id: str
    teaching_session_id: str
    artifact_id: str
    attempt_id: str


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_artifact_routes() -> None:
    bootstrap_database()


@pytest.fixture
def artifact_route_fixture() -> _ArtifactRouteFixture:
    with teaching_connection() as conn:
        fixture = _seed_artifact_route_fixture(conn)
        conn.commit()
    try:
        yield fixture
    finally:
        with teaching_connection() as conn:
            reset_user_data(conn, fixture.user_id)
            conn.commit()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed_artifact_route_fixture(
    conn: Connection[dict[str, object]],
    *,
    allowed_actions: tuple[TutorArtifactActionKind, ...] = (
        TutorArtifactActionKind.CANCEL,
    ),
) -> _ArtifactRouteFixture:
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
        idempotency_key=f"artifact-route-open:{uuid4()}",
    )
    session = opened["teaching_session"]
    assert isinstance(session, Mapping)
    repository = PostgresLearningArtifactRepository(
        conn,
        conversation_events=PostgresTutorArtifactConversationEventSink(conn),
    )
    created = repository.create_artifact(
        TutorArtifactCreate(
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
            blocking=False,
            title="变量绑定检查",
            instruction_markdown="请说明赋值后名称与值的关系。",
            presentation=TutorArtifactKnowledgeCheckPresentationV1(
                response_kind="short_text",
                prompt_markdown="执行 count = 3 后，count 表示什么？",
                maximum_text_length=400,
            ),
            allowed_actions=allowed_actions,
        ),
        creation_key=f"artifact-route:{uuid4()}",
        occurred_at=_NOW,
    )
    attempt_id = _seed_terminal_attempt(
        conn,
        scope=scope,
        artifact_id=created.artifact.id,
    )
    return _ArtifactRouteFixture(
        user_id=str(scope["user_id"]),
        conversation_id=str(scope["conversation_id"]),
        learning_track_id=str(scope["track_id"]),
        teaching_session_id=str(session["session_id"]),
        artifact_id=created.artifact.id,
        attempt_id=attempt_id,
    )


def _seed_terminal_attempt(
    conn: Connection[dict[str, object]],
    *,
    scope: Mapping[str, object],
    artifact_id: str,
) -> str:
    suffix = uuid4().hex
    revision = conn.execute(
        "SELECT revision_id FROM tutor_track_active_plans WHERE track_id = %s",
        (scope["track_id"],),
    ).fetchone()
    assert revision is not None
    exercise = conn.execute(
        """
        INSERT INTO tutor_exercise_versions (
          language_id, exercise_key, exercise_type, version, source_kind, title,
          learner_prompt_json, starter_artifact_json, required_capabilities_json,
          runtime_profile_key, execution_required, public_feedback_policy_version,
          validation_status, content_hash, published_at
        ) VALUES (
          'python', %s, 'static_code_reasoning', 'v1', 'curated_fixture',
          'Artifact route exercise', %s::jsonb, %s::jsonb, %s::jsonb,
          NULL, false, 'artifact-route-v1', 'ready', %s, now()
        ) RETURNING id
        """,
        (
            f"artifact.route.{suffix}",
            json.dumps({"text": "Explain the visible behavior."}),
            json.dumps({"content": ""}),
            json.dumps(["python.variables"]),
            _hash(f"exercise:{suffix}"),
        ),
    ).fetchone()
    assert exercise is not None
    gate_key = f"artifact.route.gate.{suffix}"
    slot = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_slots (
          document_id, user_id, track_id, knowledge_key, block_id, gate_key,
          gate_kind, assessment_contract_version, required_capabilities_json,
          learner_prompt_hash, learner_prompt
        ) VALUES (
          %s, %s, %s, %s, %s, %s, 'knowledge_check',
          'artifact-route-v1', %s::jsonb, %s, 'Explain the visible behavior.'
        ) RETURNING id
        """,
        (
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            f"artifact.route.block.{suffix}",
            gate_key,
            json.dumps(["python.variables"]),
            _hash(f"prompt:{suffix}"),
        ),
    ).fetchone()
    assert slot is not None
    binding = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_bindings (
          slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
          exercise_version_id, requirement_kind, pass_policy_version, pass_threshold,
          execution_requirement, slot_contract_hash, binding_contract_hash, published_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s, 'recommended',
          'artifact-route-v1', 0.8, 'forbidden', %s, %s, now()
        ) RETURNING id
        """,
        (
            slot["id"],
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            gate_key,
            exercise["id"],
            _hash(f"slot:{suffix}"),
            _hash(f"binding:{suffix}"),
        ),
    ).fetchone()
    assert binding is not None
    attempt = conn.execute(
        """
        INSERT INTO tutor_exercise_attempts (
          attempt_type, user_id, track_id, plan_revision_id, expected_track_version,
          expected_progress_version, knowledge_key, lesson_assignment_id, document_id,
          gate_binding_id, exercise_version_id, submission_hash, hint_state_hash,
          independence, idempotency_key, request_hash, accepted_at
        ) VALUES (
          'run', %s, %s, %s, 1, 1, %s, %s, %s, %s, %s,
          %s, %s, 'independent', %s, %s, %s
        ) RETURNING id
        """,
        (
            scope["user_id"],
            scope["track_id"],
            revision["revision_id"],
            scope["knowledge_key"],
            scope["assignment_id"],
            scope["document_id"],
            binding["id"],
            exercise["id"],
            _hash(_PRIVATE_SUBMISSION),
            _hash(f"hint:{suffix}"),
            f"artifact-route-attempt:{suffix}",
            _hash(f"request:{suffix}"),
            _NOW,
        ),
    ).fetchone()
    assert attempt is not None
    attempt_id = str(attempt["id"])
    conn.execute(
        """
        INSERT INTO tutor_exercise_attempt_submissions (
          attempt_id, user_id, exercise_version_id, submission_kind,
          content_text, content_hash
        ) VALUES (%s, %s, %s, 'code', %s, %s)
        """,
        (
            attempt_id,
            scope["user_id"],
            exercise["id"],
            _PRIVATE_SUBMISSION,
            _hash(_PRIVATE_SUBMISSION),
        ),
    )
    conn.execute(
        """
        INSERT INTO tutor_exercise_attempt_results (
          attempt_id, user_id, outcome, score, safe_feedback_json,
          capability_scores_json, policy_version, result_hash, terminal_at
        ) VALUES (%s, %s, 'passed', 1.0, %s::jsonb, %s::jsonb, %s, %s, %s)
        """,
        (
            attempt_id,
            scope["user_id"],
            json.dumps(
                {
                    "status": "static_evaluated",
                    "message": "回答符合当前检查要求。",
                    "execution_claim": "not_run",
                }
            ),
            json.dumps({"python.variables": 1.0}),
            "artifact_route_policy_v1",
            _hash(f"result:{suffix}"),
            _NOW,
        ),
    )
    conn.execute(
        """
        INSERT INTO tutor_learning_artifact_attempt_links (
          artifact_id, user_id, conversation_id, teaching_session_id,
          learning_track_id, attempt_id, artifact_version, created_at
        )
        SELECT id, user_id, conversation_id, teaching_session_id,
               learning_track_id, %s, version, %s
        FROM tutor_learning_artifacts
        WHERE id = %s
        """,
        (attempt_id, _NOW, artifact_id),
    )
    return attempt_id


def _configure_artifact_routes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    enabled: bool,
    adapters: ArtifactOwnerAdapterRegistry | None = None,
) -> None:
    settings = Settings(
        llm_type="disabled",
        tutor_learning_artifacts_enabled=enabled,
        tutor_thread_turn_v2_enabled=True,
    )
    monkeypatch.setattr(artifact_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(
        artifact_routes,
        "runtime_gate_error",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        artifact_routes,
        "thread_turn_v2_gate_error",
        lambda **_kwargs: None,
    )
    if adapters is not None:
        monkeypatch.setattr(
            artifact_routes,
            "build_learning_artifact_owner_adapters",
            lambda: adapters,
        )


def _action_payload(
    fixture: _ArtifactRouteFixture,
    *,
    client_action_id: str,
    expected_version: int,
) -> dict[str, object]:
    return {
        "user_id": fixture.user_id,
        "learning_track_id": fixture.learning_track_id,
        "teaching_session_id": fixture.teaching_session_id,
        "client_action_id": client_action_id,
        "expected_artifact_version": expected_version,
        "action": {
            "action": "cancel",
            "reason": "learner_cancelled",
        },
    }


def _run_action_payload(
    fixture: _ArtifactRouteFixture,
    *,
    client_action_id: str,
    expected_version: int,
) -> dict[str, object]:
    return {
        "user_id": fixture.user_id,
        "learning_track_id": fixture.learning_track_id,
        "teaching_session_id": fixture.teaching_session_id,
        "client_action_id": client_action_id,
        "expected_artifact_version": expected_version,
        "action": {
            "action": "run",
            "submission": "print(1)",
        },
    }


def _assert_error(response, code: str, status_code: int) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["request_id"], str)
    assert isinstance(body["error"]["recoverable"], bool)


class _RunTeachingAdapter:
    owner_kind = TutorArtifactOwnerKind.TEACHING_PRACTICE

    def __init__(self, attempt_id: str) -> None:
        self._attempt_id = attempt_id
        self.calls = 0

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation:
        assert request.action.action == "run"
        self.calls += 1
        row = conn.execute(
            """
            SELECT attempts.id::text AS attempt_id, attempts.attempt_type,
                   attempts.accepted_at, results.outcome, results.score,
                   results.result_hash, results.terminal_at
            FROM tutor_exercise_attempts AS attempts
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id = attempts.id AND results.user_id = attempts.user_id
            WHERE attempts.id = %s AND attempts.user_id = %s
            """,
            (self._attempt_id, request.user_id),
        ).fetchone()
        assert row is not None
        terminal = row.get("outcome") is not None
        attempt = TutorArtifactAttemptSummaryV1(
            attempt_id=str(row["attempt_id"]),
            attempt_type=str(row["attempt_type"]),  # type: ignore[arg-type]
            status="terminal" if terminal else "pending",
            outcome=str(row["outcome"]) if terminal else None,  # type: ignore[arg-type]
            score=float(str(row["score"])) if terminal else None,
            result_hash=str(row["result_hash"]) if terminal else None,
            accepted_at=row["accepted_at"].astimezone(UTC).isoformat(),
            terminal_at=(
                row["terminal_at"].astimezone(UTC).isoformat() if terminal else None
            ),
        )
        return ArtifactMutation(
            state=(TutorArtifactState.ACTIVE if terminal else TutorArtifactState.RUNNING),
            owner_version=artifact.owner_version,
            owner_context_version=artifact.owner_version,
            presentation=artifact.presentation,
            allowed_actions=(TutorArtifactActionKind.RUN,),
            active_attempt=attempt,
            safe_event_payload={
                "attempt_id": attempt.attempt_id,
                "status": attempt.status,
            },
        )


class _CancellingTeachingAdapter:
    owner_kind = TutorArtifactOwnerKind.TEACHING_PRACTICE

    def __init__(self) -> None:
        self.calls = 0

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation:
        del conn
        assert request.action.action == "cancel"
        self.calls += 1
        return ArtifactMutation(
            state=TutorArtifactState.CANCELLED,
            owner_version=artifact.owner_version,
            owner_context_version=artifact.owner_version,
            presentation=artifact.presentation,
            allowed_actions=(),
            active_attempt=artifact.active_attempt,
            safe_event_payload={"reason": "learner_cancelled"},
        )


def test_learning_artifact_setting_defaults_off_and_reads_remain_available(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    monkeypatch.delenv("TUTOR_LEARNING_ARTIFACTS_ENABLED", raising=False)
    assert Settings().tutor_learning_artifacts_enabled is False
    monkeypatch.setenv("TUTOR_LEARNING_ARTIFACTS_ENABLED", "true")
    assert Settings().tutor_learning_artifacts_enabled is True
    monkeypatch.delenv("TUTOR_LEARNING_ARTIFACTS_ENABLED", raising=False)
    _configure_artifact_routes(monkeypatch, enabled=False)

    with TestClient(app) as client:
        artifact = client.get(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}",
            params={"user_id": artifact_route_fixture.user_id},
        )
        assert artifact.status_code == 200
        assert artifact.json()["id"] == artifact_route_fixture.artifact_id

        attempt = client.get(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}"
            f"/attempts/{artifact_route_fixture.attempt_id}",
            params={"user_id": artifact_route_fixture.user_id},
        )
        assert attempt.status_code == 200
        attempt_body = attempt.json()
        assert attempt_body["schema_version"] == "tutor_learning_artifact_attempt_v2"
        assert attempt_body["status"] == "terminal"
        assert attempt_body["result"]["outcome"] == "passed"
        assert attempt_body["result"]["execution_result"] is None
        assert "safe_feedback" not in attempt_body["result"]
        assert _PRIVATE_SUBMISSION not in json.dumps(attempt_body, ensure_ascii=False)

        disabled = client.post(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}/actions",
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="artifact-disabled",
                expected_version=1,
            ),
        )
        _assert_error(disabled, "LEARNING_ARTIFACT_DISABLED", 409)

        foreign = client.get(
            f"/api/tutor/conversations/{uuid4()}"
            f"/artifacts/{artifact_route_fixture.artifact_id}",
            params={"user_id": artifact_route_fixture.user_id},
        )
        _assert_error(foreign, "LEARNING_ARTIFACT_NOT_FOUND", 404)

    with connect() as conn:
        row = conn.execute(
            "SELECT version, state FROM tutor_learning_artifacts WHERE id = %s",
            (artifact_route_fixture.artifact_id,),
        ).fetchone()
    assert row == {"version": 1, "state": "active"}


def test_terminal_attempt_read_projects_one_result_and_dispatches_one_evaluation(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    _configure_artifact_routes(monkeypatch, enabled=True)
    dispatched_jobs: list[tuple[str, str]] = []

    def record_dispatch(job_id: str, *, runtime_kind: str) -> None:
        dispatched_jobs.append((job_id, runtime_kind))

    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        record_dispatch,
    )
    endpoint = (
        f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
        f"/artifacts/{artifact_route_fixture.artifact_id}"
        f"/attempts/{artifact_route_fixture.attempt_id}"
    )

    with TestClient(app) as client:
        first = client.get(
            endpoint,
            params={"user_id": artifact_route_fixture.user_id},
        )
        replay = client.get(
            endpoint,
            params={"user_id": artifact_route_fixture.user_id},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["status"] == "terminal"
    assert replay.json()["status"] == "terminal"
    assert first.json()["artifact_version"] == 2
    assert replay.json()["artifact_version"] == 2
    assert len(dispatched_jobs) == 1
    assert dispatched_jobs[0][1] == "harness_v1"

    with connect() as conn:
        result_artifacts = conn.execute(
            """
            SELECT id::text AS id, instruction_markdown, active_attempt_id::text AS attempt_id
            FROM tutor_learning_artifacts
            WHERE user_id = %s AND conversation_id = %s
              AND artifact_kind = 'test_result' AND purpose = 'result'
            """,
            (
                artifact_route_fixture.user_id,
                artifact_route_fixture.conversation_id,
            ),
        ).fetchall()
        assert len(result_artifacts) == 1
        assert result_artifacts[0]["attempt_id"] == artifact_route_fixture.attempt_id
        assert result_artifacts[0]["instruction_markdown"] == "**通过**：本次运行已完成。"
        intents = conn.execute(
            """
            SELECT id, state, consumed_run_id::text AS run_id, artifact_id::text AS artifact_id
            FROM tutor_continuation_intents
            WHERE user_id = %s AND conversation_id = %s
              AND idempotency_key LIKE %s
            """,
            (
                artifact_route_fixture.user_id,
                artifact_route_fixture.conversation_id,
                "result-evaluation:%",
            ),
        ).fetchall()
        assert len(intents) == 1
        assert intents[0]["state"] == "consumed"
        assert intents[0]["artifact_id"] == result_artifacts[0]["id"]
        run_id = str(intents[0]["run_id"])
        assert run_id
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
            (artifact_route_fixture.user_id,),
        ).fetchone() == {"count": 1}
        context = TeachingSessionRepository(
            conn,
            settings=Settings(
                llm_type="disabled",
                tutor_learning_artifacts_enabled=True,
                tutor_artifact_teaching_mode_enabled=True,
                tutor_thread_turn_v2_enabled=True,
            ),
        ).teaching_context(
            user_id=artifact_route_fixture.user_id,
            run_id=run_id,
        )
        assert context is not None
        provider_context = project_teaching_provider_context(context)
        serialized = json.dumps(
            provider_context,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assert len(serialized) <= 1_200
        safe_payload = provider_context["stimulus"]["safe_payload"]
        assert safe_payload == {
            "reason_code": "result_evaluation",
            "source_handle": f"artifact:{result_artifacts[0]['id']}",
            "result_summary": "**通过**：本次运行已完成。",
        }
        assert safe_payload["source_handle"] in provider_context[
            "allowed_source_handles"
        ]
        assert _PRIVATE_SUBMISSION not in serialized
        for protected in ARTIFACT_PROTECTED_MARKERS:
            assert protected not in serialized
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_conversation_events
            WHERE conversation_id = %s AND item_kind = 'artifact' AND item_id = %s
            """,
            (
                artifact_route_fixture.conversation_id,
                result_artifacts[0]["id"],
            ),
        ).fetchone() == {"count": 0}
        pending_timeline, _, _ = PostgresTutorRepository(conn).read_public_history(
            user_id=artifact_route_fixture.user_id,
            conversation_id=artifact_route_fixture.conversation_id,
            limit=40,
        )
        assert result_artifacts[0]["id"] not in {
            item.item_id for item in pending_timeline
        }

    provider = SequenceTutorProvider([TutorProviderResult.model_unavailable()])
    evaluation = TutorInteractiveRunDispatcher(
        settings=Settings(
            llm_type="disabled",
            tutor_learning_artifacts_enabled=True,
            tutor_artifact_teaching_mode_enabled=True,
            tutor_thread_turn_v2_enabled=True,
        ),
        provider_factory=lambda _settings: provider,
    ).dispatch(
        user_id=artifact_route_fixture.user_id,
        run_id=run_id,
    )
    assert evaluation.terminal_outcome is TutorTerminalOutcome.MODEL_UNAVAILABLE
    assert evaluation.public_message == (
        "**运行评价**\n\n"
        "Tutor 暂时无法生成个性化评价，以下为服务器保存的权威结果摘要：\n\n"
        "**通过**：本次运行已完成。"
    )
    assert len(provider.calls) == 1
    with connect() as conn:
        messages = conn.execute(
            """
            SELECT id::text AS id, content FROM tutor_messages
            WHERE conversation_id = %s AND role = 'tutor'
            ORDER BY created_at, id
            """,
            (artifact_route_fixture.conversation_id,),
        ).fetchall()
        assert [str(row["content"]) for row in messages] == [
            evaluation.public_message
        ]
        published_items = conn.execute(
            """
            SELECT event_sequence, item_kind, item_id::text AS item_id
            FROM tutor_conversation_events
            WHERE conversation_id = %s
              AND ((item_kind = 'message' AND item_id = %s)
                   OR (item_kind = 'artifact' AND item_id = %s))
            ORDER BY event_sequence
            """,
            (
                artifact_route_fixture.conversation_id,
                messages[0]["id"],
                result_artifacts[0]["id"],
            ),
        ).fetchall()
        assert [(row["item_kind"], row["item_id"]) for row in published_items] == [
            ("message", messages[0]["id"]),
            ("artifact", result_artifacts[0]["id"]),
        ]
        published_timeline, _, _ = PostgresTutorRepository(conn).read_public_history(
            user_id=artifact_route_fixture.user_id,
            conversation_id=artifact_route_fixture.conversation_id,
            limit=40,
        )
        published_ids = [item.item_id for item in published_timeline]
        # History pages are newest-first, so the later result item precedes the
        # evaluation message in this transport order while rendering chronologically.
        assert published_ids.index(result_artifacts[0]["id"]) < published_ids.index(
            messages[0]["id"]
        )
        result_item = next(
            item
            for item in published_timeline
            if item.item_id == result_artifacts[0]["id"]
        )
        assert result_item.turn_id == run_id
        assert conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_exercise_attempts
            WHERE id = %s AND user_id = %s
            """,
            (artifact_route_fixture.attempt_id, artifact_route_fixture.user_id),
        ).fetchone() == {"count": 1}


def test_pending_attempt_read_does_not_project_or_schedule(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    _configure_artifact_routes(monkeypatch, enabled=True)
    dispatched_jobs: list[str] = []
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda job_id, **_kwargs: dispatched_jobs.append(job_id),
    )
    with connect() as conn:
        conn.execute(
            "SELECT set_config('aearn.learning_track_purge_user_id', %s, true)",
            (artifact_route_fixture.user_id,),
        )
        conn.execute(
            "DELETE FROM tutor_exercise_attempt_results WHERE attempt_id = %s AND user_id = %s",
            (artifact_route_fixture.attempt_id, artifact_route_fixture.user_id),
        )
        conn.commit()

    with TestClient(app) as client:
        response = client.get(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}"
            f"/attempts/{artifact_route_fixture.attempt_id}",
            params={"user_id": artifact_route_fixture.user_id},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["result"] is None
    assert dispatched_jobs == []
    with connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_learning_artifacts
            WHERE user_id = %s AND artifact_kind = 'test_result'
            """,
            (artifact_route_fixture.user_id,),
        ).fetchone() == {"count": 0}
        assert conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_continuation_intents
            WHERE user_id = %s
            """,
            (artifact_route_fixture.user_id,),
        ).fetchone() == {"count": 0}
        assert conn.execute(
            "SELECT version, state FROM tutor_learning_artifacts WHERE id = %s",
            (artifact_route_fixture.artifact_id,),
        ).fetchone() == {"version": 1, "state": "active"}


def test_terminal_run_action_returns_the_projected_source_event_identity(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    _configure_artifact_routes(monkeypatch, enabled=True)
    with connect() as conn:
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        artifact = repository.read_artifact(
            user_id=artifact_route_fixture.user_id,
            conversation_id=artifact_route_fixture.conversation_id,
            artifact_id=artifact_route_fixture.artifact_id,
        )
        detail = repository.read_attempt_detail(
            user_id=artifact_route_fixture.user_id,
            conversation_id=artifact_route_fixture.conversation_id,
            artifact_id=artifact_route_fixture.artifact_id,
            attempt_id=artifact_route_fixture.attempt_id,
        )

    assert detail.result is not None
    attempt_summary = TutorArtifactAttemptSummaryV1(
        attempt_id=detail.attempt_id,
        attempt_type=detail.attempt_type,
        status="terminal",
        outcome=detail.result.outcome,
        score=detail.result.score,
        result_hash=detail.result.result_hash,
        accepted_at=detail.accepted_at,
        terminal_at=detail.result.terminal_at,
    )
    action_write = artifact_routes.LearningArtifactWriteResult(
        artifact=artifact.model_copy(
            update={"version": 2, "active_attempt": attempt_summary}
        ),
        artifact_event_id=str(uuid4()),
        artifact_event_sequence=2,
        idempotent_replayed=False,
        owner_callback_invoked=True,
    )
    projected_write = artifact_routes.LearningArtifactWriteResult(
        artifact=artifact.model_copy(
            update={
                "version": 3,
                "state": TutorArtifactState.ACTIVE,
                "active_attempt": attempt_summary,
            }
        ),
        artifact_event_id=str(uuid4()),
        artifact_event_sequence=3,
        idempotent_replayed=False,
        owner_callback_invoked=False,
    )

    class _TerminalRunService:
        def act(self, **_kwargs: object):  # type: ignore[no-untyped-def]
            return action_write

    monkeypatch.setattr(
        artifact_routes,
        "build_learning_artifact_service",
        lambda _conn: _TerminalRunService(),
    )
    monkeypatch.setattr(
        artifact_routes,
        "_observe_artifact_attempt",
        lambda **_kwargs: artifact_routes._ArtifactAttemptObservation(
            detail=detail.model_copy(update={"artifact_version": 3}),
            source_write=projected_write,
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}/actions",
            json={
                "user_id": artifact_route_fixture.user_id,
                "learning_track_id": artifact_route_fixture.learning_track_id,
                "teaching_session_id": artifact_route_fixture.teaching_session_id,
                "client_action_id": "terminal-run-response-identity",
                "expected_artifact_version": 1,
                "action": {"action": "run", "submission": "print(1)"},
            },
        )

    assert response.status_code == 200
    assert response.json()["artifact"]["version"] == 3
    assert response.json()["artifact_event_sequence"] == 3
    assert response.json()["artifact_event_id"] == projected_write.artifact_event_id


def test_learning_artifact_action_route_enforces_scope_header_idempotency_and_cas(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    adapter = _CancellingTeachingAdapter()
    _configure_artifact_routes(
        monkeypatch,
        enabled=True,
        adapters=ArtifactOwnerAdapterRegistry((adapter,)),
    )
    endpoint = (
        f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
        f"/artifacts/{artifact_route_fixture.artifact_id}/actions"
    )

    with TestClient(app) as client:
        invalid = client.post(
            endpoint,
            json={
                **_action_payload(
                    artifact_route_fixture,
                    client_action_id="artifact-extra",
                    expected_version=1,
                ),
                "unexpected": True,
            },
        )
        _assert_error(invalid, "VALIDATION_ERROR", 400)

        invalid_header = client.post(
            endpoint,
            headers={"Idempotency-Key": " invalid"},
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="artifact-invalid-header",
                expected_version=1,
            ),
        )
        _assert_error(invalid_header, "VALIDATION_ERROR", 400)

        private_invalid_submission = "PRIVATE-VALIDATION-INPUT-" + ("x" * 48_000)
        invalid_submission = client.post(
            endpoint,
            json={
                **_action_payload(
                    artifact_route_fixture,
                    client_action_id="artifact-invalid-submission",
                    expected_version=1,
                ),
                "action": {
                    "action": "run",
                    "submission": private_invalid_submission,
                },
            },
        )
        _assert_error(invalid_submission, "VALIDATION_ERROR", 400)
        assert private_invalid_submission not in invalid_submission.text
        assert '"input"' not in invalid_submission.text

        wrong_scope = client.post(
            f"/api/tutor/conversations/{uuid4()}"
            f"/artifacts/{artifact_route_fixture.artifact_id}/actions",
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="artifact-wrong-scope",
                expected_version=1,
            ),
        )
        _assert_error(wrong_scope, "LEARNING_ARTIFACT_NOT_FOUND", 404)
        assert adapter.calls == 0

        first = client.post(
            endpoint,
            headers={"Idempotency-Key": "artifact-header-cancel"},
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="body-action-one",
                expected_version=1,
            ),
        )
        assert first.status_code == 200
        assert first.json()["artifact"]["state"] == "cancelled"
        assert first.json()["artifact"]["version"] == 2
        assert first.json()["idempotent_replayed"] is False

        replay = client.post(
            endpoint,
            headers={"Idempotency-Key": "artifact-header-cancel"},
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="body-action-two",
                expected_version=1,
            ),
        )
        assert replay.status_code == 200
        assert replay.json()["idempotent_replayed"] is True
        assert adapter.calls == 1

        collision = client.post(
            endpoint,
            headers={"Idempotency-Key": "artifact-header-cancel"},
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="body-action-three",
                expected_version=2,
            ),
        )
        _assert_error(collision, "IDEMPOTENCY_CONFLICT", 409)

        stale = client.post(
            endpoint,
            headers={"Idempotency-Key": "artifact-stale-cancel"},
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="body-action-four",
                expected_version=1,
            ),
        )
        _assert_error(stale, "LEARNING_ARTIFACT_VERSION_CONFLICT", 409)
        assert adapter.calls == 1


def test_learning_artifact_action_route_registers_teaching_owner_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    _configure_artifact_routes(monkeypatch, enabled=True)
    registry = artifact_routes.build_learning_artifact_owner_adapters()
    assert registry.owner_kinds == (
        TutorArtifactOwnerKind.LEARNING_ITEM,
        TutorArtifactOwnerKind.TEACHING_PRACTICE,
    )
    with pytest.raises(ArtifactOwnerUnavailable):
        registry.require(TutorArtifactOwnerKind.LESSON_GATE)

    with TestClient(app) as client:
        response = client.post(
            f"/api/tutor/conversations/{artifact_route_fixture.conversation_id}"
            f"/artifacts/{artifact_route_fixture.artifact_id}/actions",
            json=_action_payload(
                artifact_route_fixture,
                client_action_id="artifact-owner-unavailable",
                expected_version=1,
            ),
        )
    assert response.status_code == 200
    assert response.json()["artifact"]["state"] == "cancelled"

    with connect() as conn:
        row = conn.execute(
            "SELECT version, state FROM tutor_learning_artifacts WHERE id = %s",
            (artifact_route_fixture.artifact_id,),
        ).fetchone()
    assert row == {"version": 2, "state": "cancelled"}


def test_learning_artifact_attempt_summary_cannot_diverge_from_attempt_authority(
    artifact_route_fixture: _ArtifactRouteFixture,
) -> None:
    with connect() as conn:
        repository = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        )
        artifact = repository.read_artifact(
            user_id=artifact_route_fixture.user_id,
            conversation_id=artifact_route_fixture.conversation_id,
            artifact_id=artifact_route_fixture.artifact_id,
        )
        attempt = conn.execute(
            """
            SELECT attempts.accepted_at, results.result_hash, results.terminal_at
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE attempts.id = %s AND attempts.user_id = %s
            """,
            (artifact_route_fixture.attempt_id, artifact_route_fixture.user_id),
        ).fetchone()
        assert attempt is not None

        with pytest.raises(LearningArtifactVersionConflict):
            repository.apply_owner_update(
                artifact_id=artifact.id,
                user_id=artifact_route_fixture.user_id,
                conversation_id=artifact_route_fixture.conversation_id,
                learning_track_id=artifact_route_fixture.learning_track_id,
                teaching_session_id=artifact_route_fixture.teaching_session_id,
                expected_artifact_version=artifact.version,
                event_key="artifact-attempt-summary-mismatch",
                event_kind="attempt_linked",
                mutation=ArtifactMutation(
                    state=artifact.state,
                    owner_version=artifact.owner_version,
                    owner_context_version=artifact.owner_version,
                    presentation=artifact.presentation,
                    allowed_actions=artifact.allowed_actions,
                    active_attempt=TutorArtifactAttemptSummaryV1(
                        attempt_id=artifact_route_fixture.attempt_id,
                        attempt_type="run",
                        status="terminal",
                        outcome="passed",
                        score=0.5,
                        result_hash=str(attempt["result_hash"]),
                        accepted_at=attempt["accepted_at"].astimezone(UTC).isoformat(),
                        terminal_at=attempt["terminal_at"].astimezone(UTC).isoformat(),
                    ),
                    safe_event_payload={"status": "terminal"},
                ),
                occurred_at=_NOW,
            )

        assert conn.execute(
            "SELECT version, active_attempt_id FROM tutor_learning_artifacts WHERE id = %s",
            (artifact.id,),
        ).fetchone() == {"version": 1, "active_attempt_id": None}
