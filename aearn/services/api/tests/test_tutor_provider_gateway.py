from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Mapping, Sequence

import pytest

from app.agents.harness.contracts import (
    TutorContextSelection,
    TutorPolicySnapshot,
    TutorRunSnapshot,
    empty_checkpoint_metadata,
)
from app.core.config import Settings
from app.services.llm.llm_client import LLMCallError, LLMJsonResponse, OpenAICompatibleClient
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway, parse_tutor_decision


class FakeJsonClient:
    def __init__(self, *, content: dict[str, object] | None = None, error: Exception | None = None) -> None:
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


class FalseyJsonClient(FakeJsonClient):
    def __bool__(self) -> bool:
        return False


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-provider",
        conversation_id="conversation-provider",
        user_id="user-provider",
        input_revision=0,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
            max_capability_calls=1,
            max_effects=1,
        ),
    )


def _context() -> TutorContextSelection:
    return TutorContextSelection(
        items=(),
        checkpoint_metadata=empty_checkpoint_metadata(token_budget=1200),
    )


def _valid_payload() -> dict[str, object]:
    return {
        "public_message": "先检查变量是在回调外定义，还是只在回调内部可见。",
        "skill_references": [{"skill_id": "scope-basics", "version": "v1"}],
        "terminal_intent": "completed",
    }


def test_primary_gateway_uses_configured_deepseek_client_without_fallback() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured.update(url=url, headers=dict(headers), payload=dict(payload), timeout=timeout)
        return {
            "model": "deepseek-v4-flash",
            "choices": [{"message": {"content": json.dumps(_valid_payload(), ensure_ascii=False)}}],
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
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["payload"]["model"] == "deepseek-v4-flash"
    assert settings.llm_provider_type == "deepseek"


def test_primary_gateway_uses_configured_openai_compatible_client_without_fallback() -> None:
    captured: dict[str, object] = {}

    def transport(
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
        timeout: float,
    ) -> Mapping[str, object]:
        captured.update(url=url, headers=dict(headers), payload=dict(payload), timeout=timeout)
        return {
            "model": "provider-model",
            "output": [{"content": [{"type": "output_text", "text": json.dumps(_valid_payload(), ensure_ascii=False)}]}],
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
    gateway = PrimaryTutorProviderGateway(settings=Settings(llm_type="disabled"), client=client)

    result = gateway.decide(run=_run(), context=_context())

    assert result.decision is not None
    assert client.calls == 1


def test_primary_gateway_rejects_unknown_or_guardrail_blocked_envelopes_as_model_unavailable() -> None:
    unknown = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="k", openai_base_url="https://provider.example", openai_model="m"),
        client=FakeJsonClient(content={"public_message": "继续看变量。", "reasoning": "private chain"}),
    )
    blocked = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="k", openai_base_url="https://provider.example", openai_model="m"),
        client=FakeJsonClient(content={"public_message": "完整答案如下：...", "terminal_intent": "completed"}),
    )

    unknown_result = unknown.decide(run=_run(), context=_context())
    blocked_result = blocked.decide(run=_run(), context=_context())

    assert unknown_result.terminal_outcome is not None
    assert blocked_result.terminal_outcome is not None
    assert unknown_result.safe_code == "MODEL_UNAVAILABLE"
    assert blocked_result.safe_code == "MODEL_UNAVAILABLE"


@pytest.mark.parametrize("field_name", ["reasoning", "diagnostic", "provider_payload", "hidden_test_body"])
def test_primary_gateway_rejects_internal_nested_payload_fields_as_model_unavailable(field_name: str) -> None:
    gateway = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="k", openai_base_url="https://provider.example", openai_model="m"),
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
    assert result.safe_code == "MODEL_UNAVAILABLE"


def test_primary_gateway_maps_selected_provider_error_without_cross_provider_fallback_or_raw_detail() -> None:
    fake = FakeJsonClient(error=LLMCallError("provider raw Authorization: Bearer secret-token"))
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
    assert result.safe_code == "MODEL_UNAVAILABLE"
    assert "secret-token" not in serialized
    assert "provider raw" not in serialized


def test_provider_keeps_bounded_string_list_arguments_for_descriptor_validation() -> None:
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
