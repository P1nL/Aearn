import json
from collections.abc import Mapping, Sequence

import pytest

from app.agents.exercise_coach_agent import (
    EXERCISE_COACH_AGENT_NAME,
    AgentsSDKExerciseCoachClient,
    ExerciseCoachJsonResponse,
    build_sdk_error_explanation,
    build_sdk_explanation_check_response,
    build_sdk_hint_response,
)
from app.agents.note_assist_agent import (
    NOTE_ASSIST_AGENT_NAME,
    AgentsSDKNoteAssistClient,
    NoteAssistContext,
    assert_safe_note_draft_output,
)
from app.agents.onboarding_slot_extractor import ExtractedSlots, ResponsesOnboardingSlotExtractor
from app.agents.onboarding_plan_agent import (
    ONBOARDING_PLAN_AGENT_NAME,
    AgentsSDKOnboardingPlanClient,
    OnboardingPlanContext,
    OnboardingPlanJsonResponse,
    build_onboarding_plan_context,
    build_sdk_onboarding_plan_response,
)
from app.agents.review_coach_agent import (
    REVIEW_COACH_AGENT_NAME,
    AgentsSDKReviewCoachClient,
    ReviewCoachContext,
    ReviewCoachJsonResponse,
    build_sdk_review_coach_response,
)
from app.agents.guardrails import (
    assert_safe_teaching_output,
    check_teaching_request,
    detect_direct_answer_request,
)
from app.core.config import Settings
from app.agents.learning_conversation_agent import AgentsSDKLearningConversationClient, TEACHING_AGENT_NAME
from app.agents.sdk_runtime import extract_text_delta, normalize_openai_base_url
from app.agents.tools import build_teaching_tools, summarize_current_learning_context, summarize_latest_visible_attempt
from app.models.onboarding import PlanDraft, PlanGenerateRequest
from app.services.llm_client import LLMJsonResponse, OpenAICompatibleClient
from app.services.llm_client import LLMInvalidResponseError
from app.services.llm_explain_error import build_llm_error_explanation
from app.services.plan_generator import build_plan_draft


def test_settings_reports_openai_compatible_configuration() -> None:
    configured = Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://provider.example/v1",
        openai_model="third-party-model",
    )
    incomplete = Settings(llm_type="openai", openai_api_key="", openai_base_url="", openai_model="")

    assert configured.openai_compatible_configured is True
    assert configured.llm_configuration_status == "configured"
    assert incomplete.openai_compatible_configured is False
    assert incomplete.llm_configuration_status == "incomplete"


def test_openai_compatible_client_parses_responses_json_completion() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["payload"] = dict(payload)
        captured["timeout"] = timeout
        return {
            "model": "gpt-5.4",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"error_cause":"state_scope_error","next_action":"retry_same"}',
                        }
                    ],
                }
            ],
        }

    client = OpenAICompatibleClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="third-party-model",
            llm_timeout_seconds=7,
        ),
        transport=transport,
    )

    response = client.complete_json(
        [
            {"role": "system", "content": "system instructions"},
            {"role": "user", "content": "return JSON"},
        ]
    )

    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["timeout"] == 7
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    assert captured["payload"]["model"] == "third-party-model"
    assert captured["payload"]["instructions"] == "system instructions"
    assert captured["payload"]["input"] == "return JSON"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["text"] == {"format": {"type": "json_object"}}
    assert response.content["error_cause"] == "state_scope_error"
    assert response.model == "gpt-5.4"


def test_openai_compatible_client_adds_json_mode_hint_when_input_omits_json() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, timeout
        captured["payload"] = dict(payload)
        return {
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"ok":true}',
                        }
                    ],
                }
            ],
        }

    client = OpenAICompatibleClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example",
            openai_model="third-party-model",
        ),
        transport=transport,
    )

    response = client.complete_json([{"role": "user", "content": "return an object"}])

    assert captured["payload"]["input"] == (
        "return an object\n\nReturn the final answer as a JSON object."
    )
    assert response.content == {"ok": True}


