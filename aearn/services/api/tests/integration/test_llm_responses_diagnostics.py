"""Offline tests of the real HTTP serialization and Responses SSE parser."""
from __future__ import annotations

import io
import json
from dataclasses import FrozenInstanceError, asdict
from typing import Literal
from urllib.request import Request

import pytest

from app.core.config import Settings
from app.services.llm.contracts import LLMResponseDiagnostics
from app.services.llm.llm_client import LLMInvalidResponseError, LLMJsonResponse, OpenAICompatibleClient


PROTECTED = "private-reasoning api-key secret prompt hidden-test"
VISIBLE = '{"ok": true}'


def _settings(provider: str = "deepseek", model: str = "deepseek-flash") -> Settings:
    return Settings(
        llm_type=provider, deepseek_api_key="fake", deepseek_base_url="https://provider.invalid",
        deepseek_model=model, openai_api_key="fake", openai_base_url="https://provider.invalid",
        openai_model=model,
    )


def _response(status: str = "completed", reason: object = None, text: str = VISIBLE) -> dict:
    return {
        "model": "fake-model", "status": status,
        "incomplete_details": {"reason": reason},
        "error": {"message": PROTECTED},
        "output": [
            {"type": "reasoning", "content": [{"type": "reasoning_text", "text": PROTECTED}]},
            {"type": "message", "content": [{"type": "output_text", "text": text}]},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 25,
                  "output_tokens_details": {"reasoning_tokens": 21}},
    }


def _wire(monkeypatch: pytest.MonkeyPatch, frames: list[dict] | None = None) -> list[dict]:
    requests = []

    def urlopen(request: Request, *, timeout: float) -> io.BytesIO:
        assert request.full_url.startswith("https://provider.invalid/")
        assert request.method == "POST"
        payload = json.loads(request.data)
        requests.append(payload)
        if request.full_url.endswith("/chat/completions"):
            return io.BytesIO(json.dumps({"choices": [{"message": {"content": VISIBLE}}]}).encode())
        events = frames if frames is not None else [{"type": "response.completed", "response": _response()}]
        return io.BytesIO(b"".join(("data: " + json.dumps(event) + "\n\n").encode() for event in events))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return requests


@pytest.mark.parametrize("mode", [None, "enabled", "disabled"])
@pytest.mark.parametrize("provider,model", [
    ("deepseek", "deepseek-flash"), ("deepseek", "deepseek-chat"),
    ("openai", "fake-model"),
])
def test_protocol_specific_thinking_on_actual_wire(
    monkeypatch: pytest.MonkeyPatch, provider: str, model: str,
    mode: Literal["enabled", "disabled"] | None,
) -> None:
    requests = _wire(monkeypatch)
    result = OpenAICompatibleClient(_settings(provider, model)).complete_json(
        [{"role": "user", "content": "JSON please"}], thinking_mode=mode, max_tokens=100,
    )
    assert result.content == {"ok": True}
    assert len(requests) == 1
    payload = requests[0]
    if provider == "deepseek" and model == "deepseek-chat":
        assert "reasoning" not in payload
        assert payload.get("thinking") == ({"type": mode} if mode else None)
        assert payload["max_tokens"] == 100
        assert result.response_diagnostics is None
    else:
        assert "thinking" not in payload
        effort = ("none" if mode == "disabled" else "high") if mode and provider == "deepseek" else None
        assert payload.get("reasoning") == ({"effort": effort} if effort else None)
        assert payload["max_output_tokens"] == 100
        assert result.response_diagnostics is not None
        assert result.response_diagnostics.requested_reasoning_effort == effort
        assert result.response_diagnostics.requested_max_output_tokens == 100


def test_exact_deepseek_v4_flash_applies_the_60k_output_hard_cap_on_wire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _wire(monkeypatch)
    client = OpenAICompatibleClient(_settings())

    result = client.complete_json([{"role": "user", "content": "JSON"}])

    assert result.content == {"ok": True}
    assert requests[0]["max_output_tokens"] == 61_440
    assert result.response_diagnostics is not None
    assert result.response_diagnostics.requested_max_output_tokens == 61_440


@pytest.mark.parametrize("max_tokens", [0, 61_441])
def test_exact_deepseek_v4_flash_rejects_invalid_output_budget_before_transport(
    monkeypatch: pytest.MonkeyPatch,
    max_tokens: int,
) -> None:
    requests = _wire(monkeypatch)

    with pytest.raises(ValueError, match="max_tokens"):
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "JSON"}],
            max_tokens=max_tokens,
        )

    assert requests == []


def test_exact_deepseek_v4_flash_rejects_input_over_128k_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _wire(monkeypatch)

    with pytest.raises(ValueError, match="request input exceeds"):
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "x" * (131_072 * 4)}],
        )

    assert requests == []


