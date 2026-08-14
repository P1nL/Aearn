from __future__ import annotations

import json
import uuid
from collections.abc import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from learning_track_support import sample_plan_payload
from tutor_public_api_support import action_payload, assert_error, create_tutor_user, waiting_dispatcher


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for LearningTrack API tests.",
)


@pytest.fixture()
def learning_client() -> Iterator[TestClient]:
    bootstrap_database()
    with TestClient(app) as client:
        yield client


def _create_user(client: TestClient) -> str:
    response = client.post("/api/users", json={"display_name": f"LearningTrack API {uuid.uuid4().hex[:10]}"})
    assert response.status_code == 201
    user_id = str(response.json()["user"]["id"])
    decision = client.get(f"/api/harness/cutover?user_id={user_id}")
    assert decision.status_code == 200 and decision.json()["state"] == "verified"
    return user_id


def _create_payload(user_id: str, *, action: str, goal: str, **plan_overrides: object) -> dict[str, object]:
    target_level = str(plan_overrides.get("target_level", "beginner"))
    return {
        "user_id": user_id,
        "client_action_id": action,
        "language_id": "python",
        "goal_text": goal,
        "target_level": target_level,
        "plan": sample_plan_payload(**plan_overrides),
    }


def test_create_list_detail_roadmap_and_safe_idempotent_projection(learning_client: TestClient) -> None:
    user_id = _create_user(learning_client)
    first_payload = _create_payload(user_id, action="track-create-one", goal="Learn Python for automation")
    second_payload = _create_payload(
        user_id,
        action="track-create-two",
        goal="Learn Python for data analysis",
        title="Python Data Foundations",
    )

    first = learning_client.post("/api/learning-tracks", json=first_payload)
    second = learning_client.post("/api/learning-tracks", json=second_payload)
    replay = learning_client.post("/api/learning-tracks", json=first_payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    assert replay.json()["track"]["track_id"] == first.json()["track"]["track_id"]

    metadata_conflict_payload = json.loads(json.dumps(first_payload))
    metadata_conflict_payload["plan"]["generator_version"] = "learning-plan-test-v2"
    metadata_conflict = learning_client.post("/api/learning-tracks", json=metadata_conflict_payload)
    assert_error(metadata_conflict, "IDEMPOTENCY_CONFLICT", 409)

    track_id = str(first.json()["track"]["track_id"])
    listing = learning_client.get(f"/api/learning-tracks?user_id={user_id}")
    detail = learning_client.get(f"/api/learning-tracks/{track_id}?user_id={user_id}")
    roadmap = learning_client.get(f"/api/learning-tracks/{track_id}/roadmap?user_id={user_id}")
    assert listing.status_code == detail.status_code == roadmap.status_code == 200
    assert len(listing.json()["items"]) == 2
    assert {item["goal_text"] for item in listing.json()["items"]} == {
        "Learn Python for automation",
        "Learn Python for data analysis",
    }
    assert roadmap.json()["roadmap"]["modules"][0]["nodes"][0]["progress_status"] == "available"

    public_text = json.dumps(
        {"list": listing.json(), "detail": detail.json(), "roadmap": roadmap.json()},
        ensure_ascii=False,
    )
    for protected in (
        "plan_json",
        "evidence_summary_json",
        "source_receipt_hash",
        "provider_payload",
        "lock_fingerprint",
        "executor_health",
    ):
        assert protected not in public_text


def test_revision_proposal_activation_conflicts_and_cross_user_not_found(learning_client: TestClient) -> None:
    owner_id = _create_user(learning_client)
    other_id = _create_user(learning_client)
    created = learning_client.post(
        "/api/learning-tracks",
        json=_create_payload(owner_id, action="revision-owner-create", goal="Learn Python versions"),
    )
    assert created.status_code == 201
    track = created.json()["track"]
    track_id = str(track["track_id"])

    cross_user = learning_client.get(f"/api/learning-tracks/{track_id}?user_id={other_id}")
    assert_error(cross_user, "LEARNING_TRACK_NOT_FOUND", 404)

    proposal_payload = {
        "user_id": owner_id,
        "client_action_id": "revision-propose-v2",
        "expected_track_version": track["version"],
        "plan": sample_plan_payload(
            title="Python Foundations v2",
            target_level="intermediate",
            generator_version="learning-plan-test-v2",
            change_reason="Add a loop node.",
            include_loops=True,
        ),
    }
    proposal = learning_client.post(f"/api/learning-tracks/{track_id}/plan-revisions", json=proposal_payload)
    assert proposal.status_code == 201
    assert proposal.json()["impact"]["added"] == ["python.loops"]
    revision_id = str(proposal.json()["revision_id"])

    cross_user_activation = learning_client.post(
        f"/api/learning-tracks/{track_id}/plan-revisions/{revision_id}/activate",
        json={
            "user_id": other_id,
            "client_action_id": "revision-cross-user-activate",
            "expected_track_version": proposal.json()["track_version"],
        },
    )
    assert_error(cross_user_activation, "LEARNING_TRACK_NOT_FOUND", 404)

    stale_proposal = learning_client.post(
        f"/api/learning-tracks/{track_id}/plan-revisions",
        json={**proposal_payload, "client_action_id": "revision-stale", "expected_track_version": 1},
    )
    assert_error(stale_proposal, "LEARNING_PLAN_VERSION_CONFLICT", 409)

    activation = learning_client.post(
        f"/api/learning-tracks/{track_id}/plan-revisions/{revision_id}/activate",
        json={
            "user_id": owner_id,
            "client_action_id": "revision-activate-v2",
            "expected_track_version": proposal.json()["track_version"],
        },
    )
    assert activation.status_code == 200
    assert activation.json()["track"]["active_revision_id"] == revision_id
    assert activation.json()["track"]["progress"]["total"] == 3

    stale_activation = learning_client.post(
        f"/api/learning-tracks/{track_id}/plan-revisions/{revision_id}/activate",
        json={
            "user_id": owner_id,
            "client_action_id": "revision-activate-stale",
            "expected_track_version": proposal.json()["track_version"],
        },
    )
    assert_error(stale_activation, "LEARNING_PLAN_VERSION_CONFLICT", 409)


def test_invalid_plan_and_target_level_mismatch_use_stable_errors(learning_client: TestClient) -> None:
    user_id = _create_user(learning_client)
    mismatch = learning_client.post(
        "/api/learning-tracks",
        json={
            **_create_payload(user_id, action="invalid-target", goal="Mismatch"),
            "target_level": "intermediate",
        },
    )
    assert_error(mismatch, "LEARNING_PLAN_INVALID", 422)

    cyclic_plan = sample_plan_payload()
    modules = cyclic_plan["modules"]
    assert isinstance(modules, list)
    nodes = modules[0]["nodes"]
    assert isinstance(nodes, list)
    nodes[0]["prerequisite_keys"] = ["python.functions"]
    invalid = learning_client.post(
        "/api/learning-tracks",
        json={
            "user_id": user_id,
            "client_action_id": "invalid-cycle",
            "language_id": "python",
            "goal_text": "Cycle",
            "target_level": "beginner",
            "plan": cyclic_plan,
        },
    )
    assert_error(invalid, "VALIDATION_ERROR", 400)


def test_tutor_scope_snapshot_defaults_to_general_and_continuation_is_immutable(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="请补充你的目标。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    created = tutor_client.post(
        "/api/learning-tracks",
        json=_create_payload(user_id, action="scope-track-create", goal="Scoped Python"),
    )
    assert created.status_code == 201
    track_id = str(created.json()["track"]["track_id"])

    scoped = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(
            user_id,
            "scope-first-turn",
            content="开始变量课程。",
            learning_scope={
                "scope_kind": "learning_track",
                "learning_track_id": track_id,
                "task_kind": "lesson_teaching",
                "knowledge_key": "python.variables",
            },
        ),
    )
    assert scoped.status_code == 202
    run_id = str(scoped.json()["run_id"])
    with connect() as conn:
        scope_row = conn.execute(
            "SELECT scope_kind, learning_track_id::text, task_kind, knowledge_key, scope_version FROM tutor_run_learning_scopes WHERE run_id = %s",
            (run_id,),
        ).fetchone()
    assert scope_row == {
        "scope_kind": "learning_track",
        "learning_track_id": track_id,
        "task_kind": "lesson_teaching",
        "knowledge_key": "python.variables",
        "scope_version": 1,
    }

    legacy_continuation = tutor_client.post(
        f"/api/tutor/runs/{run_id}/inputs",
        json=action_payload(user_id, "scope-legacy-continuation", content="我准备好了。"),
    )
    assert_error(legacy_continuation, "RUN_NOT_ACTIVE", 409)

    snapshot = tutor_client.get(
        f"/api/tutor/conversations/{scoped.json()['conversation_id']}/snapshot?user_id={user_id}"
    )
    request = snapshot.json()["pending_requests"][0]
    continuation = tutor_client.post(
        f"/api/tutor/conversations/{scoped.json()['conversation_id']}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "scope-request-response",
            "expected_request_version": request["version"],
            "response": {"kind": "clarification", "answer_text": "我准备好了。"},
        },
    )
    assert continuation.status_code == 202
    answer_turn_id = str(continuation.json()["run_id"])
    with connect() as conn:
        answer_scope = conn.execute(
            "SELECT scope_kind, learning_track_id::text, task_kind, knowledge_key, scope_version FROM tutor_run_learning_scopes WHERE run_id = %s",
            (answer_turn_id,),
        ).fetchone()
    assert answer_scope == scope_row

    conflicting = tutor_client.post(
        f"/api/tutor/conversations/{scoped.json()['conversation_id']}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "scope-response-conflict",
            "expected_request_version": request["version"],
            "learning_scope": {"scope_kind": "general"},
            "response": {"kind": "clarification", "answer_text": "改成普通对话。"},
        },
    )
    assert conflicting.status_code == 400

    general = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(user_id, "general-first-turn", content="这是普通 Tutor 对话。"),
    )
    assert general.status_code == 202
    with connect() as conn:
        general_row = conn.execute(
            "SELECT scope_kind, task_kind, scope_version FROM tutor_run_learning_scopes WHERE run_id = %s",
            (general.json()["run_id"],),
        ).fetchone()
    assert general_row == {"scope_kind": "general", "task_kind": "general_tutor", "scope_version": 0}


