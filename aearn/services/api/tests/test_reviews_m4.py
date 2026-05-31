import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services import learning_conversation, learning_session_repository, review_repository, review_seed_bank
from app.services.review_scheduler import apply_attempt_review_update


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
def disable_review_coach_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLearningConversationClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del messages, temperature
            return ["我会生成当前练习，并保持讲解聚焦在可见题面。"]

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": f"这次复习围绕 {context.knowledge_point_title}，先用变体题验证你是否真的能接管这类代码。",
            "variant_reason": "本次不重复聊天问答，改用同构代码练习检查是否能独立验证。",
            "generation_source": "llm",
            "generation_model": "fake-review-coach",
        },
    )
    monkeypatch.setattr(plans_route, "build_sdk_plan_generation_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(plans_route, "build_sdk_onboarding_plan_response", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        learning_session_repository,
        "build_sdk_explanation_check_response",
        lambda *args, **kwargs: {
            "result": "passed",
            "score": 2,
            "score_breakdown": {"explanation_check": 2},
            "follow_up_required": False,
            "feedback": "解释覆盖了状态作用域和连续点击行为。",
            "next_action": "submit",
        },
    )
    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
        ),
    )
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: FakeLearningConversationClient(),
    )


def test_today_reviews_returns_empty_and_sorted_due_items(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    first_kp_id = plan["knowledge_points"][0]["id"]
    second_kp_id = plan["knowledge_points"][1]["id"]

    empty = client.get(f"/api/reviews/today?user_id={user['id']}")
    assert empty.status_code == 200
    assert empty.json()["items"] == []

    with connect() as conn:
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '20 minutes',
                last_fsrs_rating = 'Good',
                reps = 2
            WHERE knowledge_point_id = %s
            """,
            (first_kp_id,),
        )
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '10 minutes',
                last_fsrs_rating = 'Hard',
                reps = 1
            WHERE knowledge_point_id = %s
            """,
            (second_kp_id,),
        )
        conn.execute(
            """
            UPDATE knowledge_points
            SET status = 'reviewing'
            WHERE id IN (%s, %s)
            """,
            (first_kp_id, second_kp_id),
        )
        conn.commit()

    due = client.get(f"/api/reviews/today?user_id={user['id']}")
    assert due.status_code == 200
    body = due.json()
    assert [item["KnowledgePoint"]["id"] for item in body["items"][:2]] == [first_kp_id, second_kp_id]
    assert body["items"][0]["ReviewState"]["review_count"] == 2
    assert body["timezone"] == "Asia/Shanghai"


def test_review_start_requires_due_state_and_reuses_active_session(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]

    early = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert early.status_code == 409
    assert early.json()["error"]["code"] == "REVIEW_NOT_DUE"

    _mark_due(knowledge_point_id)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["session_type"] == "review"
    assert created_body["knowledge_point"]["id"] == knowledge_point_id
    assert created_body["review_exercise"]["knowledge_point_id"] == knowledge_point_id
    assert created_body["review_stage"] == "warmup"
    assert created_body["warmup"]["result"] == "pending"
    assert created_body["selected_seed_id"]
    assert created_body["seed_bank"]["status"] == "ready"
    assert created_body["variant_reason"]
    assert created_body["initial_agent_message"].startswith("这次复习围绕 ")

    replayed = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert replayed.status_code == 200
    replayed_body = replayed.json()
    assert replayed_body["session_id"] == created_body["session_id"]
    assert replayed_body["selected_seed_id"] == created_body["selected_seed_id"]
    assert replayed_body["warmup"] == created_body["warmup"]


def test_review_start_uses_sdk_review_coach_text_when_available(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": "先看状态变量的变体题，别急着提交。",
            "variant_reason": "上次薄弱点是 state_scope_error。",
            "coaching_text": "先对照上次错因再动手。",
            "generation_source": "llm",
            "generation_model": "sdk-review-model",
        },
    )

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["initial_agent_message"] == "先看状态变量的变体题，别急着提交。"
    assert created_body["variant_reason"] == "上次薄弱点是 state_scope_error。"


