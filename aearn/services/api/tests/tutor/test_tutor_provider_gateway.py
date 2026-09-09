from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from typing import Mapping, Sequence

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorContextInput,
    TutorContextSelection,
    TutorContextSource,
    TutorDecision,
    TutorPolicySnapshot,
    TutorProviderResult,
    TutorProviderAttemptOutcome,
    TutorRunSnapshot,
)
from app.core.config import Settings
from app.services.learning.plan_repository import LearningPlanSessionNotFound
from app.services.llm.llm_client import (
    LLMCallError,
    LLMInvalidResponseError,
    LLMInvalidResponseKind,
    LLMJsonResponse,
    LLMProtocol,
    LLMUsage,
    OpenAICompatibleClient,
    _extract_llm_usage,
    _extract_message_content,
    _parse_responses_stream,
    _safe_transport_error,
)
from app.services.llm.llm_urls import deepseek_responses_url
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
    TutorDecisionValidationIssue,
    build_tutor_replacement_message,
    canonical_tutor_wait_for_input_examples,
    tutor_provider_output_schema,
)
from app.services.tutor.interactive import PlanDraftingProviderGateway
from app.services.tutor.ports import SequenceTutorProvider
from app.services.tutor.provider_gateway import (
    PrimaryTutorProviderGateway,
    _build_messages,
    parse_tutor_decision,
)


class FakeJsonClient:
    def __init__(
        self,
        *,
        content: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._content = content or {}
        self._error = error
        self.calls = 0

    @property
    def model(self) -> str:
        return "fake-primary-model"

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: str | None = None,
        capture_provider_body: bool = False,
    ) -> LLMJsonResponse:
        del messages, temperature, max_tokens, timeout_seconds, output_schema, schema_name, thinking_mode, capture_provider_body
        self.calls += 1
        if self._error is not None:
            raise self._error
        return LLMJsonResponse(content=self._content, model=self.model)


class SequencedJsonClient(FakeJsonClient):
    def __init__(self, contents: list[dict[str, object]]) -> None:
        super().__init__()
        self._contents = list(contents)
        self.messages: list[tuple[dict[str, str], ...]] = []

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: float | None = None,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
        thinking_mode: str | None = None,
        capture_provider_body: bool = False,
    ) -> LLMJsonResponse:
        del temperature, max_tokens, timeout_seconds, output_schema, schema_name, thinking_mode, capture_provider_body
        self.calls += 1
        self.messages.append(tuple(dict(message) for message in messages))
        return LLMJsonResponse(content=self._contents.pop(0), model=self.model)


class FalseyJsonClient(FakeJsonClient):
    def __bool__(self) -> bool:
        return False


class RecordingThinkingSink:
    def __init__(self) -> None:
        self.operations: list[tuple[str, int, str]] = []

    def begin_attempt(self, attempt_index: int) -> None:
        self.operations.append(("begin", attempt_index, ""))

    def append_text(self, attempt_index: int, text: str) -> None:
        self.operations.append(("append", attempt_index, text))

    def complete_attempt(self, attempt_index: int) -> None:
        self.operations.append(("complete", attempt_index, ""))

    def reset_attempt(self, attempt_index: int) -> None:
        self.operations.append(("reset", attempt_index, ""))

    def discard_attempt(self, attempt_index: int) -> None:
        self.operations.append(("discard", attempt_index, ""))

    def discard_current(self) -> None:
        self.operations.append(("discard_current", 0, ""))


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-provider",
        conversation_id="conversation-provider",
        user_id="user-provider",
        origin="interactive",
        input_revision=0,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
            max_capability_calls=1,
            max_effects=1,
        ),
    )


def _context() -> TutorContextSelection:
    return TutorContextBuilder(config=TutorContextBuilderConfig(section_item_limits=())).build(
        TutorContextInput(
            run_id="run-provider",
            conversation_id="conversation-provider",
            input_revision=0,
            current_input_required=True,
            current_input=TutorContextSource("message-current", "请解释变量作用域。"),
        ),
        token_budget=1200,
    )


def _interactive_context(
    *,
    current_input: str = "我应该学哪些语言",
    prior_direction: str = "我想做个网站",
) -> TutorContextSelection:
    return TutorContextBuilder().build(
        TutorContextInput(
            run_id="run-provider",
            conversation_id="conversation-provider",
            input_revision=0,
            current_input=TutorContextSource("message-current", current_input),
            current_input_required=True,
            recent_messages=(
                TutorContextSource("message-old", {"role": "user", "content": prior_direction}),
            ),
        ),
        token_budget=1200,
    )


def _valid_payload() -> dict[str, object]:
    return {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message",
            "text": "先检查变量是在回调外定义，还是只在回调内部可见。",
            "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
            "conversation_title": None,
        },
        "action": {"type": "turn_completed"},
    }


def test_provider_payload_separates_authoritative_current_input_from_optional_history() -> None:
    messages = _build_messages(run=_run(), context=_interactive_context())
    system = messages[0]["content"]
    payload = json.loads(messages[1]["content"])

    assert payload["current_input"] == {"role": "user", "content": "我应该学哪些语言"}
    assert [item["source_id"] for item in payload["context"]] == ["message-old"]
    assert payload["context_metadata"]["current_input"]["source_id"] == "message-current"
    assert "authoritative request" in system
    assert "current_input and explicit controls" in system
    assert "then current server authority, then recent_messages" in system
    assert "persistent-thread associations" in system
    assert "continue_mainline" in system
    assert "answer_and_refocus" in system
    assert "clarify_direction" in system
    assert "confirmed_switch" in system
    assert "without keyword lists" in system
    assert "ask exactly one direction question" in system
    assert "never reconfirm the same switch" in system
    assert "answer directly first" in system
    assert "at most one necessary follow-up question" in system
    assert "website, image, or HTML" in system


