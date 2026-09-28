"""Plan drafting raw-string and bounded serialized-transport regression."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorEffectProposal,
    TutorPlanDraftPayloadField,
    TutorPolicySnapshot,
    TutorRunSnapshot,
    payload_mapping_from_fields,
)
from app.services.learning.plan_drafting import decode_compact_modules, decode_compact_profile
from app.services.tutor.decision_protocol import TutorDecisionValidationError, parse_tutor_provider_items


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="plan-wire", conversation_id="plan-wire-conversation", user_id="plan-wire-user",
        origin="interactive", input_revision=1,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC), max_capability_calls=1, max_effects=1),
    )


def _candidate(capability_id: str, arguments: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "tutor_provider_items_v5",
        "message": {"type": "agent_message", "public_thinking_text": "Draft a course.",
                    "text": "I have prepared a draft.", "conversation_title": None},
        "action": {"type": "request_capability", "capability_id": capability_id, "arguments": arguments},
    }


def _valid_parts() -> tuple[str, str, str]:
    profile = {"language_id": "python", "goal_text": "Study strings with quotes: \\\" and newlines: \\n", "target_level": "beginner",
               "weekly_minutes": 180, "experience_level": "new", "teaching_preferences": [],
               "pace_summary": "Weekly practice", "title": "Python basics"}
    first = {"module_key": "fundamentals", "title": "Foundations", "description": "Quoted example: \\\"",
             "is_core": True, "is_skippable": False, "nodes": [{"knowledge_key": "python.variables",
             "title": "Variables", "description": "Names", "is_core": True, "prerequisite_keys": [],
             "required_capabilities": ["python"]}]}
    second = {"module_key": "functions", "title": "Functions", "nodes": [{"knowledge_key": "python.functions", "title": "Functions"}]}
    profile["pace_summary"] += "x" * (350 - len(json.dumps(profile, ensure_ascii=False, separators=(",", ":"))))
    first["nodes"][0]["description"] += "x" * (350 - len(json.dumps(first, ensure_ascii=False, separators=(",", ":"))))
    parts = tuple(json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in (profile, first, second))
    assert all(len(item) <= 360 for item in parts)
    LearningPlanDraftCapabilityInput(profile_json=parts[0], module_1=parts[1], module_2=parts[2])
    decode_compact_profile(parts[0])
    decode_compact_modules(parts[1:])
    return parts  # type: ignore[return-value]


def _arguments(parts: tuple[str, str, str]) -> list[dict[str, object]]:
    return [{"key": key, "value": value} for key, value in zip(("profile_json", "module_1", "module_2"), parts)]


def test_domain_valid_compact_json_strings_roundtrip_without_truncation() -> None:
    profile, first, second = _valid_parts()
    # Each is a valid advertised raw string, though JSON string transport is longer.
    assert any(len(json.dumps(item, ensure_ascii=False, separators=(",", ":"))) > 360 for item in (profile, first))
    result = parse_tutor_provider_items(_candidate("learning.plan.draft", _arguments((profile, first, second))), run=_run())
    fields = result.capability_requests[0].arguments
    decoded = payload_mapping_from_fields(fields)
    assert decoded == {"profile_json": profile, "module_1": first, "module_2": second}
    assert decoded is not None
    LearningPlanDraftCapabilityInput.model_validate(decoded)
    decode_compact_modules((str(decoded["module_1"]), str(decoded["module_2"])))
    assert json.loads(next(field.value for field in fields if field.key == "profile_json")) == profile
    assert decode_compact_profile(json.loads(next(field.value for field in fields if field.key == "profile_json"))).goal_text == decode_compact_profile(profile).goal_text


def test_raw_over_360_and_other_capabilities_remain_bounded() -> None:
    profile, first, second = _valid_parts()
    over = first[:-1] + " " * (361 - len(first)) + "}"  # valid JSON whitespace but raw length > 360
    assert len(over) == 361
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(_candidate("learning.plan.draft", _arguments((profile, over, second))), run=_run())
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(_candidate("grounding.retrieve", [{"key": "query_text", "value": "x" * 359}]), run=_run())
    # A different capability cannot borrow plan capacity by spoofing its field name.
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(_candidate("grounding.retrieve", [{"key": "profile_json", "value": "x" * 359}]), run=_run())
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(_candidate("learning.plan.draft", [{"key": "other", "value": "x" * 359}]), run=_run())


def test_plan_transport_does_not_coerce_object_or_allow_duplicate_keys() -> None:
    profile, first, second = _valid_parts()
    arguments = _arguments((profile, first, second))
    for malformed in ([{"key": "profile_json", "value": json.loads(profile)}, *arguments[1:]],
                      [arguments[0], arguments[0], *arguments[1:]]):
        with pytest.raises(TutorDecisionValidationError):
            parse_tutor_provider_items(_candidate("learning.plan.draft", malformed), run=_run())



def test_exact_raw_360_with_outer_escapes_preserves_full_plan_fields() -> None:
    profile, first, second = _valid_parts()
    data = json.loads(profile)
    data["pace_summary"] += "x" * 10
    exact = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    assert len(exact) == 360
    assert len(json.dumps(exact, ensure_ascii=False)) > 360
    result = parse_tutor_provider_items(_candidate("learning.plan.draft", _arguments((exact, first, second))), run=_run())
    assert payload_mapping_from_fields(result.capability_requests[0].arguments)["profile_json"] == exact
    assert decode_compact_profile(exact).pace_summary == data["pace_summary"]


def test_effect_transport_does_not_inherit_plan_draft_capacity() -> None:
    payload = _candidate("learning.plan.draft", [])
    payload["action"] = {"type": "propose_effect", "effect_type": "generic", "payload": [
        {"key": "profile_json", "value": "x" * 359},
    ]}
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(payload, run=_run())


def test_direct_transport_field_cannot_borrow_capacity_outside_exact_plan_request() -> None:
    field = TutorPlanDraftPayloadField(key="profile_json", value=json.dumps("x" * 360))
    TutorCapabilityRequest(request_id="plan-1", capability_id="learning.plan.draft", arguments=(field,))
    with pytest.raises(ValueError, match="restricted"):
        TutorCapabilityRequest(request_id="other-1", capability_id="grounding.retrieve", arguments=(field,))
    with pytest.raises(ValueError, match="restricted"):
        TutorCapabilityRequest(request_id="plan-2", capability_id="learning.plan.draft",
                               arguments=(TutorPlanDraftPayloadField(key="other", value=field.value),))
    with pytest.raises(ValueError, match="business bound"):
        TutorCapabilityRequest(request_id="plan-3", capability_id="learning.plan.draft",
                               arguments=(TutorPlanDraftPayloadField(key="profile_json", value=json.dumps("x" * 361)),))
    with pytest.raises(ValueError, match="JSON string"):
        TutorCapabilityRequest(request_id="plan-4", capability_id="learning.plan.draft",
                               arguments=(TutorPlanDraftPayloadField(key="profile_json", value="{}"),))
    with pytest.raises(ValueError, match="capability results"):
        TutorCapabilityResult(request_id="result-1", status=TutorCapabilityStatus.COMPLETED, safe_result=(field,))
    with pytest.raises(ValueError, match="effects"):
        TutorEffectProposal(effect_id="effect-1", effect_type="generic", expected_input_revision=0, payload=(field,))
