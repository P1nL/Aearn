import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services import learning_session_repository as session_repository


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


def test_start_learning_session_creates_and_reuses_active_session(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]

    created = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["session_type"] == "learn"
    assert created_body["session_state"] == "learning"
    assert created_body["exercise"]["runtime_profile"]["runtime_tier"] == "browser_preview"
    assert len(created_body["exercise"]["code_blanks"]) == 2

    reused = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert reused.status_code == 200
    reused_body = reused.json()
    assert reused_body["session_id"] == created_body["session_id"]
    assert reused_body["exercise"]["id"] == created_body["exercise"]["id"]

    with connect() as conn:
        session_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM learning_sessions
            WHERE user_id = %s AND plan_id = %s AND status = 'active'
            """,
            (user["id"], plan["LearningPlan"]["id"]),
        ).fetchone()
    assert session_count is not None
    assert session_count["count"] == 1


def test_start_learning_session_keeps_distinct_knowledge_points_separate(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    assert len(plan["knowledge_points"]) >= 2

    first = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": plan["knowledge_points"][0]["id"],
        },
    )
    assert first.status_code == 201

    second = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": plan["knowledge_points"][1]["id"],
        },
    )
    assert second.status_code == 201
    assert second.json()["session_id"] != first.json()["session_id"]

    with connect() as conn:
        session_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM learning_sessions
            WHERE user_id = %s AND plan_id = %s AND status = 'active'
            """,
            (user["id"], plan["LearningPlan"]["id"]),
        ).fetchone()
    assert session_count is not None
    assert session_count["count"] == 2


def test_javascript_run_and_submit_persist_attempts(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert start_response.status_code in {200, 201}
    session = start_response.json()
    exercise = session["exercise"]
    filled_blanks = {
        "blank_1": "addEventListener",
        "blank_2": "count += 1",
    }
    code = exercise["solution_reference"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": code,
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    run_body = run_response.json()
    assert run_body["attempt_type"] == "run"
    assert run_body["runtime_status"] == "success"
    assert run_body["test_pass_rate"] == 1.0
    assert run_body["passed_test_count"] == run_body["total_test_count"] == 3

    explanation_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation_response.status_code == 200
    explanation_body = explanation_response.json()
    assert explanation_body["result"] == "passed"
    assert explanation_body["score"] == 2

    submit_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run_body["attempt_id"],
            "code": code,
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    result = submit_body["code_completion_result"]
    assert result["result"] in {"passed", "easy"}
    assert result["next_action"] == "schedule_review"
    assert result["fsrs_rating"] in {"Good", "Easy"}
    assert submit_body["KnowledgePoint"]["status"] == "reviewing"
    assert submit_body["ReviewState"]["last_attempt_id"] == submit_body["attempt_id"]

    with connect() as conn:
        attempt_rows = conn.execute(
            """
            SELECT attempt_type, score, fsrs_rating
            FROM attempts
            WHERE session_id = %s AND exercise_id = %s
            ORDER BY created_at
            """,
            (session["session_id"], exercise["id"]),
        ).fetchall()
        review_state = conn.execute(
            """
            SELECT last_attempt_id, last_fsrs_rating
            FROM review_states
            WHERE knowledge_point_id = %s
            """,
            (knowledge_point_id,),
        ).fetchone()
    assert [row["attempt_type"] for row in attempt_rows] == ["run", "submit"]
    assert attempt_rows[1]["score"] >= 6
    assert attempt_rows[1]["fsrs_rating"] in {"Good", "Easy"}
    assert review_state is not None
    assert str(review_state["last_attempt_id"]) == submit_body["attempt_id"]


def test_hint_endpoint_is_idempotent_and_accumulates_hint_count(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["starter_code"],
            "filled_blanks": {},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    run_body = run_response.json()

    first_hint = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
        json={
            "attempt_id": run_body["attempt_id"],
            "current_code": exercise["starter_code"],
            "blank_id": "blank_2",
            "hint_level": "concept",
        },
    )
    assert first_hint.status_code == 200
    first_hint_body = first_hint.json()
    assert first_hint_body["hint_usage_count"] == 1
    assert first_hint_body["hint"]["hint_level"] == "concept"

    replayed_hint = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
        json={
            "attempt_id": run_body["attempt_id"],
            "current_code": exercise["starter_code"],
            "blank_id": "blank_2",
            "hint_level": "concept",
        },
    )
    assert replayed_hint.status_code == 200
    replayed_body = replayed_hint.json()
    assert replayed_body["hint_usage_count"] == 1
    assert replayed_body["idempotency_replayed"] is True

    second_hint = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
        json={
            "attempt_id": run_body["attempt_id"],
            "current_code": exercise["starter_code"],
            "blank_id": "blank_1",
            "hint_level": "code_shape",
        },
    )
    assert second_hint.status_code == 200
    assert second_hint.json()["hint_usage_count"] == 2