@pytest.mark.parametrize(
    ("prior_direction", "latest_input"),
    [
        ("我们在规划作品集网站。", "我也在考虑转行做烘焙。"),
        ("正在学习 SQL JOIN。", "先问一下 CSS hover 动画，然后继续 JOIN。"),
        ("正在学习 Python 变量。", "DNS 是什么？问完继续变量练习。"),
        ("我们在规划网站。", "我想做一个厨师作品展示网站。"),
        ("我们在规划网站。", "停止网站方向，改学 Python 自动化。"),
    ],
)
def test_direction_drift_scenarios_keep_latest_input_authoritative_without_keyword_routing(
    prior_direction: str,
    latest_input: str,
) -> None:
    messages = _build_messages(
        run=_run(),
        context=_interactive_context(
            current_input=latest_input,
            prior_direction=prior_direction,
        ),
    )

    payload = json.loads(messages[1]["content"])
    system = messages[0]["content"]
    assert payload["current_input"]["content"] == latest_input
    assert prior_direction in payload["context"][0]["content"]
    assert "Judge the semantic relationship" in system
    assert "without keyword lists" in system
    assert "chef" not in system.casefold()
    assert "厨师" not in system


def test_repair_retry_preserves_current_input_and_latest_intent_teaching_policy() -> None:
    client = SequencedJsonClient(
        [
            {"public_message": "旧路径。", "checkpoint_reason": "invalid"},
            _valid_payload(),
        ]
    )
    gateway = PrimaryTutorProviderGateway(settings=Settings(llm_type="disabled"), client=client)

    result = gateway.decide(run=_run(), context=_interactive_context())

    assert result.decision is not None
    assert client.calls == 2
    first_payload = json.loads(client.messages[0][1]["content"])
    retry_payload = json.loads(client.messages[1][1]["content"])
    assert first_payload["current_input"] == retry_payload["current_input"]
    assert retry_payload["current_input"]["content"] == "我应该学哪些语言"
    repair_message = client.messages[1][-1]["content"]
    assert "authoritative request" in repair_message
    assert "current_input and explicit controls" in repair_message
    assert "then current server authority, then recent_messages" in repair_message
    assert "persistent-thread associations" in repair_message
    assert "continue_mainline" in repair_message
    assert "answer_and_refocus" in repair_message
    assert "clarify_direction" in repair_message
    assert "confirmed_switch" in repair_message
    assert "without keyword lists" in repair_message
    assert "stop the stale path" in repair_message
    assert "answer directly first" in repair_message


def test_primary_gateway_uses_exact_deepseek_v4_flash_responses_contract_without_fallback() -> (
    None
):
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured.update(
            url=url, headers=dict(headers), payload=dict(payload), timeout=timeout
        )
        return {
            "type": "response.completed",
            "response": {
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    _valid_payload(), ensure_ascii=False
                                ),
                            }
                        ],
                    }
                ],
            },
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-v4-flash",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is None
    assert result.decision is not None
    assert result.decision.terminal_outcome is not None
    assert captured["url"] == "https://api.deepseek.com/responses"
    payload = captured["payload"]
    assert isinstance(payload, Mapping)
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["stream"] is True
    assert payload["text"] == {"format": {"type": "json_object"}}
    assert payload["max_output_tokens"] == 16_384
    assert settings.tutor_deepseek_v4_flash_context_window_tokens == 1_000_000
    assert settings.tutor_deepseek_v4_flash_input_limit_tokens == 131_072
    assert settings.tutor_context_token_budget == 131_072
    assert isinstance(payload["input"], str)
    assert isinstance(payload["instructions"], str)
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    assert settings.llm_provider_type == "deepseek"


def test_deepseek_repair_disables_thinking_only_for_the_replacement_attempt() -> None:
    payloads: list[Mapping[str, object]] = []
    provider_contents = [
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": None,
            },
            "action": {"type": "unknown_action"},
        },
        _valid_payload(),
    ]

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, timeout
        payloads.append(dict(payload))
        content = provider_contents.pop(0)
        return {
            "type": "response.completed",
            "response": {
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(content, ensure_ascii=False),
                            }
                        ],
                    }
                ],
            },
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-v4-flash",
    )
    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context())

    assert result.decision is not None
    assert len(payloads) == 2
    assert "thinking" not in payloads[0]
    assert "thinking" not in payloads[1]
    assert "reasoning" not in payloads[0]
    assert payloads[1]["reasoning"] == {"effort": "none"}


def test_visible_thinking_complete_is_emitted_only_after_decision_validation() -> None:
    rejected = _valid_payload()
    rejected["action"] = {"type": "unknown_action"}
    accepted = _valid_payload()
    provider_contents = [rejected, accepted]

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, payload, timeout
        content = provider_contents.pop(0)
        return {
            "type": "response.completed",
            "response": {
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(content, ensure_ascii=False),
                            }
                        ],
                    }
                ],
            },
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-v4-flash",
    )
    sink = RecordingThinkingSink()
    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context(), thinking_sink=sink)

    assert result.decision is not None
    assert ("complete", 1, "") not in sink.operations
    assert ("discard", 1, "") in sink.operations
    assert ("complete", 2, "") in sink.operations
    assert sink.operations[-1] == ("complete", 2, "")
    assert "".join(
        value
        for operation, attempt_index, value in sink.operations
        if operation == "append" and attempt_index == 1
    ) == rejected["message"]["public_thinking_text"]


def test_deepseek_responses_json_schema_requires_explicit_verified_gateway_opt_in() -> None:
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
            "type": "response.completed",
            "response": {
                "model": "deepseek-v4-flash",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_valid_payload(), ensure_ascii=False),
                            }
                        ],
                    }
                ],
            },
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://verified-gateway.example/v1",
        deepseek_model="deepseek-v4-flash",
        tutor_deepseek_responses_json_schema_enabled=True,
    )
    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context())

    assert result.decision is not None
    payload = captured["payload"]
    assert isinstance(payload, Mapping)
    text_format = payload["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"] == tutor_provider_output_schema()


