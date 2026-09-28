"""The final wire budget includes retry guidance and never dispatches overflow."""
from __future__ import annotations

import json

import pytest

from app.agents.harness.context_builder import Utf8ByteTokenEstimator
from app.agents.harness.contracts import TutorContextError, TutorProviderContextCapability
from app.agents.harness.provider_request import TUTOR_TEACHING_POLICY
from app.services.tutor.decision_protocol import build_tutor_replacement_message
from app.services.tutor.provider_request_budget import assert_tutor_provider_request_budget


_BASE = [{"role": "system", "content": "Tutor contract"}, {"role": "user", "content": "学习 SQL"}]
_REPAIR = {
    "role": "user",
    "content": build_tutor_replacement_message((), teaching_policy=TUTOR_TEACHING_POLICY),
}
_PROTOCOL_RESERVE = 32
_SAFETY_MARGIN = 64
_OUTPUT_RESERVE = 4_096


def _wire_estimate(messages: list[dict[str, str]]) -> int:
    payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    return (
        Utf8ByteTokenEstimator().estimate_tokens(payload)
        + _PROTOCOL_RESERVE
        + _SAFETY_MARGIN
    )


def _capability(input_limit: int) -> TutorProviderContextCapability:
    return TutorProviderContextCapability(
        context_window_tokens=input_limit + _OUTPUT_RESERVE,
        max_output_reserve_tokens=_OUTPUT_RESERVE,
        protocol_reserve_tokens=_PROTOCOL_RESERVE,
        safety_margin_tokens=_SAFETY_MARGIN,
        maximum_dynamic_target_tokens=1,
        capability_version="retry-budget-test-v1",
    )


def test_exact_fit_is_accepted_with_wire_protocol_safety_and_output_reserves() -> None:
    messages = [*_BASE, _REPAIR]
    exact = _wire_estimate(messages)
    capability = _capability(exact)

    assert capability.context_window_tokens == exact + _OUTPUT_RESERVE
    assert capability.input_hard_limit == exact
    assert assert_tutor_provider_request_budget(messages, capability=capability) == exact
    with pytest.raises(TutorContextError) as error:
        assert_tutor_provider_request_budget(messages, capability=_capability(exact - 1))
    assert error.value.safe_code == "TUTOR_CONTEXT_REQUEST_OVERFLOW"


def test_repair_overflow_is_not_masked_by_a_fitting_first_attempt() -> None:
    initial = _wire_estimate(_BASE)
    repaired = [*_BASE, _REPAIR]
    capability = _capability(initial)
    assert assert_tutor_provider_request_budget(_BASE, capability=capability) == initial
    assert _wire_estimate(repaired) > initial

    with pytest.raises(TutorContextError) as error:
        assert_tutor_provider_request_budget(repaired, capability=capability)
    assert error.value.safe_code == "TUTOR_CONTEXT_REQUEST_OVERFLOW"


def test_budget_failure_prevents_a_new_provider_request_without_a_retry() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.requests: list[list[dict[str, str]]] = []

        def complete_json(self, messages: list[dict[str, str]]) -> None:
            self.requests.append(messages)

    client = FakeClient()
    capability = _capability(_wire_estimate(_BASE))

    def send(messages: list[dict[str, str]]) -> None:
        assert_tutor_provider_request_budget(messages, capability=capability)
        client.complete_json(messages)

    send(_BASE)
    with pytest.raises(TutorContextError, match="TUTOR_CONTEXT_REQUEST_OVERFLOW"):
        send([*_BASE, _REPAIR])
    assert client.requests == [_BASE]

