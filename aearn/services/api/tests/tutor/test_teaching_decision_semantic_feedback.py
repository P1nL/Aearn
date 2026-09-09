from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Callable

import pytest

from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunSnapshot
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
    TutorDecisionValidationError,
    TutorDecisionValidationIssue,
    build_tutor_replacement_message,
    parse_tutor_provider_items,
    validation_diagnostic_code,
)


_PRIVATE_MARKER = "PRIVATE_PROVIDER_PAYLOAD_MARKER"


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-semantic-feedback",
        conversation_id="conversation-semantic-feedback",
        user_id="user-semantic-feedback",
        origin="interactive",
        input_revision=0,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )


def _valid_teaching_payload() -> dict[str, object]:
    message = f"请完成这个小检查。{_PRIVATE_MARKER}"
    return {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message",
            "public_thinking_text": "先用一个有界问题检查当前理解。",
            "text": message,
            "conversation_title": None,
        },
        "action": {
            "type": "teaching_step",
            "action": "check_understanding",
            "objective_id": "knowledge:python.variables",
            "focus_id": "knowledge:python.variables",
            "source_handles": ["knowledge:python.variables"],
            "public_message": message,
            "focus_resolution": "stay",
            "pause_kind": "soft_pause",
            "escalation_hint": None,
            "teaching_moves": ["prediction", "error_detection"],
            "interaction": {
                "mode": "composer",
                "intent": "text_answer",
                "artifact_handle": None,
            },
        },
    }


def _public_message_mismatch(payload: dict[str, object]) -> None:
    action = payload["action"]
    assert isinstance(action, dict)
    action["public_message"] = "另一段不应回显的 provider 文本"


def _push_child_without_child_identity(payload: dict[str, object]) -> None:
    action = payload["action"]
    assert isinstance(action, dict)
    action["focus_resolution"] = "push_child"


def _completion_pause_without_summary(payload: dict[str, object]) -> None:
    action = payload["action"]
    assert isinstance(action, dict)
    action["pause_kind"] = "completion_pause"


def _artifact_mode_without_v3_interaction(payload: dict[str, object]) -> None:
    payload["schema_version"] = "tutor_provider_items_v4"
    action = payload["action"]
    assert isinstance(action, dict)
    action.pop("interaction")
    action["learner_response_mode"] = "artifact"


@pytest.mark.parametrize(
    ("mutate", "expected_issue", "expected_code", "guidance_fragment"),
    [
        (
            _public_message_mismatch,
            TutorDecisionValidationIssue(
                path="action.public_message",
                category="public_message_mismatch",
            ),
            "TUTOR_PROVIDER_DECISION_PUBLIC_MESSAGE_MISMATCH",
            "action.public_message exactly equal to message.text",
        ),
        (
            _push_child_without_child_identity,
            TutorDecisionValidationIssue(
                path="action.focus_id",
                category="child_focus_required",
            ),
            "TUTOR_PROVIDER_DECISION_CHILD_FOCUS_REQUIRED",
            "focus_id must be a distinct stable child identity",
        ),
        (
            _completion_pause_without_summary,
            TutorDecisionValidationIssue(
                path="action.pause_kind",
                category="completion_action_required",
            ),
            "TUTOR_PROVIDER_DECISION_COMPLETION_ACTION_REQUIRED",
            "completion_pause only with action=summarize_progress",
        ),
        (
            _artifact_mode_without_v3_interaction,
            TutorDecisionValidationIssue(
                path="action.interaction",
                category="interaction_mode_mismatch",
            ),
            "TUTOR_PROVIDER_DECISION_INTERACTION_MODE_MISMATCH",
            "artifact mode requires the v3 interaction object",
        ),
    ],
)
def test_authoritative_teaching_semantics_emit_precise_safe_repair_feedback(
    mutate: Callable[[dict[str, object]], None],
    expected_issue: TutorDecisionValidationIssue,
    expected_code: str,
    guidance_fragment: str,
) -> None:
    payload = deepcopy(_valid_teaching_payload())
    mutate(payload)

    with pytest.raises(TutorDecisionValidationError) as exc_info:
        parse_tutor_provider_items(payload, run=_run())

    assert exc_info.value.issues == (expected_issue,)
    assert validation_diagnostic_code(exc_info.value.issues) == expected_code

    feedback = build_tutor_replacement_message(
        exc_info.value.issues,
        teaching_policy="current server authority remains binding",
    )
    assert f"{expected_issue.path}:{expected_issue.category}" in feedback
    assert guidance_fragment in feedback
    assert _PRIVATE_MARKER not in feedback
    assert "另一段不应回显的 provider 文本" not in feedback
    assert _PRIVATE_MARKER not in repr(exc_info.value)


def test_interaction_schema_remains_strict_while_returning_allowlisted_guidance() -> (
    None
):
    payload = _valid_teaching_payload()
    action = payload["action"]
    assert isinstance(action, dict)
    action["learner_response_mode"] = "none"

    with pytest.raises(TutorDecisionValidationError) as exc_info:
        parse_tutor_provider_items(payload, run=_run())

    assert exc_info.value.issues == (
        TutorDecisionValidationIssue(
            path="action.interaction",
            category="interaction_mode_mismatch",
        ),
    )
    feedback = build_tutor_replacement_message(
        exc_info.value.issues,
        teaching_policy="current server authority remains binding",
    )
    assert "omit the legacy learner_response_mode field" in feedback
    assert _PRIVATE_MARKER not in feedback