def test_onboarding_slot_extractor_uses_streaming_responses_json_client() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["payload"] = dict(payload)
        captured["timeout"] = timeout
        return {
            "model": "gpt-5.5",
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(
                                {
                                    "language": "python",
                                    "target_level": "beginner",
                                    "goal_text": "学习 Python Web 后端开发",
                                    "time_budget": {"minutes_per_day": 60, "days_per_week": 7},
                                    "focus": "Web 后端",
                                    "plan_ready": True,
                                    "missing_slot_question": None,
                                    "revising": False,
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ],
                }
            ],
        }

    settings = Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://provider.example",
        openai_model="third-party-model",
        llm_timeout_seconds=11,
    )
    client = OpenAICompatibleClient(settings, transport=transport)
    extractor = ResponsesOnboardingSlotExtractor(settings, client=client)

    slots = extractor.extract(
        [{"role": "user", "content": "我想学 Python Web 后端，零基础，每天 1 小时"}],
        ExtractedSlots(),
    )

    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["timeout"] == 11
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    assert captured["payload"]["model"] == "third-party-model"
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["text"] == {"format": {"type": "json_object"}}
    assert "建档槽位提取助手" in str(captured["payload"]["instructions"])
    assert "对话历史" in str(captured["payload"]["input"])
    assert slots.language == "python"
    assert slots.target_level == "beginner"
    assert slots.goal_text == "学习 Python Web 后端开发"
    assert slots.time_budget is not None
    assert slots.time_budget.minutes_per_day == 60
    assert slots.time_budget.days_per_week == 7
    assert slots.focus == "Web 后端"
    assert slots.plan_ready is True


def test_openai_compatible_client_streams_text_deltas() -> None:
    captured: dict[str, object] = {}

    def stream_transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Sequence[str]:
        captured["url"] = url
        captured["headers"] = dict(headers)
        captured["payload"] = dict(payload)
        captured["timeout"] = timeout
        return ["先看状态变量", "，再看事件回调。"]

    client = OpenAICompatibleClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
            llm_timeout_seconds=9,
        ),
        stream_transport=stream_transport,
    )

    chunks = list(
        client.complete_text_stream(
            [
                {"role": "system", "content": "system instructions"},
                {"role": "user", "content": "draft note"},
            ]
        )
    )

    assert chunks == ["先看状态变量", "，再看事件回调。"]
    assert captured["url"] == "https://provider.example/v1/responses"
    assert captured["timeout"] == 9
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    assert captured["payload"]["model"] == "third-party-model"
    assert captured["payload"]["input"] == "draft note"
    assert captured["payload"]["stream"] is True
    assert "text" not in captured["payload"]
    assert "temperature" not in captured["payload"]


def test_agents_sdk_learning_conversation_client_streams_text_deltas() -> None:
    captured: dict[str, object] = {}

    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, delta: str) -> None:
            self.data = FakeDelta(delta)

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            yield FakeEvent("先看状态变量")
            yield FakeEvent("，再看事件回调。")

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            captured["agent_name"] = starting_agent.name
            captured["tool_names"] = [tool.name for tool in starting_agent.tools]
            captured["input_guardrail_count"] = len(starting_agent.input_guardrails)
            captured["output_guardrail_count"] = len(starting_agent.output_guardrails)
            captured["input"] = input
            captured["run_config"] = kwargs["run_config"]
            captured["max_turns"] = kwargs["max_turns"]
            return FakeStreamedRun()

    client = AgentsSDKLearningConversationClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
            llm_timeout_seconds=9,
        ),
        runner=FakeRunner(),
    )

    chunks = list(
        client.complete_text_stream(
            _teaching_messages()
        )
    )

    assert chunks == ["先看状态变量", "，再看事件回调。"]
    assert captured["agent_name"] == TEACHING_AGENT_NAME
    assert captured["tool_names"] == ["get_current_learning_context", "get_latest_visible_attempt_summary"]
    assert captured["input_guardrail_count"] == 1
    assert captured["output_guardrail_count"] == 1
    assert "draft note" in str(captured["input"])
    assert captured["max_turns"] == 4
    assert captured["run_config"].tracing_disabled is True
    assert client.model == "third-party-model"


def test_agents_sdk_streaming_ignores_done_text_after_deltas() -> None:
    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeDone:
        type = "response.output_text.done"

        def __init__(self, text: str) -> None:
            self.text = text

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, data: FakeDelta | FakeDone) -> None:
            self.data = data

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            yield FakeEvent(FakeDelta("先看状态变量"))
            yield FakeEvent(FakeDelta("，再看事件回调。"))
            yield FakeEvent(FakeDone("先看状态变量，再看事件回调。"))

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            del starting_agent, input, kwargs
            return FakeStreamedRun()

    client = AgentsSDKLearningConversationClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
        ),
        runner=FakeRunner(),
    )

    chunks = list(client.complete_text_stream(_teaching_messages()))

    assert chunks == ["先看状态变量", "，再看事件回调。"]