def test_deepseek_v4_flash_token_limits_reserve_output_capacity_within_the_context_window() -> None:
    settings = Settings(
        llm_type="deepseek",
        deepseek_model="deepseek-v4-flash",
        tutor_deepseek_v4_flash_context_window_tokens=1_000_000,
        tutor_deepseek_v4_flash_input_limit_tokens=131_072,
        tutor_deepseek_v4_flash_max_output_tokens=61_440,
    )

    assert settings.uses_deepseek_v4_flash_responses is True
    assert settings.tutor_deepseek_v4_flash_context_window_tokens == 1_000_000
    assert settings.tutor_deepseek_v4_flash_input_limit_tokens == 131_072
    assert settings.tutor_max_output_tokens == 61_440
    assert settings.tutor_decision_max_output_tokens == 16_384
    assert settings.tutor_context_token_budget == 131_072

    with pytest.raises(ValueError, match="must leave room within the context window"):
        Settings(
            llm_type="deepseek",
            deepseek_model="deepseek-v4-flash",
            tutor_deepseek_v4_flash_context_window_tokens=61_440,
            tutor_deepseek_v4_flash_max_output_tokens=61_440,
        )

    with pytest.raises(ValueError, match="configured DeepSeek V4 Flash maximum"):
        PrimaryTutorProviderGateway(settings=settings, max_output_tokens=61_441)

    with pytest.raises(ValueError, match="request limits exceed"):
        Settings(
            llm_type="deepseek",
            deepseek_model="deepseek-v4-flash",
            tutor_deepseek_v4_flash_context_window_tokens=192_511,
            tutor_deepseek_v4_flash_input_limit_tokens=131_072,
            tutor_deepseek_v4_flash_max_output_tokens=61_440,
        )


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("https://api.deepseek.com", "https://api.deepseek.com/responses"),
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/responses"),
        ("https://api.deepseek.com/responses", "https://api.deepseek.com/responses"),
        (
            "https://api.deepseek.com/v1/chat/completions",
            "https://api.deepseek.com/responses",
        ),
    ],
)
def test_deepseek_responses_url_normalizes_known_configured_endpoints(
    base_url: str,
    expected_url: str,
) -> None:
    assert deepseek_responses_url(base_url) == expected_url


def test_primary_gateway_uses_exact_model_match_for_deepseek_responses() -> None:
    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="DeepSeek-V4-Flash",
    )

    from app.services.llm.llm_client import LLMProtocol, select_llm_protocol

    assert select_llm_protocol(settings) is LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS


def test_primary_gateway_keeps_other_deepseek_models_on_chat_completions() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured.update(
            url=url, headers=dict(headers), payload=dict(payload), timeout=timeout
        )
        return {
            "model": "deepseek-v4-pro",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_payload(), ensure_ascii=False)
                    }
                }
            ],
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-v4-pro",
    )
    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context())

    assert result.decision is not None
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["payload"]["model"] == "deepseek-v4-pro"
    assert captured["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize(
    ("provider_response", "expected_code"),
    [
        (
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "private"}],
                        }
                    ]
                },
            },
            "TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING",
        ),
        (
            {
                "type": "response.incomplete",
                "response": {"status": "incomplete", "output": []},
            },
            "TUTOR_PROVIDER_RESPONSE_INCOMPLETE",
        ),
        (
            {
                "type": "response.failed",
                "response": {"status": "failed", "error": {"message": "private"}},
            },
            "TUTOR_PROVIDER_RESPONSE_FAILED",
        ),
    ],
)
def test_primary_gateway_classifies_deepseek_responses_terminal_shapes_without_retaining_bodies(
    provider_response: Mapping[str, object],
    expected_code: str,
) -> None:
    calls: list[None] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, payload, timeout
        calls.append(None)
        return provider_response

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://provider.example",
        deepseek_model="deepseek-v4-flash",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == expected_code
    expected_calls = (
        2 if expected_code == "TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING" else 1
    )
    assert len(calls) == expected_calls
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    ("provider_response", "expected_code"),
    [
        (
            {"error": {"type": "unexpected_shape"}},
            "TUTOR_PROVIDER_RESPONSE_ENVELOPE_INVALID",
        ),
        (
            {"choices": [{"message": {"content": ""}}]},
            "TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING",
        ),
        (
            {"choices": [{"message": {"content": "not a JSON object"}}]},
            "TUTOR_PROVIDER_RESPONSE_CONTENT_NOT_JSON",
        ),
    ],
)
def test_primary_gateway_classifies_deepseek_invalid_response_shapes_without_retaining_bodies(
    provider_response: Mapping[str, object],
    expected_code: str,
) -> None:
    calls: list[None] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, payload, timeout
        calls.append(None)
        return provider_response

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://provider.example",
        deepseek_model="model",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == expected_code
    expected_calls = (
        1 if expected_code == "TUTOR_PROVIDER_RESPONSE_ENVELOPE_INVALID" else 2
    )
    assert len(calls) == expected_calls
    assert "unexpected_shape" not in repr(result)
    assert "private" not in repr(result)


def _sse_frame(payload: Mapping[str, object]) -> tuple[bytes, bytes]:
    return (
        ("data: " + json.dumps(payload, ensure_ascii=False) + chr(10)).encode("utf-8"),
        b"\n",
    )


def _sse_lines(*frames: tuple[bytes, bytes]) -> tuple[bytes, ...]:
    return tuple(line for frame in frames for line in frame)


