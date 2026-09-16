"""Response-mode errors must be repairable without weakening final teaching admission."""
from copy import deepcopy

import pytest

from app.core.config import Settings
from app.services.learning.teaching_contracts import (
    TeachingAction, TeachingLearnerResponseMode, TeachingMove,
    teaching_response_mode_is_valid,
)
from app.services.tutor.decision_protocol import (
    TutorDecisionValidationError, build_tutor_replacement_message,
    parse_tutor_provider_items, validation_diagnostic_code,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from tests.tutor.test_teaching_decision_semantic_feedback import _run, _valid_teaching_payload
from tests.tutor.test_tutor_provider_gateway import SequencedJsonClient, _context

INVALID_UNITS = [
    ("explain_concept", "composer", ["prediction", "targeted_explanation"]),
    ("check_understanding", "composer", ["targeted_explanation", "worked_example"]),
    ("check_understanding", "none", ["prediction", "error_detection"]),
    ("wait_for_input", "none", ["prediction", "error_detection"]),
]


def _payload(action, mode, moves):
    payload = deepcopy(_valid_teaching_payload())
    payload["message"]["text"] = "Predict the new value."
    payload["action"]["public_message"] = "Predict the new value."
    payload["action"].update(action=action, teaching_moves=moves)
    payload["action"]["interaction"].update(
        mode=mode, intent="text_answer" if mode == "composer" else "none",
    )
    return payload


@pytest.mark.parametrize(("action", "mode", "moves"), INVALID_UNITS)
def test_mode_failure_is_precise_and_contains_no_rejected_provider_text(action, mode, moves):
    with pytest.raises(TutorDecisionValidationError) as caught:
        parse_tutor_provider_items(_payload(action, mode, moves), run=_run())
    issue, = caught.value.issues
    assert (issue.path, issue.category) == ("action.interaction.mode", "response_mode_invalid")
    assert validation_diagnostic_code(caught.value.issues) == "TUTOR_PROVIDER_DECISION_RESPONSE_MODE_INVALID"
    feedback = build_tutor_replacement_message(caught.value.issues, teaching_policy="authority unchanged")
    assert "composer requires action=check_understanding or wait_for_input" in feedback
    assert "none cannot use either response action" in feedback
    assert "Predict the new value." not in feedback


@pytest.mark.parametrize(("action", "mode", "moves"), INVALID_UNITS)
def test_mode_failure_uses_existing_one_same_model_repair(action, mode, moves):
    client = SequencedJsonClient([
        _payload(action, mode, moves),
        _payload("check_understanding", "composer", ["prediction", "learner_feedback"]),
    ])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="test-key"), client=client,
    ).decide(run=_run(), context=_context())
    assert result.decision is not None
    assert client.calls == 2
    assert result.attempts[0].diagnostic_code == "TUTOR_PROVIDER_DECISION_RESPONSE_MODE_INVALID"
    assert "action.interaction.mode:response_mode_invalid" in str(client.messages[1])


def test_repeated_mode_failure_stops_after_existing_repair_limit():
    bad = _payload(*INVALID_UNITS[0])
    client = SequencedJsonClient([bad, deepcopy(bad)])
    result = PrimaryTutorProviderGateway(
        settings=Settings(llm_type="openai", openai_api_key="test-key"), client=client,
    ).decide(run=_run(), context=_context())
    assert result.decision is None
    assert client.calls == 2
    assert len(result.attempts) == 2


@pytest.mark.parametrize("action", list(TeachingAction))
@pytest.mark.parametrize("mode", list(TeachingLearnerResponseMode))
@pytest.mark.parametrize("moves", [(), (TeachingMove.TARGETED_EXPLANATION,), (TeachingMove.PREDICTION,)])
def test_shared_policy_preserves_existing_admission_matrix(action, mode, moves):
    response_action = action.value in {"check_understanding", "wait_for_input"}
    if mode.value == "composer":
        expected = response_action and bool({"prediction", "error_detection", "misconception_contrast", "micro_transfer"}.intersection(m.value for m in moves))
    else:
        expected = mode.value != "none" or not response_action
    assert teaching_response_mode_is_valid(action=action, mode=mode, teaching_moves=moves) is expected
