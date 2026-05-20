from collections.abc import Mapping, Sequence

from app.core.config import Settings
from app.services.llm_client import LLMJsonResponse, OpenAICompatibleClient
from app.services.llm_explain_error import build_llm_error_explanation, with_deterministic_generation_metadata


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


def test_llm_explain_error_falls_back_when_output_leaks_hidden_identifier() -> None:
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


def test_deterministic_generation_metadata_is_non_secret() -> None:
    response = with_deterministic_generation_metadata(
        {
            "error_cause": "runtime_error",
            "explanation": "运行失败。",
            "fix_suggestion": "检查 stderr。",
            "related_knowledge_points": [],
            "next_action": "retry_same",
        }
    )

    assert response["generation_source"] == "deterministic"
    assert response["generation_model"] == "deterministic_error_guidance_v1"


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
