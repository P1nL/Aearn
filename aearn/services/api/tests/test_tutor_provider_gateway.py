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
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorRunSnapshot,
)
from app.core.config import Settings
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
from app.services.tutor.provider_gateway import (
    PrimaryTutorProviderGateway,
    _TUTOR_DECISION_REPAIR_MESSAGE,
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
    ) -> LLMJsonResponse:
        del messages, temperature, max_tokens, timeout_seconds
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
    ) -> LLMJsonResponse:
        del temperature, max_tokens, timeout_seconds
        self.calls += 1
        self.messages.append(tuple(dict(message) for message in messages))
        return LLMJsonResponse(content=self._contents.pop(0), model=self.model)


class FalseyJsonClient(FakeJsonClient):
    def __bool__(self) -> bool:
        return False


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


def _interactive_context() -> TutorContextSelection:
    return TutorContextBuilder().build(
        TutorContextInput(
            run_id="run-provider",
            conversation_id="conversation-provider",
            input_revision=0,
            current_input=TutorContextSource("message-current", "我应该学哪些语言"),
            current_input_required=True,
            recent_messages=(
                TutorContextSource("message-old", {"role": "user", "content": "我想做个网站"}),
            ),
        ),
        token_budget=1200,
    )


def _valid_payload() -> dict[str, object]:
    return {
        "public_message": "先检查变量是在回调外定义，还是只在回调内部可见。",
        "skill_references": [{"skill_id": "scope-basics", "version": "v1"}],
        "terminal_intent": "completed",
    }


def test_provider_payload_separates_authoritative_current_input_from_optional_history() -> None:
    messages = _build_messages(run=_run(), context=_interactive_context())
    system = messages[0]["content"]
    payload = json.loads(messages[1]["content"])

    assert payload["current_input"] == {"role": "user", "content": "我应该学哪些语言"}
    assert [item["source_id"] for item in payload["context"]] == ["message-old"]
    assert payload["context_metadata"]["current_input"]["source_id"] == "message-current"
    assert "authoritative request" in system
    assert "correction" in system
    assert "already complete" in system
    assert "answer directly first" in system
    assert "at most one necessary follow-up question" in system
    assert "website, image, or HTML" in system


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
    assert payload["max_output_tokens"] == 384_000
    assert settings.tutor_deepseek_v4_flash_context_window_tokens == 1_000_000
    assert settings.tutor_context_token_budget == 616_000
    assert isinstance(payload["input"], str)
    assert isinstance(payload["instructions"], str)
    assert captured["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    assert settings.llm_provider_type == "deepseek"


def test_deepseek_v4_flash_token_limits_reserve_output_capacity_within_the_context_window() -> None:
    settings = Settings(
        llm_type="deepseek",
        deepseek_model="deepseek-v4-flash",
        tutor_deepseek_v4_flash_context_window_tokens=1_000_000,
        tutor_deepseek_v4_flash_max_output_tokens=384_000,
    )

    assert settings.uses_deepseek_v4_flash_responses is True
    assert settings.tutor_deepseek_v4_flash_context_window_tokens == 1_000_000
    assert settings.tutor_max_output_tokens == 384_000
    assert settings.tutor_context_token_budget == 616_000

    with pytest.raises(ValueError, match="must leave room within the context window"):
        Settings(
            llm_type="deepseek",
            deepseek_model="deepseek-v4-flash",
            tutor_deepseek_v4_flash_context_window_tokens=384_000,
            tutor_deepseek_v4_flash_max_output_tokens=384_000,
        )

    with pytest.raises(ValueError, match="configured DeepSeek V4 Flash maximum"):
        PrimaryTutorProviderGateway(settings=settings, max_output_tokens=384_001)


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
    assert settings.llm_provider_type == "openai"


def test_primary_gateway_uses_the_injected_client_even_when_it_is_falsey() -> None:
    client = FalseyJsonClient(content=_valid_payload())
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert client.calls == 1


def test_parse_tutor_decision_accepts_safe_title_and_explicit_continuation() -> None:
    decision = parse_tutor_decision(
        {
            "public_message": "请确认是否要继续执行下一步。",
            "conversation_title": "  函数基础练习  ",
            "skill_references": [],
            "capability_requests": [],
            "effect_proposals": [],
            "checkpoint_reason": "capability_result",
            "continuation_kind": "approval",
            "terminal_intent": None,
        }
    )

    assert decision.conversation_title == "函数基础练习"
    assert decision.checkpoint_reason is TutorCheckpointReason.CAPABILITY_RESULT
    assert decision.continuation_kind is TutorContinuationKind.APPROVAL
    assert decision.terminal_outcome is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "public_message": "继续。",
            "conversation_title": "x" * 49,
            "terminal_intent": "completed",
        },
        {
            "public_message": "继续。",
            "conversation_title": "private\nname",
            "terminal_intent": "completed",
        },
        {
            "public_message": "继续。",
            "conversation_title": "raw prompt summary",
            "terminal_intent": "completed",
        },
        {
            "public_message": "继续。",
            "continuation_kind": "approval",
            "terminal_intent": "completed",
        },
        {
            "public_message": "继续。",
            "continuation_kind": "approval",
            "checkpoint_reason": "safe_progress",
        },
        {"public_message": "继续。", "terminal_intent": None},
    ],
)
def test_parse_tutor_decision_rejects_invalid_title_or_ambiguous_continuation(
    payload: Mapping[str, object],
) -> None:
    with pytest.raises(LLMInvalidResponseError):
        parse_tutor_decision(payload)