def test_deepseek_responses_sse_visible_text_delta_finishes_as_completed_output() -> (
    None
):
    visible_json = json.dumps(_valid_payload(), ensure_ascii=False)
    response = _parse_responses_stream(
        _sse_lines(
            _sse_frame(
                {"type": "response.output_text.delta", "delta": visible_json[:12]}
            ),
            _sse_frame(
                {"type": "response.output_text.delta", "delta": visible_json[12:]}
            ),
            _sse_frame(
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp-safe",
                        "model": "deepseek-v4-flash",
                        "status": "completed",
                        "output": [
                            {
                                "type": "reasoning",
                                "summary": [
                                    {"type": "summary_text", "text": "private"}
                                ],
                            }
                        ],
                    },
                }
            ),
        )
    )

    content = response["output"]
    assert isinstance(content, list)
    assert content[0]["content"][0]["text"] == visible_json
    assert "private" not in repr(response)


def test_deepseek_responses_completed_reasoning_only_envelope_has_no_visible_text() -> (
    None
):
    with pytest.raises(LLMInvalidResponseError) as exc_info:
        _extract_message_content(
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "reasoning",
                            "summary": [{"type": "summary_text", "text": "private"}],
                        }
                    ]
                },
            }
        )

    assert exc_info.value.kind is LLMInvalidResponseKind.CONTENT_MISSING
    assert "private" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("event_type", "expected_kind"),
    [
        ("response.incomplete", LLMInvalidResponseKind.RESPONSE_INCOMPLETE),
        ("response.failed", LLMInvalidResponseKind.RESPONSE_FAILED),
    ],
)
def test_deepseek_responses_sse_terminal_failure_events_are_safe(
    event_type: str,
    expected_kind: LLMInvalidResponseKind,
) -> None:
    with pytest.raises(LLMInvalidResponseError) as exc_info:
        _parse_responses_stream(
            _sse_lines(
                _sse_frame(
                    {
                        "type": event_type,
                        "response": {
                            "status": event_type.rsplit(".", 1)[-1],
                            "error": {"message": "private provider body"},
                        },
                    }
                )
            )
        )

    assert exc_info.value.kind is expected_kind
    assert "private provider body" not in str(exc_info.value)


def test_primary_gateway_does_not_retry_or_fallback_after_selected_provider_request_rejection() -> (
    None
):
    urls: list[str] = []

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del headers, payload, timeout
        urls.append(url)
        raise urllib.error.HTTPError(url, 400, "request rejected", hdrs=None, fp=None)

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com/v1",
        deepseek_model="deepseek-v4-flash",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert urls == ["https://api.deepseek.com/responses"]
    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_REQUEST_REJECTED"
    assert "request rejected" not in repr(result)


def test_primary_gateway_uses_configured_openai_compatible_client_without_fallback() -> (
    None
):
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured.update(
            url=url, headers=dict(headers), payload=dict(payload), timeout=timeout
        )
        return {
            "model": "provider-model",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(_valid_payload(), ensure_ascii=False),
                        }
                    ]
                }
            ],
        }

    settings = Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://provider.example/v1",
        openai_model="provider-model",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert result.model == "provider-model"
    assert captured["url"] == "https://provider.example/v1/responses"
    payload = captured["payload"]
    assert isinstance(payload, Mapping)
    text_format = payload["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["name"] == TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION
    assert text_format["strict"] is True
    assert text_format["schema"] == tutor_provider_output_schema()
    assert settings.llm_provider_type == "openai"


def test_primary_gateway_uses_the_injected_client_even_when_it_is_falsey() -> None:
    client = FalseyJsonClient(content=_valid_payload())
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert client.calls == 1


@pytest.mark.parametrize(
    ("continuation_kind", "question_key"),
    [
        ("clarification", None),
        ("planning_input", "weekly_minutes"),
        ("approval", None),
        ("capability_result", None),
        ("external_result", None),
    ],
)
def test_parse_tutor_decision_accepts_each_exact_continuation_contract(
    continuation_kind: str,
    question_key: str | None,
) -> None:
    action: dict[str, object] = {
        "type": "wait_for_input",
        "continuation_kind": continuation_kind,
    }
    if question_key is not None:
        action["question_key"] = question_key
    decision = parse_tutor_decision(
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "请补充这一项信息。",
                "public_thinking_text": "这一项输入是继续当前有限步骤所必需的。",
                "conversation_title": None,
            },
            "action": action,
        },
        run=_run(),
    )

    assert decision.continuation_kind is TutorContinuationKind(continuation_kind)
    assert decision.question_key == question_key


@pytest.mark.parametrize(
    ("continuation_kind", "question_key"),
    [
        ("planning_input", None),
        ("planning_input", "unknown_fact"),
        ("clarification", "weekly_minutes"),
        ("approval", "goal_text"),
        ("capability_result", "language_id"),
        ("external_result", "pace_constraints"),
    ],
)
def test_parse_tutor_decision_rejects_continuation_question_key_mismatch(
    continuation_kind: str,
    question_key: str | None,
) -> None:
    action: dict[str, object] = {
        "type": "wait_for_input",
        "continuation_kind": continuation_kind,
    }
    if question_key is not None:
        action["question_key"] = question_key

    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(
            {
                "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                "message": {
                    "type": "agent_message",
                    "text": "继续。",
                    "public_thinking_text": "当前需要一项明确输入。",
                    "conversation_title": None,
                },
                "action": action,
            },
            run=_run(),
        )


def test_parse_tutor_decision_accepts_strict_semantic_language_hint() -> None:
    decision = parse_tutor_decision(
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "你想学习哪门编程语言？",
                "public_thinking_text": "LangChain 与当前 Python 课程生态匹配，但仍需学习者确认。",
                "conversation_title": "确认实现语言",
            },
            "action": {
                "type": "wait_for_input",
                "continuation_kind": "planning_input",
                "question_key": "language_id",
                "planning_intent_hint": {
                    "schema_version": "planning-intent-hint-v2",
                    "candidate_language_ids": ["python"],
                    "confidence": "high",
                    "reason_code": "technology_ecosystem_match",
                },
            },
        },
        run=_run(),
    )

    assert decision.planning_intent_hint is not None
    assert decision.planning_intent_hint.candidate_language_ids == ("python",)
    assert decision.planning_intent_hint.confidence == "high"
    assert decision.planning_intent_hint.reason_code == "technology_ecosystem_match"