def test_agents_sdk_exercise_coach_client_streams_json_and_attaches_guardrails() -> None:
    captured: dict[str, object] = {}

    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, delta: str) -> None:
            self.data = FakeDelta(delta)

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            yield FakeEvent('{"content":"先看共享状态位置，')
            yield FakeEvent('不要重写整题。"}')

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            captured["agent_name"] = starting_agent.name
            captured["tool_names"] = [tool.name for tool in starting_agent.tools]
            captured["input_guardrail_count"] = len(starting_agent.input_guardrails)
            captured["output_guardrail_count"] = len(starting_agent.output_guardrails)
            captured["input"] = input
            captured["run_config"] = kwargs["run_config"]
            captured["max_turns"] = kwargs["max_turns"]
            return FakeStreamedRun()

    client = AgentsSDKExerciseCoachClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
        ),
        runner=FakeRunner(),
    )

    response = client.complete_json(
        [
            {"role": "system", "content": "system instructions"},
            {"role": "user", "content": '{"learner_message":"Generate a hint."}'},
        ]
    )

    assert response.content == {"content": "先看共享状态位置，不要重写整题。"}
    assert captured["agent_name"] == EXERCISE_COACH_AGENT_NAME
    assert captured["tool_names"] == []
    assert captured["input_guardrail_count"] == 1
    assert captured["output_guardrail_count"] == 1
    assert captured["max_turns"] == 2
    assert captured["run_config"].tracing_disabled is True


def test_agents_sdk_note_assist_client_streams_text_deltas_and_attaches_guardrails() -> None:
    captured: dict[str, object] = {}

    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, delta: str) -> None:
            self.data = FakeDelta(delta)

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            yield FakeEvent("补充主题：JavaScript DOM 基础 / 状态变量\n")
            yield FakeEvent("可补充：\n- 错因：最近一次运行状态为 success。")

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            captured["agent_name"] = starting_agent.name
            captured["tool_names"] = [tool.name for tool in starting_agent.tools]
            captured["input_guardrail_count"] = len(starting_agent.input_guardrails)
            captured["output_guardrail_count"] = len(starting_agent.output_guardrails)
            captured["input"] = input
            captured["run_config"] = kwargs["run_config"]
            captured["max_turns"] = kwargs["max_turns"]
            return FakeStreamedRun()

    client = AgentsSDKNoteAssistClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
            llm_timeout_seconds=9,
        ),
        runner=FakeRunner(),
    )

    context = NoteAssistContext(
        note_id="note_001",
        note_title="状态变量位置",
        knowledge_point_title="事件监听与状态变量",
        module_title="DOM 事件",
        language="javascript",
        note_excerpt="count 不能写在回调内部。",
        style="concise",
        focus="mistake_summary",
        session_id="sess_001",
        session_summary="上次在点击计数上犯了作用域错误。",
        latest_attempt={
            "attempt_id": "att_001",
            "session_id": "sess_001",
            "attempt_type": "run",
            "runtime_status": "success",
            "test_pass_rate": 0.5,
            "passed_test_count": 1,
            "total_test_count": 2,
            "error_message": "Expected textContent to be 3, got 1.",
            "error_cause": "state_scope_error",
            "explanation_text": "count 放在回调外层才能跨点击共享。",
            "hint_usage_count": 1,
            "error_count": 0,
        },
    )

    chunks = list(client.complete_text_stream(context))

    assert chunks == ["补充主题：JavaScript DOM 基础 / 状态变量\n", "可补充：\n- 错因：最近一次运行状态为 success。"]
    assert captured["agent_name"] == NOTE_ASSIST_AGENT_NAME
    assert captured["tool_names"] == []
    assert captured["input_guardrail_count"] == 1
    assert captured["output_guardrail_count"] == 1
    assert "count 不能写在回调内部。" in str(captured["input"])
    assert captured["max_turns"] == 2
    assert captured["run_config"].tracing_disabled is True
    assert client.model == "third-party-model"


def test_note_assist_client_rejects_output_that_leaks_code_draft_wording() -> None:
    class LeakingRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            del starting_agent, input, kwargs

            class FakeStreamedRun:
                final_output = None

                async def stream_events(self):  # type: ignore[no-untyped-def]
                    yield type(
                        "FakeEvent",
                        (),
                        {
                            "type": "raw_response_event",
                            "data": type(
                                "FakeDelta",
                                (),
                                {
                                    "type": "response.output_text.delta",
                                    "delta": "CodeDraft /api/code-drafts 完整笔记必须重写。",
                                },
                            )(),
                        },
                    )()

            return FakeStreamedRun()

    client = AgentsSDKNoteAssistClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
        ),
        runner=LeakingRunner(),
    )

    context = NoteAssistContext(
        note_id="note_001",
        note_title="状态变量位置",
        knowledge_point_title="事件监听与状态变量",
        module_title="DOM 事件",
        language="javascript",
        note_excerpt="count 不能写在回调内部。",
        style="concise",
        focus="mistake_summary",
    )

    assert client.complete_text(context) is None


