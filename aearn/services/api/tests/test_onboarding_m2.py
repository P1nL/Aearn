import json
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.onboarding as onboarding_route
import app.routes.plans as plans_route
from app.agents.onboarding_slot_extractor import ExtractedSlots
from app.agents.plan_generation_agent import PlanGenerationResult
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.main import app
from app.models.onboarding import DraftKnowledgePoint, DraftModule, PlanDraft
from app.services.llm_client import LLMCallError, LLMConfigurationError
from app.services.onboarding_conversation import (
    OnboardingConversationContext,
    OnboardingMessageGeneration,
    create_onboarding_session,
    detect_plan_proposal,
    extract_slots as extract_onboarding_slots,
    stash_plan_draft,
)


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
    monkeypatch.setattr(
        plans_route,
        "build_sdk_onboarding_plan_response",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        plans_route,
        "build_sdk_plan_generation_response",
        lambda *args, **kwargs: None,
    )


def test_user_create_get_and_preferences(client: TestClient) -> None:
    created = _create_user(client)

    fetched = client.get(f"/api/users/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["user"]["id"] == created["id"]

    patched = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"teaching_preference": "example_then_practice", "profession": "frontend_developer"},
    )
    assert patched.status_code == 200
    assert patched.json()["user"]["teaching_preference"] == "example_then_practice"


def test_preference_update_rejects_fixed_backend_rules(client: TestClient) -> None:
    created = _create_user(client)

    response = client.patch(
        f"/api/users/{created['id']}/preferences",
        json={"fsrs_parameters": {"retention": 0.95}, "attempt_policy": "off"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert sorted(response.json()["error"]["details"]["forbidden_fields"]) == [
        "attempt_policy",
        "fsrs_parameters",
    ]


def test_language_courses_include_compiled_later_placeholders(client: TestClient) -> None:
    response = client.get("/api/language-courses")

    assert response.status_code == 200
    items = response.json()["items"]
    runtime_tiers = {item["language"]: item["runtime_profile"]["runtime_tier"] for item in items}
    assert runtime_tiers["java"] == "compiled_sandbox_later"
    assert runtime_tiers["cpp"] == "compiled_sandbox_later"


def test_generate_plan_goal_and_material_modes(client: TestClient) -> None:
    user = _create_user(client)
    js_course = _course_by_language(client, "javascript")
    goal_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM events by validating generated code.",
            "course_id": js_course["id"],
            "target_level": "beginner_to_intermediate",
        },
    )
    assert goal_response.status_code == 200
    goal_draft = goal_response.json()["plan_draft"]
    assert goal_draft["runtime_boundary"]["runtime_tier"] == "browser_preview"
    assert goal_draft["modules"][0]["is_skippable"] is False
    assert "Fallback: static template" in goal_draft["source_attribution"]

    python_course = _course_by_language(client, "python")
    material_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "material_based",
            "materials": [{"type": "text", "title": "函数笔记", "content": "return 和 print"}],
            "course_id": python_course["id"],
        },
    )
    assert material_response.status_code == 200
    python_draft = material_response.json()["plan_draft"]
    assert len(python_draft["modules"]) >= 2
    assert [module["order_index"] for module in python_draft["modules"]] == list(
        range(len(python_draft["modules"]))
    )
    assert "Official documentation taxonomy: Python Tutorial" in python_draft["source_attribution"]
    assert any(source.startswith("User materials") for source in python_draft["source_attribution"])


