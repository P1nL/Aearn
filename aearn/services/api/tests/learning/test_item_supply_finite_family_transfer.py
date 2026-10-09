"""One deterministic three-target PLAN test; no PG/provider/OS acceptance or seals."""
import ast
import json

import pytest

from app.services.learning.item_bank.contracts import LearningItemDifficultyProfileV1, LearningItemPublicationPolicyV1
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.finite_candidate_factory import (
    FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2, build_finite_candidate_spec,
)
from app.services.learning.item_supply.finite_family_transfer import build_finite_family_transfer_plan, finite_family_transfer_work
from app.services.learning.item_supply.finite_task_families import initial_slot_allocations
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION
from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION
from tests.learning.test_item_supply_finite_candidate_factory import materials_for


def test_closed_three_target_transfer_plans_are_deterministic_and_not_evidence():
    difficulty = LearningItemDifficultyProfileV1(base="D1", reasoning_depth=1, concept_count=1,
        context_novelty=1, transfer_distance=1, response_complexity=1, scaffolding=5)
    publication = LearningItemPublicationPolicyV1(risk_tier="low", required_review_roles=REQUIRED_REVIEW_ROLES,
                                                  human_approval_required=False)
    for target, scorer, planned_count in (("python-state-update-v1", PYTHON_STATE_SCORER_VERSION, 12),
            ("sqlite-predicate-order-v1", GATE_PASS_POLICY_VERSION, 7),
            ("python-kc-binding-v1", PYTHON_KC_SCORER_VERSION, 0)):
        # These synthetic materials are only declaration coordinates, never C authority.
        materials = materials_for(target)
        args = dict(target_id=target, seed=1 if target == "python-kc-binding-v1" else 0,
            version="v1", materials=materials, runtime_profile_hash=None if target == "python-kc-binding-v1" else "a" * 64,
            scorer_version=scorer, assistance_policy_hash="b" * 64, policy_version="fixture-v1",
            difficulty_profile=difficulty, publication_policy=publication,
            public_spec_version=PYTHON_FACTORY_VERSION_V2 if target == "python-state-update-v1" else FACTORY_VERSION)
        specs = tuple(build_finite_candidate_spec(**args, variant_id=a.variant_id,
            item_key="transfer-plan." + a.variant_id.replace(":", ".")) for a in initial_slot_allocations(target)[:4])
        plan = build_finite_family_transfer_plan(target, specs=specs, materials=materials)
        assert plan == build_finite_family_transfer_plan(target, specs=specs, materials=materials)
        by_family = {s.allocation.family_id: s for s in specs}
        directions = tuple(d for pair in plan.pairs for d in pair.directions)
        assert len(plan.pairs) == 6 and len(directions) == 12
        assert len({(d.source_family_id, d.target_family_id) for d in directions}) == 12
        assert sum(d.construction == "planned" for d in directions) == planned_count
        assert plan.authority == "not_family_pair_evidence" and not plan.publication_enabled
        for direction in directions:
            for reference in (direction.source_reference, direction.target_reference):
                spec = by_family[reference.family_id]
                assert reference.specification_hash == spec.specification_hash
                assert reference.blueprint_version == spec.blueprint.version
                assert reference.public_task_hash == spec.public_template.public_hash
                assert json.loads(reference.public_task_json) == spec.public_template.model_dump(mode="json")
                assert reference.purpose == "reference_success" and reference.status == "not_performed"
            check = direction.transfer_check
            if check is None:
                assert direction.construction == "unresolved" and direction.reasons
            else:
                assert check.request.submission == direction.adapted_submission
                assert check.public_task_hash == direction.target_reference.public_task_hash
                assert check.required_terminal == "successful_supported_semantics"
                expected = json.loads(check.expected_json)
                assert expected["required_scorer_result"] == "reject"
                delta = json.loads(direction.semantic_difference_json)
                if target == "python-state-update-v1":
                    assert delta["different_state_components"]  # Not print arity/AST/hash inequality alone.
                    source_tree = ast.parse(direction.source_reference.submission)
                    adapted_tree = ast.parse(direction.adapted_submission)
                    assert [type(n) for n in ast.walk(source_tree)] == [type(n) for n in ast.walk(adapted_tree)]
                    assert expected["predicted_terminal_cases"][0]["goal_status"] == "unsatisfied"
                else:
                    assert delta["predicted"] != delta["target_expected"]
                    assert "JOIN" not in check.submission and "GROUP BY" not in check.submission
        work = finite_family_transfer_work(plan, materials=materials)
        assert work.plan_inputs_hash == plan.inputs_hash
        assert work.resources.execution_seconds == 10 * sum(c.request is not None for c in work.checks)
        assert all(c.status == "not_performed" for c in work.checks)
        if target == "python-kc-binding-v1":
            assert len(work.checks) == 4 and work.resources.execution_seconds == 0
            for check in work.checks:
                expected = json.loads(check.expected_json)
                proposition = json.loads(check.submission)
                assert "option_id" not in proposition and len(expected["complete_options"]) == 4
                assert sum(all(option[k] == proposition[k] for k in proposition) for option in expected["complete_options"]) == 1
                assert check.request is None and check.required_terminal == "not_run_static"
        elif target == "python-state-update-v1":
            # Explicit version boundary only; no old hash/goal/scorer is altered.
            legacy = build_finite_candidate_spec(**{**args, "public_spec_version": FACTORY_VERSION},
                variant_id=specs[0].allocation.variant_id, item_key=specs[0].public_template.item_key)
            assert legacy.public_template.public_hash != specs[0].public_template.public_hash
            with pytest.raises(ValueError, match="public_spec_version_mismatch"):
                build_finite_family_transfer_plan(target, specs=(legacy, *specs[1:]), materials=materials)
        payload = plan.model_dump(mode="json")
        assert "relation" not in payload and "seal" not in payload
        assert all("relation" not in pair and "witnesses" not in pair for pair in payload["pairs"])