def test_agents_sdk_review_coach_client_streams_text_deltas_and_attaches_guardrails() -> None:
    captured: dict[str, object] = {}

    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, delta: str) -> None:
            self.data = FakeDelta(delta)

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            yield FakeEvent('{"initial_agent_message":"先用变体题验证能否接管，",')
            yield FakeEvent('"variant_reason":"上次薄弱点是 state_scope_error。"}')

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            captured["agent_name"] = starting_agent.name
            captured["tool_names"] = [tool.name for tool in starting_agent.tools]
            captured["input_guardrail_count"] = len(starting_agent.input_guardrails)
            captured["output_guardrail_count"] = len(starting_agent.output_guardrails)
            captured["input"] = input
            captured["run_config"] = kwargs["run_config"]
            captured["max_turns"] = kwargs["max_turns"]
            return FakeStreamedRun()

    client = AgentsSDKReviewCoachClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
            llm_timeout_seconds=9,
        ),
        runner=FakeRunner(),
    )

    context = ReviewCoachContext(
        knowledge_point_id="kp_dom_event_state",
        knowledge_point_title="事件监听与状态变量",
        knowledge_point_description="理解事件回调和外层状态变量的关系。",
        weak_points_json=["state_scope_error"],
        mastery_score=0.42,
        due_at="2026-05-11T09:00:00Z",
        forget_risk="normal",
        last_fsrs_rating="Good",
        review_exercise_id="ex_dom_click_count",
        review_exercise_title="点击按钮后计数递增",
        review_exercise_type="code_blank",
        review_exercise_prompt="补全事件绑定代码，让按钮每点击一次数字加 1。",
        runtime_language="javascript",
        runtime_tier="browser_preview",
        visible_tests=[
            {
                "case_type": "visible",
                "weight": 1,
                "is_critical": True,
                "timeout_ms": 5000,
                "order_index": 0,
            },
        ],
        latest_attempt={
            "attempt_id": "att_001",
            "attempt_type": "review_submit",
            "runtime_status": "success",
            "test_pass_rate": 1.0,
            "passed_test_count": 1,
            "total_test_count": 1,
            "error_message": None,
            "error_cause": None,
            "explanation_text": "状态变量在回调外层。",
            "hint_usage_count": 0,
            "error_count": 0,
            "score": 8,
            "fsrs_rating": "Good",
        },
    )

    response = client.complete_json(context)

    assert response.content == {
        "initial_agent_message": "先用变体题验证能否接管，",
        "variant_reason": "上次薄弱点是 state_scope_error。",
    }
    assert captured["agent_name"] == REVIEW_COACH_AGENT_NAME
    assert captured["tool_names"] == []
    assert captured["input_guardrail_count"] == 1
    assert captured["output_guardrail_count"] == 1
    assert "state_scope_error" in str(captured["input"])
    assert captured["max_turns"] == 2
    assert captured["run_config"].tracing_disabled is True
    assert client.model == "third-party-model"


def test_review_coach_sdk_response_rejects_output_that_leaks_hidden_identifier() -> None:
    class LeakingCoachClient:
        model = "sdk-review-model"

        def complete_json(
            self,
            context: ReviewCoachContext,
            *,
            temperature: float = 0.2,
        ) -> ReviewCoachJsonResponse:
            del context, temperature
            return ReviewCoachJsonResponse(
                content={
                    "initial_agent_message": "先看 hidden_three_clicks 再做题。",
                    "variant_reason": "上次薄弱点是 hidden_three_clicks。",
                },
                model=self.model,
            )

    context = ReviewCoachContext(
        knowledge_point_id="kp_dom_event_state",
        knowledge_point_title="事件监听与状态变量",
        knowledge_point_description="理解事件回调和外层状态变量的关系。",
        weak_points_json=["state_scope_error"],
        mastery_score=0.42,
        due_at="2026-05-11T09:00:00Z",
        forget_risk="normal",
        last_fsrs_rating="Good",
        review_exercise_id="ex_dom_click_count",
        review_exercise_title="点击按钮后计数递增",
        review_exercise_type="code_blank",
        review_exercise_prompt="补全事件绑定代码，让按钮每点击一次数字加 1。",
        runtime_language="javascript",
        runtime_tier="browser_preview",
        visible_tests=[],
    )

    assert build_sdk_review_coach_response(context, client=LeakingCoachClient()) is None


