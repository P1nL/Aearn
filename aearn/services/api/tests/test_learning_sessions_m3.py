import json
import uuid
from collections.abc import Mapping

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.plans as plans_route
from app.agents.graphs.graph_runtime_contracts import IntentType, build_run_result, make_intent
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.agents.tooling.tools import AgentSideEffects, LearningToolContext
from app.main import app
from app.services.exercises.exercise_guidance import (
    build_error_explanation_response,
    build_explanation_check_response,
    build_hint_response,
)
from app.services.curriculum.dynamic_plan_generation import DynamicPlanDraftResult
from app.services.curriculum.plan_generator import build_plan_draft
from app.services.grounding.grounding_index_repository import run_and_persist_fixture_grounding_reindex
from app.services.repositories.learner_profile import ensure_learner_profile, get_learner_profile, merge_observations
from app.services.conversations import learning_conversation
from app.services.repositories import learning_session_repository as session_repository
from app.services.llm.llm_client import LLMCallError


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
def disable_llm_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLearningConversationClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del temperature
            prompt_text = json.dumps(messages, ensure_ascii=False)
            normalized_prompt = prompt_text.replace("\\", "")
            if '"concept_check_result":"correct"' in normalized_prompt and '"stage":"practice_offer"' in normalized_prompt:
                return ["概念判断已通过，", "可以点击“开始练习”。"]
            if '"concept_check_result":"incorrect"' in normalized_prompt and '"stage":"concept_repair"' in normalized_prompt:
                return ["这个判断还不稳，", "请回答下面的修复题。"]
            if '"concept_check_result":"unclear"' in normalized_prompt:
                return ["这次回答还不够明确，", "请补充当前题的选项或一句依据。"]
            if "检查我的理解" in prompt_text or "理解了" in prompt_text:
                return ["费曼检查：", "请用自己的话解释事件和状态的关系。"]
            return ["我会根据当前阶段继续引导你，", "先说清一个最小下一步。"]

    def fake_hint(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return build_hint_response(*args, **kwargs)

    def fake_error_explanation(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        response = build_error_explanation_response(*args, **kwargs)
        response["generation_source"] = "llm"
        response["generation_model"] = "fake-exercise-coach"
        return response

    def fake_explanation_check(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        return build_explanation_check_response(*args, **kwargs)

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

    def fake_concept_check_result(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        del args
        answer = str(kwargs.get("learner_answer") or "").lower()
        if answer.strip() in {"a", "选a"} or "回调外" in answer or "共享" in answer or "重新从初始" in answer:
            return {
                "result": "correct",
                "confidence": "high",
                "explanation": "你的判断抓住了回调作用域和跨点击状态共享的关系。",
                "next_prompt": "如果要继续，可以回复“开始练习”。",
                "actions": [
                    {"id": "start_practice", "label": "开始练习"},
                    {"id": "show_another_example", "label": "再看一个例子"},
                ],
                "repair_check": None,
            }
        if answer.strip() in {"b", "选b"} or "局部变量" in answer or "错误" in answer:
            return {
                "result": "incorrect",
                "confidence": "medium",
                "explanation": "这里的误解是把回调里的局部变量当成了跨点击共享状态。",
                "next_prompt": "再判断一次：如果变量每次回调都会重新创建，它能记住上次点击吗？",
                "actions": [],
                "repair_check": {
                    "type": "single_choice",
                    "question": "变量每次回调都会重新创建时，它能记住上次点击吗？",
                    "options": [
                        {"id": "A", "text": "不能，它会重新开始。"},
                        {"id": "B", "text": "能，因为事件会保存它。"},
                    ],
                    "expected_focus": "局部变量生命周期",
                },
            }
        return {
            "result": "unclear",
            "confidence": "low",
            "explanation": "这次回答还不能判断你选的是哪种作用域关系。",
            "next_prompt": "请直接回复 A/B/C，或说明 count 是否能跨点击共享。",
            "actions": [],
            "repair_check": None,
        }

    monkeypatch.setattr(session_repository, "build_sdk_concept_intro", fake_concept_intro)
    monkeypatch.setattr(learning_conversation, "build_sdk_concept_check_result", fake_concept_check_result)
    monkeypatch.setattr(session_repository, "build_llm_error_explanation", fake_error_explanation)
    monkeypatch.setattr(session_repository, "build_sdk_hint_response", fake_hint)
    monkeypatch.setattr(session_repository, "build_sdk_explanation_check_response", fake_explanation_check)
    monkeypatch.setattr(plans_route, "build_dynamic_plan_draft", _fake_dynamic_plan_draft)
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
    assert created_body["learning_stage"] == "concept_check"
    assert created_body["exercise"] is None
    assert created_body["lesson_outline"]
    assert created_body["lesson_sources"]
    assert created_body["initial_tool_calls"][0]["name"] == "show_concept_intro"
    intro_args = created_body["initial_tool_calls"][0]["args"]
    assert intro_args["summary"]
    assert len(intro_args["check"]["options"]) == 3
    assert "值、变量与类型" in created_body["initial_agent_message"]
    assert "练习" not in created_body["initial_agent_message"]

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
    assert reused_body["learning_stage"] == "concept_check"
    assert reused_body["exercise"] is None
    assert reused_body["initial_tool_calls"][0]["args"] == intro_args

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

    with connect() as conn:
        message_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM learning_messages
            WHERE session_id = %s AND role = 'agent'
            """,
            (created_body["session_id"],),
        ).fetchone()
    assert message_count is not None
    assert message_count["count"] == 1


def test_learning_intro_answer_is_judged_and_enters_practice_offer(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    assert session["initial_tool_calls"][0]["name"] == "show_concept_intro"

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "A",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_state"]["learning_stage"] == "practice_offer"
    assert body["session_state"]["learning_stage_state"]["concept_check_result"] == "correct"
    assert body["tool_calls"][0]["name"] == "show_concept_check_result"
    assert body["tool_calls"][0]["args"]["result"] == "correct"
    assert "概念判断已通过" in body["agent_message"]["content"]


def test_learning_concept_blocked_judgement_does_not_unlock_practice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    def blocked_concept_check(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        del args, kwargs
        return {
            "result": "correct",
            "confidence": "high",
            "explanation": "答案看起来可能正确，但依据还不够明确。",
            "next_prompt": "请补一句为什么 A 能说明状态没有跨点击共享。",
            "actions": [{"id": "start_practice", "label": "开始练习"}],
            "repair_check": None,
            "judgements": {
                "answer_correctness": {
                    "status": "ambiguous",
                    "clarification_question": "请补一句为什么 A 能说明状态没有跨点击共享。",
                },
                "confidence": {"status": "confirmed"},
            },
        }

    monkeypatch.setattr(learning_conversation, "build_sdk_concept_check_result", blocked_concept_check)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "A",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_state"]["learning_stage"] == "concept_check"
    state = body["session_state"]["learning_stage_state"]
    assert state["concept_check_result"] == "unclear"
    assert state["learning_incomplete"] is True
    assert state["blocked_concept_judgement"]["blocking_fields"] == ["answer_correctness"]
    assert body["tool_calls"][0]["args"]["result"] == "unclear"
    assert body["tool_calls"][0]["args"]["judgement_ready"] is False

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT learning_stage, learning_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (session["session_id"],),
        ).fetchone()
    assert stored is not None
    assert stored["learning_stage"] == "concept_check"
    assert stored["learning_stage_state_json"]["concept_check_attempts"] == 0


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


def test_start_learning_session_invalid_intro_returns_concept_intro_generation_failed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    monkeypatch.setattr(session_repository, "build_sdk_concept_intro", lambda *args, **kwargs: None)

    response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": knowledge_point_id,
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CONCEPT_INTRO_GENERATION_FAILED"
    with connect() as conn:
        session_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM learning_sessions
            WHERE user_id = %s AND plan_id = %s AND entry_point = %s
            """,
            (user["id"], plan["LearningPlan"]["id"], knowledge_point_id),
        ).fetchone()
    assert session_count is not None
    assert session_count["count"] == 0


def test_learning_concept_stage_unlocks_practice_early_with_incomplete_notice(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    unlock = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我想先开始练习，给我题。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert unlock.status_code == 200
    body = unlock.json()
    assert body["session_state"]["learning_stage"] == "practice_support"
    assert body["session_state"]["learning_stage_state"]["learning_incomplete"] is True
    assert body["session_state"]["learning_stage_state"]["practice_unlock_reason"] == "concept_check_skipped"
    assert body["tool_calls"][0]["name"] == "show_concept_check_result"
    assert body["tool_calls"][0]["args"]["result"] == "skipped"
    tool_call = body["tool_calls"][1]
    assert tool_call["name"] == "show_code_exercise"
    assert tool_call["args"]["unlock_reason"] == "concept_check_skipped"
    assert "概念检查会标记为未完成" in tool_call["args"]["notice"]
    assert tool_call["args"]["exercise"]["runtime_profile"]["runtime_tier"] == "browser_preview"

    resumed = _resume_session(client, user, plan)
    assert resumed["learning_stage"] == "practice_support"
    assert resumed["exercise"]["id"] == tool_call["args"]["exercise"]["id"]


def test_learning_concept_stage_uses_check_offer_before_normal_unlock(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    prompt_check = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "状态放在回调外部，所以多次点击会共享并累加同一个 count。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert prompt_check.status_code == 200
    assert prompt_check.json()["session_state"]["learning_stage"] == "practice_offer"
    assert prompt_check.json()["tool_calls"][0]["args"]["result"] == "correct"

    unlock = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "开始练习",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert unlock.status_code == 200
    result = unlock.json()
    assert result["session_state"]["learning_stage"] == "practice_support"
    assert result["session_state"]["learning_stage_state"]["learning_incomplete"] is False
    assert result["session_state"]["learning_stage_state"]["practice_unlock_reason"] == "concept_check_passed"
    assert result["tool_calls"][0]["name"] == "show_code_exercise"


def test_practice_offer_start_unlocks_when_model_is_disabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    prompt_check = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "状态放在回调外部，所以多次点击会共享并累加同一个 count。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert prompt_check.status_code == 200
    assert prompt_check.json()["session_state"]["learning_stage"] == "practice_offer"

    monkeypatch.setattr(learning_conversation, "get_settings", lambda: Settings(llm_type="disabled"))

    unlock = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "开始练习",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert unlock.status_code == 200
    result = unlock.json()
    assert result["generation_source"] == "deterministic"
    assert "直接进入练习" in result["agent_message"]["content"]
    assert result["session_state"]["learning_stage"] == "practice_support"
    assert result["session_state"]["learning_stage_state"]["practice_unlock_reason"] == "concept_check_passed"
    assert result["tool_calls"][0]["name"] == "show_code_exercise"


def test_practice_offer_start_sse_unlocks_when_model_is_disabled(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = f"req_practice_unlock_sse_{uuid.uuid4().hex}"
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    prompt_check = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "状态放在回调外部，所以多次点击会共享并累加同一个 count。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert prompt_check.status_code == 200
    assert prompt_check.json()["session_state"]["learning_stage"] == "practice_offer"

    monkeypatch.setattr(learning_conversation, "get_settings", lambda: Settings(llm_type="disabled"))

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "role": "user",
            "content": "开始练习",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    event_names = [event["event"] for event in events]
    assert "error" not in event_names
    assert event_names[0] == "agent_message"
    assert event_names[-1] == "done"
    assert events[-1]["data"]["generation_source"] == "deterministic"
    tool_call_starts = [
        event
        for event in events
        if event["event"] == "tool_call" and event["data"].get("phase") == "start"
    ]
    assert any(event["data"].get("name") == "show_code_exercise" for event in tool_call_starts)
    tool_call_dones = [
        event
        for event in events
        if event["event"] == "tool_call" and event["data"].get("phase") == "done"
    ]
    exercise_call = next(
        (
            event
            for event in tool_call_dones
            if event["data"].get("arguments", {}).get("unlock_reason") == "concept_check_passed"
        ),
        None,
    )
    assert exercise_call is not None


def test_learning_concept_incorrect_unclear_and_repair_limit_paths(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    unclear_session = _start_session(client, user, plan)

    unclear = client.post(
        f"/api/learning-sessions/{unclear_session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我不确定。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert unclear.status_code == 200
    unclear_body = unclear.json()
    assert unclear_body["session_state"]["learning_stage"] == "concept_check"
    assert unclear_body["tool_calls"][0]["name"] == "show_concept_check_result"
    assert unclear_body["tool_calls"][0]["args"]["result"] == "unclear"
    assert "还不够明确" in unclear_body["agent_message"]["content"]
    assert unclear_body["session_state"]["learning_stage_state"]["learning_incomplete"] is True
    assert unclear_body["tool_calls"][0]["args"]["repair_check"] is None

    with connect() as conn:
        conn.execute("UPDATE learning_sessions SET status = 'finished' WHERE id = %s", (unclear_session["session_id"],))
        conn.commit()

    repair_session = _start_session(client, user, plan)
    first_wrong = client.post(
        f"/api/learning-sessions/{repair_session['session_id']}/messages",
        json={
            "role": "user",
            "content": "B",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert first_wrong.status_code == 200
    first_body = first_wrong.json()
    assert first_body["session_state"]["learning_stage"] == "concept_repair"
    assert first_body["session_state"]["learning_stage_state"]["concept_check_attempts"] == 1
    assert first_body["tool_calls"][0]["args"]["result"] == "incorrect"
    assert "判断还不稳" in first_body["agent_message"]["content"]
    assert first_body["tool_calls"][0]["args"]["repair_check"]["options"]
    assert first_body["tool_calls"] == [item for item in first_body["tool_calls"] if item["name"] != "show_code_exercise"]

    second_wrong = client.post(
        f"/api/learning-sessions/{repair_session['session_id']}/messages",
        json={
            "role": "user",
            "content": "B",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert second_wrong.status_code == 200
    second_body = second_wrong.json()
    assert second_body["session_state"]["learning_stage"] == "concept_repair"
    assert second_body["session_state"]["learning_stage_state"]["concept_check_attempts"] == 2
    assert second_body["session_state"]["learning_stage_state"]["repair_limit_reached"] is True
    assert second_body["tool_calls"][0]["args"]["repair_check"] is None
    assert any(action["id"] == "guided_practice" for action in second_body["tool_calls"][0]["args"]["actions"])

    guided = client.post(
        f"/api/learning-sessions/{repair_session['session_id']}/messages",
        json={
            "role": "user",
            "content": "进入引导练习",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert guided.status_code == 200
    guided_body = guided.json()
    assert guided_body["session_state"]["learning_stage"] == "practice_support"
    assert guided_body["session_state"]["learning_stage_state"]["practice_unlock_reason"] == "concept_check_repair_limit"
    assert guided_body["session_state"]["learning_stage_state"]["learning_incomplete"] is True
    assert guided_body["tool_calls"][0]["name"] == "show_concept_check_result"
    assert guided_body["tool_calls"][1]["name"] == "show_code_exercise"


def test_learning_history_includes_only_learning_turns_across_sessions(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    first = _start_session(client, user, plan)
    first_reply = client.post(
        f"/api/learning-sessions/{first['session_id']}/messages",
        json={
            "role": "user",
            "content": "我先记录第一段学习对话。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert first_reply.status_code == 200
    with connect() as conn:
        conn.execute("UPDATE learning_sessions SET status = 'finished' WHERE id = %s", (first["session_id"],))
        conn.commit()

    second = _start_session(client, user, plan)
    history_request = client.post(
        f"/api/learning-sessions/{second['session_id']}/messages",
        json={
            "role": "user",
            "content": "查看历史对话。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert history_request.status_code == 200
    assert history_request.json()["tool_calls"][0]["name"] == "show_learning_history"

    history = client.get(
        f"/api/learning-sessions/history?user_id={user['id']}&knowledge_point_id={plan['knowledge_points'][0]['id']}&active_session_id={second['session_id']}",
    )
    assert history.status_code == 200
    body = history.json()
    assert [item["session_id"] for item in body["sessions"][:2]] == [second["session_id"], first["session_id"]]
    serialized = json.dumps(body, ensure_ascii=False)
    assert "第一段学习对话" in serialized
    assert all(message["role"] in {"user", "agent"} for item in body["sessions"] for message in item["messages"])


def test_learning_message_json_uses_model_and_is_idempotent(client: TestClient) -> None:
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
    payload = {
        "role": "user",
        "content": "为什么 count 每次点击都会重置？",
        "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
    }

    first = client.post(f"/api/learning-sessions/{session['session_id']}/messages", json=payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["agent_message"]["role"] == "assistant"
    assert first_body["agent_message"]["content"]
    assert first_body["session_state"]["session_id"] == session["session_id"]
    assert first_body["session_state"]["next_action"] == "retry_same"
    assert first_body["generation_source"] == "llm"
    assert first_body["generation_model"] == "fake-teaching-model"
    assert "solution_reference" not in json.dumps(first_body, ensure_ascii=False)

    replay = client.post(f"/api/learning-sessions/{session['session_id']}/messages", json=payload)
    assert replay.status_code == 200
    replay_body = replay.json()
    assert replay_body["idempotency_replayed"] is True
    assert replay_body["agent_message"]["id"] == first_body["agent_message"]["id"]
    assert replay_body["tool_calls"] == first_body["tool_calls"]


def test_learning_message_returns_and_stores_official_docs_grounding_metadata(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="python")
    session = _start_session(client, user, plan)
    with connect() as conn:
        run_and_persist_fixture_grounding_reindex(conn)
        conn.commit()

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "Python functions 为什么需要 return？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grounding"]["status"] == "used"
    assert body["grounding"]["source_mode"] == "persisted_index"
    assert body["grounding"]["citation_count"] > 0
    assert body["grounding"]["citations"][0]["source_trust_tier"] == "official"
    assert "content" not in body["grounding"]["citations"][0]

    with connect() as conn:
        row = conn.execute(
            """
            SELECT metadata
            FROM learning_messages
            WHERE session_id = %s AND role = 'agent'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session["session_id"],),
        ).fetchone()
    assert row is not None
    assert row["metadata"]["grounding"]["status"] == "used"
    assert row["metadata"]["grounding"]["citation_count"] == body["grounding"]["citation_count"]


def test_learning_message_routes_and_passes_handoffs_to_sdk_client(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    class FakeRoutedClient:
        model = "fake-routed-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            captured["temperature"] = temperature
            return ["路由接入完成。"]

    def fake_route_message(
        *,
        session_stage: str,
        user_message: str,
        session_type: str = "learning",
        latest_attempt: Mapping[str, object] | None = None,
        learner_profile_summary: str = "",
        tool_context: Mapping[str, object] | None = None,
    ) -> str:
        captured["route_input"] = {
            "session_stage": session_stage,
            "user_message": user_message,
            "session_type": session_type,
            "latest_attempt": latest_attempt,
            "learner_profile_summary": learner_profile_summary,
            "tool_context": dict(tool_context or {}),
        }
        return "exercise_coach"

    def fake_handoff_targets(agent_name: str) -> list[str]:
        captured["handoff_agent"] = agent_name
        return ["teaching", "diagnosis"]

    def fake_agent_factory(settings, **kwargs):  # type: ignore[no-untyped-def]
        del settings
        captured["agent_name"] = kwargs.get("agent_name")
        captured["handoff_targets"] = tuple(kwargs.get("handoff_targets") or ())
        return FakeRoutedClient()

    monkeypatch.setattr(learning_conversation, "route_message", fake_route_message)
    monkeypatch.setattr(learning_conversation, "get_handoff_targets", fake_handoff_targets)
    monkeypatch.setattr(learning_conversation, "AgentsSDKLearningConversationClient", fake_agent_factory)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agent_message"]["content"] == "路由接入完成。"
    assert body["generation_model"] == "fake-routed-model"
    route_input = captured["route_input"]
    assert route_input["session_stage"] == "concept_check"
    assert route_input["user_message"] == "为什么要用变量保存状态？"
    assert route_input["session_type"] == "learning"
    assert route_input["latest_attempt"] is None
    assert isinstance(route_input["learner_profile_summary"], str)
    assert route_input["tool_context"] == {
        "exercise_available": False,
        "exercise_id": "",
        "knowledge_point_id": plan["knowledge_points"][0]["id"],
    }
    assert captured["handoff_agent"] == "exercise_coach"
    assert captured["agent_name"] == "exercise_coach"
    assert captured["handoff_targets"] == ("teaching", "diagnosis")
    assert "handoff_targets" not in json.dumps(body, ensure_ascii=False)
    assert "agent_name" not in json.dumps(body, ensure_ascii=False)


def test_learning_message_langgraph_flag_off_does_not_invoke_graph(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured = {"compiled": False}

    def fail_compile_graph():  # type: ignore[no-untyped-def]
        captured["compiled"] = True
        raise AssertionError("LANGGRAPH_ENABLED=false should not compile the graph")

    monkeypatch.setattr(learning_conversation, "compile_learning_graph", fail_compile_graph)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    assert response.json()["generation_source"] == "llm"
    assert captured["compiled"] is False


def test_learning_message_langgraph_flag_on_invokes_graph_from_request_path(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    with connect() as conn:
        merge_observations(
            conn,
            str(user["id"]),
            [
                {
                    "type": "weak_point",
                    "content": "closures",
                    "confidence": "confirmed",
                    "session_id": "seed",
                }
            ],
        )
        conn.commit()

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured["orchestration"] = kwargs
        return {
            "run_result": build_run_result(
                next_stage="concept_qna",
                intents=[
                    make_intent(
                        IntentType.STAGE_UPDATE,
                        "learning_session",
                        {
                            "learning_stage": "concept_qna",
                            "learning_stage_state": {"graph_owned": True},
                            "learner_content": "",
                        },
                    )
                ],
            )
        }

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured["state"] = state
            captured["config"] = config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "graph_checked",
                "errors": [],
            }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(
        learning_conversation,
        "invoke_orchestration",
        fake_invoke_orchestration,
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    state = captured["state"]
    config = captured["config"]
    orchestration = captured["orchestration"]
    assert isinstance(state, dict)
    assert isinstance(config, dict)
    assert isinstance(orchestration, dict)
    assert orchestration["session_id"] == session["session_id"]
    assert config["configurable"]["thread_id"] == f"aearn:learning:{session['session_id']}"
    assert config["configurable"]["checkpoint_ns"] == "learning"
    assert config["metadata"]["durable_state_owner"] == "service"
    assert response.json()["session_state"]["learning_stage"] == "concept_qna"
    assert response.json()["session_state"]["learning_stage_state"]["graph_owned"] is True
    assert state["user_id"] == user["id"]
    assert state["session_id"] == session["session_id"]
    assert state["session_type"] == "learning"
    assert state["messages"] == [{"role": "user", "content": "为什么要用变量保存状态？"}]
    assert state["memory_snapshot"]["available"] is True
    assert "closures" in state["memory_snapshot"]["profile_summary"]
    assert state["rag_context"]["knowledge_point_id"] == plan["knowledge_points"][0]["id"]
    assert state["rag_context"]["source_scope"] == "knowledge_point"
    assert orchestration["memory_snapshot"] == state["memory_snapshot"]
    assert orchestration["rag_context"] == state["rag_context"]
    assert "solution_reference" not in json.dumps(state, ensure_ascii=False)
    response_text = json.dumps(response.json(), ensure_ascii=False)
    assert "langgraph_runtime" not in response_text
    assert "memory_snapshot" not in response_text
    assert "rag_context" not in response_text


def test_learning_message_langgraph_ordered_tool_loop_unlocks_practice(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured["orchestration"] = kwargs
        next_state = {
            "covered_subpoint_ids": ["graph-sp1"],
            "feynman_status": "pending",
            "practice_unlock_reason": "concept_check_skipped",
            "learning_incomplete": True,
            "concept_summary": "graph-selected early practice",
            "concept_check_result": "skipped",
        }
        return {
            "run_result": build_run_result(
                next_stage="practice_support",
                intents=[
                    make_intent(
                        IntentType.STAGE_UPDATE,
                        "learning_session",
                        {
                            "learning_stage": "practice_support",
                            "learning_stage_state": next_state,
                            "learner_content": "",
                        },
                    ),
                    make_intent(IntentType.TOOL_CALL, "show_concept_check_result", {"name": "show_concept_check_result"}),
                    make_intent(IntentType.TOOL_CALL, "show_code_exercise", {"name": "show_code_exercise"}),
                ],
            )
        }

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured["state"] = state
            captured["config"] = config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "graph_checked",
                "errors": [],
            }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(learning_conversation, "invoke_orchestration", fake_invoke_orchestration)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我想先开始练习，给我题。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "orchestration" in captured
    assert body["generation_source"] == "deterministic"
    assert body["session_state"]["learning_stage"] == "practice_support"
    assert body["session_state"]["learning_stage_state"]["practice_unlock_reason"] == "concept_check_skipped"
    assert [tool_call["name"] for tool_call in body["tool_calls"]] == [
        "show_concept_check_result",
        "show_code_exercise",
    ]
    assert body["tool_calls"][0]["args"]["result"] == "skipped"
    exercise_tool_call = body["tool_calls"][1]
    assert exercise_tool_call["args"]["unlock_reason"] == "concept_check_skipped"
    assert exercise_tool_call["args"]["concept_summary"] == "graph-selected early practice"
    assert exercise_tool_call["args"]["exercise"]["runtime_profile"]["runtime_tier"] == "browser_preview"

    resumed = _resume_session(client, user, plan)
    assert resumed["learning_stage"] == "practice_support"
    assert resumed["exercise"]["id"] == exercise_tool_call["args"]["exercise"]["id"]


def test_learning_message_langgraph_accepts_scoped_human_checkpoint_without_public_leak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured["orchestration"] = kwargs
        return {
            "run_result": build_run_result(
                next_stage="concept_qna",
                intents=[
                    make_intent(
                        IntentType.STAGE_UPDATE,
                        "learning_session",
                        {
                            "learning_stage": "concept_qna",
                            "learning_stage_state": {"graph_checkpoint_accepted": True},
                            "learner_content": "",
                        },
                    ),
                    make_intent(
                        IntentType.FEEDBACK_REQUEST,
                        "human_checkpoint",
                        {
                            "checkpoint_id": "cp1",
                            "checkpoint_type": "clarification",
                            "reason": "feynman_readiness_unclear",
                            "prompt": "请再具体说明原因。",
                            "scope": "learning_stage_transition",
                            "metadata": {
                                "current_stage": "readiness_check",
                                "api_key": "sk-secret",
                            },
                        },
                    ),
                ],
            )
        }

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured["state"] = state
            captured["config"] = config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "graph_checked",
                "errors": [],
            }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(learning_conversation, "invoke_orchestration", fake_invoke_orchestration)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "orchestration" in captured
    assert body["session_state"]["learning_stage"] == "concept_qna"
    assert body["session_state"]["learning_stage_state"]["graph_checkpoint_accepted"] is True
    response_text = json.dumps(body, ensure_ascii=False)
    assert "human_checkpoint" not in response_text
    assert "api_key" not in response_text
    assert "sk-secret" not in response_text


def test_learning_message_langgraph_rejects_unscoped_human_checkpoint_intent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured["orchestration"] = kwargs
        return {
            "run_result": build_run_result(
                next_stage="practice_support",
                intents=[
                    make_intent(
                        IntentType.FEEDBACK_REQUEST,
                        "unsafe_checkpoint",
                        {
                            "checkpoint_id": "cp_bad",
                            "unsafe_graph_write": True,
                        },
                    )
                ],
            )
        }

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured["state"] = state
            captured["config"] = config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "graph_checked",
                "errors": [],
            }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(learning_conversation, "invoke_orchestration", fake_invoke_orchestration)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "状态放在回调外部，所以多次点击会共享并累加同一个 count。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "orchestration" in captured
    assert body["session_state"]["learning_stage"] == "practice_offer"
    assert body["session_state"]["learning_stage"] != "practice_support"
    assert "unsafe_checkpoint" not in json.dumps(body, ensure_ascii=False)


def test_learning_message_langgraph_rejects_unscoped_intents(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        captured["orchestration"] = kwargs
        return {
            "run_result": build_run_result(
                next_stage="practice_support",
                intents=[
                    make_intent(
                        IntentType.PERSISTENCE,
                        "learning_session",
                        {
                            "learning_stage": "practice_support",
                            "unsafe_graph_write": True,
                        },
                    )
                ],
            )
        }

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            captured["state"] = state
            captured["config"] = config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "graph_checked",
                "errors": [],
            }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(
        learning_conversation,
        "invoke_orchestration",
        fake_invoke_orchestration,
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我觉得应该选 A，因为状态变量在回调外面共享",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "orchestration" in captured
    config = captured["config"]
    assert isinstance(config, dict)
    assert config["configurable"]["thread_id"] == f"aearn:learning:{session['session_id']}"
    assert body["session_state"]["learning_stage"] == "practice_offer"
    assert body["session_state"]["learning_stage"] != "practice_support"
    assert body["tool_calls"][0]["name"] == "show_concept_check_result"
    assert "unsafe_graph_write" not in json.dumps(body, ensure_ascii=False)


def test_learning_message_langgraph_failure_falls_back_without_leaking_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )

    def fail_compile_graph():  # type: ignore[no-untyped-def]
        raise RuntimeError("raw graph failure should stay internal")

    monkeypatch.setattr(learning_conversation, "compile_learning_graph", fail_compile_graph)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body_text = json.dumps(response.json(), ensure_ascii=False)
    assert "raw graph failure" not in body_text
    assert "langgraph_runtime" not in body_text


def test_learning_message_routes_wire_agent_side_effects_and_tool_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    session = _start_session(client, user, plan)
    captured: list[dict[str, object]] = []

    class FakeToolAwareClient:
        model = "fake-tool-aware-model"

        def __init__(
            self,
            *,
            side_effects: AgentSideEffects | None,
            tool_context: LearningToolContext | None,
        ) -> None:
            self.side_effects = side_effects
            self.tool_context = tool_context

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del messages, temperature
            if self.side_effects is not None and self.tool_context is not None:
                self.side_effects.diagnosis_updates.append(
                    {
                        "stuck_point": "count scope confusion",
                        "recommended_action": "inspect state lifetime",
                    },
                )
                self.side_effects.attempt_records.append(
                    {
                        "attempt_id": "tool_attempt_1",
                        "exercise_id": self.tool_context.exercise_id,
                        "code": "SECRET_CODE_SHOULD_NOT_STORE",
                        "action": "run",
                    },
                )
            return ["工具上下文已接入。"]

    def fake_agent_factory(settings, **kwargs):  # type: ignore[no-untyped-def]
        del settings
        side_effects = kwargs.get("side_effects")
        tool_context = kwargs.get("tool_context")
        if side_effects is not None or tool_context is not None:
            captured.append({"side_effects": side_effects, "tool_context": tool_context})
        return FakeToolAwareClient(
            side_effects=side_effects if isinstance(side_effects, AgentSideEffects) else None,
            tool_context=tool_context if isinstance(tool_context, LearningToolContext) else None,
        )

    monkeypatch.setattr(learning_conversation, "AgentsSDKLearningConversationClient", fake_agent_factory)

    json_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么 count 每次点击都会重置？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )
    assert json_response.status_code == 200
    assert "agent_side_effects" not in json.dumps(json_response.json(), ensure_ascii=False)

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": f"req_side_effects_{uuid.uuid4().hex}"},
        json={
            "role": "user",
            "content": "我还是卡在 count 的作用域。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    ) as stream_response:
        assert stream_response.status_code == 200
        events = _parse_sse_events("".join(stream_response.iter_text()))
    assert "error" not in {event["event"] for event in events}
    assert "agent_side_effects" not in json.dumps(events, ensure_ascii=False)

    wired_contexts = [
        item["tool_context"]
        for item in captured
        if isinstance(item.get("side_effects"), AgentSideEffects)
        and isinstance(item.get("tool_context"), LearningToolContext)
    ]
    assert len(wired_contexts) >= 2
    for tool_context in wired_contexts:
        assert isinstance(tool_context, LearningToolContext)
        assert tool_context.session_id == session["session_id"]
        assert tool_context.knowledge_point_id == knowledge_point_id
        assert tool_context.current_stage in {"concept_check", "concept_repair", "practice_offer"}

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT metadata
            FROM learning_messages
            WHERE session_id = %s AND role = 'agent'
            ORDER BY created_at DESC
            LIMIT 2
            """,
            (session["session_id"],),
        ).fetchall()
    side_effect_metadata = [
        row["metadata"]["agent_side_effects"]
        for row in rows
        if isinstance(row.get("metadata"), dict) and "agent_side_effects" in row["metadata"]
    ]
    assert len(side_effect_metadata) == 2
    for metadata in side_effect_metadata:
        assert metadata["diagnosis_updates"][0]["stuck_point"] == "count scope confusion"
        assert metadata["attempt_records"][0]["code_length"] == len("SECRET_CODE_SHOULD_NOT_STORE")
        assert "SECRET_CODE_SHOULD_NOT_STORE" not in json.dumps(metadata, ensure_ascii=False)


def test_learning_session_start_ensures_learner_profile(client: TestClient) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    with connect() as conn:
        conn.execute("DELETE FROM learner_profiles WHERE user_id = %s", (user["id"],))
        conn.commit()
        assert get_learner_profile(conn, str(user["id"])) is None

    _start_session(client, user, plan)

    with connect() as conn:
        profile = get_learner_profile(conn, str(user["id"]))
    assert profile is not None
    assert profile["user_id"] == user["id"]
    assert profile["weak_points"] == []


def test_learning_message_injects_profile_summary_and_drains_profile_side_effects(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    other_user = _create_user(client)
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    with connect() as conn:
        merge_observations(
            conn,
            str(user["id"]),
            [{"type": "weak_point", "content": "closures", "confidence": "confirmed", "session_id": "seed"}],
        )
        ensure_learner_profile(conn, str(other_user["id"]))
        conn.commit()

    class FakeProfileAwareClient:
        model = "fake-profile-aware-model"

        def __init__(
            self,
            *,
            side_effects: AgentSideEffects | None,
            tool_context: LearningToolContext | None,
        ) -> None:
            self.side_effects = side_effects
            self.tool_context = tool_context

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del temperature
            if self.side_effects is not None and self.tool_context is not None:
                captured["messages"] = messages
                captured["profile_summary"] = self.tool_context.profile_summary
                captured["tool_user_id"] = self.tool_context.user_id
                self.side_effects.profile_updates.append(
                    {
                        "type": "error_pattern",
                        "content": "off_by_one",
                        "confidence": "confirmed",
                        "session_id": "malicious-other-session",
                        "user_id": other_user["id"],
                    },
                )
            return ["我会结合你的历史薄弱点继续引导。"]

    def fake_agent_factory(settings, **kwargs):  # type: ignore[no-untyped-def]
        del settings
        side_effects = kwargs.get("side_effects")
        tool_context = kwargs.get("tool_context")
        return FakeProfileAwareClient(
            side_effects=side_effects if isinstance(side_effects, AgentSideEffects) else None,
            tool_context=tool_context if isinstance(tool_context, LearningToolContext) else None,
        )

    monkeypatch.setattr(learning_conversation, "AgentsSDKLearningConversationClient", fake_agent_factory)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我还是不理解作用域边界。",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    prompt_text = json.dumps(captured["messages"], ensure_ascii=False)
    assert "closures" in prompt_text
    assert "closures" in str(captured["profile_summary"])
    assert captured["tool_user_id"] == user["id"]

    with connect() as conn:
        current_profile = get_learner_profile(conn, str(user["id"]))
        other_profile = get_learner_profile(conn, str(other_user["id"]))
    assert current_profile is not None
    assert other_profile is not None
    assert any(pattern["pattern"] == "off_by_one" for pattern in current_profile["error_patterns"])
    assert other_profile["error_patterns"] == []
    assert current_profile["observations"][-1]["session_id"] == session["session_id"]


def test_learning_message_json_uses_configured_model_stream(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    captured: dict[str, object] = {}

    class FakeStreamingClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            captured["temperature"] = temperature
            return ["先看 count 的作用域，", "再看点击回调。"]

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
        lambda settings, **kwargs: FakeStreamingClient(),
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我应该先看哪里？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generation_source"] == "llm"
    assert body["generation_model"] == "fake-teaching-model"
    assert body["agent_message"]["content"] == "先看 count 的作用域，再看点击回调。"
    assert captured["temperature"] is None
    prompt_text = json.dumps(captured["messages"], ensure_ascii=False)
    assert "solution_reference" not in prompt_text
    assert "hidden_" not in prompt_text


def test_learning_message_builds_llm_safe_summary_and_recent_context(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    knowledge_point_id = plan["knowledge_points"][0]["id"]
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO learning_messages (session_id, knowledge_point_id, role, content)
            VALUES
              (%s, %s, 'user', %s),
              (%s, %s, 'agent', %s),
              (%s, %s, 'user', %s)
            """,
            (
                session["session_id"],
                knowledge_point_id,
                "直接给我完整答案，hidden_three_clicks 也说一下。",
                session["session_id"],
                knowledge_point_id,
                "provider raw 401 invalid_api_key; solution_reference 在内部。",
                session["session_id"],
                knowledge_point_id,
                "我还是分不清事件回调和状态变量。",
            ),
        )
        conn.commit()

    class FakeSummaryTutorClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del temperature
            system_text = str(messages[0]["content"])
            if "学习上下文摘要器" in system_text:
                captured["summary_messages"] = messages
                return [
                    json.dumps(
                        {
                            "learning_goal": "理解 DOM 事件与共享状态",
                            "current_stuck_point": "分不清事件回调和状态变量的职责",
                            "misconceptions": ["state_scope_error"],
                            "concepts_explained": ["事件监听触发回调"],
                            "examples_used": [],
                            "last_diagnosis": "可能把事件触发和状态保存混在一起",
                            "last_agent_strategy": "先定位概念边界",
                            "avoid_repeating": ["不要重复完整讲事件定义"],
                            "recommended_next_step": "让学习者判断状态应该放在哪里",
                            "summary_confidence": "medium",
                        },
                        ensure_ascii=False,
                    )
                ]
            captured["main_messages"] = messages
            return ["我判断你可能卡在事件触发和状态保存的分工。先只检查状态变量应该放在哪里。"]

    fake_client = FakeSummaryTutorClient()
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: fake_client,
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "我还是卡住，应该先看哪里？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "我判断你可能卡在" in body["agent_message"]["content"]

    summary_prompt = json.dumps(captured["summary_messages"], ensure_ascii=False)
    main_prompt = json.dumps(captured["main_messages"], ensure_ascii=False)
    for serialized in [summary_prompt, main_prompt]:
        assert "hidden_three_clicks" not in serialized
        assert "solution_reference" not in serialized
        assert "provider raw" not in serialized
        assert "invalid_api_key" not in serialized
    assert "conversation_context" in main_prompt
    assert "recent_safe_messages" in main_prompt
    assert "诊断型编程语言学习导师" in main_prompt
    assert "每次最多问一个高价值追问" in main_prompt
    assert "分不清事件回调和状态变量的职责" in main_prompt

    with connect() as conn:
        row = conn.execute(
            """
            SELECT learning_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (session["session_id"],),
        ).fetchone()
    assert row is not None
    summary_state = row["learning_stage_state_json"]["conversation_summary"]
    assert summary_state["source"] == "llm"
    assert summary_state["safe_summary"]["current_stuck_point"] == "分不清事件回调和状态变量的职责"


def test_learning_message_reuses_persisted_summary_until_refresh_threshold(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {"summary_called": False}

    with connect() as conn:
        row = conn.execute(
            """
            SELECT learning_stage_state_json
            FROM learning_sessions
            WHERE id = %s
            """,
            (session["session_id"],),
        ).fetchone()
        message_count = conn.execute(
            """
            SELECT count(*) AS count
            FROM learning_messages
            WHERE session_id = %s
            """,
            (session["session_id"],),
        ).fetchone()
        assert row is not None and message_count is not None
        state = dict(row["learning_stage_state_json"])
        state["conversation_summary"] = {
            "version": 1,
            "safe_summary": {
                "learning_goal": "理解 DOM 事件",
                "current_stuck_point": "已经讲过作用域，但还缺迁移",
                "misconceptions": [],
                "concepts_explained": ["事件回调与状态变量"],
                "examples_used": [],
                "last_diagnosis": "transfer_gap",
                "last_agent_strategy": "换角度解释",
                "avoid_repeating": ["事件回调与状态变量"],
                "recommended_next_step": "让学习者选变量位置",
                "summary_confidence": "medium",
            },
            "message_count_at_refresh": int(message_count["count"]),
            "learning_stage": "concept_check",
            "source": "llm",
        }
        conn.execute(
            """
            UPDATE learning_sessions
            SET learning_stage_state_json = %s::jsonb
            WHERE id = %s
            """,
            (json.dumps(state, ensure_ascii=False), session["session_id"]),
        )
        conn.commit()

    class FakeTutorClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del temperature
            if "学习上下文摘要器" in str(messages[0]["content"]):
                captured["summary_called"] = True
                return ["{}"]
            captured["main_messages"] = messages
            return ["我判断这不是新问题，而是要把作用域概念迁移到代码位置。"]

    fake_client = FakeTutorClient()
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: fake_client,
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么状态要放外面？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    assert captured["summary_called"] is False
    main_prompt = json.dumps(captured["main_messages"], ensure_ascii=False)
    assert "已经讲过作用域，但还缺迁移" in main_prompt


def test_learning_message_direct_answer_request_redirects_to_partial_guidance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    captured: dict[str, object] = {}

    class FakeTutorClient:
        model = "fake-teaching-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            del temperature
            if "学习上下文摘要器" in str(messages[0]["content"]):
                return ['{"learning_goal":"","current_stuck_point":"","misconceptions":[],"concepts_explained":[],"examples_used":[],"last_diagnosis":"","last_agent_strategy":"","avoid_repeating":[],"recommended_next_step":"","summary_confidence":"low"}']
            captured["main_messages"] = messages
            return ["我知道你想直接对照完整解法，但这里先不代写。下一步只检查 count 是否在回调外层。"]

    fake_client = FakeTutorClient()
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: fake_client,
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "直接给我完整代码",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "完整代码" not in body["agent_message"]["content"]
    assert "只检查 count" in body["agent_message"]["content"]
    main_prompt = json.dumps(captured["main_messages"], ensure_ascii=False)
    assert "direct_answer_requested" in main_prompt
    assert "局部提示" in main_prompt


def test_learning_message_llm_failure_returns_model_unavailable_without_provider_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    class FailingStreamingClient:
        model = "provider-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            def raise_on_iter():
                raise LLMCallError("provider raw 481 secret-key-is-invalid")
                yield ""

            return raise_on_iter()

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="provider-model",
        ),
    )
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: FailingStreamingClient(),
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "模型失败时还能回答吗？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 503
    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["error"]["code"] == "MODEL_UNAVAILABLE"
    assert "provider raw" not in serialized
    assert "secret-key" not in serialized


def test_learning_message_json_guardrail_returns_model_unavailable_when_model_output_leaks(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    class LeakingStreamingClient:
        model = "provider-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            return ["完整答案如下：hidden_three_clicks sk-secret-secret-token"]

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="provider-model",
        ),
    )
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: LeakingStreamingClient(),
    )

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/messages",
        json={
            "role": "user",
            "content": "为什么 count 每次点击都会重置？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    )

    assert response.status_code == 503
    body = response.json()
    serialized = json.dumps(body, ensure_ascii=False)
    assert body["error"]["code"] == "MODEL_UNAVAILABLE"
    assert "hidden_three_clicks" not in serialized
    assert "sk-secret" not in serialized
    assert "完整答案如下" not in serialized


def test_learning_message_sse_streams_agent_message_and_done(client: TestClient) -> None:
    request_id = f"req_message_sse_{uuid.uuid4().hex}"
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

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "role": "user",
            "content": "为什么可见测试没过？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events("".join(response.iter_text()))

    assert events
    assert events[-1]["event"] == "done"
    assert all(event["event"] in {"agent_message", "tool_call", "done"} for event in events)
    assert "tool_status" not in {event["event"] for event in events}
    agent_events = [event for event in events if event["event"] == "agent_message"]
    assert agent_events
    assert any(
        event["event"] == "tool_call"
        and event["data"]["phase"] == "done"
        and event["data"]["arguments"]["result"] in {"correct", "incorrect", "unclear"}
        for event in events
    )
    assert agent_events[0]["data"]["request_id"] == request_id
    assert agent_events[0]["data"]["session_id"] == session["session_id"]
    assert agent_events[-1]["data"]["content"]
    assert events[-1]["data"]["message_id"] == agent_events[-1]["data"]["message_id"]
    assert events[-1]["data"]["generation_source"] == "llm"


def test_learning_message_sse_emits_graph_tool_status_before_agent_message(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = f"req_graph_stream_{uuid.uuid4().hex}"
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    class FakeCompiledGraph:
        def invoke(self, state, config=None):  # type: ignore[no-untyped-def]
            del config
            return {
                "current_node": "persist_side_effects",
                "learning_stage": state["learning_stage"],
                "next_action": "provider payload sk-secret",
                "errors": ["stack_trace sk-secret"],
            }

    def fake_invoke_orchestration(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return {
            "run_result": build_run_result(
                next_stage="concept_qna",
                intents=[
                    make_intent(
                        IntentType.STAGE_UPDATE,
                        "learning_session",
                        {
                            "learning_stage": "concept_qna",
                            "learning_stage_state": {"graph_stream": True},
                            "learner_content": "",
                        },
                    )
                ],
            )
        }

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="fake-teaching-model",
            langgraph_enabled=True,
        ),
    )
    monkeypatch.setattr(learning_conversation, "compile_learning_graph", lambda: FakeCompiledGraph())
    monkeypatch.setattr(learning_conversation, "invoke_orchestration", fake_invoke_orchestration)

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "role": "user",
            "content": "为什么要用变量保存状态？",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    event_names = [event["event"] for event in events]
    assert event_names[0] == "tool_status"
    assert event_names.index("tool_status") < event_names.index("agent_message")
    graph_status = events[0]["data"]
    assert graph_status == {
        "request_id": request_id,
        "session_id": session["session_id"],
        "node": "learning_graph",
        "tool": "graph_runtime",
        "status": "completed",
        "message": "Learning graph context prepared with safe fallback.",
        "observability": {
            "fallback_used": True,
            "memory_available": False,
            "next_action": "",
            "rag_chunk_count": 3,
            "rag_retrieval_status": "available",
        },
    }
    serialized = json.dumps(events, ensure_ascii=False)
    assert "persist_side_effects" not in serialized
    assert "langgraph_runtime" not in serialized
    assert "human_checkpoint" not in serialized
    assert "provider payload" not in serialized
    assert "sk-secret" not in serialized


def test_learning_message_sse_concept_check_reply_uses_judged_result(client: TestClient) -> None:
    request_id = f"req_message_sse_concept_result_{uuid.uuid4().hex}"
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "role": "user",
            "content": "A",
            "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    agent_events = [event for event in events if event["event"] == "agent_message"]
    assert agent_events
    assert "概念判断已通过" in agent_events[-1]["data"]["content"]
    tool_done = next(
        event
        for event in events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    assert tool_done["data"]["arguments"]["result"] == "correct"


def test_learning_message_sse_guardrail_error_after_partial_output(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = f"req_message_sse_guardrail_{uuid.uuid4().hex}"
    client_message_id = f"desktop_msg_{uuid.uuid4().hex}"
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

    class PartiallyLeakingStreamingClient:
        model = "provider-model"

        def complete_text_stream(self, messages, *, temperature=None):  # type: ignore[no-untyped-def]
            return ["先看状态变量。", "provider raw hidden_three_clicks"]

    monkeypatch.setattr(
        learning_conversation,
        "get_settings",
        lambda: Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="provider-model",
        ),
    )
    monkeypatch.setattr(
        learning_conversation,
        "AgentsSDKLearningConversationClient",
        lambda settings, **kwargs: PartiallyLeakingStreamingClient(),
    )

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "role": "user",
            "content": "为什么可见测试没过？",
            "client_message_id": client_message_id,
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == ["agent_message", "error"]
    assert events[1]["data"]["error"]["code"] == "MODEL_UNAVAILABLE"
    assert events[1]["data"]["error"]["recoverable"] is True

    with connect() as conn:
        stored = conn.execute(
            """
            SELECT count(*) AS count
            FROM idempotency_records
            WHERE key = %s
            """,
            (f"learning-message:{session['session_id']}:{client_message_id}",),
        ).fetchone()
    assert stored is not None
    assert stored["count"] == 0


def test_learning_message_errors_for_missing_session_json_and_sse(client: TestClient) -> None:
    request_id = f"req_message_missing_{uuid.uuid4().hex}"
    missing_session_id = str(uuid.uuid4())
    payload = {
        "role": "user",
        "content": "这个会话还在吗？",
        "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
    }

    json_response = client.post(f"/api/learning-sessions/{missing_session_id}/messages", json=payload)
    assert json_response.status_code == 404
    assert json_response.json()["error"]["code"] == "SESSION_NOT_FOUND"

    with client.stream(
        "POST",
        f"/api/learning-sessions/{missing_session_id}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json=payload,
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == ["error"]
    assert events[0]["data"]["error"]["code"] == "SESSION_NOT_FOUND"
    assert events[0]["data"]["error"]["request_id"] == request_id


def test_learning_message_validation_error_json_and_sse(client: TestClient) -> None:
    request_id = f"req_message_validation_{uuid.uuid4().hex}"
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
    invalid_payload = {
        "role": "user",
        "content": "   ",
        "client_message_id": f"desktop_msg_{uuid.uuid4().hex}",
    }

    json_response = client.post(f"/api/learning-sessions/{session['session_id']}/messages", json=invalid_payload)
    assert json_response.status_code == 400
    assert json_response.json()["error"]["code"] == "VALIDATION_ERROR"

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json=invalid_payload,
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == ["error"]
    assert events[0]["data"]["error"]["code"] == "VALIDATION_ERROR"
    assert events[0]["data"]["error"]["request_id"] == request_id


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
    exercise = _unlock_practice_exercise(client, session)
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
        profile = get_learner_profile(conn, str(user["id"]))
    assert [row["attempt_type"] for row in attempt_rows] == ["run", "submit"]
    assert attempt_rows[1]["score"] >= 6
    assert attempt_rows[1]["fsrs_rating"] in {"Good", "Easy"}
    assert review_state is not None
    assert str(review_state["last_attempt_id"]) == submit_body["attempt_id"]
    assert profile is not None
    assert profile["pace_indicators"]["last_attempt_outcome"] == "mastered"
    assert profile["pace_indicators"]["mastery_signal"] == "mastered"


def test_run_endpoint_streams_sse_events(client: TestClient) -> None:
    request_id = f"req_run_sse_{uuid.uuid4().hex}"
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
    exercise = _unlock_practice_exercise(client, session)

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": {
                "blank_1": "addEventListener",
                "blank_2": "count += 1",
            },
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == ["tool_status", "runner_result", "done"]
    runner_result = events[1]["data"]
    assert runner_result["request_id"] == request_id
    assert runner_result["session_id"] == session["session_id"]
    assert runner_result["runtime_status"] == "success"
    assert runner_result["test_pass_rate"] == 1.0
    assert events[2]["data"]["result_ref"]["id"] == runner_result["attempt_id"]


def test_submit_endpoint_streams_runner_and_evaluation_events(client: TestClient) -> None:
    request_id = f"req_submit_sse_{uuid.uuid4().hex}"
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
    exercise = _unlock_practice_exercise(client, session)
    filled_blanks = {
        "blank_1": "addEventListener",
        "blank_2": "count += 1",
    }
    explanation = "状态变量放在回调外层，所以多次点击会共享同一个 count；如果写在回调里，每次点击都会重新初始化。"
    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()
    explanation_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": explanation,
            "focus": "core_logic",
            "round": 1,
        },
    )
    assert explanation_response.status_code == 200

    with client.stream(
        "POST",
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/submit",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "attempt_id": run_body["attempt_id"],
            "code": exercise["solution_reference"],
            "filled_blanks": filled_blanks,
            "submit_version": 1,
            "explanation": explanation,
            "hint_usage_count": 0,
            "error_count": 0,
        },
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == [
        "tool_status",
        "runner_result",
        "evaluation_result",
        "done",
    ]
    runner_result = events[1]["data"]
    evaluation_result = events[2]["data"]
    assert runner_result["attempt_id"] == evaluation_result["attempt_id"]
    assert evaluation_result["code_completion_result"]["next_action"] == "schedule_review"
    assert events[3]["data"]["result_ref"]["id"] == evaluation_result["attempt_id"]


def test_run_endpoint_streams_error_event(client: TestClient) -> None:
    request_id = f"req_run_sse_error_{uuid.uuid4().hex}"
    missing_session_id = str(uuid.uuid4())
    missing_exercise_id = str(uuid.uuid4())
    with client.stream(
        "POST",
        f"/api/learning-sessions/{missing_session_id}/exercises/{missing_exercise_id}/run",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={"code": "console.log(1)", "filled_blanks": {}, "run_mode": "visible_tests"},
    ) as response:
        assert response.status_code == 200
        events = _parse_sse_events("".join(response.iter_text()))

    assert [event["event"] for event in events] == ["tool_status", "error"]
    assert events[1]["data"]["error"]["code"] == "SESSION_NOT_FOUND"
    assert events[1]["data"]["error"]["request_id"] == request_id


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
    exercise = _unlock_practice_exercise(client, session)

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


def test_hint_endpoint_uses_sdk_coach_without_changing_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    exercise = _unlock_practice_exercise(client, session)

    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["starter_code"],
            "filled_blanks": {},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()
    calls = {"count": 0}

    def fake_sdk_hint(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return {
            "hint": {
                "hint_level": "concept",
                "content": "SDK 提示：先解释共享状态，再只改当前空缺。",
            },
            "hint_usage_count": 1,
            "affected_score": {"max_result": "passed", "score_penalty_hint": 1},
            "next_action": "retry_same",
        }

    monkeypatch.setattr(session_repository, "build_sdk_hint_response", fake_sdk_hint)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
        json={
            "attempt_id": run_body["attempt_id"],
            "current_code": exercise["starter_code"],
            "blank_id": "blank_2",
            "hint_level": "concept",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["hint"] == {
        "hint_level": "concept",
        "content": "SDK 提示：先解释共享状态，再只改当前空缺。",
    }
    assert body["hint_usage_count"] == 1
    assert set(body) == {"hint", "hint_usage_count", "affected_score", "next_action"}
    assert calls["count"] == 1


def test_hint_endpoint_returns_model_unavailable_when_model_output_is_missing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    exercise = _unlock_practice_exercise(client, session)
    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["starter_code"],
            "filled_blanks": {},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()
    monkeypatch.setattr(session_repository, "build_sdk_hint_response", lambda *args, **kwargs: None)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/hint",
        json={
            "attempt_id": run_body["attempt_id"],
            "current_code": exercise["starter_code"],
            "blank_id": "blank_2",
            "hint_level": "concept",
        },
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


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
    exercise = _unlock_practice_exercise(client, session)
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


def test_explain_error_llm_generation_is_idempotent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
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
    exercise = _unlock_practice_exercise(client, session)
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
    run_body = run_response.json()
    failed_tests = [item for item in run_body["test_results"] if not item["passed"]]
    payload = {
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
    }
    calls = {"count": 0}

    def fake_llm_explanation(*args, **kwargs) -> dict[str, object]:
        calls["count"] += 1
        return {
            "error_cause": "state_scope_error",
            "explanation": "count 被放在点击回调里，每次点击都会重新初始化。",
            "fix_suggestion": "把共享状态移到回调外层，只在回调里累加并同步页面。",
            "related_knowledge_points": [{"id": knowledge_point_id, "title": "事件监听与状态变量"}],
            "next_action": "retry_same",
            "generation_source": "llm",
            "generation_model": "third-party-model",
        }

    monkeypatch.setattr(session_repository, "build_llm_error_explanation", fake_llm_explanation)

    first = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/explain-error",
        json=payload,
    )
    second = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/explain-error",
        json=payload,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["generation_source"] == "llm"
    assert second.json()["idempotency_replayed"] is True
    assert calls["count"] == 1


def test_check_explanation_endpoint_uses_sdk_coach_without_changing_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    exercise = _unlock_practice_exercise(client, session)
    run_response = client.post(
        f"/api/learning-sessions/{session['session_id']}/exercises/{exercise['id']}/run",
        json={
            "code": exercise["starter_code"],
            "filled_blanks": {},
            "runtime_profile_id": exercise["runtime_profile"]["id"],
            "run_mode": "visible_tests",
        },
    )
    run_body = run_response.json()
    calls = {"count": 0}

    def fake_sdk_check(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return {
            "result": "partial",
            "score": 1,
            "score_breakdown": {"explanation_check": 1},
            "follow_up_required": True,
            "feedback": "SDK 检查：主路径接近，但还要说明连续点击为什么会保留状态。",
            "next_action": "retry_same",
        }

    monkeypatch.setattr(session_repository, "build_sdk_explanation_check_response", fake_sdk_check)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{run_body['attempt_id']}/check-explanation",
        json={
            "explanation": "状态变量在外层。",
            "focus": "core_logic",
            "round": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "result": "partial",
        "score": 1,
        "score_breakdown": {"explanation_check": 1},
        "follow_up_required": True,
        "feedback": "SDK 检查：主路径接近，但还要说明连续点击为什么会保留状态。",
        "next_action": "retry_same",
    }
    assert calls["count"] == 1


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
    exercise = _unlock_practice_exercise(client, session)
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
    exercise = _unlock_practice_exercise(client, session)

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


def test_explanation_check_blocked_judgement_does_not_update_attempt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, plan = _confirmed_plan(client, language="javascript")
    session = _start_session(client, user, plan)
    exercise = _unlock_practice_exercise(client, session)

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
    assert run_response.status_code == 201
    attempt_id = run_response.json()["attempt_id"]

    def blocked_explanation_check(*args, **kwargs) -> dict[str, object]:  # type: ignore[no-untyped-def]
        del args, kwargs
        return {
            "result": "passed",
            "score": 2,
            "score_breakdown": {"explanation_check": 2},
            "follow_up_required": False,
            "feedback": "看起来通过，但解释依据不够可靠。",
            "next_action": "advance_next",
            "judgements": {
                "explanation_sufficiency": {
                    "status": "ambiguous",
                    "clarification_question": "请再说明 count 为什么必须放在回调外层。",
                },
                "feedback_grounding": {"status": "confirmed"},
                "next_action": {"status": "confirmed"},
            },
        }

    monkeypatch.setattr(session_repository, "build_sdk_explanation_check_response", blocked_explanation_check)

    response = client.post(
        f"/api/learning-sessions/{session['session_id']}/attempts/{attempt_id}/check-explanation",
        json={
            "explanation": "状态会共享。",
            "focus": "core_logic",
            "round": 1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["judgement_ready"] is False
    assert body["next_action"] == "retry_same"
    assert body["judgement_blocking_fields"] == ["explanation_sufficiency"]

    with connect() as conn:
        attempt = conn.execute(
            """
            SELECT explanation_text, explanation_check_result
            FROM attempts
            WHERE id = %s
            """,
            (attempt_id,),
        ).fetchone()
    assert attempt is not None
    assert attempt["explanation_text"] is None
    assert attempt["explanation_check_result"] is None


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
    exercise = _unlock_practice_exercise(client, session)

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
    exercise = _unlock_practice_exercise(client, session)
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
    exercise = _unlock_practice_exercise(client, session)

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
    exercise = _unlock_practice_exercise(client, session)

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
    exercise = _unlock_practice_exercise(client, session)
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


@pytest.mark.parametrize(
    ("runtime_status", "expected_next_action"),
    [
        ("missing_toolchain", "retry_same"),
        ("unsupported", "retry_same"),
        ("compile_error", "explain_error"),
        ("runtime_error", "explain_error"),
        ("timeout", "retry_same"),
        ("test_failure", "explain_error"),
        ("success", "advance_next"),
    ],
)
def test_managed_java_runtime_statuses_are_public_and_persisted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    runtime_status: str,
    expected_next_action: str,
) -> None:
    from app.services.runners import runner_registry
    from app.services.runners.managed_compiled_runner import ManagedCompiledExecutionResult, ManagedCompiledTestCaseResult

    def fake_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        if runtime_status == "success":
            return ManagedCompiledExecutionResult(
                status="success",
                stdout="compiled stdout",
                stderr="",
                error=None,
                test_results=[
                    ManagedCompiledTestCaseResult(
                        case_id="visible_increment",
                        case_type="visible",
                        passed=True,
                        weight=1,
                        is_critical=True,
                        message="Passed",
                        duration_ms=1,
                    ),
                    ManagedCompiledTestCaseResult(
                        case_id="hidden_increment",
                        case_type="hidden",
                        passed=True,
                        weight=1,
                        is_critical=False,
                        message="Hidden passed",
                        duration_ms=1,
                    ),
                ],
                total_duration_ms=2,
            )
        if runtime_status == "test_failure":
            return ManagedCompiledExecutionResult(
                status="test_failure",
                stdout="",
                stderr="",
                error=None,
                test_results=[
                    ManagedCompiledTestCaseResult(
                        case_id="visible_increment",
                        case_type="visible",
                        passed=False,
                        weight=1,
                        is_critical=True,
                        message="Expected 2, got 1",
                        duration_ms=1,
                    ),
                    ManagedCompiledTestCaseResult(
                        case_id="hidden_secret_case",
                        case_type="hidden",
                        passed=False,
                        weight=1,
                        is_critical=False,
                        message="Expected 999, got 1",
                        duration_ms=1,
                    ),
                ],
                total_duration_ms=2,
            )
        return ManagedCompiledExecutionResult(
            status=runtime_status,
            stdout="",
            stderr=f"{runtime_status} stderr",
            error=f"{runtime_status} public error",
            test_results=[],
            total_duration_ms=1,
        )

    monkeypatch.setattr(runner_registry, "execute_managed_compiled_with_tests", fake_execute)

    user, plan = _confirmed_plan(client, language="java")
    session = _start_session(client, user, plan)
    exercise = _unlock_practice_exercise(client, session)
    assert exercise["runtime_profile"]["runtime_tier"] == "managed_compiled_test"

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
    assert body["runtime_status"] == runtime_status
    assert body["next_action"] == expected_next_action
    if runtime_status == "success":
        assert body["test_pass_rate"] == 1.0
        assert body["stdout"] == "compiled stdout"
    if runtime_status == "test_failure":
        serialized = repr(body["test_results"])
        assert body["test_pass_rate"] < 1.0
        assert "hidden_secret_case" not in serialized
        assert "999" not in serialized

    with connect() as conn:
        attempt = conn.execute(
            """
            SELECT runtime_status
            FROM attempts
            WHERE id = %s
            """,
            (body["attempt_id"],),
        ).fetchone()
    assert attempt is not None
    assert attempt["runtime_status"] == runtime_status


def test_cpp_is_not_a_public_route_language(client: TestClient) -> None:
    response = client.get("/api/language-courses?language=cpp")

    assert response.status_code == 200
    assert response.json()["items"] == []


def _start_session(
    client: TestClient,
    user: dict[str, object],
    plan: dict[str, object],
) -> dict[str, object]:
    response = client.post(
        "/api/learning-sessions/start",
        json={
            "user_id": user["id"],
            "plan_id": plan["LearningPlan"]["id"],
            "knowledge_point_id": plan["knowledge_points"][0]["id"],
        },
    )
    assert response.status_code in {200, 201}
    session = response.json()
    assert isinstance(session, dict)
    return session


def _resume_session(
    client: TestClient,
    user: dict[str, object],
    plan: dict[str, object],
) -> dict[str, object]:
    return _start_session(client, user, plan)


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


def _parse_sse_events(text: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in text.replace("\r\n", "\n").split("\n\n"):
        if not frame.strip():
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_type = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())
        if not event_type:
            continue
        events.append({"event": event_type, "data": json.loads("\n".join(data_lines))})
    return events