@pytest.mark.parametrize("status", ["completed", "incomplete", "failed", "missing_terminal"])
@pytest.mark.parametrize("reason", [None, "max_output_tokens", "content_filter", "context_length_exceeded", PROTECTED, [PROTECTED]])
def test_terminal_diagnostics_are_safe_and_partial_json_is_never_accepted(
    monkeypatch: pytest.MonkeyPatch, status: str, reason: object,
) -> None:
    response = _response(status, reason)
    frames = [
        {"type": "response.created", "response": response},
        {"type": "response.reasoning_text.delta", "delta": PROTECTED},
        {"type": "response.output_text.delta", "delta": VISIBLE},
    ]
    if status != "missing_terminal":
        frames.append({"type": "response." + status, "response": response})
    requests = _wire(monkeypatch, frames)
    client = OpenAICompatibleClient(_settings())
    if status == "completed":
        result = client.complete_json([{ "role": "user", "content": "JSON"}], max_tokens=90, thinking_mode="disabled")
    else:
        with pytest.raises(LLMInvalidResponseError) as caught:
            client.complete_json([{ "role": "user", "content": "JSON"}], max_tokens=90, thinking_mode="disabled")
        result = caught.value
        assert PROTECTED not in str(result)
    assert len(requests) == 1
    assert result.model == "fake-model"
    assert result.usage is not None and result.usage.reasoning_tokens == 21
    diagnostics = result.response_diagnostics
    assert diagnostics is not None
    assert asdict(diagnostics) == {
        "response_status": status,
        "incomplete_reason": "unknown" if reason == PROTECTED or isinstance(reason, list) else reason,
        "requested_max_output_tokens": 90,
        "requested_reasoning_effort": "none",
        "visible_output_chars": len(VISIBLE),
    }
    assert PROTECTED not in repr(diagnostics)


