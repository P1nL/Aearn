"""Safe protocol repair metadata; no provider bodies or live dependencies."""
from __future__ import annotations

import json

import pytest

from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunSnapshot
from app.services.tutor.decision_protocol import (
    TutorDecisionValidationError,
    build_tutor_replacement_message,
    parse_tutor_provider_items,
)
from app.services.tutor.validation_diagnostics import validation_log_fields


def _run() -> TutorRunSnapshot:
    from datetime import datetime, timezone

    return TutorRunSnapshot(
        run_id="repair-test", conversation_id="repair-conversation",
        user_id="repair-user", origin="interactive", input_revision=1,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
            max_capability_calls=1, max_effects=1,
        ),
    )


def _candidate(value: object, *, key: str = "profile_json") -> dict[str, object]:
    return {
        "schema_version": "tutor_provider_items_v5",
        "message": {
            "type": "agent_message", "public_thinking_text": "Plan a course.",
            "text": "Here is a plan.", "conversation_title": None,
        },
        "action": {
            "type": "request_capability", "capability_id": "learning.plan.draft",
            "arguments": [{"key": key, "value": value}],
        },
    }


def _rejection(payload: dict[str, object]) -> TutorDecisionValidationError:
    with pytest.raises(TutorDecisionValidationError) as caught:
        parse_tutor_provider_items(payload, run=_run())
    return caught.value


def test_union_object_reports_observed_type_not_last_expected_branch() -> None:
    secret = "untrusted-PRIVATE-BODY"
    rejected = _rejection(_candidate({"secret": secret}))
    issues = [issue for issue in rejected.issues if issue.path.endswith("arguments.0.value")]
    assert len(issues) == 1
    issue = issues[0]
    fields = validation_log_fields(issue)
    assert fields["field_path"] == "action.arguments[0].value"
    assert fields["argument_key"] == "profile_json"
    assert fields["observed_type"] == "object"
    assert fields["expected_types"] == ("string", "integer", "number", "boolean", "array", "null")
    assert fields["serialized_length"] == len(json.dumps({"secret": secret}, ensure_ascii=False, separators=(",", ":")))
    prompt = build_tutor_replacement_message(rejected.issues, teaching_policy="", planning_capability_active=True)
    assert "observed JSON type object" in prompt
    assert "array of {key,value}" in prompt
    assert secret not in str(fields) + prompt
    # A wrong replacement remains subject to the same parser, not silent coercion.
    assert _rejection(_candidate({"secret": secret})).issues


def test_actual_safe_logger_keeps_shape_counts_without_rejected_values(caplog) -> None:
    import logging
    from app.core.safe_diagnostics import log_safe_event

    value = 'PRIVATE-VALUE-' * 40
    rejected = _rejection(_candidate(value, key='module_1'))
    fields = validation_log_fields(rejected.issues[0])
    log_safe_event(logging.getLogger(__name__), 'tutor_provider_validation_issue', **fields)
    event = json.loads(caplog.records[-1].getMessage())
    assert event['observed_type'] == 'string'
    assert event['argument_key'] == 'module_1'
    assert event['string_length'] == len(value)
    assert event['serialized_length'] == len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    assert value not in caplog.text
    log_safe_event(logging.getLogger(__name__), 'tutor_provider_validation_issue',
                   observed_type='PRIVATE-TYPE', argument_key='PRIVATE-KEY',
                   expected_types=['string', 'PRIVATE-TYPE'], string_length=10**50)
    event = json.loads(caplog.records[-1].getMessage())
    assert 'observed_type' not in event and 'argument_key' not in event and 'expected_types' not in event
    assert event['string_length'] == 1_000_000_000
    assert 'PRIVATE-KEY' not in caplog.text and 'PRIVATE-TYPE' not in caplog.text


def test_string_character_count_does_not_replace_serialized_wire_limit() -> None:
    too_many_escapes = '"' * 180  # 180 characters but 362 outer JSON characters.
    rejected = _rejection(_candidate(too_many_escapes, key="other"))
    issue = next(issue for issue in rejected.issues if issue.path.endswith("arguments.0.value"))
    fields = validation_log_fields(issue)
    assert fields["string_length"] == 180
    assert fields["serialized_length"] == 362
    assert "expected_rule" not in fields  # Generic fields keep the serialized-360 bound.
    assert "raw JSON" in build_tutor_replacement_message(rejected.issues, teaching_policy="", planning_capability_active=True)
    assert '"' * 15 not in str(fields)


def test_oversized_array_reports_count_and_rejects_repair() -> None:
    rejected = _rejection(_candidate(["a", "b", "c", "d", "e"], key="module_2"))
    issue = next(issue for issue in rejected.issues if issue.path.endswith("arguments.0.value"))
    fields = validation_log_fields(issue)
    assert fields["observed_type"] == "array"
    assert fields["list_count"] == 5
    assert fields["argument_key"] == "module_2"
    assert "list items 5" in build_tutor_replacement_message(
        rejected.issues, teaching_policy="", planning_capability_active=True,
    )
    assert _rejection(_candidate(["a", "b", "c", "d", "e"], key="module_2")).issues


def test_wire_string_limit_is_serialized_360_not_raw_360() -> None:
    accepted = "x" * 358
    result = parse_tutor_provider_items(_candidate(accepted), run=_run())
    assert result.capability_requests[0].arguments[0].value == json.dumps(accepted)
    rejected = _rejection(_candidate("x" * 359, key="other"))
    issue = next(issue for issue in rejected.issues if issue.path.endswith("arguments.0.value"))
    assert validation_log_fields(issue)["serialized_length"] == 361



def test_union_array_member_type_uses_true_item_type() -> None:
    rejected = _rejection(_candidate(["valid", 123], key="module_2"))
    issue = next(issue for issue in rejected.issues if issue.path.endswith("arguments.0.value.1"))
    fields = validation_log_fields(issue)
    assert fields["field_path"] == "action.arguments[0].value[1]"
    assert fields["observed_type"] == "integer"
    assert fields["expected_type"] == "string"
    assert _rejection(_candidate(["valid", 123], key="module_2")).issues


def test_missing_and_malicious_unknown_key_never_reveal_value() -> None:
    missing = _candidate("{}")
    assert isinstance(missing["message"], dict)
    missing["message"].pop("conversation_title")
    rejected = _rejection(missing)
    issue = next(issue for issue in rejected.issues if issue.path.endswith("conversation_title"))
    assert validation_log_fields(issue)["expected_rule"] == "This schema field is required."

    secret = "secret-body-DO-NOT-LOG"
    payload = _candidate("{}", key="module_1")
    assert isinstance(payload["message"], dict)
    payload["message"][secret] = "credential-data"
    rejected = _rejection(payload)
    unknown = next(issue for issue in rejected.issues if secret in issue.path)
    fields = validation_log_fields(unknown)
    assert str(fields["field_path"]).startswith("sha256:")
    prompt = build_tutor_replacement_message(rejected.issues, teaching_policy="", planning_capability_active=True)
    assert "unknown_field" in prompt
    assert secret not in str(fields) + prompt
    assert "credential-data" not in str(fields) + prompt


def test_valid_wire_string_is_not_coerced_or_truncated() -> None:
    value = json.dumps({"language_id": "python", "goal_text": "learn syntax"}, separators=(",", ":"))
    result = parse_tutor_provider_items(_candidate(value), run=_run())
    assert result.capability_requests[0].arguments[0].value == json.dumps(value, ensure_ascii=False)
    assert "Valid teaching-step example" not in build_tutor_replacement_message(
        (), teaching_policy="", planning_capability_active=True,
    )
