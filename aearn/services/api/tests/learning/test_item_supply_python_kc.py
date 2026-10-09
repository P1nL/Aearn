"""Static data tests only; no source, model, Docker or publication authority."""
import json

import pytest

from app.services.learning.item_supply.finite_targets.python_kc import (
    PYTHON_KC_SCORER_VERSION, PythonKcFixtureV1, python_kc_exercise_material,
    python_kc_fixture, python_kc_public_content, validate_python_kc_fixture,
)
from app.services.learning.practice.contracts import ExerciseValidationStatus


def test_four_distinct_structures_have_one_data_derived_answer_and_clause_facts():
    expected = {"trace": "c", "diagnose": "b", "repair": "b", "counterexample": "c"}
    for kind, answer in expected.items():
        fixture = python_kc_fixture(kind)
        result = validate_python_kc_fixture(fixture)
        assert result.correct_option_id == answer and result.admission_eligible is False
        assert fixture.execution_status == "not_run_static" and fixture.family_independence_status == "pending"
        assert fixture.family_id == "python-kc-binding-v1:" + kind
        assert sum(all(f.clause_passes) for f in fixture.option_facts) == 1
        assert {f.option_id for f in fixture.option_facts if f.failure_reason} == set("abcd") - {answer}
    assert python_kc_fixture("trace").option_facts[2].observation == (9, 6, 7)
    assert python_kc_fixture("repair").option_facts[1].observation == (3, 10, 8, 20)
    assert PYTHON_KC_SCORER_VERSION.startswith("kc-binding-v1.")


def test_public_projection_omits_private_truth_and_material_cannot_claim_ready():
    public = python_kc_public_content("trace").model_dump(mode="json")
    assert set(public) == {"type", "response_kind", "prompt_markdown", "options"}
    text = json.dumps(public)
    for private_key in ("accepted_answers", "clause_passes", "failure_reason", "answer_explanation_markdown"):
        assert private_key not in text
    material = python_kc_exercise_material("trace")
    assert material.exercise.validation_status is ExerciseValidationStatus.REJECTED
    assert material.exercise.runtime_profile_id is None and material.exercise.execution_required is False
    assert material.runner_payload == {} and material.standard_submission == "c"


def test_exact_text_truth_binding_rejects_tampering_and_remediation_is_not_transfer():
    original = python_kc_fixture("diagnose")
    guided = python_kc_fixture("diagnose", guided=True)
    assert original.fixture_hash != guided.fixture_hash and original.family_id == guided.family_id
    assert guided.purpose == "remediation" and original.purpose == "knowledge_check"
    assert validate_python_kc_fixture(guided).correct_option_id == "b"
    for kind in ("trace", "repair", "counterexample"):
        with pytest.raises(ValueError, match="guided_diagnose_only"):
            python_kc_fixture(kind, guided=True)
    payload = original.model_dump(mode="json")
    payload["public_content"]["options"][1]["label"] = "An unbound replacement answer"
    with pytest.raises(ValueError, match="registered_fixture_mismatch"):
        validate_python_kc_fixture(PythonKcFixtureV1.model_validate_json(json.dumps(payload)))
    with pytest.raises(ValueError):
        validate_python_kc_fixture(original.model_copy(update={"ready": True}))