@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("snapshot_policy", [False, True])
def test_gateway_blocks_actual_repair_send_and_preserves_only_real_attempt(
    monkeypatch: pytest.MonkeyPatch, *, streaming: bool, snapshot_policy: bool,
) -> None:
    from dataclasses import replace

    from app.agents.harness.context_budget import build_tutor_context_budget_policy
    from app.agents.harness.contracts import (
        TutorProviderAttemptOutcome,
        TutorTerminalOutcome,
    )
    from app.core.config import Settings
    from app.services.llm.llm_client import OpenAICompatibleClient
    from app.services.tutor import provider_gateway
    from tests.tutor.test_tutor_provider_gateway import (
        RecordingThinkingSink,
        SequencedJsonClient,
        _context,
        _run,
        _valid_payload,
    )

    run, context = _run(), _context()
    first_messages = provider_gateway._build_messages(run=run, context=context)
    exact = _wire_estimate(first_messages)
    settings = Settings(
        llm_type="deepseek",
        deepseek_api_key="test-key-not-a-real-credential",
        deepseek_base_url="https://deepseek.example.test",
        deepseek_model="deepseek-flash",
        tutor_deepseek_v4_flash_input_limit_tokens=exact,
        tutor_deepseek_v4_flash_max_output_tokens=_OUTPUT_RESERVE,
        tutor_deepseek_v4_flash_decision_max_output_tokens=_OUTPUT_RESERVE,
        tutor_deepseek_v4_flash_max_dynamic_target_tokens=1,
        tutor_context_protocol_reserve_tokens=_PROTOCOL_RESERVE,
        tutor_context_safety_margin_tokens=_SAFETY_MARGIN,
    )
    if snapshot_policy:
        run = replace(run, policy=replace(
            run.policy, context_budget_policy=build_tutor_context_budget_policy(settings),
        ))

    rejected = _valid_payload()
    rejected["action"] = {"type": "unknown_action"}
    checked_messages: list[list[dict[str, str]]] = []
    original_guard = provider_gateway.assert_tutor_provider_request_budget

    def observe_guard(messages, *, capability):
        checked_messages.append([dict(message) for message in messages])
        return original_guard(messages, capability=capability)

    monkeypatch.setattr(provider_gateway, "assert_tutor_provider_request_budget", observe_guard)
    payloads: list[object] = []

    def transport(url, headers, payload, timeout):
        del url, headers, timeout
        payloads.append(payload)
        return {
            "type": "response.completed",
            "response": {
                "model": "deepseek-flash",
                "output": [{"type": "message", "content": [{
                    "type": "output_text", "text": json.dumps(rejected, ensure_ascii=False),
                }]}],
            },
        }

    fake_client = SequencedJsonClient([rejected])
    client = OpenAICompatibleClient(settings, transport=transport) if streaming else fake_client
    sink = RecordingThinkingSink() if streaming else None
    result = provider_gateway.PrimaryTutorProviderGateway(settings=settings, client=client).decide(
        run=run, context=context, thinking_sink=sink,
    )

    assert (len(payloads) if streaming else fake_client.calls) == 1
    assert result.decision is None
    assert result.terminal_outcome is TutorTerminalOutcome.FAILED
    assert result.safe_code == "TUTOR_CONTEXT_REQUEST_OVERFLOW"
    assert len(result.attempts) == 1
    assert result.attempts[0].attempt_index == 1
    assert result.attempts[0].outcome is TutorProviderAttemptOutcome.REPAIRABLE_REJECTED
    assert result.attempts[0].diagnostic_code != "TUTOR_CONTEXT_REQUEST_OVERFLOW"
    assert len(checked_messages) == 2
    assert checked_messages[0] == first_messages
    assert checked_messages[1][:-1] == first_messages
    assert "previous candidate was rejected" in checked_messages[1][-1]["content"]
    assert _wire_estimate(checked_messages[0]) == exact
    assert _wire_estimate(checked_messages[1]) > exact
    if sink is not None:
        assert ("begin", 1, "") in sink.operations
        assert ("discard", 1, "") in sink.operations
        assert ("begin", 2, "") in sink.operations
        assert sink.operations[-1] == ("discard", 2, "")
        assert not any(operation == "complete" for operation, _, _ in sink.operations)
        assert not any(operation == "append" and index == 2 for operation, index, _ in sink.operations)
        assert any(operation == "append" and index == 1 for operation, index, _ in sink.operations)
