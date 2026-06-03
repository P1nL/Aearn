import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.curriculum.dynamic_plan_generation import DynamicPlanDraftResult
from app.services.curriculum.plan_generator import build_plan_draft


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


@pytest.fixture()
def client() -> TestClient:
    bootstrap_database()
    return TestClient(app)


@pytest.fixture(autouse=True)
def disable_live_plan_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans_route, "build_dynamic_plan_draft", _fake_dynamic_plan_draft)


def _fake_dynamic_plan_draft(payload, user, course, **kwargs):  # type: ignore[no-untyped-def]
    del kwargs
    plan_draft = build_plan_draft(payload, user, course)
    return DynamicPlanDraftResult(
        plan_draft=plan_draft,
        agent_notes=[plan_draft.runtime_boundary.notice, "Test fake dynamic plan."],
    )


def test_user_list_summary_export_and_cross_user_guards(client: TestClient) -> None:
    owner, owner_plan, _owner_draft = _confirmed_plan(client, language="javascript")
    other, _other_plan, _other_draft = _confirmed_plan(client, language="python")
    owner_kp = owner_plan["knowledge_points"][0]
    owner_plan_id = owner_plan["LearningPlan"]["id"]
    _attach_private_learning_data(owner["id"], owner_plan, hidden_marker="SECRET_HIDDEN_EXPECTED")

    listed = client.get("/api/users")
    assert listed.status_code == 200
    user_ids = {item["id"] for item in listed.json()["items"]}
    assert owner["id"] in user_ids
    assert other["id"] in user_ids

    same_plan = client.get(f"/api/plans/{owner_plan_id}?user_id={owner['id']}")
    assert same_plan.status_code == 200

    cross_plan = client.get(f"/api/plans/{owner_plan_id}?user_id={other['id']}")
    assert cross_plan.status_code == 404
    assert cross_plan.json()["error"]["code"] == "PLAN_NOT_FOUND"

    created_note = client.post(
        "/api/notes",
        json={
            "user_id": owner["id"],
            "knowledge_point_id": owner_kp["id"],
            "title": "Owned note",
            "content_markdown": "Learner-owned note content.",
        },
    )
    assert created_note.status_code == 201
    note_id = created_note.json()["note"]["id"]

    cross_note = client.patch(
        f"/api/notes/{note_id}",
        json={
            "user_id": other["id"],
            "title": "Wrong user edit",
            "content_markdown": "This must not update the note.",
            "is_user_edited": True,
        },
    )
    assert cross_note.status_code == 404
    assert cross_note.json()["error"]["code"] == "NOTE_NOT_FOUND"

    summary = client.get(f"/api/users/{owner['id']}/data-summary")
    assert summary.status_code == 200
    summary_body = summary.json()["summary"]
    assert summary_body["counts"]["active_plans"] >= 1
    assert summary_body["counts"]["notes"] >= 1
    assert summary_body["counts"]["attempts"] >= 1

    exported = client.get(f"/api/users/{owner['id']}/export")
    assert exported.status_code == 200
    export_text = json.dumps(exported.json(), ensure_ascii=False)
    assert "Learner-owned note content." in export_text
    assert "SECRET_HIDDEN_EXPECTED" not in export_text
    assert "SECRET_SOLUTION_REFERENCE" not in export_text
    assert "assertion_code" not in export_text
    assert "raw provider payload must not export" not in export_text