def test_agents_sdk_onboarding_plan_client_streams_json_and_attaches_guardrails() -> None:
    captured: dict[str, object] = {}
    context, base_draft = _onboarding_plan_context()
    candidate = base_draft.model_copy(update={"goal_text": "Learn DOM events while validating AI-generated code."})

    class FakeDelta:
        type = "response.output_text.delta"

        def __init__(self, delta: str) -> None:
            self.delta = delta

    class FakeEvent:
        type = "raw_response_event"

        def __init__(self, delta: str) -> None:
            self.data = FakeDelta(delta)

    class FakeStreamedRun:
        final_output = None

        async def stream_events(self):  # type: ignore[no-untyped-def]
            payload = json.dumps(
                {
                    "plan_draft": candidate.model_dump(mode="json"),
                    "agent_notes": ["保持 DOM 模板，只细化验证 AI 生成代码的目标。"],
                },
                ensure_ascii=False,
            )
            midpoint = len(payload) // 2
            yield FakeEvent(payload[:midpoint])
            yield FakeEvent(payload[midpoint:])

    class FakeRunner:
        def run_streamed(self, starting_agent, input, **kwargs):  # type: ignore[no-untyped-def]
            captured["agent_name"] = starting_agent.name
            captured["tool_names"] = [tool.name for tool in starting_agent.tools]
            captured["input_guardrail_count"] = len(starting_agent.input_guardrails)
            captured["output_guardrail_count"] = len(starting_agent.output_guardrails)
            captured["input"] = input
            captured["run_config"] = kwargs["run_config"]
            captured["max_turns"] = kwargs["max_turns"]
            return FakeStreamedRun()

    client = AgentsSDKOnboardingPlanClient(
        Settings(
            llm_type="openai",
            openai_api_key="test-key",
            openai_base_url="https://provider.example/v1",
            openai_model="third-party-model",
            llm_timeout_seconds=9,
        ),
        runner=FakeRunner(),
    )

    response = client.complete_json(context)

    assert response.content["plan_draft"]["goal_text"] == "Learn DOM events while validating AI-generated code."  # type: ignore[index]
    assert captured["agent_name"] == ONBOARDING_PLAN_AGENT_NAME
    assert captured["tool_names"] == []
    assert captured["input_guardrail_count"] == 1
    assert captured["output_guardrail_count"] == 1
    assert "safe_base_plan_draft" in str(captured["input"])
    assert captured["max_turns"] == 2
    assert captured["run_config"].tracing_disabled is True
    assert client.model == "third-party-model"


def test_onboarding_plan_sdk_response_accepts_valid_template_candidate() -> None:
    context, base_draft = _onboarding_plan_context()
    candidate = base_draft.model_copy(update={"goal_text": "Learn DOM events with visible assertion practice."})

    class FakePlanClient:
        model = "sdk-onboarding-model"

        def complete_json(
            self,
            context: OnboardingPlanContext,
            *,
            temperature: float = 0.2,
        ) -> OnboardingPlanJsonResponse:
            del context, temperature
            return OnboardingPlanJsonResponse(
                content={
                    "plan_draft": candidate.model_dump(mode="json"),
                    "agent_notes": ["先保留浏览器 preview 边界，再安排 DOM 事件练习。"],
                },
                model=self.model,
            )

    response = build_sdk_onboarding_plan_response(context, client=FakePlanClient())

    assert response is not None
    plan_draft = response["plan_draft"]
    assert isinstance(plan_draft, PlanDraft)
    assert plan_draft.goal_text == "Learn DOM events with visible assertion practice."
    assert response["agent_notes"] == ["先保留浏览器 preview 边界，再安排 DOM 事件练习。"]
    assert response["generation_model"] == "sdk-onboarding-model"


def test_onboarding_plan_sdk_response_rejects_invalid_draft() -> None:
    context, base_draft = _onboarding_plan_context()
    invalid = base_draft.model_dump(mode="json") | {"modules": []}

    class InvalidPlanClient:
        model = "sdk-onboarding-model"

        def complete_json(
            self,
            context: OnboardingPlanContext,
            *,
            temperature: float = 0.2,
        ) -> OnboardingPlanJsonResponse:
            del context, temperature
            return OnboardingPlanJsonResponse(content={"plan_draft": invalid}, model=self.model)

    assert build_sdk_onboarding_plan_response(context, client=InvalidPlanClient()) is None


