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
from app.services.learning.teaching_sessions import TeachingSessionService
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
            allowed_actions=(TutorArtifactActionKind.CANCEL,),
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


def _assert_error(response, code: str, status_code: int) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == status_code
    body = response.json()
    assert body["error"]["code"] == code
    assert isinstance(body["error"]["request_id"], str)
    assert isinstance(body["error"]["recoverable"], bool)


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
        assert attempt_body["schema_version"] == "tutor_learning_artifact_attempt_v1"
        assert attempt_body["status"] == "terminal"
        assert attempt_body["result"]["outcome"] == "passed"
        assert attempt_body["result"]["safe_feedback"]["execution_claim"] == "not_run"
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
