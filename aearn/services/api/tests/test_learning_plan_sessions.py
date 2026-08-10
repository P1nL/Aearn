from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.core.config import Settings
from app.db.connection import connect
from app.services.learning.plan_capability import LearningPlanDraftCapabilityHandler
from app.services.tutor.persistence import PostgresTutorRepository
from tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    waiting_dispatcher,
)


pytest_plugins = ("tutor_public_api_support",)


def _capability_input() -> LearningPlanDraftCapabilityInput:
    profile = {
        "language_id": "python",
        "goal_text": "Build reliable automation tools",
        "target_level": "intermediate",
        "weekly_minutes": 240,
        "experience_level": "beginner",
        "teaching_preferences": ["examples", "practice"],
        "pace_summary": "Four focused sessions each week.",
        "title": "Python Automation Foundations",
    }
    modules = (
        {
            "module_key": "foundations",
            "title": "Foundations",
            "nodes": [
                {
                    "knowledge_key": "python.variables",
                    "title": "Variables",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "module_key": "automation",
            "title": "Automation",
            "nodes": [
                {
                    "knowledge_key": "python.files",
                    "title": "Files",
                    "prerequisite_keys": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    )
    return LearningPlanDraftCapabilityInput(
        profile_json=json.dumps(profile, separators=(",", ":")),
        module_1=json.dumps(modules[0], separators=(",", ":")),
        module_2=json.dumps(modules[1], separators=(",", ":")),
    )


def _create_session(client: TestClient, user_id: str, action_id: str = "plan-session-create") -> dict[str, object]:
    response = client.post(
        "/api/learning-plan-sessions",
        json={
            "user_id": user_id,
            "client_action_id": action_id,
            "preferred_language_id": "python",
        },
    )
    assert response.status_code in {200, 201}
    session = response.json()["session"]
    assert isinstance(session, dict)
    return session


def test_session_create_resume_cancel_and_cross_user_scope(
    tutor_client: TestClient,
) -> None:
    owner_id = str(create_tutor_user(tutor_client)["id"])
    other_id = str(create_tutor_user(tutor_client)["id"])
    created = _create_session(tutor_client, owner_id)
    resumed = _create_session(tutor_client, owner_id, "plan-session-resume")

    assert resumed["session_id"] == created["session_id"]
    current = tutor_client.get(f"/api/learning-plan-sessions/current?user_id={owner_id}")
    assert current.status_code == 200
    assert current.json()["session"]["conversation_id"] == created["conversation_id"]

    hidden = tutor_client.get(
        f"/api/learning-plan-sessions/{created['session_id']}?user_id={other_id}"
    )
    assert_error(hidden, "LEARNING_PLAN_SESSION_NOT_FOUND", 404)

    cancelled = tutor_client.post(
        f"/api/learning-plan-sessions/{created['session_id']}/cancel",
        json={
            "user_id": owner_id,
            "client_action_id": "plan-session-cancel",
            "expected_session_version": created["version"],
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["session"]["status"] == "cancelled"
    assert tutor_client.get(f"/api/learning-plan-sessions/current?user_id={owner_id}").json()["session"] is None


def test_capability_appends_typed_draft_and_confirm_creates_one_track(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="计划信息已足够。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-confirm-session")
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-draft-input",
            content="我想每周学习四小时，用 Python 做可靠的自动化工具。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        run = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None
        output = LearningPlanDraftCapabilityHandler(conn).generate(
            run=run,
            capability_input=_capability_input(),
        )
        conn.commit()

    current = tutor_client.get(f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}")
    assert current.status_code == 200
    draft_session = current.json()["session"]
    draft = draft_session["current_draft"]
    assert draft["draft_id"] == output.draft_id
    assert draft["draft_version"] == 1
    assert draft["content_hash"] == output.content_hash
    assert draft["sources"][0]["source_id"] == "python-tutorial"
    public_text = json.dumps(draft_session, ensure_ascii=False)
    for protected in ("raw_prompt", "provider_body", "reasoning", "credential", "transport_body"):
        assert protected not in public_text

    with connect() as conn:
        PostgresTutorRepository(conn).request_cancellation(
            user_id=user_id,
            run_id=run_id,
            now=datetime.now(UTC),
        )
        conn.commit()

    confirm_payload = {
        "user_id": user_id,
        "client_action_id": "plan-confirm-draft-1",
        "expected_session_version": draft_session["version"],
        "draft_id": draft["draft_id"],
        "draft_version": draft["draft_version"],
        "content_hash": draft["content_hash"],
    }
    confirmed = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json=confirm_payload,
    )
    replay = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json=confirm_payload,
    )
    assert confirmed.status_code == replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    track_id = str(confirmed.json()["track"]["track_id"])
    assert replay.json()["track"]["track_id"] == track_id

    listing = tutor_client.get(f"/api/learning-tracks?user_id={user_id}")
    assert listing.status_code == 200
    assert [item["track_id"] for item in listing.json()["items"]] == [track_id]
    with connect() as conn:
        scope = conn.execute(
            "SELECT scope_kind, learning_track_id::text FROM tutor_conversation_learning_scopes WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*)::int FROM tutor_learning_plan_drafts WHERE user_id = %s) AS drafts,
              (SELECT count(*)::int FROM tutor_learning_tracks WHERE user_id = %s) AS tracks,
              (SELECT count(*)::int FROM tutor_track_plan_revisions WHERE user_id = %s) AS revisions
            """,
            (user_id, user_id, user_id),
        ).fetchone()
    assert scope == {"scope_kind": "learning_track", "learning_track_id": track_id}
    assert counts == {"drafts": 1, "tracks": 1, "revisions": 1}


def test_confirm_rejects_stale_draft_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="计划已准备。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-stale-session")
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{session['conversation_id']}/inputs",
        json=action_payload(
            user_id,
            "plan-stale-input",
            content="生成 Python 学习计划。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    run_id = str(accepted.json()["run_id"])
    with connect() as conn:
        run = PostgresTutorRepository(conn).load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None
        LearningPlanDraftCapabilityHandler(conn).generate(run=run, capability_input=_capability_input())
        conn.commit()
    current = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    draft = current["current_draft"]
    stale = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json={
            "user_id": user_id,
            "client_action_id": "plan-stale-confirm",
            "expected_session_version": current["version"] - 1,
            "draft_id": draft["draft_id"],
            "draft_version": draft["draft_version"],
            "content_hash": draft["content_hash"],
        },
    )
    assert_error(stale, "LEARNING_PLAN_DRAFT_STALE", 409)
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_tracks WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert count == {"count": 0}
