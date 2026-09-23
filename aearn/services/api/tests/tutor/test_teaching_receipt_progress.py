"""A new authoritative response is progress, not a repeated learner Continue."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput,
    TutorContextSource,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
)
from app.services.tutor.decision_gate import TeachingTutorDecisionGate
from app.services.tutor.decision_protocol import parse_tutor_provider_items
from tests.tutor.test_teaching_decision_semantic_feedback import _run, _valid_teaching_payload


@pytest.mark.parametrize(
    "verified,exact_text,reason,source_allowed,approved",
    [
        (True, False, "knowledge_check_evaluation", True, True),
        (False, False, "knowledge_check_evaluation", True, False),
        (True, True, "knowledge_check_evaluation", True, False),
        (True, False, "learner_continue", True, False),
        (True, False, "knowledge_check_evaluation", False, False),
    ],
)
def test_new_receipt_can_reuse_strategy_but_never_duplicate_text(
    verified, exact_text, reason, source_allowed, approved,
):
    run = _run()
    decision = parse_tutor_provider_items(_valid_teaching_payload(), run=run)
    step = decision.teaching_step
    assert step is not None
    source = "artifact:82e4c306-7aca-5ba4-96e3-32258464dd46"
    context = {
        "objective": {"objective_id": step.objective_id},
        "active_focus": {"focus_id": step.focus_id},
        "suspended_focuses": [],
        "session": {"mode": "guided", "progress_status": "in_progress"},
        "allowed_source_handles": [*step.source_handles, *([source] if source_allowed else [])],
        "candidate_focus_id": "other-focus",
        "stimulus": {
            "kind": "teaching_control", "control_key": "continue",
            "safe_payload": {"reason_code": reason, "source_handle": source},
        },
        "fresh_knowledge_check_evidence": verified,
        "recent_teaching_units": [{
            "schema_version": "teaching_action_receipt_v3",
            "action": step.action.value, "focus_id": step.focus_id,
            "teaching_moves": [move.value for move in step.teaching_moves],
            "learner_response_mode": "composer",
            "public_message_hash": hashlib.sha256(
                (step.public_message if exact_text else "Feedback about an older response.").encode()
            ).hexdigest(),
        }],
    }
    skill = SimpleNamespace(reference="exact-skill", manifest_hash="manifest", instruction_hash="instructions")
    gate = TeachingTutorDecisionGate(
        base=SimpleNamespace(validate=Mock(return_value=TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED))),
        catalog=SimpleNamespace(resolve_skill=Mock(return_value=skill)),
        selection_store=SimpleNamespace(get=Mock(return_value=skill)),
        teaching=SimpleNamespace(teaching_context=Mock(return_value=context)),
    )
    provider_context = TutorContextBuilder().build(
        TutorContextInput(
            run_id=run.run_id,
            conversation_id=run.conversation_id,
            input_revision=run.input_revision,
            current_input_required=False,
            teaching_session=(
                TutorContextSource(
                    source_id="teaching-session:session-1",
                    content={"allowed_source_handles": context["allowed_source_handles"]},
                ),
            ),
        ),
        token_budget=10_000,
    )
    result = gate.validate(run=run, decision=decision, context=provider_context)
    assert (result.status is TutorDecisionGateStatus.APPROVED) is approved
    if not approved:
        assert result.diagnostic_code == "teaching_unit_not_advanced"
