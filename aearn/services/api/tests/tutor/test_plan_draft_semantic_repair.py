"""Offline primary/repair parity through the actual plan wire parser."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from app.agents.harness.capabilities import (
    CapabilitySchemaExporter,
    LEARNING_PLAN_DRAFT_DESCRIPTOR,
    LearningPlanDraftCapabilityInput,
)
from app.agents.harness.context_budget import build_tutor_context_budget_policy
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSource,
    TutorProviderAttemptOutcome,
    payload_mapping_from_fields,
)
from app.core.config import Settings
from app.services.learning.plan_drafting import decode_compact_modules, decode_compact_profile
from app.services.llm.llm_client import LLMJsonResponse
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from tests.tutor.test_tutor_plan_wire_contract import _arguments, _candidate, _run, _valid_parts


class _Client:
    model = "offline-plan-repair"

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.messages: list[tuple[Mapping[str, str], ...]] = []

    def complete_json(self, messages: Sequence[Mapping[str, str]], **_kwargs: Any) -> LLMJsonResponse:
        self.messages.append(tuple(messages))
        return LLMJsonResponse(content=self.responses.pop(0), model=self.model)


def _context():
    return TutorContextBuilder().build(
        TutorContextInput(
            run_id="plan-wire", conversation_id="plan-wire-conversation", input_revision=1,
            current_input_required=True,
            current_input=TutorContextSource("request", "Revise the plan using current material facts."),
            capability_schemas=(TutorContextSource(
                "catalog:capability:learning.plan.draft@1.0.0",
                CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR),
            ),),
        ),
        token_budget=16_384,
    )


def _repair_run():
    settings = Settings(llm_type="disabled", tutor_default_context_window_tokens=32_768)
    return replace(_run(), policy=replace(_run().policy,
        context_budget_policy=build_tutor_context_budget_policy(settings)))


def test_semantic_denial_then_full_plan_repair_preserves_escaped_wire_and_review() -> None:
    profile, first, second = _valid_parts()
    parts = (profile, first, second)
    assert len(profile) <= 360 < len(json.dumps(profile, ensure_ascii=False))
    initial = _candidate("learning.plan.draft", _arguments(parts))
    repaired = _candidate("learning.plan.draft", _arguments(parts))
    initial["message"]["text"] = "All materials are ready."  # type: ignore[index]
    repaired["message"]["text"] = "The draft preserves the current material gaps."  # type: ignore[index]
    client = _Client([initial, repaired])
    reviewed = []

    def review(run, context, decision, attempt):
        reviewed.append((run, context, decision, attempt))
        return "material_readiness_overclaim" if attempt == 1 else None

    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client, decision_validator=review,
    ).decide(run=_repair_run(), context=_context())

    assert result.decision is not None
    assert [entry[3] for entry in reviewed] == [1, 2]
    assert [item.outcome for item in result.attempts] == [
        TutorProviderAttemptOutcome.REPAIRABLE_REJECTED, TutorProviderAttemptOutcome.ACCEPTED,
    ]
    decoded = payload_mapping_from_fields(result.decision.capability_requests[0].arguments)
    assert decoded == dict(zip(("profile_json", "module_1", "module_2"), parts))
    assert decoded is not None
    typed = LearningPlanDraftCapabilityInput.model_validate(decoded)
    assert decode_compact_profile(typed.profile_json) == decode_compact_profile(profile)
    assert decode_compact_modules(typed.module_values()) == decode_compact_modules(parts[1:])
    assert client.messages[0][1] == client.messages[1][1]
    assert "material_readiness_overclaim" in client.messages[1][-1]["content"]
    assert "360-character limit" in client.messages[1][-1]["content"]
    assert all(text in client.messages[1][-1]["content"] for text in (
        "Correct only the identified semantic overclaim", "preserve the other valid compact plan fields",
        "top-level message.text", "not in profile_json or module_N", "selected capability's raw-character bound",
        "do not truncate or remove goals or prerequisites", "replacement still requires semantic review",
    ))


def test_semantic_repair_raw_602_is_rejected_before_second_review() -> None:
    profile, first, second = _valid_parts()
    initial = _candidate("learning.plan.draft", _arguments((profile, first, second)))
    expanded = json.loads(profile)
    for key, maximum in (("goal_text", 200), ("pace_summary", 240), ("title", 240)):
        remaining = 602 - len(json.dumps(expanded, ensure_ascii=False, separators=(",", ":")))
        expanded[key] += "x" * min(remaining, maximum - len(expanded[key]))
    over = json.dumps(expanded, ensure_ascii=False, separators=(",", ":"))
    assert len(over) == 602
    decode_compact_profile(over)  # Domain fields are valid; the advertised wire bound is not.
    repair = _candidate("learning.plan.draft", _arguments((over, first, second)))
    client = _Client([initial, repair])
    reviewed = []

    def review(run, context, decision, attempt):
        reviewed.append(attempt)
        return "material_readiness_overclaim"

    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="disabled"), client=client, decision_validator=review,
    ).decide(run=_repair_run(), context=_context())

    assert result.decision is None
    assert result.safe_code == "TUTOR_PROVIDER_DECISION_INVALID_VALUE"
    assert reviewed == [1]
    assert len(client.messages) == 2