def test_generate_plan_uses_valid_sdk_candidate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")

    def fake_sdk_response(context, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        candidate = PlanDraft.model_validate(context.deterministic_plan_draft).model_copy(
            update={"goal_text": "SDK refined DOM validation goal."}
        )
        return {"plan_draft": candidate, "agent_notes": ["SDK note: keep deterministic DOM templates."]}

    monkeypatch.setattr(plans_route, "build_sdk_onboarding_plan_response", fake_sdk_response)

    response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM.",
            "course_id": course["id"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan_draft"]["goal_text"] == "SDK refined DOM validation goal."
    assert "SDK note: keep deterministic DOM templates." in body["agent_notes"]
    assert body["plan_draft"]["runtime_boundary"]["runtime_tier"] == "browser_preview"


def test_generate_plan_uses_dynamic_modules_and_source_attribution(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")

    dynamic_result = PlanGenerationResult(
        modules=_dynamic_modules("javascript"),
        source_attribution=[
            "Dynamic generation: agent_generated",
            "Dynamic source: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide",
            "Dynamic notes: 参考 MDN JavaScript 指南和用户目标生成路线。",
        ],
        model="fake-plan-model",
    )
    monkeypatch.setattr(
        plans_route,
        "build_sdk_plan_generation_response",
        lambda *args, **kwargs: dynamic_result,
    )

    response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "学习 JavaScript DOM 交互。",
            "course_id": course["id"],
        },
    )

    assert response.status_code == 200
    draft = response.json()["plan_draft"]
    assert draft["user_id"] == user["id"]
    assert draft["language_course_id"] == course["id"]
    assert draft["runtime_boundary"]["runtime_tier"] == "browser_preview"
    assert draft["modules"][0]["source"] == "agent_generated"
    assert draft["modules"][0]["title"] == "动态模块1"
    assert "Dynamic source: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide" in draft[
        "source_attribution"
    ]
    assert "Fallback: static template" not in draft["source_attribution"]


def test_generate_plan_failure_paths_and_java_notice(client: TestClient) -> None:
    user = _create_user(client)
    java_course = _course_by_language(client, "java")

    insufficient = client.post(
        "/api/plans/generate",
        json={"user_id": user["id"], "mode": "goal_based", "course_id": java_course["id"]},
    )
    assert insufficient.status_code == 400
    assert insufficient.json()["error"]["code"] == "VALIDATION_ERROR"

    unknown_user = client.post(
        "/api/plans/generate",
        json={"user_id": str(uuid.uuid4()), "mode": "goal_based", "goal_text": "Learn", "course_id": java_course["id"]},
    )
    assert unknown_user.status_code == 404
    assert unknown_user.json()["error"]["code"] == "USER_NOT_FOUND"

    unknown_course = client.post(
        "/api/plans/generate",
        json={"user_id": user["id"], "mode": "goal_based", "goal_text": "Learn", "course_id": str(uuid.uuid4())},
    )
    assert unknown_course.status_code == 404
    assert unknown_course.json()["error"]["code"] == "COURSE_NOT_FOUND"

    java_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Read Java method signatures.",
            "course_id": java_course["id"],
        },
    )
    assert java_response.status_code == 200
    draft = java_response.json()["plan_draft"]
    assert draft["runtime_boundary"]["runtime_tier"] == "compiled_sandbox_later"
    assert "planned later" in draft["runtime_boundary"]["notice"]


def test_confirm_plan_persists_review_states_and_is_idempotent(client: TestClient) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Build a deterministic DOM learning route.",
            "course_id": course["id"],
        },
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()["plan_draft"]

    confirm = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert confirm.status_code == 201
    body = confirm.json()
    assert body["LearningPlan"]["current_module_id"] == body["modules"][0]["id"]
    assert len(body["knowledge_points"]) >= 1

    replay = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": draft})
    assert replay.status_code == 201
    assert replay.json()["LearningPlan"]["id"] == body["LearningPlan"]["id"]
    assert replay.json()["idempotency_replayed"] is True

    with connect() as conn:
        review_count = conn.execute(
            "SELECT count(*) AS count FROM review_states WHERE plan_id = %s",
            (body["LearningPlan"]["id"],),
        ).fetchone()
    assert review_count is not None
    assert review_count["count"] == len(body["knowledge_points"])