def test_onboarding_plan_sdk_response_rejects_unsupported_runtime_claim() -> None:
    context, base_draft = _onboarding_plan_context()
    unsupported = base_draft.model_dump(mode="json")
    unsupported["runtime_boundary"] = {
        "runtime_tier": "compiled_sandbox_later",
        "unsupported_languages": ["java", "cpp"],
        "notice": "Java/C++ can run in the first MVP.",
    }

    class UnsupportedRuntimeClient:
        model = "sdk-onboarding-model"

        def complete_json(
            self,
            context: OnboardingPlanContext,
            *,
            temperature: float = 0.2,
        ) -> OnboardingPlanJsonResponse:
            del context, temperature
            return OnboardingPlanJsonResponse(content={"plan_draft": unsupported}, model=self.model)

    assert build_sdk_onboarding_plan_response(context, client=UnsupportedRuntimeClient()) is None


def test_note_assist_guardrails_block_code_draft_and_full_note_phrasing() -> None:
    for text in [
        "CodeDraft /api/code-drafts 应该重写整篇笔记。",
        "publishDrawer 不应该出现在笔记辅助输出里。",
        "完整笔记如下：状态变量要放在回调外层。",
    ]:
        with pytest.raises(LLMInvalidResponseError):
            assert_safe_note_draft_output(text)


def test_agents_sdk_extract_text_delta_accepts_raw_event_duck_type() -> None:
    class FakeDelta:
        type = "response.output_text.delta"
        delta = "delta text"

    class FakeEvent:
        type = "raw_response_event"
        data = FakeDelta()

    assert extract_text_delta(FakeEvent()) == "delta text"


def test_agents_sdk_normalizes_openai_base_url_for_client() -> None:
    assert normalize_openai_base_url("https://provider.example") == "https://provider.example/v1"
    assert normalize_openai_base_url("https://provider.example/v1") == "https://provider.example/v1"
    assert normalize_openai_base_url("https://provider.example/v1/responses") == "https://provider.example/v1"


def test_teaching_tools_return_safe_bounded_summaries() -> None:
    evidence = _learning_evidence()
    tools = build_teaching_tools(_teaching_messages())
    context_summary = summarize_current_learning_context(evidence)
    attempt_summary = summarize_latest_visible_attempt(evidence)
    serialized = json.dumps([context_summary, attempt_summary], ensure_ascii=False)

    assert [tool.name for tool in tools] == ["get_current_learning_context", "get_latest_visible_attempt_summary"]
    assert context_summary["exercise"]["has_starter_code"] is True  # type: ignore[index]
    assert attempt_summary["non_visible_test_counts"] == {"total": 1, "failed": 1}
    assert "hidden_three_clicks" not in serialized
    assert "solution_reference" not in serialized
    assert "secret solution" not in serialized
    assert "submitted_code" not in serialized
    assert "let count = 0" not in serialized


def test_sdk_hint_response_uses_safe_prompt_and_normalizes_shape() -> None:
    captured: dict[str, object] = {}

    class FakeCoachClient:
        model = "sdk-coach-model"

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> ExerciseCoachJsonResponse:
            captured["messages"] = messages
            captured["temperature"] = temperature
            return ExerciseCoachJsonResponse(
                content={"content": "先确认状态更新发生在点击回调中，不要重写整题。"},
                model=self.model,
            )

    response = build_sdk_hint_response(
        _exercise(),
        blank={
            "blank_key": "blank_2",
            "placeholder": "count += 1",
            "expected_concept": "在回调里递增共享状态。",
            "is_core": True,
        },
        hint_level="concept",
        current_code="button.__BLANK_1__('click', () => { __BLANK_2__; });",
        hint_usage_count=2,
        client=FakeCoachClient(),
    )

    assert response == {
        "hint": {"hint_level": "concept", "content": "先确认状态更新发生在点击回调中，不要重写整题。"},
        "hint_usage_count": 2,
        "affected_score": {"max_result": "passed", "score_penalty_hint": 1},
        "next_action": "retry_same",
    }
    prompt_text = json.dumps(captured["messages"], ensure_ascii=False)
    assert captured["temperature"] == 0.2
    assert "solution_reference" not in prompt_text
    assert "secret solution" not in prompt_text
    assert "submitted_code" not in prompt_text
    assert "hidden_three_clicks" not in prompt_text