@pytest.mark.parametrize(
    "hint",
    [
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": [], "confidence": "high", "reason_code": "technology_ecosystem_match"},
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": ["python", "python"], "confidence": "high", "reason_code": "technology_ecosystem_match"},
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": ["python", "java", "go", "sql"], "confidence": "high", "reason_code": "technology_ecosystem_match"},
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": ["python"], "confidence": "low", "reason_code": "technology_ecosystem_match"},
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": ["python"], "confidence": "high", "reason_code": "free_text"},
        {"schema_version": "planning-intent-hint-v2", "candidate_language_ids": ["python"], "confidence": "high", "reason_code": "technology_ecosystem_match", "label": "Python"},
    ],
)
def test_parse_tutor_decision_rejects_invalid_semantic_language_hints(
    hint: dict[str, object],
) -> None:
    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(
            {
                "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                "message": {
                    "type": "agent_message",
                    "text": "你想学习哪门编程语言？",
                    "public_thinking_text": "先确认实现语言。",
                    "conversation_title": None,
                },
                "action": {
                    "type": "wait_for_input",
                    "continuation_kind": "planning_input",
                    "question_key": "language_id",
                    "planning_intent_hint": hint,
                },
            },
            run=_run(),
        )


def test_parse_tutor_decision_rejects_hint_on_non_language_or_clarification() -> None:
    hint = {
        "schema_version": "planning-intent-hint-v2",
        "candidate_language_ids": ["python"],
        "confidence": "high",
        "reason_code": "technology_ecosystem_match",
    }
    for action in (
        {"type": "wait_for_input", "continuation_kind": "planning_input", "question_key": "weekly_minutes", "planning_intent_hint": hint},
        {"type": "wait_for_input", "continuation_kind": "clarification", "planning_intent_hint": hint},
    ):
        with pytest.raises(LLMInvalidResponseError):
            parse_tutor_decision(
                {
                    "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                    "message": {
                        "type": "agent_message",
                        "text": "请补充信息。",
                        "public_thinking_text": "先确认当前缺失信息。",
                        "conversation_title": None,
                    },
                    "action": action,
                },
                run=_run(),
            )


def test_parse_tutor_decision_accepts_safe_title_and_explicit_continuation() -> None:
    decision = parse_tutor_decision(
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "请确认是否要继续执行下一步。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": "  函数基础练习  ",
            },
            "action": {
                "type": "wait_for_input",
                "continuation_kind": "approval",
            },
        },
        run=_run(),
    )

    assert decision.conversation_title == "函数基础练习"
    assert decision.checkpoint_reason is TutorCheckpointReason.CAPABILITY_RESULT
    assert decision.continuation_kind is TutorContinuationKind.APPROVAL
    assert decision.terminal_outcome is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": "x" * 49,
            },
            "action": {"type": "turn_completed"},
        },
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": "private\nname",
            },
            "action": {"type": "turn_completed"},
        },
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": "raw prompt summary",
            },
            "action": {"type": "turn_completed"},
        },
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": None,
            },
            "action": {
                "type": "wait_for_input",
                "continuation_kind": "unknown",
            },
        },
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": None,
            },
            "action": {"type": "turn_completed", "terminal_intent": "completed"},
        },
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "继续。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": None,
            },
        },
    ],
)
def test_parse_tutor_decision_rejects_invalid_title_or_ambiguous_continuation(
    payload: Mapping[str, object],
) -> None:
    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(payload, run=_run())


class _ActivePlanRepository:
    def active_session_for_run(self, **_kwargs: object) -> dict[str, object]:
        return {"id": "session-1", "status": "draft_ready"}


class _MissingPlanRepository:
    def active_session_for_run(self, **_kwargs: object) -> dict[str, object]:
        raise LearningPlanSessionNotFound("not a planning run")


def test_plan_drafting_provider_gateway_completes_redundant_plan_approval() -> None:
    delegate = SequenceTutorProvider([
        TutorProviderResult(decision=TutorDecision(
            public_message="计划已经可以审阅。",
            checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
            continuation_kind=TutorContinuationKind.APPROVAL,
        )),
    ])
    result = PlanDraftingProviderGateway(
        delegate=delegate,
        plans=_ActivePlanRepository(),  # type: ignore[arg-type]
    ).decide(run=_run(), context=_context())

    assert result.decision is not None
    assert result.decision.public_message == "计划已经可以审阅。"
    assert result.decision.continuation_kind is None
    assert result.decision.checkpoint_reason is None


def test_plan_drafting_provider_gateway_preserves_non_plan_approval() -> None:
    delegate = SequenceTutorProvider([
        TutorProviderResult(decision=TutorDecision(
            public_message="是否允许执行受控操作？",
            checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
            continuation_kind=TutorContinuationKind.APPROVAL,
        )),
    ])
    result = PlanDraftingProviderGateway(
        delegate=delegate,
        plans=_MissingPlanRepository(),  # type: ignore[arg-type]
    ).decide(run=_run(), context=_context())

    assert result.decision is not None
    assert result.decision.continuation_kind is TutorContinuationKind.APPROVAL


def test_canonical_approval_example_preserves_generic_authorization_without_plan_confirmation() -> None:
    examples = canonical_tutor_wait_for_input_examples()

    assert '"continuation_kind":"approval"' in examples
    assert "受控操作" in examples
    assert "确认学习计划" not in examples
    assert "这份学习计划" not in examples