def test_session_mutations_validate_active_user_id(client: TestClient) -> None:
    owner, owner_plan, _owner_draft = _confirmed_plan(client, language="javascript")
    other, _other_plan, _other_draft = _confirmed_plan(client, language="python")
    attached = _attach_private_learning_data(owner["id"], owner_plan, hidden_marker="SESSION_HIDDEN_EXPECTED")
    review_session_id = _attach_review_session(
        owner["id"],
        owner_plan,
        exercise_id=attached["exercise_id"],
    )

    run_payload = {
        "user_id": owner["id"],
        "code": "const value = 1;",
        "filled_blanks": {"value": "1"},
        "runtime_profile_id": attached["runtime_profile_id"],
        "run_mode": "visible_tests",
        "code_hash": "sha256:active-user-boundary",
    }
    run = client.post(
        f"/api/learning-sessions/{attached['session_id']}/exercises/{attached['exercise_id']}/run",
        json=run_payload,
    )
    assert run.status_code == 201

    replay = client.post(
        f"/api/learning-sessions/{attached['session_id']}/exercises/{attached['exercise_id']}/run",
        json=run_payload,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotency_replayed"] is True

    wrong_user_run = client.post(
        f"/api/learning-sessions/{attached['session_id']}/exercises/{attached['exercise_id']}/run",
        json={**run_payload, "user_id": other["id"]},
    )
    assert wrong_user_run.status_code == 404
    assert wrong_user_run.json()["error"]["code"] == "SESSION_NOT_FOUND"

    wrong_user_message = client.post(
        f"/api/learning-sessions/{attached['session_id']}/messages",
        json={
            "user_id": other["id"],
            "role": "user",
            "content": "继续讲这个知识点。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert wrong_user_message.status_code == 404
    assert wrong_user_message.json()["error"]["code"] == "SESSION_NOT_FOUND"

    wrong_user_warmup = client.post(
        f"/api/reviews/{review_session_id}/warmup-result",
        json={
            "user_id": other["id"],
            "action": "skip",
        },
    )
    assert wrong_user_warmup.status_code == 404
    assert wrong_user_warmup.json()["error"]["code"] == "SESSION_NOT_FOUND"

    owner_warmup = client.post(
        f"/api/reviews/{review_session_id}/warmup-result",
        json={
            "user_id": owner["id"],
            "action": "skip",
        },
    )
    assert owner_warmup.status_code == 200

    wrong_user_review_submit = client.post(
        f"/api/reviews/{review_session_id}/exercise-result",
        json={
            "user_id": other["id"],
            "exercise_id": attached["exercise_id"],
            "code": "const value = 1;",
            "filled_blanks": {"value": "1"},
            "submit_version": 1,
        },
    )
    assert wrong_user_review_submit.status_code == 404
    assert wrong_user_review_submit.json()["error"]["code"] == "SESSION_NOT_FOUND"

    wrong_user_review_message = client.post(
        f"/api/reviews/{review_session_id}/messages",
        json={
            "user_id": other["id"],
            "content": "继续讲这道复习题。",
            "client_message_id": f"review_msg_{uuid.uuid4().hex}",
        },
        headers={"Accept": "text/event-stream"},
    )
    assert wrong_user_review_message.status_code == 200
    assert '"code":"SESSION_NOT_FOUND"' in wrong_user_review_message.text
    assert "REVIEW_SESSION_NOT_FOUND" not in wrong_user_review_message.text


def test_reset_preserves_user_preferences_clears_learning_data_and_prevents_stale_replay(client: TestClient) -> None:
    user, plan, draft = _confirmed_plan(client, language="javascript")
    original_plan_id = plan["LearningPlan"]["id"]
    _attach_private_learning_data(user["id"], plan, hidden_marker="RESET_HIDDEN_EXPECTED")

    patched = client.patch(
        f"/api/users/{user['id']}/preferences",
        json={"profession": "frontend_developer"},
    )
    assert patched.status_code == 200

    before = client.get(f"/api/users/{user['id']}/data-summary")
    assert before.status_code == 200
    assert before.json()["summary"]["counts"]["active_plans"] >= 1
    assert before.json()["summary"]["counts"]["attempts"] >= 1

    reset = client.post(f"/api/users/{user['id']}/reset-data", json={"confirm": True})
    assert reset.status_code == 200
    reset_body = reset.json()
    assert reset_body["user"]["id"] == user["id"]
    assert reset_body["user"]["profession"] == "frontend_developer"
    assert reset_body["summary"]["counts"]["active_plans"] == 0
    assert reset_body["summary"]["counts"]["attempts"] == 0
    assert reset_body["summary"]["counts"]["notes"] == 0

    old_plan = client.get(f"/api/plans/{original_plan_id}?user_id={user['id']}")
    assert old_plan.status_code == 404

    replay_or_recreate = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert replay_or_recreate.status_code == 201
    assert replay_or_recreate.json()["LearningPlan"]["id"] != original_plan_id
    assert "idempotency_replayed" not in replay_or_recreate.json()


def test_delete_hides_user_data_and_invalidates_idempotency_replay(client: TestClient) -> None:
    user, plan, draft = _confirmed_plan(client, language="javascript")
    plan_id = plan["LearningPlan"]["id"]
    _attach_private_learning_data(user["id"], plan, hidden_marker="DELETE_HIDDEN_EXPECTED")

    deleted = client.request("DELETE", f"/api/users/{user['id']}", json={"confirm": True})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_user_id"] == user["id"]

    read_user = client.get(f"/api/users/{user['id']}")
    assert read_user.status_code == 404
    assert read_user.json()["error"]["code"] == "USER_NOT_FOUND"

    listed = client.get("/api/users")
    assert listed.status_code == 200
    assert user["id"] not in {item["id"] for item in listed.json()["items"]}

    old_plan = client.get(f"/api/plans/{plan_id}?user_id={user['id']}")
    assert old_plan.status_code == 404

    replay = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert replay.status_code == 404
    assert replay.json()["error"]["code"] == "USER_NOT_FOUND"


def _confirmed_plan(
    client: TestClient,
    *,
    language: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, language)
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": f"Practice {language} local user data boundary.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm_response = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm_response.status_code == 201
    return user, confirm_response.json(), draft


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"Boundary User {uuid.uuid4().hex[:8]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
            "encouragement_preference": "direct",
        },
    )
    assert response.status_code == 201
    user = response.json()["user"]
    assert isinstance(user, dict)
    return user


def _course_by_language(client: TestClient, language: str) -> dict[str, object]:
    response = client.get(f"/api/language-courses?language={language}")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    course = items[0]
    assert isinstance(course, dict)
    return course


def _attach_private_learning_data(
    user_id: str,
    plan: dict[str, object],
    *,
    hidden_marker: str,
) -> dict[str, str]:
    plan_id = plan["LearningPlan"]["id"]
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    runtime_profile_id = _runtime_profile_id_for_plan(plan)

    with connect() as conn:
        exercise = conn.execute(
            """
            INSERT INTO exercises (
              knowledge_point_id, runtime_profile_id, title, exercise_type,
              prompt_markdown, starter_code, solution_reference, metadata_json
            )
            VALUES (%s, %s, 'Boundary exercise', 'code_blank', 'Fill the blank.', 'const value = __VALUE__;', %s, %s::jsonb)
            RETURNING id
            """,
            (
                knowledge_point_id,
                runtime_profile_id,
                "SECRET_SOLUTION_REFERENCE",
                json.dumps({"provider_payload": "raw provider payload must not export"}),
            ),
        ).fetchone()
        assert exercise is not None
        exercise_id = str(exercise["id"])
        conn.execute(
            """
            INSERT INTO code_blanks (exercise_id, blank_key, placeholder, expected_concept, acceptable_patterns_json, order_index)
            VALUES (%s, 'value', '__VALUE__', 'literal', '[]'::jsonb, 0)
            """,
            (exercise_id,),
        )
        conn.execute(
            """
            INSERT INTO test_cases (
              exercise_id, case_type, input_json, expected_output_json, assertion_code, weight, is_critical, order_index
            )
            VALUES (%s, 'hidden', '{}'::jsonb, %s::jsonb, 'secret assertion_code', 1, true, 0)
            """,
            (exercise_id, json.dumps({"expected": hidden_marker})),
        )
        session = conn.execute(
            """
            INSERT INTO learning_sessions (
              user_id, plan_id, session_type, status, entry_point, next_entry_point, learning_stage
            )
            VALUES (%s, %s, 'learn', 'active', %s, %s, 'practice_support')
            RETURNING id
            """,
            (user_id, plan_id, knowledge_point_id, knowledge_point_id),
        ).fetchone()
        assert session is not None
        attempt = conn.execute(
            """
            INSERT INTO attempts (
              session_id, exercise_id, user_id, attempt_type, submitted_code, code_hash,
              filled_blanks_json, runtime_status, test_pass_rate, passed_test_count, total_test_count,
              test_results_json, stdout, stderr, error_message, error_count, evaluation_status
            )
            VALUES (
              %s, %s, %s, 'run', 'const value = 1;', 'sha256:boundary',
              '{"value":"1"}'::jsonb, 'success', 1.0, 1, 1,
              '[{"case_id":"visible_1","case_type":"visible","passed":true,"message":"ok"}]'::jsonb,
              'ok', '', NULL, 0, 'pending'
            )
            RETURNING id
            """,
            (session["id"], exercise_id, user_id),
        ).fetchone()
        assert attempt is not None
        conn.commit()
    return {
        "exercise_id": exercise_id,
        "session_id": str(session["id"]),
        "attempt_id": str(attempt["id"]),
        "runtime_profile_id": runtime_profile_id,
    }


def _attach_review_session(user_id: str, plan: dict[str, object], *, exercise_id: str) -> str:
    plan_id = plan["LearningPlan"]["id"]
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    state = {
        "review_stage": "warmup",
        "knowledge_point_id": knowledge_point_id,
        "seed_bank_id": "manual_boundary_seed_bank",
        "seed_id": "manual_boundary_seed",
        "warmup": {
            "question": "这条复习为什么要看状态变化？",
            "expected_focus": "state",
        },
        "variant": {
            "exercise_id": exercise_id,
            "exercise_type": "code_blank",
            "guided": False,
            "selection_reason": "local user boundary regression",
        },
    }
    with connect() as conn:
        session = conn.execute(
            """
            INSERT INTO learning_sessions (
              user_id, plan_id, session_type, status, entry_point, next_entry_point,
              review_stage, review_stage_state_json
            )
            VALUES (%s, %s, 'review', 'active', %s, %s, 'warmup', %s::jsonb)
            RETURNING id
            """,
            (user_id, plan_id, knowledge_point_id, knowledge_point_id, json.dumps(state)),
        ).fetchone()
        assert session is not None
        conn.commit()
    return str(session["id"])


def _runtime_profile_id_for_plan(plan: dict[str, object]) -> str:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT language_courses.runtime_profile_id::text AS runtime_profile_id
            FROM language_courses
            WHERE language_courses.id = %s
            """,
            (plan["LearningPlan"]["language_course_id"],),
        ).fetchone()
    assert row is not None
    return str(row["runtime_profile_id"])
