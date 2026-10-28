"""CPU-only completion policy, exact payload and bounded HTTP regression checks."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import FrozenInstanceError, asdict, replace
from datetime import UTC, datetime
from math import ceil
from typing import Any

import pytest
import httpx

from app.agents.harness.context_budget import TutorContextBudgetPlanner, build_tutor_context_budget_policy
from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    TutorContextBudgetMode, TutorContextError, TutorContextInput, TutorContextSource,
    TutorExecutionProfile, TutorPolicySnapshot, TutorProviderContextCapability, TutorRunSnapshot,
)
from app.agents.harness.provider_request import TutorProviderRequestSerializer
from app.core.config import Settings
from app.services.llm.completion_policy import estimate_completion_request_tokens, resolve_completion_stage_policy
from app.services.llm import http_execution as http_scope
from app.services.llm.http_execution import LLMHTTPExecution, LLMHTTPExecutionError, use_http_execution
from app.services.llm.llm_client import OpenAICompatibleClient, build_json_request_payload
from app.services.tutor.decision_protocol import TUTOR_PROVIDER_ITEMS_SCHEMA_NAME, tutor_provider_output_schema
from app.services.tutor.provider_request_budget import assert_tutor_provider_request_budget
from tests.llm.test_mvp_http_execution import _completed, _no_worker, _wire


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "llm_type": "deepseek", "deepseek_model": "deepseek-flash",
        "deepseek_api_key": "fake", "deepseek_base_url": "https://provider.invalid",
        "tutor_completion_driven_enabled": True, "llm_timeout_seconds": 900,
        "tutor_provider_debug_capture_mode": "off",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_off_and_environment_names_leave_legacy_contract_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TUTOR_COMPLETION_DRIVEN_ENABLED", raising=False)
    assert Settings().tutor_completion_driven_enabled is False
    monkeypatch.setenv("TUTOR_COMPLETION_DRIVEN_ENABLED", "true")
    monkeypatch.setenv("TUTOR_COMPLETION_VALIDATED_CHANNEL_CONTEXT_TOKENS", "400000")
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-flash")
    assert settings.tutor_completion_driven_enabled is True
    assert settings.tutor_completion_validated_channel_context_tokens == 400_000
    assert settings.tutor_deepseek_v4_flash_input_limit_tokens == 131_072
    assert settings.tutor_deepseek_v4_flash_max_output_tokens == 61_440
    assert settings.tutor_completion_batch_timeout_seconds == 2400
    assert settings.tutor_completion_max_decisions == 8
    assert settings.tutor_completion_max_http_requests == 16
    assert settings.tutor_completion_result_reserve_seconds == 60
    with pytest.raises(ValueError):
        Settings(tutor_deepseek_v4_flash_input_limit_tokens=262_144)
    with pytest.raises(ValueError, match="tutor_completion_batch_timeout_seconds"):
        Settings(tutor_completion_batch_timeout_seconds=60)


@pytest.mark.parametrize(("name", "value"), [
    ("tutor_completion_batch_timeout_seconds", 1200), ("tutor_completion_batch_timeout_seconds", 2401),
    ("tutor_completion_max_decisions", 4), ("tutor_completion_max_decisions", 9),
    ("tutor_completion_max_http_requests", 8), ("tutor_completion_max_http_requests", 17),
    ("tutor_completion_result_reserve_seconds", 30), ("tutor_completion_result_reserve_seconds", 61),
])
def test_fixed_batch_contract_rejects_ignored_or_excessive_overrides(
    monkeypatch: pytest.MonkeyPatch, name: str, value: int,
) -> None:
    # Cover both programmatic and actual environment inputs to Settings; no
    # owner/DB fixture or runtime activation is needed to reject a false knob.
    with pytest.raises(ValueError, match=name):
        _settings(**{name: value})
    monkeypatch.setenv(name.upper(), str(value))
    with pytest.raises(ValueError, match=name):
        Settings()


def test_completion_environment_defaults_obey_declared_field_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TUTOR_COMPLETION_LESSON_TIMEOUT_SECONDS", "601")
    with pytest.raises(ValueError, match="tutor_completion_lesson_timeout_seconds"):
        Settings()


@pytest.mark.parametrize(("stage", "output", "timeout"), [
    ("tutor_decision", 16384, 300), ("material_semantic_review", 256, 90),
    ("lesson_authoring", 12000, 600), ("model_review_authoring", 6000, 90),
])
def test_frozen_stage_policy_defaults_and_fallback(stage: str, output: int, timeout: int) -> None:
    policy = resolve_completion_stage_policy(_settings(), stage)
    assert policy.max_output_tokens == output
    assert policy.timeout_seconds == timeout
    assert policy.thinking_mode == ("disabled" if stage == "material_semantic_review" else None)
    capability = policy.context_capability
    assert capability is not None
    assert capability.input_hard_limit == 131_072
    assert capability.max_output_reserve_tokens == output
    assert capability.safety_margin_tokens == 4096
    assert capability.safety_margin_ratio == 0.05
    assert capability.capability_version == "completion-legacy-application-fallback-v1"
    persisted = asdict(capability)
    assert "safety_margin_ratio" not in persisted
    assert TutorProviderContextCapability(**persisted).safety_margin_ratio == 0.05
    with pytest.raises(FrozenInstanceError):
        setattr(policy, "timeout_seconds", 1)


def test_declared_channel_is_bounded_by_model_and_not_a_sidecar_output_claim() -> None:
    settings = _settings(tutor_completion_validated_channel_context_tokens=400_000)
    policy = resolve_completion_stage_policy(settings, "lesson_authoring")
    assert policy.context_capability is not None
    assert policy.context_capability.input_hard_limit == 400_000 - 12_000
    assert policy.context_capability.capability_version == "completion-declared-validated-channel-v1"
    bigger = resolve_completion_stage_policy(
        _settings(tutor_completion_validated_channel_context_tokens=2_000_000), "tutor_decision",
    )
    assert bigger.context_capability is not None
    assert bigger.context_capability.context_window_tokens == 1_000_000
    sidecar = resolve_completion_stage_policy(settings, "sidecar_turn")
    assert sidecar.timeout_seconds == 900
    assert sidecar.max_output_tokens is sidecar.context_capability is None
    with pytest.raises(ValueError, match="Unknown completion stage"):
        resolve_completion_stage_policy(settings, "invented")
    with pytest.raises(ValueError, match="output capacity"):
        resolve_completion_stage_policy(_settings(tutor_completion_lesson_max_output_tokens=70000), "lesson_authoring")


def test_exact_final_payload_reserves_schema_unicode_and_ratio_margin() -> None:
    settings = _settings(tutor_completion_validated_channel_context_tokens=400_000)
    capability = resolve_completion_stage_policy(settings, "lesson_authoring").context_capability
    assert capability is not None
    messages = [{"role": "user", "content": "课程" * 60000}]
    payload = build_json_request_payload(
        settings, messages, max_tokens=12000,
        output_schema={"type": "object", "description": "condition and exception"},
    )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    raw_estimate = ceil(len(encoded) / 4)
    expected = raw_estimate + capability.protocol_reserve_tokens + max(4096, ceil(raw_estimate * 0.05))
    assert expected == estimate_completion_request_tokens(payload, capability=capability)
    boundary = replace(capability, context_window_tokens=expected + 12000, maximum_dynamic_target_tokens=1)
    assert assert_tutor_provider_request_budget(messages, capability=boundary, payload=payload) == expected
    repair = build_json_request_payload(
        settings, [*messages, {"role": "system", "content": "Repair this JSON exactly." * 30}], max_tokens=12000,
    )
    with pytest.raises(TutorContextError, match="TUTOR_CONTEXT_REQUEST_OVERFLOW"):
        assert_tutor_provider_request_budget(messages, capability=boundary, payload=repair)


def test_planner_keeps_required_evidence_over_targets_and_legacy_input_limit() -> None:
    settings = _settings(tutor_completion_validated_channel_context_tokens=400_000)
    policy = build_tutor_context_budget_policy(settings, completion_stage="tutor_decision")
    assert [policy.target_for(mode) for mode in (
        TutorContextBudgetMode.COMPACT, TutorContextBudgetMode.NORMAL, TutorContextBudgetMode.COMPLEX,
    )] == [16_000, 64_000, 96_000]
    run = TutorRunSnapshot(
        run_id="completion-budget", conversation_id="conversation", user_id="user", input_revision=1,
        origin="interactive", policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC), context_budget_policy=policy,
            execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
        ),
    )
    evidence = "condition exception reference. " * 20000
    context_input = TutorContextInput(
        run_id=run.run_id, conversation_id=run.conversation_id, input_revision=1,
        current_input=TutorContextSource("current", "Explain the required source."),
        current_input_required=True, required_facts=(TutorContextSource("required-source", evidence),),
    )
    selection = TutorContextBudgetPlanner(settings=settings).build_context(
        run=run, context_input=context_input,
        builder=TutorContextBuilder(),
    )
    assert selection.items[0].content == evidence.strip()
    assert selection.checkpoint_metadata.required_fact_missing_count == 0
    assert selection.checkpoint_metadata.truncated_count == 0
    messages = TutorProviderRequestSerializer().build_messages(run=run, context=selection)
    payload = build_json_request_payload(
        settings, messages, max_tokens=16384, output_schema=tutor_provider_output_schema(),
        schema_name=TUTOR_PROVIDER_ITEMS_SCHEMA_NAME,
    )
    estimate = assert_tutor_provider_request_budget(messages, capability=policy.capability, payload=payload)
    assert estimate > 131_072
    assert estimate == selection.checkpoint_metadata.estimated_total_input_tokens
    legacy_run = replace(run, policy=replace(
        run.policy, context_budget_policy=build_tutor_context_budget_policy(settings), execution_profile=None,
    ))
    with pytest.raises(TutorContextError):
        TutorContextBudgetPlanner(settings=settings).build_context(
            run=legacy_run, context_input=context_input,
            builder=TutorContextBuilder(config=TutorContextBuilderConfig(max_source_characters=1_000_000)),
        )


@pytest.mark.parametrize(("stage", "output", "timeout"), [
    ("tutor_decision", 16384, 300), ("material_semantic_review", 256, 90),
    ("lesson_authoring", 12000, 600), ("model_review_authoring", 6000, 90),
])
def test_stage_limits_reach_actual_mock_http_and_nonthinking_semantic(
    monkeypatch: pytest.MonkeyPatch, stage: str, output: int, timeout: int,
) -> None:
    requests, clients = _wire(monkeypatch)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    with use_http_execution(execution):
        result = OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "Return JSON"}], completion_stage=stage,
        )
    assert result.content == {"ok": True}
    assert execution.physical_attempts == len(requests) == 1
    wire = json.loads(requests[0].content)
    assert wire["max_output_tokens"] == output
    if stage == "material_semantic_review":
        assert wire["reasoning"] == {"effort": "none"}
    assert timeout - 2 < requests[0].extensions["timeout"]["read"] <= timeout
    assert requests[0].content == json.dumps(wire, ensure_ascii=False, separators=(",", ":")).encode()
    assert all(client.is_closed for client in clients)
    _no_worker()


def test_completion_final_wire_accepts_declared_large_input_but_rejects_oversized_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests, _ = _wire(monkeypatch)
    client = OpenAICompatibleClient(_settings(tutor_completion_validated_channel_context_tokens=400_000))
    messages = [{"role": "user", "content": "evidence " * 70000}]
    with pytest.raises(ValueError, match="configured DeepSeek Flash maximum"):
        client.complete_json(messages, max_tokens=12000)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    with use_http_execution(execution):
        client.complete_json(messages, completion_stage="lesson_authoring", timeout_seconds=75)
        with pytest.raises(TutorContextError, match="TUTOR_CONTEXT_REQUEST_OVERFLOW"):
            client.complete_json(
                [*messages, {"role": "system", "content": "repair " * 200000}],
                completion_stage="lesson_authoring",
            )
    assert len(requests) == execution.physical_attempts == 1
    assert requests[0].extensions["timeout"]["read"] <= 75
    _no_worker()


def test_new_stage_cannot_use_legacy_transport_or_override_its_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    requests, _ = _wire(monkeypatch)
    messages = [{"role": "user", "content": "Return JSON"}]
    with pytest.raises(ValueError, match="disabled"):
        OpenAICompatibleClient(_settings(tutor_completion_driven_enabled=False)).complete_json(
            messages, completion_stage="tutor_decision",
        )
    client = OpenAICompatibleClient(_settings())
    with pytest.raises(ValueError, match="explicit HTTP execution scope"):
        client.complete_json(messages, completion_stage="lesson_authoring")
    with pytest.raises(ValueError, match="output policy"):
        client.complete_json(messages, completion_stage="lesson_authoring", max_tokens=6000)
    with pytest.raises(ValueError, match="thinking_mode conflicts"):
        client.complete_json(messages, completion_stage="material_semantic_review", thinking_mode="enabled")
    with pytest.raises(ValueError, match="Sidecar"):
        client.complete_json(messages, completion_stage="sidecar_turn")
    assert requests == []


def test_final_guard_counts_schema_and_cannot_hide_it_behind_small_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    requests, _ = _wire(monkeypatch)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    settings = _settings(tutor_deepseek_responses_json_schema_enabled=True)
    with use_http_execution(execution), pytest.raises(TutorContextError, match="TUTOR_CONTEXT_REQUEST_OVERFLOW"):
        OpenAICompatibleClient(settings).complete_json(
            [{"role": "user", "content": "Return JSON"}], completion_stage="lesson_authoring",
            output_schema={"type": "object", "description": "schema condition " * 40000},
        )
    assert requests == []
    assert execution.physical_attempts == 0


def test_long_http_requires_new_profile_and_respects_fresh_owner_deadline() -> None:
    assert LLMHTTPExecution(lambda: 1000, lambda: None)._timeout(900) == 300
    assert LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.MVP_TEACHING_V1,
    )._timeout(900) == 300
    completion = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    assert completion._timeout(900) == 600
    assert completion._timeout(90) == 90
    completion.before_send = lambda: 40
    assert completion._timeout(600) == 40


def test_new_profile_silent_read_survives_renewed_watchdog_without_duplicate_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(http_scope, "_LEASE_PUMP_SECONDS", 0.01)

    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        assert request.extensions["timeout"]["read"] > 0.4
        await asyncio.sleep(0.08)
        return httpx.Response(200, content=_completed())

    requests, clients = _wire(monkeypatch, receive)
    renewals: list[bool] = []
    execution = LLMHTTPExecution(
        lambda: 2, lambda: renewals.append(True), execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    with use_http_execution(execution):
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "Return JSON"}], completion_stage="lesson_authoring", timeout_seconds=0.5,
        )
    assert len(renewals) >= 3
    assert len(requests) == execution.physical_attempts == 1
    assert all(client.is_closed for client in clients)
    _no_worker()


def test_new_profile_sent_unknown_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        raise httpx.ReadTimeout("sent request", request=request)

    requests, clients = _wire(monkeypatch, receive)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "Return JSON"}], completion_stage="lesson_authoring",
        )
    assert caught.value.outcome_unknown is True
    assert len(requests) == execution.physical_attempts == 1
    assert all(client.is_closed for client in clients)
    _no_worker()


def test_completion_safe_retry_keeps_one_stage_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        if number == 1:
            await asyncio.sleep(0.06)
            raise httpx.ConnectError("not sent", request=request)
        return httpx.Response(200, content=_completed())

    requests, clients = _wire(monkeypatch, receive, sent=False)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    monkeypatch.setattr(execution, "_retry_wait", lambda _delay: time.sleep(0.03))
    with use_http_execution(execution):
        result = OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "Return JSON"}],
            completion_stage="lesson_authoring", timeout_seconds=0.5,
        )
    assert result.content == {"ok": True}
    assert len(requests) == execution.physical_attempts == 2
    assert requests[1].extensions["timeout"]["read"] < requests[0].extensions["timeout"]["read"] - 0.05
    assert all(client.is_closed for client in clients)
    _no_worker()


def test_completion_safe_retry_wait_cannot_outlive_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    async def receive(request: httpx.Request, number: int) -> httpx.Response:
        raise httpx.ConnectError("not sent", request=request)

    requests, clients = _wire(monkeypatch, receive, sent=False)
    execution = LLMHTTPExecution(
        lambda: 1000, lambda: None, execution_profile=TutorExecutionProfile.COMPLETION_DRIVEN_V1,
    )
    started = time.monotonic()
    with use_http_execution(execution), pytest.raises(LLMHTTPExecutionError) as caught:
        OpenAICompatibleClient(_settings()).complete_json(
            [{"role": "user", "content": "Return JSON"}],
            completion_stage="lesson_authoring", timeout_seconds=0.1,
        )
    assert caught.value.reason == "before_send_rejected"
    assert caught.value.outcome_unknown is False
    assert len(requests) == execution.physical_attempts == 1
    assert time.monotonic() - started < 0.8
    assert all(client.is_closed for client in clients)
    _no_worker()
