from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.learning.artifacts.contracts import (
    TutorArtifactCodeRangeResponse,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactOrderingResponse,
    TutorArtifactTextResponse,
)
from app.services.learning.artifacts.knowledge_checks import (
    KnowledgeCheckDisclosureLevel,
    _score,
    disclosure_decision,
)
from app.services.learning.item_bank.contracts import (
    LearningItemDifficultyProfileV1,
    LearningItemKnowledgeCheckContentV1,
    LearningItemKnowledgeCheckPrivateV1,
)


def test_difficulty_profile_is_deterministic_and_uses_base_band() -> None:
    profile = LearningItemDifficultyProfileV1(
        base="D3",
        reasoning_depth=3,
        concept_count=3,
        context_novelty=3,
        transfer_distance=3,
        response_complexity=3,
        scaffolding=3,
    )
    assert profile.computed_base.value == "D3"


def test_knowledge_check_contract_rejects_extra_fields_and_invalid_hint_order() -> None:
    with pytest.raises(ValidationError):
        TutorArtifactKnowledgeCheckPresentationV1.model_validate(
            {
                "response_kind": "single_select",
                "prompt_markdown": "Choose.",
                "options": [{"value": "a", "label": "A"}],
                "hints": [{"level": 2, "label": "概念", "markdown": "Think."}],
                "future_field": True,
            }
        )


def test_disclosure_policy_distinguishes_first_failure_second_failure_and_direct_answer() -> None:
    first = disclosure_decision(first_failure="hint_then_remediate", prior_incorrect_count=0)
    assert first.allowed_disclosure_level is KnowledgeCheckDisclosureLevel.HINT_ONLY
    assert first.independent_mastery_eligible is False

    second = disclosure_decision(first_failure="hint_then_remediate", prior_incorrect_count=1)
    assert second.allowed_disclosure_level is KnowledgeCheckDisclosureLevel.WORKED_ANSWER
    assert second.independent_mastery_eligible is False

    direct = disclosure_decision(
        first_failure="hint_then_remediate",
        prior_incorrect_count=0,
        direct_answer_requested=True,
    )
    assert direct.assistance_kind == "direct_answer"
    assert direct.independent_mastery_eligible is False


def test_answered_presentation_is_locked_and_result_fields_are_atomic() -> None:
    answered = TutorArtifactKnowledgeCheckPresentationV1(
        response_kind="short_text",
        prompt_markdown="Name the value.",
        answer_locked=True,
        outcome="incorrect",
        assistance_kind="hinted",
        evaluation_markdown="Review the binding relationship.",
        response_receipt_id="receipt-1",
    )
    assert answered.answer_locked is True
    with pytest.raises(ValidationError):
        TutorArtifactKnowledgeCheckPresentationV1.model_validate(
            {**answered.model_dump(mode="json"), "response_receipt_id": None}
        )


def _private(*accepted_answers: str) -> LearningItemKnowledgeCheckPrivateV1:
    return LearningItemKnowledgeCheckPrivateV1.model_validate(
        {
            "accepted_answers": list(accepted_answers),
            "answer_explanation_markdown": "Authoritative explanation.",
            "tests": [
                {
                    "id": "visible.accepted",
                    "case_type": "visible",
                    "input_json": {"answer": accepted_answers[0]},
                    "expected_output_json": {"accepted": True},
                    "weight": 1,
                    "is_critical": True,
                    "order_index": 0,
                }
                ,{
                    "id": "hidden.rejected",
                    "case_type": "hidden",
                    "input_json": {"answer": "not-accepted"},
                    "expected_output_json": {"accepted": False},
                    "weight": 1,
                    "is_critical": False,
                    "order_index": 1,
                }
            ],
            "score_policy": {"kind": "static_exact", "policy_version": "static_exact_v1", "threshold": 1},
        }
    )


def test_prediction_ordering_and_code_range_are_strictly_scored() -> None:
    prediction = LearningItemKnowledgeCheckContentV1(
        response_kind="prediction", prompt_markdown="Predict the value."
    )
    assert _score(prediction, _private("3"), TutorArtifactTextResponse(kind="prediction", text="3")) is True

    ordering = LearningItemKnowledgeCheckContentV1.model_validate(
        {
            "response_kind": "ordering",
            "prompt_markdown": "Order the steps.",
            "options": [{"option_id": "parse", "label": "Parse"}, {"option_id": "run", "label": "Run"}],
        }
    )
    assert _score(ordering, _private("parse", "run"), TutorArtifactOrderingResponse(values=("parse", "run"))) is True
    assert _score(ordering, _private("parse", "run"), TutorArtifactOrderingResponse(values=("run", "parse"))) is False

    code_range = LearningItemKnowledgeCheckContentV1(
        response_kind="code_range", prompt_markdown="Select the faulty range."
    )
    assert _score(
        code_range,
        _private("2:4:logic"),
        TutorArtifactCodeRangeResponse(start_line=2, end_line=4, category="logic", note="The branch is inverted."),
    ) is True
    with pytest.raises(ValidationError):
        TutorArtifactCodeRangeResponse(start_line=4, end_line=2, category="logic", note="Invalid range")


def test_ordering_presentation_requires_every_option_and_code_range_rejects_options() -> None:
    with pytest.raises(ValidationError):
        TutorArtifactKnowledgeCheckPresentationV1(
            response_kind="ordering",
            prompt_markdown="Order.",
            options=({"value": "a", "label": "A"}, {"value": "b", "label": "B"}),
            minimum_selections=1,
            maximum_selections=2,
        )
    with pytest.raises(ValidationError):
        LearningItemKnowledgeCheckContentV1.model_validate(
            {
                "response_kind": "code_range",
                "prompt_markdown": "Range.",
                "options": [{"option_id": "a", "label": "A"}, {"option_id": "b", "label": "B"}],
            }
        )