def test_hidden_failure_can_be_explained_without_leaking_hidden_source(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]
    flawed_code = (
        "const button = document.querySelector(\"#counter-button\");\n"
        "const output = document.querySelector(\"#counter-output\");\n\n"
        "button.addEventListener(\"click\", () => {\n"
        "  let count = 0;\n"
        "  count += 1;\n"
        "  output.textContent = String(count);\n"
        "});\n"
    )

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": flawed_code,
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    run_body = run_response.json()
    assert run_body["runtime_status"] == "success"
    assert run_body["test_pass_rate"] < 1.0
    failed_tests = [item for item in run_body["test_results"] if not item["passed"]]
    assert failed_tests

    explain_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/explain-error",
        json={
            "error_message": run_body["error_message"],
            "stderr": run_body["stderr"],
            "failed_tests": [
                {
                    "case_id": item["case_id"],
                    "case_type": item["case_type"],
                    "message": item["message"],
                }
                for item in failed_tests
            ],
            "current_code": flawed_code,
        },
    )
    assert explain_response.status_code == 200
    explain_body = explain_response.json()
    assert explain_body["error_cause"] == "state_scope_error"
    assert "回调外层" in explain_body["fix_suggestion"] or "回调外" in explain_body["fix_suggestion"]


def test_python_runtime_error_can_be_explained(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="python")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]
    broken_code = "def summarize_scores(scores)\n    return total\n"

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": broken_code,
            "filled_blanks": {"blank_1": "total"},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    run_body = run_response.json()
    assert run_body["runtime_status"] == "runtime_error"

    explain_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/explain-error",
        json={
            "error_message": run_body["error_message"],
            "stderr": run_body["stderr"],
            "failed_tests": [],
            "current_code": broken_code,
        },
    )
    assert explain_response.status_code == 200
    explain_body = explain_response.json()
    assert explain_body["error_cause"] == "python_syntax_error"