def test_tutor_decision_prompt_and_generated_schema_share_one_typed_protocol() -> None:
    initial_messages = _build_messages(run=_run(), context=_context())
    initial_system = initial_messages[0]["content"]
    schema = tutor_provider_output_schema()
    replacement_message = build_tutor_replacement_message(
        (TutorDecisionValidationIssue(path="action.type", category="invalid_literal"),),
        teaching_policy="current_input is authoritative",
    )

    assert TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION in initial_system
    assert '"type":"agent_message"' in initial_system
    assert '"type":"turn_completed"' in initial_system
    assert "request_id, effect_id, expected_input_revision" in initial_system
    assert "Managed actions are two-phase" in initial_system
    assert "only then request a capability or propose an effect" in initial_system
    assert "Choose its wording, paragraphs, line breaks, tone, and granularity naturally" in initial_system
    assert "do not force numbering, a list, or a fixed linguistic template" in initial_system
    assert "我先判断" not in initial_system
    assert "接着比较" not in initial_system
    assert "最后决定" not in initial_system
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["schema_version", "message", "action"]
    message_schema = schema["$defs"]["TutorProviderAgentMessageItem"]
    assert message_schema["required"] == [
        "type",
        "public_thinking_text",
        "text",
        "conversation_title",
    ]
    assert message_schema["properties"]["public_thinking_text"]["minLength"] == 1
    assert message_schema["properties"]["public_thinking_text"]["maxLength"] == 1280
    wait_schema = schema["$defs"]["TutorProviderWaitForInputItem"]
    wait_branches = wait_schema["anyOf"]
    assert {branch["properties"]["continuation_kind"]["const"] for branch in wait_branches} == {
        "clarification",
        "planning_input",
        "approval",
        "capability_result",
        "external_result",
    }
    planning_branches = [
        branch
        for branch in wait_branches
        if branch["properties"]["continuation_kind"]["const"] == "planning_input"
    ]
    assert len(planning_branches) == 2
    language_branch = next(
        branch
        for branch in planning_branches
        if branch["properties"]["question_key"].get("const") == "language_id"
    )
    other_planning_branch = next(branch for branch in planning_branches if branch is not language_branch)
    assert language_branch["required"] == ["type", "continuation_kind", "question_key"]
    assert "TutorProviderPlanningIntentHintV2" in json.dumps(
        language_branch["properties"]["planning_intent_hint"]
    )
    assert set(other_planning_branch["properties"]["question_key"]["enum"]) == {
        "goal_text",
        "target_level",
        "weekly_minutes",
        "experience_level",
        "teaching_preferences",
        "pace_constraints",
    }
    for branch in wait_branches:
        if branch in planning_branches:
            assert branch["required"] == ["type", "continuation_kind", "question_key"]
            continue
        assert branch["required"] == ["type", "continuation_kind"]
        assert "question_key" not in branch["properties"]
        assert "planning_intent_hint" not in branch["properties"]
    for continuation_kind in (
        "clarification",
        "planning_input",
        "approval",
        "capability_result",
        "external_result",
    ):
        assert continuation_kind in initial_system
        assert continuation_kind in replacement_message
    assert '"question_key":"weekly_minutes"' in initial_system
    assert '"question_key":"weekly_minutes"' in replacement_message
    assert "action.type:invalid_literal" in replacement_message
    assert "never emit them" in replacement_message
    assert "Choose its wording, paragraphs, line breaks, tone, and granularity naturally" in replacement_message
    assert "do not force numbered steps or a fixed linguistic template" in replacement_message
    assert "private chain" not in replacement_message


def test_parse_tutor_decision_requires_bounded_public_thinking_text() -> None:
    missing = _valid_payload()
    assert isinstance(missing["message"], dict)
    missing["message"].pop("public_thinking_text")
    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(missing, run=_run())

    oversized = _valid_payload()
    assert isinstance(oversized["message"], dict)
    oversized["message"]["public_thinking_text"] = "公开思考" * 321
    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(oversized, run=_run())


def test_primary_gateway_rejects_unsafe_public_thinking_before_domain_assembly() -> None:
    payload = _valid_payload()
    assert isinstance(payload["message"], dict)
    payload["message"]["public_thinking_text"] = "raw prompt summary"
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"),
        client=FakeJsonClient(content=payload),
    ).decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_OUTPUT_SAFETY_REJECTED"
    assert "raw prompt summary" not in repr(result)


def test_primary_gateway_retries_one_invalid_envelope_on_the_same_primary_model() -> None:
    client = SequencedJsonClient(
        [
            {
                "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                "message": {
                    "type": "agent_message",
                    "text": "先看一个小例子。",
                    "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                    "conversation_title": None,
                },
                "action": {"type": "initialization"},
            },
            _valid_payload(),
        ]
    )
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert result.terminal_outcome is None
    assert client.calls == 2
    assert len(client.messages[0]) == 2
    assert len(client.messages[1]) == 3
    repair_message = client.messages[1][-1]
    assert repair_message["role"] == "user"
    assert "fresh replacement" in repair_message["content"]
    assert "action:invalid_type" in repair_message["content"]
    assert "initialization" not in repair_message["content"]
    assert "先看一个小例子" not in repair_message["content"]


def test_primary_gateway_rejects_unknown_or_guardrail_blocked_envelopes_as_model_unavailable() -> None:
    unknown_payload = _valid_payload()
    unknown_payload["reasoning"] = "private chain"
    blocked_payload = _valid_payload()
    blocked_payload["message"] = {
        "type": "agent_message",
        "text": "完整答案如下：...",
        "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
        "conversation_title": None,
    }
    unknown = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="openai",
            openai_api_key="k",
            openai_base_url="https://provider.example",
            openai_model="m",
        ),
        client=FakeJsonClient(content=unknown_payload),
    )
    blocked = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="openai",
            openai_api_key="k",
            openai_base_url="https://provider.example",
            openai_model="m",
        ),
        client=FakeJsonClient(content=blocked_payload),
    )

    unknown_result = unknown.decide(run=_run(), context=_context())
    blocked_result = blocked.decide(run=_run(), context=_context())

    assert unknown_result.terminal_outcome is not None
    assert blocked_result.terminal_outcome is not None
    assert unknown_result.safe_code == "TUTOR_PROVIDER_DECISION_EXTRA_FIELD"
    assert blocked_result.safe_code == "TUTOR_PROVIDER_OUTPUT_SAFETY_REJECTED"
    assert "private chain" not in repr(unknown_result)