def test_tutor_decision_prompts_share_the_canonical_shape_without_internal_term_lists() -> (
    None
):
    initial_messages = _build_messages(run=_run(), context=_context())
    initial_system = initial_messages[0]["content"]

    assert '"conversation_title"' in initial_system
    assert '"continuation_kind"' in initial_system
    assert '"terminal_intent":"completed"' in initial_system
    assert "reasoning, diagnostics" not in initial_system
    assert "provider data" not in initial_system
    assert "prompts, secrets" not in initial_system
    assert "reasoning, diagnostics" not in _TUTOR_DECISION_REPAIR_MESSAGE
    assert "provider data" not in _TUTOR_DECISION_REPAIR_MESSAGE
    assert "prompts, secrets" not in _TUTOR_DECISION_REPAIR_MESSAGE


def test_primary_gateway_retries_one_invalid_envelope_on_the_same_primary_model() -> (
    None
):
    client = SequencedJsonClient(
        [
            {
                "public_message": "先看一个小例子。",
                "checkpoint_reason": "initialization",
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
    assert "replacement" in repair_message["content"]
    assert "initialization" not in repair_message["content"]
    assert "先看一个小例子" not in repair_message["content"]


def test_primary_gateway_rejects_unknown_or_guardrail_blocked_envelopes_as_model_unavailable() -> (
    None
):
    unknown = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="openai",
            openai_api_key="k",
            openai_base_url="https://provider.example",
            openai_model="m",
        ),
        client=FakeJsonClient(
            content={"public_message": "继续看变量。", "reasoning": "private chain"}
        ),
    )
    blocked = PrimaryTutorProviderGateway(
        settings=Settings(
            llm_type="openai",
            openai_api_key="k",
            openai_base_url="https://provider.example",
            openai_model="m",
        ),
        client=FakeJsonClient(
            content={
                "public_message": "完整答案如下：...",
                "terminal_intent": "completed",
            }
        ),
    )

    unknown_result = unknown.decide(run=_run(), context=_context())
    blocked_result = blocked.decide(run=_run(), context=_context())

    assert unknown_result.terminal_outcome is not None
    assert blocked_result.terminal_outcome is not None
    assert unknown_result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID"
    assert blocked_result.safe_code == "TUTOR_PROVIDER_OUTPUT_SAFETY_REJECTED"


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
                "effect_proposals": [
                    {
                        "effect_id": "effect-1",
                        "effect_type": "save_note",
                        "expected_input_revision": 0,
                        "payload": {field_name: "private internal detail"},
                    }
                ]
            }
        ),
    )

    result = gateway.decide(run=_run(), context=_context())

    assert result.terminal_outcome is not None
    assert result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID"


def test_primary_gateway_maps_selected_provider_error_without_cross_provider_fallback_or_raw_detail() -> (
    None
):
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


def test_provider_keeps_bounded_string_list_arguments_for_descriptor_validation() -> (
    None
):
    decision = parse_tutor_decision(
        {
            "capability_requests": [
                {
                    "request_id": "grounding-1",
                    "capability_id": "grounding.retrieve",
                    "arguments": {
                        "language_id_or_alias": "python",
                        "query_text": "function return",
                        "topic_tags": ["functions"],
                        "top_k": 1,
                    },
                }
            ]
        }
    )

    request = decision.capability_requests[0]
    arguments = {field.key: json.loads(field.value) for field in request.arguments}
    assert arguments["topic_tags"] == ["functions"]
    assert arguments["top_k"] == 1


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
