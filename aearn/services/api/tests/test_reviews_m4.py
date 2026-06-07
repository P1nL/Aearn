import json
import uuid
from collections.abc import Mapping

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
import app.routes.reviews as reviews_route
from app.agents.learning.learning_public_output import learning_public_output_json
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.services.conversations import learning_conversation
from app.services.curriculum.dynamic_plan_generation import DynamicPlanDraftResult
from app.services.curriculum.plan_generator import build_plan_draft
from app.services.repositories import learning_session_repository, review_repository, review_seed_bank
from app.services.repositories.learner_profile import get_learner_profile
from app.services.repositories.review_scheduler import apply_attempt_review_update


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

        def complete_structured_text_stream(self, messages, *, output_type, temperature=None):  # type: ignore[no-untyped-def]
            del output_type
            public_message = "".join(self.complete_text_stream(messages, temperature=temperature))
            return [learning_public_output_json(public_message)]

    def fake_concept_intro(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        del args, kwargs
        return {
            "summary": "事件绑定会把一次用户动作连接到回调函数，状态变量决定多次动作之间是否共享记忆。",
            "example": {
                "title": "计数按钮",
                "body": "count 放在回调外面时，每次点击都会基于同一个 count 继续累加。",
                "takeaway": "先看状态放在哪里，再看事件什么时候触发回调。",
            },
            "check": {
                "type": "single_choice",
                "question": "如果 count 写在点击回调里面，每次点击最可能发生什么？",
                "options": [
                    {"id": "A", "text": "每次点击都重新从初始值开始。"},
                    {"id": "B", "text": "每次点击都会复用上一次回调里的局部变量。"},
                    {"id": "C", "text": "事件监听器不会再触发。"},
                ],
                "expected_focus": "回调作用域与跨点击状态共享的关系",
            },
        }

    monkeypatch.setattr(learning_session_repository, "build_sdk_concept_intro", fake_concept_intro)
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
    monkeypatch.setattr(plans_route, "build_dynamic_plan_draft", _fake_dynamic_plan_draft)
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


def _fake_dynamic_plan_draft(payload, user, course, **kwargs):  # type: ignore[no-untyped-def]
    del kwargs
    plan_draft = build_plan_draft(payload, user, course)
    return DynamicPlanDraftResult(
        plan_draft=plan_draft,
        agent_notes=[plan_draft.runtime_boundary.notice, "Test fake dynamic plan."],
    )


def _fake_model_review_seeds(context: Mapping[str, object]) -> list[dict[str, object]]:
    runtime_profile = context.get("runtime_profile")
    runtime_profile = runtime_profile if isinstance(runtime_profile, Mapping) else {}
    language = str(runtime_profile.get("language") or "javascript")
    runtime_tier = str(runtime_profile.get("runtime_tier") or "browser_preview")
    knowledge_point_id = str(context["knowledge_point_id"])
    title = str(context.get("knowledge_point_title") or "Review concept")
    supported = context.get("supported_exercise_types")
    supported_types = [str(item) for item in supported] if isinstance(supported, list) else ["code_blank"]
    preferred = ["code_blank", "fix_bug", "review_ai_patch", "explain_code", "implement_function"]
    type_cycle = [exercise_type for exercise_type in preferred if exercise_type in supported_types] or [supported_types[0]]
    target_seed_count = int(context.get("target_seed_count") or 8)

    seeds: list[dict[str, object]] = []
    for index in range(target_seed_count):
        exercise_type = type_cycle[index % len(type_cycle)]
        if exercise_type == "review_ai_patch":
            seed = _fake_model_review_patch_seed(
                knowledge_point_id=knowledge_point_id,
                title=title,
                language=language,
                runtime_tier=runtime_tier,
                index=index,
            )
        else:
            seed = _fake_model_practice_seed(
                knowledge_point_id=knowledge_point_id,
                title=title,
                language=language,
                runtime_tier=runtime_tier,
                exercise_type=exercise_type,
                index=index,
            )
        seeds.append(seed)
    return seeds


def _fake_model_practice_seed(
    *,
    knowledge_point_id: str,
    title: str,
    language: str,
    runtime_tier: str,
    exercise_type: str,
    index: int,
) -> dict[str, object]:
    seed_id = f"fake_model_{exercise_type}_{index + 1:02d}"
    if language == "python":
        starter_code = "def summarize_scores(scores):\n    total = sum(scores)\n    return __BLANK_1__\n"
        required_patterns = ["return total"]
        code_blanks = [
            {
                "blank_key": "blank_1",
                "placeholder": "total",
                "expected_concept": "Return the computed total so callers can use it.",
                "acceptable_patterns_json": [{"type": "literal", "value": "total"}],
                "is_core": True,
                "order_index": 0,
            }
        ]
        test_cases = [_fake_visible_case({"scores": [2, 3, 4]}, {"return": 9})]
    else:
        starter_code = (
            "const button = document.querySelector(\"#counter-button\");\n"
            "const output = document.querySelector(\"#counter-output\");\n"
            "let count = 0;\n\n"
            "button.__BLANK_1__(\"click\", () => {\n"
            "  __BLANK_2__;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
        required_patterns = ["addEventListener", "count += 1", "output.textContent"]
        code_blanks = [
            {
                "blank_key": "blank_1",
                "placeholder": "addEventListener",
                "expected_concept": "Bind the click listener to the button.",
                "acceptable_patterns_json": [{"type": "literal", "value": "addEventListener"}],
                "is_core": True,
                "order_index": 0,
            },
            {
                "blank_key": "blank_2",
                "placeholder": "count += 1",
                "expected_concept": "Increment the shared counter inside the event callback.",
                "acceptable_patterns_json": [{"type": "literal", "value": "count += 1"}],
                "is_core": True,
                "order_index": 1,
            },
        ]
        test_cases = [
            _fake_visible_case({"event": "click"}, {"textContent": "1"}),
            _fake_preview_case({"selector": "#counter-output"}, {"textContent": "1"}, order_index=1),
        ]
    return {
        "id": seed_id,
        "exercise_type": exercise_type,
        "difficulty": 2 + (index % 3),
        "target_misconception": f"model_context_gap_{index}",
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "title": f"{title}: model-generated {exercise_type}",
        "warmup_question": f"Before the model-generated variant {index + 1}, recall what state must stay observable.",
        "warmup_expected_focus": "State, return value, or evidence must match the visible behavior.",
        "warmup_keywords": ["state", "return", "evidence"],
        "review_focus": "Use the latest learner state to target the fragile concept.",
        "prompt_markdown": f"Model-generated review seed {index + 1}: complete the {exercise_type} task for **{title}**.",
        "starter_code": starter_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "required_patterns": required_patterns,
            "browser_rule_family": "js_event_flow" if language != "python" else "",
            "review_focus": "latest learner state",
        },
        "code_blanks": code_blanks,
        "test_cases": test_cases,
    }


def _fake_model_review_patch_seed(
    *,
    knowledge_point_id: str,
    title: str,
    language: str,
    runtime_tier: str,
    index: int,
) -> dict[str, object]:
    if language == "python":
        original_code = "def summarize_scores(scores):\n    total = sum(scores)\n    return total\n"
        ai_diff = "-    return total\n+    print(total)\n+    return None"
        expected_risk = "The caller loses the function return value."
    else:
        original_code = (
            "let count = 0;\n"
            "button.addEventListener(\"click\", () => {\n"
            "  count += 1;\n"
            "  output.textContent = String(count);\n"
            "});\n"
        )
        ai_diff = "-let count = 0;\n button.addEventListener(\"click\", () => {\n+  let count = 0;\n   count += 1;"
        expected_risk = "The counter is recreated on every click, so repeated clicks do not accumulate."
    rubric = {
        "verdict_correctness": "0-2",
        "evidence_grounding": "0-2",
        "knowledge_point_alignment": "0-2",
        "actionability": "0-2",
    }
    return {
        "id": f"fake_model_review_ai_patch_{index + 1:02d}",
        "exercise_type": "review_ai_patch",
        "difficulty": 4,
        "target_misconception": "review_patch_evidence",
        "knowledge_point_id": knowledge_point_id,
        "runtime_tier": runtime_tier,
        "title": f"{title}: model-generated AI patch review",
        "warmup_question": "What evidence should you inspect before accepting an AI patch?",
        "warmup_expected_focus": "Use the requirement, diff, and visible behavior together.",
        "warmup_keywords": ["requirement", "diff", "evidence"],
        "review_focus": "Ground the verdict in the requirement and diff.",
        "prompt_markdown": f"Model-generated review seed {index + 1}: audit the AI patch for **{title}**.",
        "starter_code": original_code,
        "visible_test_policy": "visible_only",
        "requires_explanation": True,
        "metadata": {
            "requirement": "Keep the observable behavior and preserve the concept under review.",
            "original_code": original_code,
            "ai_diff": ai_diff,
            "review_focus": "Ground the verdict in requirement, diff, and behavior.",
            "expected_risk": expected_risk,
            "expected_verdict": "fail",
            "expected_next_action": "request_change",
            "rubric": rubric,
        },
        "rubric": rubric,
        "code_blanks": [],
        "test_cases": [],
    }


def _fake_visible_case(input_json: Mapping[str, object], expected_output_json: Mapping[str, object]) -> dict[str, object]:
    return {
        "case_type": "visible",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": True,
        "timeout_ms": 5000,
        "order_index": 0,
    }


def _fake_preview_case(
    input_json: Mapping[str, object],
    expected_output_json: Mapping[str, object],
    *,
    order_index: int,
) -> dict[str, object]:
    return {
        "case_type": "preview_assertion",
        "input_json": dict(input_json),
        "expected_output_json": dict(expected_output_json),
        "assertion_code": None,
        "weight": 1,
        "is_critical": False,
        "timeout_ms": 5000,
        "order_index": order_index,
    }


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
    assert created_body["seed_bank"]["generator_version"] == "review_seed_bank_model_v2"
    assert "模型生成复习题" in created_body["review_exercise"]["prompt_markdown"]
    assert created_body["review_exercise"]["metadata_json"]["seed_generator_version"] == "review_seed_bank_model_v2"
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

    def raise_generation_failure(context: Mapping[str, object]) -> None:
        del context
        return None

    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", raise_generation_failure)

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


def test_review_seed_bank_model_context_adapts_to_learner_state(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    learning = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )
    assert learning.status_code == 201
    exercise = _unlock_practice_exercise(client, learning.json())
    filled_blanks = _filled_blanks_for(exercise)
    run = client.post(
        f"/api/learning-sessions/{learning.json()['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    assert run.status_code == 201
    submitted = client.post(
        f"/api/learning-sessions/{learning.json()['session_id']}/exercises/{exercise['id']}/submit",
        json={
            "attempt_id": run.json()["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": "状态变量放在回调外层，所以多次点击会共享同一个 count。",
            "hint_usage_count": 0,
            "error_count": 0,
        },
    )
    assert submitted.status_code == 200
    attempt_id = submitted.json()["attempt_id"]
    _mark_due(knowledge_point_id, reps=4)
    with connect() as conn:
        conn.execute(
            """
            UPDATE knowledge_points
            SET weak_points_json = %s::jsonb,
                mastery_score = 0.31
            WHERE id = %s
            """,
            (json.dumps(["state_scope_error", "test_evidence_gap"]), knowledge_point_id),
        )
        conn.execute(
            """
            UPDATE review_states
            SET last_attempt_id = %s,
                last_fsrs_rating = 'Again',
                reps = 4,
                lapses = 2
            WHERE knowledge_point_id = %s
            """,
            (attempt_id, knowledge_point_id),
        )
        conn.commit()

    captured: dict[str, object] = {}
    fake_generator = review_seed_bank.build_model_review_seed_bank

    def capture_generation_context(context: Mapping[str, object]):  # type: ignore[no-untyped-def]
        captured["context"] = context
        return fake_generator(context)

    monkeypatch.setattr(review_seed_bank, "build_model_review_seed_bank", capture_generation_context)

    started = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert started.status_code == 201
    started_body = started.json()
    context = captured["context"]
    assert isinstance(context, dict)
    learner_state = context["learner_state"]
    runtime_profile = context["runtime_profile"]
    assert isinstance(learner_state, dict)
    assert isinstance(runtime_profile, dict)
    assert learner_state["weak_points"] == ["state_scope_error", "test_evidence_gap"]
    assert learner_state["mastery_score"] == 0.31
    assert learner_state["last_fsrs_rating"] == "Again"
    assert learner_state["review_count"] == 4
    assert learner_state["lapse_count"] == 2
    assert learner_state["latest_attempt"]["attempt_id"] == attempt_id
    assert runtime_profile["language"] == "javascript"
    assert runtime_profile["runtime_tier"] == "browser_preview"
    assert context["target_seed_count"] == 12
    assert "模型生成" in started_body["review_exercise"]["title"]
    assert started_body["seed_bank"]["quality_report"]["generation_source"] == "llm"
    assert started_body["seed_bank"]["quality_report"]["generation_model"] == "fake-review-seed-model"


def test_review_messages_replay_start_and_warmup_history(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)

    created = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201
    review_session = created.json()
    session_id = review_session["session_id"]

    history = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert [message["role"] for message in messages[:2]] == ["agent", "agent"]
    assert messages[0]["content"] == review_session["initial_agent_message"]
    assert review_session["warmup"]["question"] in messages[1]["content"]

    replayed = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert replayed.status_code == 200
    replay_history = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert replay_history.status_code == 200
    assert len(replay_history.json()["messages"]) == len(messages)

    warmup = client.post(
        f"/api/reviews/{session_id}/warmup-result",
        json={"user_id": user["id"], "action": "answer", "answer": "不太确定"},
    )
    assert warmup.status_code == 200
    after_warmup = client.get(f"/api/reviews/{session_id}/messages", params={"user_id": user["id"]})
    assert after_warmup.status_code == 200
    serialized = json.dumps(after_warmup.json(), ensure_ascii=False)
    assert "不太确定" in serialized
    assert warmup.json()["warmup"]["feedback"] in serialized


def test_review_messages_cross_user_returns_session_not_found(client: TestClient) -> None:
    owner, plan = _confirmed_plan(client, language="javascript")
    other = _create_user(client)
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id)
    created = client.post(
        "/api/reviews/start",
        json={"user_id": owner["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert created.status_code == 201

    history = client.get(
        f"/api/reviews/{created.json()['session_id']}/messages",
        params={"user_id": other["id"]},
    )
    assert history.status_code == 404
    assert history.json()["error"]["code"] == "SESSION_NOT_FOUND"


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
        profile = get_learner_profile(conn, str(user["id"]))
    assert state is not None
    assert state["reps"] == 3
    assert str(state["last_attempt_id"]) == submit_body["attempt_id"]
    assert log_count is not None
    assert log_count["count"] == 1
    assert profile is not None
    assert profile["pace_indicators"]["last_review_rating"] == submit_body["fsrs_rating"]
    assert profile["pace_indicators"]["mastery_signal"] == "review_recovered"


def test_review_routes_langgraph_flag_on_invokes_start_and_submit_graph(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings(langgraph_enabled=True))

    def fake_invoke_review_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(dict(kwargs))
        action = kwargs["action"]
        return {
            "next_action": (
                "submit_and_update"
                if action == "submit"
                else "warmup"
                if action == "warmup"
                else "start_session"
            ),
            "intent_type": "tool_call" if action == "warmup" else "persistence",
            "intent_payload": {
                "target": "attempt_and_fsrs" if action == "submit" else "review_session",
                "tool": "evaluate_warmup" if action == "warmup" else "",
            },
        }

    monkeypatch.setattr(
        reviews_route,
        "invoke_review_orchestration",
        fake_invoke_review_orchestration,
    )

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )
    assert start.status_code == 201
    review_session = start.json()
    exercise = review_session["review_exercise"]
    filled_blanks = _filled_blanks_for(exercise)

    warmup = client.post(
        f"/api/reviews/{review_session['session_id']}/warmup-result",
        json={"action": "skip"},
    )
    assert warmup.status_code == 200

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

    submitted = client.post(
        f"/api/reviews/{review_session['session_id']}/exercise-result",
        json={
            "exercise_id": exercise["id"],
            "attempt_id": run.json()["attempt_id"],
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
        },
    )
    assert submitted.status_code == 200

    start_call = next(call for call in captured if call["action"] == "start")
    warmup_call = next(call for call in captured if call["action"] == "warmup")
    submit_call = next(call for call in captured if call["action"] == "submit")
    assert start_call["is_due"] is True
    assert start_call["has_active_session"] is False
    assert start_call["knowledge_point_id"] == knowledge_point_id
    assert warmup_call["session_id"] == review_session["session_id"]
    assert warmup_call["knowledge_point_id"] == knowledge_point_id
    assert submit_call["session_id"] == review_session["session_id"]
    assert submit_call["explanation_ready"] is True


def test_review_start_invalid_graph_intent_falls_back_to_service_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    _mark_due(knowledge_point_id, reps=2)
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(reviews_route, "get_settings", lambda: Settings(langgraph_enabled=True))

    def fake_invoke_review_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured.append(dict(kwargs))
        return {
            "next_action": "reject_not_due",
            "intent_type": "persistence",
            "intent_payload": {
                "target": "delete_review_state",
                "stack_trace": "provider payload sk-secret",
            },
        }

    monkeypatch.setattr(
        reviews_route,
        "invoke_review_orchestration",
        fake_invoke_review_orchestration,
    )

    start = client.post(
        "/api/reviews/start",
        json={"user_id": user["id"], "knowledge_point_id": knowledge_point_id},
    )

    assert start.status_code == 201
    assert captured
    payload = json.dumps(start.json(), ensure_ascii=False)
    assert "delete_review_state" not in payload
    assert "provider payload" not in payload
    assert "sk-secret" not in payload


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