@pytest.mark.parametrize(
    "field_name", ["reasoning", "diagnostic", "provider_payload", "hidden_test_body"]
)
def test_primary_gateway_rejects_internal_nested_payload_fields_as_model_unavailable(
    field_name: str,
) -> None:
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="openai",
            openai_api_key="k",
            openai_base_url="https://provider.example",
            openai_model="m",
        ),
        client=FakeJsonClient(
            content={
                "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
                "message": {
                    "type": "agent_message",
                    "text": "准备保存学习笔记。",
                    "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                    "conversation_title": None,
                },
                "action": {
                    "type": "propose_effect",
                    "effect_type": "save_note",
                    "payload": [
                        {"key": field_name, "value": "private internal detail"}
                    ],
                },
            }
        ),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID_VALUE"
    assert "private internal detail" not in repr(result)


def test_primary_gateway_maps_selected_provider_error_without_cross_provider_fallback_or_raw_detail() -> None:
    fake = FakeJsonClient(
        error=LLMCallError("provider raw Authorization: Bearer secret-token")
    )
    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-flash",
    )
    gateway = PrimaryTutorProviderGateway(settings=settings, client=fake)

    result = gateway.decide(run=_run(), context=_context())
    serialized = repr(result)

    assert fake.calls == 1
    assert settings.llm_provider_type == "deepseek"
    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_REQUEST_FAILED"
    assert "secret-token" not in serialized
    assert "provider raw" not in serialized


def test_provider_keeps_bounded_string_list_arguments_and_server_owns_action_ids() -> None:
    decision = parse_tutor_decision(
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "text": "先检索一个函数返回值示例。",
                "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
                "conversation_title": None,
            },
            "action": {
                "type": "request_capability",
                "capability_id": "grounding.retrieve",
                "arguments": [
                    {"key": "language_id_or_alias", "value": "python"},
                    {"key": "query_text", "value": "function return"},
                    {"key": "topic_tags", "value": ["functions"]},
                    {"key": "top_k", "value": 1},
                ],
            },
        },
        run=_run(),
    )

    request = decision.capability_requests[0]
    arguments = {field.key: json.loads(field.value) for field in request.arguments}
    assert request.request_id.startswith("capability-")
    assert arguments["topic_tags"] == ["functions"]
    assert arguments["top_k"] == 1


@pytest.mark.parametrize(
    "value",
    [float("nan"), "x" * 361, ["x" * 100] * 4],
)
def test_provider_payload_values_must_be_finite_and_round_trip_within_domain_bound(
    value: object,
) -> None:
    payload = {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message",
            "text": "准备调用能力。",
            "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
            "conversation_title": None,
        },
        "action": {
            "type": "request_capability",
            "capability_id": "grounding.retrieve",
            "arguments": [{"key": "query", "value": value}],
        },
    }

    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(payload, run=_run())


def test_server_owned_effect_id_and_revision_are_deterministic() -> None:
    payload = {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message",
            "text": "准备保存学习笔记。",
            "public_thinking_text": "当前目标可以收敛为一个可验证的小步骤。",
            "conversation_title": None,
        },
        "action": {
            "type": "propose_effect",
            "effect_type": "save_note",
            "payload": [{"key": "topic", "value": "scope"}],
        },
    }

    first = parse_tutor_decision(payload, run=_run()).effect_proposals[0]
    second = parse_tutor_decision(payload, run=_run()).effect_proposals[0]

    assert first.effect_id == second.effect_id
    assert first.effect_id.startswith("effect-")
    assert first.expected_input_revision == _run().input_revision


def test_llm_transport_log_category_omits_provider_detail() -> None:
    assert (
        _safe_transport_error(
            urllib.error.URLError("https://token@example.invalid/private")
        )
        == "URLError"
    )
    assert (
        _safe_transport_error(RuntimeError("Authorization: Bearer secret-token"))
        == "RuntimeError"
    )


def _llm_call_error_with_cause(cause: BaseException) -> LLMCallError:
    try:
        raise LLMCallError("selected provider failed") from cause
    except LLMCallError as error:
        return error


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (
            LLMInvalidResponseError(
                "provider response envelope is invalid",
                kind=LLMInvalidResponseKind.ENVELOPE_INVALID,
            ),
            "TUTOR_PROVIDER_RESPONSE_ENVELOPE_INVALID",
        ),
        (
            LLMInvalidResponseError(
                "provider response has no message content",
                kind=LLMInvalidResponseKind.CONTENT_MISSING,
            ),
            "TUTOR_PROVIDER_RESPONSE_CONTENT_MISSING",
        ),
        (
            LLMInvalidResponseError(
                "provider message content is not a JSON object",
                kind=LLMInvalidResponseKind.CONTENT_NOT_JSON_OBJECT,
            ),
            "TUTOR_PROVIDER_RESPONSE_CONTENT_NOT_JSON",
        ),
        (
            LLMInvalidResponseError("legacy unclassified invalid response"),
            "TUTOR_PROVIDER_RESPONSE_INVALID",
        ),
        (
            _llm_call_error_with_cause(TimeoutError("provider request timed out")),
            "TUTOR_PROVIDER_TIMEOUT",
        ),
        (
            _llm_call_error_with_cause(
                urllib.error.HTTPError(
                    "https://provider.example",
                    400,
                    "request rejected",
                    hdrs=None,
                    fp=None,
                )
            ),
            "TUTOR_PROVIDER_REQUEST_REJECTED",
        ),
        (
            _llm_call_error_with_cause(
                urllib.error.HTTPError(
                    "https://provider.example", 429, "rate limited", hdrs=None, fp=None
                )
            ),
            "TUTOR_PROVIDER_RATE_LIMITED",
        ),
        (RuntimeError("adapter seam failed"), "TUTOR_PROVIDER_ADAPTER_FAILED"),
    ],
)
def test_primary_gateway_records_safe_configuration_and_failure_categories(
    error: Exception,
    expected_code: str,
) -> None:
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="deepseek",
            deepseek_api_key="test-key",
            deepseek_base_url="https://provider.example",
            deepseek_model="model",
        ),
        client=FakeJsonClient(error=error),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == expected_code