def test_sdk_error_explanation_uses_server_knowledge_point_and_metadata() -> None:
    class FakeCoachClient:
        model = "sdk-coach-model"

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> ExerciseCoachJsonResponse:
            return ExerciseCoachJsonResponse(
                content={
                    "error_cause": "state_scope_error",
                    "explanation": "状态放在点击回调里，每次点击都会重新初始化。",
                    "fix_suggestion": "把共享状态移到回调外层，再重新运行可见测试。",
                    "related_knowledge_points": [{"id": "model_should_not_control_this", "title": "bad"}],
                    "next_action": "retry_same",
                },
                model=self.model,
            )

    response = build_sdk_error_explanation(
        _exercise(),
        error_message="Expected textContent to be 3, got 1.",
        stderr="",
        failed_tests=[{"case_id": "hidden_three_clicks", "case_type": "hidden", "message": "连续点击三次后状态未累加"}],
        current_code="button.addEventListener('click', () => { let count = 0; count += 1; });",
        related_knowledge_points=[{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}],
        client=FakeCoachClient(),
    )

    assert response is not None
    assert response["generation_source"] == "llm"
    assert response["generation_model"] == "sdk-coach-model"
    assert response["related_knowledge_points"] == [{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}]


def test_sdk_error_explanation_rejects_output_that_leaks_hidden_identifier() -> None:
    class LeakingCoachClient:
        model = "sdk-coach-model"

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> ExerciseCoachJsonResponse:
            return ExerciseCoachJsonResponse(
                content={
                    "error_cause": "state_scope_error",
                    "explanation": "失败来自 hidden_three_clicks。",
                    "fix_suggestion": "修改状态位置。",
                    "next_action": "retry_same",
                },
                model=self.model,
            )

    response = build_sdk_error_explanation(
        _exercise(),
        error_message="Expected textContent to be 3, got 1.",
        stderr="",
        failed_tests=[{"case_id": "hidden_three_clicks", "case_type": "hidden", "message": "连续点击三次后状态未累加"}],
        current_code="button.addEventListener('click', () => { let count = 0; count += 1; });",
        related_knowledge_points=[{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}],
        client=LeakingCoachClient(),
    )

    assert response is None


def test_sdk_explanation_check_rejects_invalid_output() -> None:
    class InvalidCoachClient:
        model = "sdk-coach-model"

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> ExerciseCoachJsonResponse:
            return ExerciseCoachJsonResponse(
                content={"result": "easy", "feedback": "looks good"},
                model=self.model,
            )

    response = build_sdk_explanation_check_response(
        _exercise(),
        explanation="状态变量放在回调外层，所以连续点击能共享同一个 count。",
        focus="core_logic",
        round_number=1,
        client=InvalidCoachClient(),
    )

    assert response is None


def test_teaching_guardrails_block_leaky_or_complete_answer_text() -> None:
    assert check_teaching_request("为什么 count 每次点击都会重置？").blocked is False
    assert check_teaching_request("直接给我完整答案").blocked is False
    assert detect_direct_answer_request("直接给我完整答案") is True

    for leaky_text in [
        "失败来自 hidden_three_clicks。",
        "solution_reference 里已经有参考答案。",
        "provider raw 401 invalid_api_key",
        "完整答案如下：button.addEventListener(...)",
        "完整答案如下：\n```js\nbutton.addEventListener('click', () => {})\n```",
    ]:
        with pytest.raises(LLMInvalidResponseError):
            assert_safe_teaching_output(leaky_text)

    assert_safe_teaching_output("例如 `:hover` 表示鼠标移上去时的状态。")
    assert_safe_teaching_output("```css\n.button:hover { color: red; }\n```")


def test_llm_explain_error_uses_model_output_and_server_knowledge_point() -> None:
    class FakeClient:
        model = "third-party-model"

        def __init__(self) -> None:
            self.messages: Sequence[Mapping[str, str]] = []

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> LLMJsonResponse:
            self.messages = messages
            return LLMJsonResponse(
                content={
                    "error_cause": "state_scope_error",
                    "explanation": "count 被放在点击回调里，每次点击都会重新初始化。",
                    "fix_suggestion": "把共享状态移到回调外层，只在回调里累加并同步页面。",
                    "related_knowledge_points": [{"id": "model_should_not_control_this", "title": "bad"}],
                    "next_action": "retry_same",
                },
                model=self.model,
            )

    fake_client = FakeClient()
    response = build_llm_error_explanation(
        _exercise(),
        error_message="Expected textContent to be 3, got 1.",
        stderr="",
        failed_tests=[{"case_id": "hidden_three_clicks", "case_type": "hidden", "message": "连续点击三次后状态未累加"}],
        current_code="button.addEventListener('click', () => { let count = 0; count += 1; });",
        related_knowledge_points=[{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}],
        client=fake_client,
    )

    assert response is not None
    assert response["generation_source"] == "llm"
    assert response["generation_model"] == "third-party-model"
    assert response["related_knowledge_points"] == [{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}]
    assert "secret solution" not in fake_client.messages[1]["content"]