def test_conversation_binding_rejects_run_only_scope_fields(
    tutor_client: TestClient,
) -> None:
    user = create_tutor_user(tutor_client)
    user_id = str(user["id"])
    created = tutor_client.post(
        "/api/learning-tracks",
        json=_create_payload(user_id, action="binding-track-create", goal="Broad binding"),
    )
    assert created.status_code == 201
    track_id = str(created.json()["track"]["track_id"])

    denied = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(
            user_id,
            "binding-run-only-fields",
            learning_scope={
                "scope_kind": "learning_track",
                "learning_track_id": track_id,
                "task_kind": "exercise_feedback",
                "knowledge_key": "python.variables",
            },
        ),
    )
    assert_error(denied, "LEARNING_SCOPE_CONFLICT", 409)


def test_invalid_cross_user_scope_rolls_back_the_entire_fresh_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = waiting_dispatcher(settings=tutor_api_settings, message="不会执行。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    owner = create_tutor_user(tutor_client)
    requester = create_tutor_user(tutor_client)
    owner_id = str(owner["id"])
    requester_id = str(requester["id"])
    created = tutor_client.post(
        "/api/learning-tracks",
        json=_create_payload(owner_id, action="scope-owner-track", goal="Owner only"),
    )
    assert created.status_code == 201
    track_id = str(created.json()["track"]["track_id"])

    denied = tutor_client.post(
        "/api/tutor/conversations/first-turn",
        json=action_payload(
            requester_id,
            "scope-cross-user-first-turn",
            content="尝试进入别人的主线。",
            learning_scope={
                "scope_kind": "learning_track",
                "learning_track_id": track_id,
                "task_kind": "lesson_teaching",
            },
        ),
    )
    assert_error(denied, "LEARNING_TRACK_NOT_FOUND", 404)
    assert provider.calls == []
    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*)::int FROM tutor_conversations WHERE user_id = %s) AS conversations,
              (SELECT count(*)::int FROM tutor_runs WHERE user_id = %s) AS runs,
              (SELECT count(*)::int FROM tutor_api_idempotency_records
               WHERE user_id = %s AND operation = 'tutor.conversation.first_turn') AS receipts
            """,
            (requester_id, requester_id, requester_id),
        ).fetchone()
    assert counts == {"conversations": 0, "runs": 0, "receipts": 0}


def test_unexpected_learning_track_failure_uses_the_common_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_database()
    with TestClient(app, raise_server_exceptions=False) as client:
        user_id = _create_user(client)

        def fail_list(_self: object, *, user_id: str) -> dict[str, object]:
            del user_id
            raise RuntimeError("database detail must not leak")

        monkeypatch.setattr("app.routes.learning_tracks.LearningTrackService.list_tracks", fail_list)
        failed = client.get(
            f"/api/learning-tracks?user_id={user_id}",
            headers={"X-Request-Id": "req-learning-internal"},
        )

    assert_error(failed, "INTERNAL_ERROR", 500)
    assert failed.json()["error"]["request_id"] == "req-learning-internal"
    assert "database detail" not in json.dumps(failed.json(), ensure_ascii=False)