def test_primary_gateway_records_safe_configuration_failure_without_a_client() -> None:
    gateway = PrimaryTutorProviderGateway(settings=Settings(llm_type="disabled"))

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_CONFIGURATION_UNAVAILABLE"



def test_llm_usage_derives_uncached_input_without_double_counting_cached_tokens() -> None:
    usage = LLMUsage(
        input_tokens=175_420,
        cached_input_tokens=170_368,
        output_tokens=2_223,
        total_tokens=177_643,
        reasoning_tokens=321,
    )

    assert usage.usage_available is True
    assert usage.uncached_input_tokens == 5_052
    assert usage.calculated_total_tokens == 177_643
    assert usage.input_tokens + usage.cached_input_tokens != usage.total_tokens

    with pytest.raises(ValueError, match="must not exceed"):
        LLMUsage(input_tokens=10, cached_input_tokens=11)
    with pytest.raises(ValueError, match="non-negative"):
        LLMUsage(output_tokens=-1)


def test_responses_usage_parser_keeps_cached_and_reasoning_details() -> None:
    usage = _extract_llm_usage(
        {
            "type": "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 175_420,
                    "input_tokens_details": {"cached_tokens": 170_368},
                    "output_tokens": 2_223,
                    "output_tokens_details": {"reasoning_tokens": 321},
                    "total_tokens": 177_643,
                }
            },
        },
        protocol=LLMProtocol.RESPONSES,
    )

    assert usage == LLMUsage(
        input_tokens=175_420,
        cached_input_tokens=170_368,
        output_tokens=2_223,
        total_tokens=177_643,
        reasoning_tokens=321,
    )
    assert usage is not None and usage.uncached_input_tokens == 5_052


def test_chat_completions_usage_parser_normalizes_prompt_fields() -> None:
    usage = _extract_llm_usage(
        {
            "usage": {
                "prompt_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 100},
                "completion_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 7},
                "total_tokens": 150,
            }
        },
        protocol=LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS,
    )

    assert usage == LLMUsage(
        input_tokens=120,
        cached_input_tokens=100,
        output_tokens=30,
        total_tokens=150,
        reasoning_tokens=7,
    )
    assert usage is not None and usage.uncached_input_tokens == 20


def test_malformed_or_missing_provider_usage_is_unavailable_without_blocking_content() -> None:
    malformed = _extract_llm_usage(
        {
            "usage": {
                "prompt_tokens": 10,
                "prompt_tokens_details": {"cached_tokens": 11},
                "completion_tokens": 2,
            }
        },
        protocol=LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS,
    )
    missing = _extract_llm_usage(
        {"choices": [{"message": {"content": "{}"}}]},
        protocol=LLMProtocol.DEEPSEEK_CHAT_COMPLETIONS,
    )

    assert malformed is None
    assert missing is None


def test_gateway_records_usage_for_each_repair_attempt_and_preserves_model_call_semantics() -> None:
    provider_responses: list[Mapping[str, object]] = [
        {
            "model": "deepseek-v4-pro",
            "usage": {
                "prompt_tokens": 175_420,
                "prompt_tokens_details": {"cached_tokens": 170_368},
                "completion_tokens": 20,
                "total_tokens": 175_440,
            },
            "choices": [{"message": {"content": "not json"}}],
        },
        {
            "model": "deepseek-v4-pro",
            "usage": {
                "prompt_tokens": 180,
                "completion_tokens": 40,
                "total_tokens": 220,
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_valid_payload(), ensure_ascii=False)
                    }
                }
            ],
        },
    ]

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, payload, timeout
        return provider_responses.pop(0)

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://provider.example",
        deepseek_model="deepseek-v4-pro",
    )
    gateway = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert [attempt.outcome for attempt in result.attempts] == [
        TutorProviderAttemptOutcome.REPAIRABLE_REJECTED,
        TutorProviderAttemptOutcome.ACCEPTED,
    ]
    assert result.attempts[0].usage is not None
    assert result.attempts[0].usage.uncached_input_tokens == 5_052
    assert result.attempts[1].usage == LLMUsage(
        input_tokens=180,
        output_tokens=40,
        total_tokens=220,
    )


def test_gateway_preserves_completed_envelope_usage_when_visible_content_is_rejected() -> None:
    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        del url, headers, payload, timeout
        return {
            "type": "response.failed",
            "response": {
                "status": "failed",
                "model": "deepseek-v4-flash",
                "usage": {
                    "input_tokens": 60,
                    "input_tokens_details": {"cached_tokens": 50},
                    "output_tokens": 3,
                    "total_tokens": 63,
                },
                "error": {"message": "private provider body"},
            },
        }

    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key",
        deepseek_base_url="https://provider.example",
        deepseek_model="deepseek-v4-flash",
    )
    result = PrimaryTutorProviderGateway(
        settings=settings,
        client=OpenAICompatibleClient(settings, transport=transport),
    ).decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert len(result.attempts) == 1
    attempt = result.attempts[0]
    assert attempt.outcome is TutorProviderAttemptOutcome.TERMINAL_REJECTED
    assert attempt.diagnostic_code == "TUTOR_PROVIDER_RESPONSE_FAILED"
    assert attempt.usage == LLMUsage(
        input_tokens=60,
        cached_input_tokens=50,
        output_tokens=3,
        total_tokens=63,
    )
    assert "private provider body" not in repr(result)