def test_review_start_returns_model_unavailable_when_sdk_review_text_leaks_answer(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    monkeypatch.setattr(
        review_repository,
        "build_sdk_review_coach_response",
        lambda context: {
            "initial_agent_message": "完整答案如下：直接把 count 放在回调内部。",
            "variant_reason": "失败来自 hidden_three_clicks。",
        },
    )

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 503
    body = created.json()
    assert body["error"]["code"] == "MODEL_UNAVAILABLE"


def test_review_start_returns_seed_bank_generation_failed_without_fallback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    def raise_generation_failure(context: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, object]]:
        del context
        raise review_seed_bank.ReviewSeedBankValidationError("unsafe generated payload")

    monkeypatch.setattr(review_seed_bank, "build_review_seed_bank_payload", raise_generation_failure)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 503
    body = created.json()
    assert body["error"]["code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"
    assert "review_exercise" not in body

    with connect() as conn:
        bank = conn.execute(
            """
            SELECT status, seed_count, failure_code
            FROM review_seed_banks
            WHERE user_id = %s AND knowledge_point_id = %s
            """,
            (user["id"], knowledge_point_id),
        ).fetchone()
    assert bank is not None
    assert bank["status"] == "failed"
    assert bank["seed_count"] == 0
    assert bank["failure_code"] == "REVIEW_SEED_BANK_GENERATION_FAILED"


def test_review_warmup_branches_do_not_create_fsrs_evidence(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=4)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    skipped = client.post(f"/api/reviews/{session_id}/warmup-result", json={"action": "skip"})
    assert skipped.status_code == 200
    skipped_body = skipped.json()
    assert skipped_body["review_stage"] == "variant_practice"
    assert skipped_body["warmup"]["result"] == "skipped"

    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (session_id, knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert counts is not None
    assert counts["attempt_count"] == 0
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 4

    with connect() as conn:
        conn.execute("UPDATE learning_sessions SET status = 'finished' WHERE id = %s", (session_id,))
        conn.commit()

    again = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert again.status_code == 201
    repair_session_id = again.json()["session_id"]

    first_wrong = client.post(
        f"/api/reviews/{repair_session_id}/warmup-result",
        json={"action": "answer", "answer": "随便试一下"},
    )
    assert first_wrong.status_code == 200
    assert first_wrong.json()["review_stage"] == "warmup_repair"
    assert first_wrong.json()["warmup"]["repair_count"] == 1

    second_wrong = client.post(
        f"/api/reviews/{repair_session_id}/warmup-result",
        json={"action": "answer", "answer": "还是随便猜"},
    )
    assert second_wrong.status_code == 200
    second_body = second_wrong.json()
    assert second_body["review_stage"] == "variant_practice"
    assert second_body["review_stage_state"]["variant"]["guided"] is True


def test_review_warmup_unclear_judgement_does_not_advance_stage(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=3)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    session_id = start.json()["session_id"]

    unclear = client.post(
        f"/api/reviews/{session_id}/warmup-result",
        json={"action": "answer", "answer": "不知道"},
    )
    assert unclear.status_code == 200
    body = unclear.json()
    assert body["review_stage"] == "warmup"
    assert body["warmup"]["result"] == "unclear"
    assert body["warmup"]["judgement_ready"] is False
    assert body["next_action"] == "retry_same"

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT review_stage, review_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (session_id,),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (session_id, knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert stored is not None
    assert stored["review_stage"] == "warmup"
    assert stored["review_stage_state_json"]["warmup"]["result"] == "pending"
    assert counts is not None
    assert counts["attempt_count"] == 0
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 3


def test_review_ai_patch_scoring_requires_grounded_evidence(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=1)
    with connect() as conn:
        conn.execute(
            "UPDATE knowledge_points SET weak_points_json = %s::jsonb WHERE id = %s",
            (json.dumps(["review_patch_evidence"]), knowledge_point_id),
        )
        conn.commit()

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = review_session["review_exercise"]
    assert exercise["exercise_type"] == "review_ai_patch"
    metadata = exercise["metadata_json"]
    assert metadata["requirement"]
    assert metadata["ai_diff"]
    assert "rubric" in metadata
    assert not exercise["solution_reference"]

    payload = {
        "exercise_id": exercise["id"],
        "submit_version": 1,
        "review_ai_patch_answer": {
            "verdict": "fail",
            "evidence": "tests passed",
            "knowledge_point_risk": "状态作用域风险",
            "next_action": "request_change",
        },
    }
    submitted = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert submitted.status_code == 200
    submit_body = submitted.json()
    assert submit_body["score_breakdown"]["verdict_correctness"] == 2
    assert submit_body["score_breakdown"]["evidence_grounding"] == 1
    assert submit_body["fsrs_rating"] == "Hard"
    assert submit_body["result"] == "partial"
    assert submit_body["code_completion_result"]["review_ai_patch_result"]["evidence_quality"] == "weak"

    replayed = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_replayed"] is True
    assert replayed.json()["ReviewState"]["review_count"] == 2

    with connect() as conn:
        attempt = conn.execute(
            """
            SELECT attempt_type, code_completion_result, fsrs_rating
            FROM attempts
            WHERE id = %s
            """,
            (submit_body["attempt_id"],),
        ).fetchone()
    assert attempt is not None
    assert attempt["attempt_type"] == "review_submit"
    assert attempt["fsrs_rating"] == "Hard"
    assert attempt["code_completion_result"]["score_breakdown"]["actionability"] == 2


def test_review_run_and_submit_updates_schedule_once(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = review_session["review_exercise"]
    filled_blanks = _filled_blanks_for(exercise)

    run = client.post(
        f"/api/learning-sessions/{review_session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201
    run_body = run.json()
    assert run_body["attempt_type"] == "run"
    assert run_body["runtime_status"] == "success"

    payload = {
        "exercise_id": exercise["id"],
        "attempt_id": run_body["attempt_id"],
        "code": exercise["solution_reference"],
        "filled_blanks": filled_blanks,
        "submit_version": 1,
        "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
        "hint_usage_count": 0,
        "error_count": 0,
        "explanation_check": {
            "result": "passed",
            "score": 2,
            "feedback": "能解释状态共享原因。",
        },
    }
    submitted = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert submitted.status_code == 200
    submit_body = submitted.json()
    assert submit_body["fsrs_rating"] in {"Good", "Easy"}
    assert submit_body["ReviewState"]["last_attempt_id"] == submit_body["attempt_id"]
    assert submit_body["ReviewState"]["review_count"] == 3
    assert submit_body["due_at"] == submit_body["ReviewState"]["due_at"]
    assert submit_body["forget_risk"] in {"low", "normal", "high"}

    replayed = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)
    assert replayed.status_code == 200
    assert replayed.json()["idempotency_replayed"] is True
    assert replayed.json()["ReviewState"]["review_count"] == 3

    with connect() as conn:
        state = conn.execute(
            "SELECT reps, last_attempt_id FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
        log_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM review_logs
            WHERE attempt_id = %s AND source = 'review_submit'
            """,
            (submit_body["attempt_id"],),
        ).fetchone()
    assert state is not None
    assert state["reps"] == 3
    assert str(state["last_attempt_id"]) == submit_body["attempt_id"]
    assert log_count is not None
    assert log_count["count"] == 1


def test_review_submit_blocked_explanation_judgement_does_not_write_attempt(
    client: TestClient,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = review_session["review_exercise"]
    filled_blanks = _filled_blanks_for(exercise)

    run = client.post(
        f"/api/learning-sessions/{review_session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201

    payload = {
        "exercise_id": exercise["id"],
        "attempt_id": run.json()["attempt_id"],
        "code": exercise["solution_reference"],
        "filled_blanks": filled_blanks,
        "submit_version": 1,
        "explanation": "状态变量会共享。",
        "hint_usage_count": 0,
        "error_count": 0,
        "explanation_check": {
            "result": "passed",
            "score": 2,
            "feedback": "反馈不足以确认薄弱点。",
            "judgements": {
                "review_explanation_sufficiency": {
                    "status": "ambiguous",
                    "clarification_question": "请再补充这次提交为什么能覆盖状态作用域风险。",
                },
                "weak_point_signal": {"status": "confirmed"},
                "repair_needed": {"status": "confirmed"},
            },
        },
    }
    submitted = client.post(f"/api/reviews/{review_session['session_id']}/exercise-result", json=payload)

    assert submitted.status_code == 200
    body = submitted.json()
    assert body["judgement_ready"] is False
    assert body["next_action"] == "retry_same"
    assert "attempt_id" not in body

    with connect() as conn:
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM attempts WHERE session_id = %s) AS attempt_count,
              (SELECT count(*) FROM review_logs WHERE knowledge_point_id = %s) AS review_log_count,
              (SELECT reps FROM review_states WHERE knowledge_point_id = %s) AS reps
            """,
            (review_session["session_id"], knowledge_point_id, knowledge_point_id),
        ).fetchone()
    assert counts is not None
    assert counts["attempt_count"] == 1
    assert counts["review_log_count"] == 0
    assert counts["reps"] == 2


def test_run_attempt_does_not_update_review_state_and_scheduler_is_idempotent(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    start = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    session = start.json()
    exercise = _unlock_practice_exercise(client, session)
    filled_blanks = _filled_blanks_for(exercise)

    run = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201

    with connect() as conn:
        state_after_run = conn.execute(
            "SELECT reps, last_attempt_id FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
    assert state_after_run is not None
    assert state_after_run["reps"] == 0
    assert state_after_run["last_attempt_id"] is None

    explanation = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run.json()['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation.status_code == 200
    submit = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submit.status_code == 200
    submit_body = submit.json()

    with connect() as conn:
        replayed = apply_attempt_review_update(
            conn,
            knowledge_point_id=knowledge_point_id,
            attempt_id=submit_body["attempt_id"],
            source="learn_submit",
            request_id=None,
        )
        conn.commit()
        state_after_replay = conn.execute(
            "SELECT reps FROM review_states WHERE knowledge_point_id = %s",
            (knowledge_point_id,),
        ).fetchone()
        log_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM review_logs
            WHERE attempt_id = %s AND source = 'learn_submit'
            """,
            (submit_body["attempt_id"],),
        ).fetchone()
    assert replayed["ReviewState"]["review_count"] == 1
    assert state_after_replay is not None
    assert state_after_replay["reps"] == 1
    assert log_count is not None
    assert log_count["count"] == 1


def _confirmed_plan(client: TestClient, *, language: str) -> tuple[dict[str, object], dict[str, object]]:
    user = _create_user(client)
    course = _course_by_language(client, language)
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": f"Practice {language} review scheduling validation.",
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
            "display_name": f"M4 User {uuid.uuid4().hex[:8]}",
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


def _unlock_practice_exercise(client: TestClient, session: dict[str, object]) -> dict[str, object]:
    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "开始练习，给我题。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_state"]["learning_stage"] == "practice_support"
    tool_calls = body["tool_calls"]
    exercise_tool_call = next(
        (tool_call for tool_call in tool_calls if tool_call["name"] == "show_code_exercise"),
        None,
    )
    assert exercise_tool_call is not None
    exercise = exercise_tool_call["args"]["exercise"]
    assert isinstance(exercise, dict)
    return exercise


def _mark_due(knowledge_point_id: str, *, reps: int = 1) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE review_states
            SET card_state = 'review',
                due_at = now() - interval '5 minutes',
                last_fsrs_rating = 'Good',
                reps = %s
            WHERE knowledge_point_id = %s
            """,
            (reps, knowledge_point_id),
        )
        conn.execute(
            "UPDATE knowledge_points SET status = 'reviewing' WHERE id = %s",
            (knowledge_point_id,),
        )
        conn.commit()


def _filled_blanks_for(exercise: dict[str, object]) -> dict[str, str]:
    blanks = exercise["code_blanks"]
    assert isinstance(blanks, list)
    result: dict[str, str] = {}
    for blank in blanks:
        assert isinstance(blank, dict)
        result[str(blank["blank_key"])] = str(blank["placeholder"])
    return result