@pytest.mark.parametrize("text", ["", "not json", "[]"])
def test_content_rejection_preserves_response_diagnostics(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    _wire(monkeypatch, [{"type": "response.completed", "response": _response(text=text)}])
    with pytest.raises(LLMInvalidResponseError) as caught:
        OpenAICompatibleClient(_settings()).complete_json([{ "role": "user", "content": "JSON"}])
    assert caught.value.response_diagnostics == LLMResponseDiagnostics(
        response_status="completed",
        requested_max_output_tokens=61_440,
        visible_output_chars=len(text),
    )
    assert caught.value.usage.reasoning_tokens == 21


@pytest.mark.parametrize("field", ["response_status", "incomplete_reason", "requested_reasoning_effort"])
@pytest.mark.parametrize("value", [PROTECTED, [PROTECTED], {"secret": PROTECTED}, True, 42])
def test_diagnostic_literals_are_validated_without_unsafe_errors(field: str, value: object) -> None:
    with pytest.raises(ValueError) as caught:
        LLMResponseDiagnostics(**{field: value})
    assert PROTECTED not in str(caught.value)


@pytest.mark.parametrize("field", ["requested_max_output_tokens", "visible_output_chars"])
@pytest.mark.parametrize("value", [True, -1, 0.2, "2", [], {}])
def test_diagnostic_counts_reject_invalid_types(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        LLMResponseDiagnostics(**{field: value})


def test_diagnostics_are_immutable_and_default_optional_fields() -> None:
    diagnostics = LLMResponseDiagnostics(response_status="incomplete")
    assert diagnostics.incomplete_reason is None
    assert diagnostics.requested_max_output_tokens is None
    assert diagnostics.requested_reasoning_effort is None
    assert diagnostics.visible_output_chars is None
    with pytest.raises(FrozenInstanceError):
        diagnostics.response_status = "completed"


@pytest.mark.parametrize("frames", [[], [{"type": "response.output_text.done", "text": VISIBLE}]])
def test_stream_without_terminal_never_promotes_text_to_json(monkeypatch: pytest.MonkeyPatch, frames: list[dict]) -> None:
    _wire(monkeypatch, frames)
    with pytest.raises(LLMInvalidResponseError) as caught:
        OpenAICompatibleClient(_settings()).complete_json([{ "role": "user", "content": "JSON"}])
    assert caught.value.response_diagnostics.response_status == "missing_terminal"


@pytest.mark.parametrize("status", ["queued", "in_progress", "cancelled", PROTECTED, [PROTECTED]])
def test_noncompleted_envelope_is_rejected_with_closed_status(monkeypatch: pytest.MonkeyPatch, status: object) -> None:
    response = _response()
    response["status"] = status
    _wire(monkeypatch, [{"type": "response.completed", "response": response}])
    with pytest.raises(LLMInvalidResponseError) as caught:
        OpenAICompatibleClient(_settings()).complete_json([{ "role": "user", "content": "JSON"}])
    diagnostics = caught.value.response_diagnostics
    assert diagnostics.response_status == (status if isinstance(status, str) and status in ("queued", "in_progress", "cancelled") else "unknown")
    assert PROTECTED not in repr(diagnostics)


def test_reasoning_only_response_has_zero_visible_chars(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _response()
    response["output"] = response["output"][:1]
    _wire(monkeypatch, [{"type": "response.completed", "response": response}])
    with pytest.raises(LLMInvalidResponseError) as caught:
        OpenAICompatibleClient(_settings()).complete_json([{ "role": "user", "content": "JSON"}])
    assert caught.value.response_diagnostics.visible_output_chars == 0
    assert caught.value.usage.reasoning_tokens == 21


def test_max_reasoning_effort_is_supported() -> None:
    assert LLMResponseDiagnostics(requested_reasoning_effort="max").requested_reasoning_effort == "max"


def test_json_response_preserves_fourth_positional_capture_argument() -> None:
    capture = object()
    result = LLMJsonResponse({}, "fake", None, capture)
    assert result.diagnostic_capture is capture
    assert result.response_diagnostics is None


def test_legacy_injected_envelope_without_status_remains_compatible() -> None:
    response = _response()
    del response["status"]
    client = OpenAICompatibleClient(_settings(), transport=lambda *_args: response)
    result = client.complete_json([{ "role": "user", "content": "JSON"}])
    assert result.content == {"ok": True}
    assert result.response_diagnostics.response_status == "unknown"

@pytest.mark.parametrize("model", ["deepseek-flash", "deepseek-v4-pro"])
@pytest.mark.parametrize("effort", ["low", "high", "max"])
def test_explicit_deepseek_thinking_effort_uses_exact_protocol_wire(monkeypatch, model, effort):
    requests = _wire(monkeypatch)
    result = OpenAICompatibleClient(_settings(model=model), max_http_attempts=1).complete_json(
        [{"role": "user", "content": "Return JSON."}], thinking_mode="enabled",
        reasoning_effort=effort, max_tokens=512, temperature=None, capture_provider_body=False,
    )
    assert result.content == {"ok": True} and len(requests) == 1
    payload = requests[0]
    assert "temperature" not in payload
    if model == "deepseek-flash":
        assert payload["reasoning"] == {"effort": effort}
        assert "thinking" not in payload and "reasoning_effort" not in payload
        assert payload["max_output_tokens"] == 512
    else:
        assert payload["thinking"] == {"type": "enabled"}
        assert payload["reasoning_effort"] == effort and "reasoning" not in payload
        assert payload["max_tokens"] == 512


@pytest.mark.parametrize("mode,effort", [(None, "high"), ("disabled", "high"), ("enabled", "ultra")])
def test_explicit_effort_invalid_or_conflicting_request_never_dispatches(monkeypatch, mode, effort):
    requests = _wire(monkeypatch)
    with pytest.raises(ValueError, match="reasoning_effort"):
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "JSON"}], thinking_mode=mode, reasoning_effort=effort,
        )
    assert requests == []


@pytest.mark.parametrize("provider,model", [("openai", "fake-model"), ("deepseek", "deepseek-chat")])
def test_explicit_deepseek_effort_does_not_guess_unsupported_model_protocol(monkeypatch, provider, model):
    requests = _wire(monkeypatch)
    with pytest.raises(ValueError, match="reasoning_effort"):
        OpenAICompatibleClient(_settings(provider, model)).complete_json(
            [{"role": "user", "content": "JSON"}], thinking_mode="enabled", reasoning_effort="high",
        )
    assert requests == []


@pytest.mark.parametrize("finish", ["length", "content_filter"])
def test_thinking_chat_truncation_is_pending_even_when_visible_content_is_valid_json(finish):
    requests = []

    def transport(url, headers, payload, timeout):
        requests.append(payload)
        return {"model": "deepseek-v4-pro", "choices": [{"finish_reason": finish,
            "message": {"content": VISIBLE, "reasoning_content": PROTECTED}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 25}}

    with pytest.raises(LLMInvalidResponseError, match="incomplete") as caught:
        OpenAICompatibleClient(_settings(model="deepseek-v4-pro"), transport=transport,
            max_http_attempts=1).complete_json(
            [{"role": "user", "content": "JSON"}], thinking_mode="enabled",
            reasoning_effort="high", max_tokens=512, capture_provider_body=False,
        )
    assert len(requests) == 1 and PROTECTED not in str(caught.value)
    assert caught.value.usage is not None and caught.value.usage.output_tokens == 25
    assert caught.value.response_diagnostics is not None
    assert caught.value.response_diagnostics.requested_reasoning_effort == "high"
    assert caught.value.response_diagnostics.incomplete_reason == (
        "max_output_tokens" if finish == "length" else "content_filter")