def test_confirm_plan_invalid_draft_and_idempotency_conflict(client: TestClient) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "javascript")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "Learn DOM.",
            "course_id": course["id"],
        },
    )
    draft = draft_response.json()["plan_draft"]
    invalid_draft = draft | {"modules": []}

    invalid = client.post("/api/plans", json={"user_id": user["id"], "plan_draft": invalid_draft})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "PLAN_DRAFT_INVALID"

    idempotency_key = f"m2-conflict-key-{uuid.uuid4().hex}"
    first = client.post(
        "/api/plans",
        headers={"Idempotency-Key": idempotency_key},
        json={"user_id": user["id"], "plan_draft": draft},
    )
    assert first.status_code == 201
    changed_draft = draft | {"goal_text": "Changed goal with same idempotency key."}
    conflict = client.post(
        "/api/plans",
        headers={"Idempotency-Key": idempotency_key},
        json={"user_id": user["id"], "plan_draft": changed_draft},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_onboarding_model_slots_drive_plan_readiness() -> None:
    vague_history = [{"role": "user", "content": "好的"} for _ in range(5)]
    vague_slots = ExtractedSlots(plan_ready=False)
    vague_context = OnboardingConversationContext(
        conversation_id="conv_vague",
        user_id="user_vague",
        status="active",
        extracted_context=vague_slots.model_dump(mode="json"),
        history=vague_history,
    )

    assert vague_slots.plan_ready is False
    assert detect_plan_proposal(vague_context, vague_slots) is False

    full_history = [{"role": "user", "content": "我想学 Python Web 后端，零基础，每天 1 小时"}]
    full_slots = ExtractedSlots(
        language="python",
        target_level="beginner",
        goal_text="学习 Python，聚焦 Web，从零基础入门",
        time_budget={"minutes_per_day": 60, "days_per_week": 7},
        focus="Web",
        plan_ready=True,
    )
    full_context = OnboardingConversationContext(
        conversation_id="conv_ready",
        user_id="user_ready",
        status="active",
        extracted_context=full_slots.model_dump(mode="json"),
        history=full_history,
    )

    assert full_slots.language == "python"
    assert full_slots.target_level == "beginner"
    assert full_slots.time_budget is not None
    assert full_slots.time_budget.minutes_per_day == 60
    assert full_slots.time_budget.days_per_week == 7
    assert full_slots.plan_ready is True
    assert detect_plan_proposal(full_context, full_slots) is True

    revised_slots = ExtractedSlots(
        language="python",
        target_level="beginner_to_intermediate",
        goal_text="学习 Python，聚焦数据分析，从入门到进阶",
        time_budget={"minutes_per_day": 120, "days_per_week": 1},
        focus="数据分析",
        plan_ready=True,
        revising=True,
    )
    assert revised_slots.revising is True
    assert revised_slots.time_budget is not None
    assert revised_slots.time_budget.minutes_per_day == 120
    assert revised_slots.time_budget.days_per_week == 1


def test_onboarding_extract_slots_requires_model_configuration() -> None:
    context = OnboardingConversationContext(
        conversation_id="conv_model_required",
        user_id="user_model_required",
        status="active",
        extracted_context={},
        history=[{"role": "user", "content": "我想学 Python"}],
    )

    with pytest.raises(LLMConfigurationError):
        extract_onboarding_slots(context, settings=Settings(llm_type="disabled"))


def test_confirm_onboarding_plan_uses_stashed_draft(client: TestClient) -> None:
    user = _create_user(client)
    course = _course_by_language(client, "python")
    draft_response = client.post(
        "/api/plans/generate",
        json={
            "user_id": user["id"],
            "mode": "goal_based",
            "goal_text": "学习 Python Web 后端，从零基础入门。",
            "course_id": course["id"],
            "target_level": "beginner",
        },
    )
    assert draft_response.status_code == 200
    plan_draft = PlanDraft.model_validate(draft_response.json()["plan_draft"])
    slots = ExtractedSlots(
        language="python",
        target_level="beginner",
        goal_text=plan_draft.goal_text,
        time_budget={"minutes_per_day": 60, "days_per_week": 7},
        focus="Web",
        plan_ready=True,
    )

    with connect() as conn:
        conversation_id = create_onboarding_session(conn, user_id=str(user["id"]))
        stash_plan_draft(
            conn,
            conversation_id=conversation_id,
            plan_draft=plan_draft,
            slots=slots,
        )
        conn.commit()

    confirm = client.post(
        f"/api/onboarding/{conversation_id}/confirm_plan",
        json={"user_id": user["id"]},
    )
    assert confirm.status_code == 201
    body = confirm.json()
    assert body["LearningPlan"]["goal_text"] == plan_draft.goal_text
    assert body["LearningPlan"]["language"] == "python"
    assert len(body["modules"]) == len(plan_draft.modules)

    replay = client.post(
        f"/api/onboarding/{conversation_id}/confirm_plan",
        json={"user_id": user["id"]},
    )
    assert replay.status_code == 201
    assert replay.json()["LearningPlan"]["id"] == body["LearningPlan"]["id"]
    assert replay.json()["idempotency_replayed"] is True

    with connect() as conn:
        row = conn.execute(
            "SELECT status, extracted_context FROM onboarding_conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    assert row["status"] == "confirmed"
    assert row["extracted_context"]["plan_draft"]["draft_id"] == plan_draft.draft_id


def test_onboarding_message_stream_triggers_plan_from_first_complete_turn(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)
    request_id = f"req_onboarding_sse_{uuid.uuid4().hex}"

    monkeypatch.setattr(
        onboarding_route,
        "extract_slots",
        lambda context: ExtractedSlots(
            language="python",
            target_level="beginner",
            goal_text="学习 Python，聚焦 Web，从零基础入门",
            time_budget={"minutes_per_day": 60, "days_per_week": 7},
            focus="Web",
            plan_ready=True,
        ),
    )

    with client.stream(
        "POST",
        "/api/onboarding/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": request_id},
        json={
            "user_id": user["id"],
            "content": "我想学 Python Web 后端，零基础，每天 1 小时",
            "client_message_id": f"desktop_onboarding_msg_{uuid.uuid4().hex}",
        },
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse_events("".join(response.iter_text()))

    event_types = [event["event"] for event in events]
    assert "session_created" in event_types
    assert "agent_message" in event_types
    assert "tool_call" in event_types
    assert "plan_draft" not in event_types
    assert event_types[-1] == "done"
    agent_text = str(
        [event for event in events if event["event"] == "agent_message"][-1]["data"]["content"]
    )
    assert agent_text == "信息够了，我生成一份路线卡片。想改方向、时间或难度，直接回复我就行。"

    session_created = next(event for event in events if event["event"] == "session_created")
    conversation_id = str(session_created["data"]["onboarding_session_id"])
    tool_done = next(
        event
        for event in events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    route_args = tool_done["data"]["arguments"]
    assert route_args["language"] == "python"
    assert route_args["goal_text"] == "学习 Python，聚焦 Web，从零基础入门"
    assert len(route_args["modules"]) >= 5
    assert route_args["modules"][0]["title"] == "Python 基础与值流动"

    with connect() as conn:
        row = conn.execute(
            "SELECT extracted_context FROM onboarding_conversations WHERE id = %s",
            (conversation_id,),
        ).fetchone()
    assert row is not None
    assert row["extracted_context"]["language"] == "python"
    assert row["extracted_context"]["plan_draft"]["draft_id"] == route_args["plan_id"]

    confirm = client.post(
        f"/api/onboarding/{conversation_id}/confirm_plan",
        json={"user_id": user["id"]},
    )
    assert confirm.status_code == 201
    assert confirm.json()["LearningPlan"]["goal_text"] == route_args["goal_text"]


def test_onboarding_message_stream_returns_error_when_model_unavailable(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)

    def fail_extract_slots(context):  # type: ignore[no-untyped-def]
        del context
        raise LLMCallError("provider unavailable")

    monkeypatch.setattr(onboarding_route, "extract_slots", fail_extract_slots)

    events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="我想学 Python 自动化脚本",
        conversation_id=None,
    )

    event_types = [event["event"] for event in events]
    assert "session_created" in event_types
    assert "agent_message" not in event_types
    assert "tool_call" not in event_types
    error = next(event["data"]["error"] for event in events if event["event"] == "error")
    assert error["code"] == "MODEL_UNAVAILABLE"
    assert error["recoverable"] is True


def test_onboarding_message_stream_generates_and_revises_route_from_guided_chat(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)
    monkeypatch.setattr(
        onboarding_route,
        "start_onboarding_generation",
        lambda context, *, user_content, settings=None, client=None: OnboardingMessageGeneration(
            chunks=["继续补充一个关键信息。"],
            generation_source="llm",
            generation_model="fake-onboarding-model",
        ),
    )
    slot_outputs = iter(
        [
            ExtractedSlots(
                language="python",
                missing_slot_question="你主要想用 Python 做什么？",
                plan_ready=False,
            ),
            ExtractedSlots(
                language="python",
                focus="自动化",
                goal_text="学习 Python，聚焦自动化脚本",
                missing_slot_question="你现在的基础大概是哪一档？",
                plan_ready=False,
            ),
            ExtractedSlots(
                language="python",
                target_level="beginner_to_intermediate",
                goal_text="学习 Python，聚焦自动化脚本，从入门到进阶",
                focus="自动化",
                plan_ready=True,
            ),
            ExtractedSlots(
                language="python",
                target_level="beginner_to_intermediate",
                goal_text="学习 Python，聚焦数据分析，从入门到进阶",
                time_budget={"minutes_per_day": 120, "days_per_week": 1},
                focus="数据分析",
                plan_ready=True,
                revising=True,
            ),
        ]
    )
    monkeypatch.setattr(
        onboarding_route,
        "extract_slots",
        lambda context: next(slot_outputs),
    )

    conversation_id: str | None = None
    for content in ("Python", "自动化脚本"):
        events = _send_onboarding_stream(
            client,
            user_id=str(user["id"]),
            content=content,
            conversation_id=conversation_id,
        )
        if conversation_id is None:
            session_created = next(event for event in events if event["event"] == "session_created")
            conversation_id = str(session_created["data"]["onboarding_session_id"])
        assert all(event["event"] != "tool_call" for event in events)

    assert conversation_id is not None
    generated_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="基础过一点语法",
        conversation_id=conversation_id,
    )
    generated_tool = next(
        event["data"]["arguments"]
        for event in generated_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    assert generated_tool["language"] == "python"
    assert "自动化" in generated_tool["goal_text"]

    revised_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="我想改成数据分析方向，每周只有 2 小时",
        conversation_id=conversation_id,
    )
    revised_tool = next(
        event["data"]["arguments"]
        for event in revised_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    assert "数据分析" in revised_tool["goal_text"]
    assert revised_tool["plan_id"] != generated_tool["plan_id"]


def test_onboarding_message_stream_revises_route_when_only_time_budget_changes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)
    slot_outputs = iter(
        [
            ExtractedSlots(
                language="python",
                target_level="beginner_to_intermediate",
                goal_text="学习 Python，聚焦自动化脚本，从入门到进阶",
                focus="自动化",
                plan_ready=True,
            ),
            ExtractedSlots(
                language="python",
                target_level="beginner_to_intermediate",
                goal_text="学习 Python，聚焦自动化脚本，从入门到进阶",
                time_budget={"minutes_per_day": 120, "days_per_week": 1},
                focus="自动化",
                plan_ready=True,
                revising=True,
            ),
        ]
    )
    monkeypatch.setattr(
        onboarding_route,
        "extract_slots",
        lambda context: next(slot_outputs),
    )

    generated_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="我想学 Python 自动化脚本，看过基础语法",
        conversation_id=None,
    )
    session_created = next(event for event in generated_events if event["event"] == "session_created")
    conversation_id = str(session_created["data"]["onboarding_session_id"])
    generated_tool = next(
        event["data"]["arguments"]
        for event in generated_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    assert generated_tool["time_budget"] is None

    revised_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="每周只有 2 小时",
        conversation_id=conversation_id,
    )
    revised_tool = next(
        event["data"]["arguments"]
        for event in revised_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    assert revised_tool["time_budget"] == {"minutes_per_day": 120, "days_per_week": 1}
    assert revised_tool["plan_id"] != generated_tool["plan_id"]


def test_onboarding_message_stream_replays_stored_route_tool_call(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(client)
    monkeypatch.setattr(
        onboarding_route,
        "extract_slots",
        lambda context: ExtractedSlots(
            language="python",
            target_level="beginner_to_intermediate",
            goal_text="学习 Python，聚焦自动化脚本，从入门到进阶",
            focus="自动化",
            plan_ready=True,
        ),
    )
    client_message_id = f"desktop_onboarding_msg_{uuid.uuid4().hex}"
    first_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="我想学 Python 自动化脚本，看过基础语法",
        conversation_id=None,
        client_message_id=client_message_id,
    )
    session_created = next(event for event in first_events if event["event"] == "session_created")
    conversation_id = str(session_created["data"]["onboarding_session_id"])
    first_tool = next(
        event["data"]
        for event in first_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )

    replay_events = _send_onboarding_stream(
        client,
        user_id=str(user["id"]),
        content="我想学 Python 自动化脚本，看过基础语法",
        conversation_id=conversation_id,
        client_message_id=client_message_id,
    )
    replay_tool = next(
        event["data"]
        for event in replay_events
        if event["event"] == "tool_call" and event["data"]["phase"] == "done"
    )
    done = next(event["data"] for event in replay_events if event["event"] == "done")

    assert replay_tool == first_tool
    assert done["generation_source"] == "replay"

    with connect() as conn:
        agent_count = conn.execute(
            "SELECT count(*) AS count FROM onboarding_messages WHERE conversation_id = %s AND role = 'agent'",
            (conversation_id,),
        ).fetchone()
    assert agent_count is not None
    assert agent_count["count"] == 1


def _create_user(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/users",
        json={
            "display_name": f"M2 User {uuid.uuid4().hex[:8]}",
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


def _dynamic_modules(language: str) -> list[DraftModule]:
    modules: list[DraftModule] = []
    for index in range(4):
        modules.append(
            DraftModule(
                temp_id=f"mod_draft_{language}_dynamic_{index}",
                title=f"动态模块{index + 1}",
                description=f"这是第{index + 1}个动态模块。",
                order_index=index,
                is_skippable=index >= 3,
                estimated_sessions=3,
                source="agent_generated",
                knowledge_points=[
                    DraftKnowledgePoint(
                        temp_id=f"kp_draft_{language}_dynamic_{index}_{point}",
                        title=f"动态知识点{index + 1}-{point + 1}",
                        description=f"这是第{index + 1}个模块的动态知识点。",
                        skill_tags=["dynamic", "practice"],
                        source="agent_generated",
                    )
                    for point in range(2)
                ],
            )
        )
    return modules


def _parse_sse_events(raw: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in raw.replace("\r\n", "\n").split("\n\n"):
        event_type: str | None = None
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


def _send_onboarding_stream(
    client: TestClient,
    *,
    user_id: str,
    content: str,
    conversation_id: str | None,
    client_message_id: str | None = None,
) -> list[dict[str, object]]:
    payload: dict[str, object] = {
        "user_id": user_id,
        "content": content,
        "client_message_id": client_message_id or f"desktop_onboarding_msg_{uuid.uuid4().hex}",
    }
    if conversation_id is not None:
        payload["onboarding_session_id"] = conversation_id
    with client.stream(
        "POST",
        "/api/onboarding/messages",
        headers={"Accept": "text/event-stream", "X-Request-Id": f"req_{uuid.uuid4().hex}"},
        json=payload,
    ) as response:
        assert response.status_code == 200
        return _parse_sse_events("".join(response.iter_text()))