def test_llm_explain_error_rejects_output_that_leaks_hidden_identifier() -> None:
    class LeakingClient:
        model = "third-party-model"

        def complete_json(
            self,
            messages: Sequence[Mapping[str, str]],
            *,
            temperature: float = 0.2,
        ) -> LLMJsonResponse:
            return LLMJsonResponse(
                content={
                    "error_cause": "state_scope_error",
                    "explanation": "失败来自 hidden_three_clicks。",
                    "fix_suggestion": "修改状态位置。",
                    "related_knowledge_points": [],
                    "next_action": "retry_same",
                },
                model=self.model,
            )

    response = build_llm_error_explanation(
        _exercise(),
        error_message="Expected textContent to be 3, got 1.",
        stderr="",
        failed_tests=[{"case_id": "hidden_three_clicks", "case_type": "hidden", "message": "连续点击三次后状态未累加"}],
        current_code="button.addEventListener('click', () => { let count = 0; count += 1; });",
        related_knowledge_points=[{"id": "kp_dom_event_state", "title": "事件监听与状态变量"}],
        client=LeakingClient(),
    )

    assert response is None


def _exercise() -> dict[str, object]:
    return {
        "title": "事件监听与状态变量",
        "exercise_type": "code_blank",
        "prompt_markdown": "修复点击计数状态。",
        "solution_reference": "secret solution",
        "runtime_profile": {"language": "javascript", "runtime_tier": "browser_preview"},
        "code_blanks": [
            {
                "blank_key": "blank_2",
                "expected_concept": "shared state update",
                "is_core": True,
            }
        ],
    }


def _teaching_messages() -> list[dict[str, str]]:
    return [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": f"reply to learner\n{json.dumps(_learning_evidence(), ensure_ascii=False)}"},
    ]


def _learning_evidence() -> dict[str, object]:
    return {
        "current_stage": "DOM 事件",
        "knowledge_point": {
            "id": "kp_dom_event_state",
            "title": "事件监听与状态变量",
            "status": "learning",
            "weak_points": ["state_scope_error"],
        },
        "exercise": {
            "id": "ex_dom_click_count",
            "title": "点击按钮后计数递增",
            "exercise_type": "code_blank",
            "prompt_markdown": "补全事件绑定代码，让按钮每点击一次数字加 1。",
            "starter_code": "let count = 0; __BLANK_1__",
            "solution_reference": "secret solution",
            "difficulty": 2,
            "runtime_profile": {"language": "javascript", "runtime_tier": "browser_preview"},
            "code_blanks": [
                {
                    "blank_key": "blank_1",
                    "placeholder": "事件绑定方法",
                    "expected_concept": "DOM event listener",
                    "is_core": True,
                }
            ],
        },
        "latest_attempt": {
            "attempt_type": "run",
            "runtime_status": "success",
            "test_pass_rate": 0.5,
            "passed_test_count": 1,
            "total_test_count": 2,
            "visible_results": [{"case_type": "visible", "passed": True, "message": "visible ok"}],
            "hidden_summary": {"total": 1, "failed": 1},
            "hidden_case_id": "hidden_three_clicks",
            "submitted_code": "button.addEventListener('click', () => { count += 1; });",
            "completion_result": {"result": "partial", "feedback": "需要继续验证", "next_action": "retry_same"},
        },
        "learner_message": "draft note",
    }


def _onboarding_plan_context() -> tuple[OnboardingPlanContext, PlanDraft]:
    payload = PlanGenerateRequest(
        user_id="user_001",
        mode="goal_based",
        goal_text="Learn DOM events by validating generated code.",
        course_id="course_js_dom",
        target_level="beginner_to_intermediate",
    )
    user = {
        "id": "user_001",
        "display_name": "M2 User",
        "learning_style": "practice_first",
        "teaching_preference": "step_by_step",
        "profession": "frontend_developer",
    }
    course = {
        "id": "course_js_dom",
        "slug": "javascript-dom-basics",
        "language": "javascript",
        "title": "JavaScript DOM 基础",
        "description": "通过浏览器预览和 DOM 断言学习事件、状态和渲染。",
        "level": "beginner",
        "runtime_profile_id": "rt_browser_js",
        "runtime_profile": {
            "id": "rt_browser_js",
            "slug": "browser-js",
            "runtime_tier": "browser_preview",
            "language": "javascript",
            "runner": "browser",
            "supports_realtime_preview": True,
            "supports_stdout": True,
            "supports_tests": True,
            "compile_required": False,
            "sandbox_policy": "dom_preview_only",
        },
        "supported_exercise_types_json": ["code_blank", "fix_bug"],
    }
    base_draft = build_plan_draft(payload, user, course)
    return build_onboarding_plan_context(payload, user, course, base_draft), base_draft