def test_explanation_round_limit_and_partial_submit(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()

    first_round = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "因为这样写比较方便。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert first_round.status_code == 200
    assert first_round.json()["result"] in {"partial", "failed"}
    assert first_round.json()["follow_up_required"] is True

    second_round = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "我知道要这样写，但还说不清为什么。",
            "focus": "core_logic",
            "round": 2,
        },
    )
    assert second_round.status_code == 200
    assert second_round.json()["result"] in {"partial", "failed"}

    third_round = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "第三轮继续试。",
            "focus": "core_logic",
            "round": 3,
        },
    )
    assert third_round.status_code == 422
    assert third_round.json()["error"]["code"] == "EVALUATION_CONFLICT"

    submit_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run_body["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "submit_version": 1,
            "explanation": "我知道要这样写，但还说不清为什么。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["code_completion_result"]["result"] == "partial"
    assert submit_body["code_completion_result"]["hard_gates"]["explanation_gate"] is False
    assert submit_body["next_action"] == "review_variant"


def test_many_hints_degrade_fsrs_rating(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()

    for blank_id, hint_level in [("blank_1", "nudge"), ("blank_2", "concept"), ("blank_2", "code_shape")]:
        hint_response = client.post(
            f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
            json={
                "attempt_id": run_body["attempt_id"],
                "current_code": exercise["solution_reference"],
                "blank_id": blank_id,
                "hint_level": hint_level,
            },
        )
        assert hint_response.status_code == 200

    explanation_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation_response.status_code == 200
    assert explanation_response.json()["result"] == "passed"

    submit_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run_body["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["code_completion_result"]["hint_usage_count"] >= 3
    assert submit_body["code_completion_result"]["fsrs_rating"] == "Hard"
    assert submit_body["next_action"] == "review_variant"


def test_core_blank_failure_stays_failed_even_with_explanation(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]
    wrong_code = exercise["solution_reference"].replace("count += 1", "count = 1")

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": wrong_code,
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count = 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()
    assert run_body["runtime_status"] == "success"

    explanation_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "我把 count 放在回调外层，但这里没有累加。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation_response.status_code == 200

    submit_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run_body["attempt_id"],
            "code": wrong_code,
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count = 1",
            },
            "submit_version": 1,
            "explanation": "我把 count 放在回调外层，但这里没有累加。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit_response.status_code == 200
    submit_body = submit_response.json()
    assert submit_body["code_completion_result"]["result"] == "failed"
    assert submit_body["code_completion_result"]["hard_gates"]["core_blank_gate"] is False


def test_submit_rolls_back_when_learning_record_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    bootstrap_database()
    client = TestClient(app, raise_server_exceptions=False)
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start_response.json()
    exercise = session["exercise"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()

    explanation_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation_response.status_code == 200

    def fail_update(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced failure")

    monkeypatch.setattr(session_repository, "_update_learning_records", fail_update)

    submit_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run_body["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit_response.status_code == 500

    with connect() as conn:
        attempt_rows = conn.execute(
            """
            SELECT attempt_type
            FROM attempts
            WHERE session_id = %s AND exercise_id = %s
            ORDER BY created_at
            """,
            (session["session_id"], exercise["id"]),
        ).fetchall()
    assert [row["attempt_type"] for row in attempt_rows] == ["run"]


def test_distinct_run_payloads_create_distinct_attempts(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert start_response.status_code in {200, 201}
    session = start_response.json()
    exercise = session["exercise"]

    first_run = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["starter_code"],
            "filled_blanks": {},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert first_run.status_code == 201

    second_run = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert second_run.status_code == 201
    assert second_run.json()["attempt_id"] != first_run.json()["attempt_id"]

    with connect() as conn:
        attempt_rows = conn.execute(
            """
            SELECT id
            FROM attempts
            WHERE session_id = %s AND exercise_id = %s AND attempt_type = 'run'
            ORDER BY created_at
            """,
            (session["session_id"], exercise["id"]),
        ).fetchall()
    assert len(attempt_rows) == 2


def test_python_run_returns_stdout_and_test_summary(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="python")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert start_response.status_code in {200, 201}
    session = start_response.json()
    exercise = session["exercise"]
    filled_blanks = {"blank_1": "total"}
    code = exercise["solution_reference"]

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": code,
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    body = run_response.json()
    assert body["runtime_status"] == "success"
    assert body["stdout"] == "total=9"
    assert body["test_pass_rate"] == 1.0
    assert body["total_test_count"] == 2


def test_compiled_later_runtime_returns_unsupported_boundary(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="java")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start_response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert start_response.status_code in {200, 201}
    session = start_response.json()
    exercise = session["exercise"]
    assert exercise["runtime_profile"]["runtime_tier"] == "compiled_sandbox_later"

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {"blank_1": "value + 1"},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run_response.status_code == 201
    body = run_response.json()
    assert body["runtime_status"] == "unsupported"
    assert body["test_pass_rate"] == 0.0
    assert body["next_action"] == "retry_same"

    with connect() as conn:
        knowledge_point = conn.execute(
            """
            SELECT last_exercise_result
            FROM knowledge_points
            WHERE id = %s
            """,
            (knowledge_point_id,),
        ).fetchone()
    assert knowledge_point is not None
    assert knowledge_point["last_exercise_result"] is None


def _confirmed_plan(client: TestClient, *, language: str) -> tuple[dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, language)
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": f"Practice {language} learning session runtime validation.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm_response = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm_response.status_code == 201
    return user, confirm_response.json()


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"M3 User {uuid.uuid4().hex[:8]}",
            "learning_style": "practice_first",
            "teaching_preference": "step_by_step",
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
