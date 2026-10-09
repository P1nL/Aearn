"""Three synthetic protocol-only shapes. No real generation, terminal, DB or IO."""
import json
from types import SimpleNamespace

from aearn_shared.execution import SandboxResultV1

import pytest

from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1, LearningItemSqlDatasetV2,
)
from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_task_families import initial_slot_allocations
from app.services.learning.item_supply.finite_targets.python_kc import PYTHON_KC_SCORER_VERSION, _spec, _truth
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.finite_targets.sqlite_predicates import sqlite_oracle, sqlite_private_fixture
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.finite_probe_plans import build_finite_candidate_probe_plan, native_python_tests, public_python_state_target
from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
from app.services.learning.item_supply.sandbox.python_goal_scorer import compile_goal_tests, source_goal_contract, source_scorer_version
from app.services.learning.item_supply.validation_adapter import validate_candidate
from app.services.learning.item_supply.validators.profiles import COMMON_PROBES, SQL_PROBES, required_probes
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION
from tests.learning.test_item_supply_finite_candidate_factory import materials_for
from tests.learning.test_item_supply_generation import make_request


def _context(target, slot=0):
    base, _ = make_request()
    scorer = {"python-state-update-v1": PYTHON_STATE_SCORER_VERSION,
              "sqlite-predicate-order-v1": GATE_PASS_POLICY_VERSION,
              "python-kc-binding-v1": PYTHON_KC_SCORER_VERSION}[target]
    materials = materials_for(target)
    allocation = initial_slot_allocations(target)[slot]
    spec = build_finite_candidate_spec(target_id=target, variant_id=allocation.variant_id,
        seed=1, item_key="finite-validation." + target, version="v1", materials=materials,
        runtime_profile_hash=None if target == "python-kc-binding-v1" else "a" * 64,
        scorer_version=scorer, assistance_policy_hash="b" * 64, policy_version="fixture-v1",
        difficulty_profile=base.blueprint.difficulty_profile, publication_policy=base.blueprint.publication_policy)
    return spec, materials


def _source(spec, private):
    return LearningItemSourceV1.model_validate_json(json.dumps(dict(
        blueprint=spec.blueprint.model_dump(mode="json"), public=spec.public_template.model_dump(mode="json"),
        private=dict(item_key=spec.public_template.item_key, version=spec.public_template.version,
                     kind=spec.public_template.kind.value, content=private))))


def test_python_state_native_expectations_semantic_controls_and_honest_boundary():
    spec, materials = _context("python-state-update-v1")
    goal = spec.python_goal
    assert public_python_state_target(spec.blueprint, spec.public_template) == goal
    reference = _programs(goal)[2]
    proposed = [{"id": name, "case_type": kind, "input_json": {},
        "expected_output_json": {"stdout": python_state_expected_stdout(goal)}, "order_index": index}
        for index, (name, kind) in enumerate((("visible-state", "visible"), ("hidden-state", "hidden")))]
    source = _source(spec, dict(type="code", standard_answer=reference, tests=proposed,
        score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0)))
    prepared = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    assert prepared.probe_plan == build_finite_candidate_probe_plan(source, spec=spec)
    assert prepared.source_hash == source.source_hash and prepared.specification_hash == spec.specification_hash
    assert "fixed_instance_candidate_boundary_pending" not in prepared.pending_boundaries
    assert prepared.probe_plan.boundary_cases_json is not None
    assert "real_sealed_candidate_execution_pending" in prepared.pending_boundaries
    assert prepared.static_facts is None and not prepared.publication_enabled
    compiled = native_python_tests(source)
    assert compile_goal_tests(source) == compiled
    assert source_goal_contract(source) == "python-state-update-v1"
    assert source_scorer_version(source) == PYTHON_STATE_SCORER_VERSION
    runner = SimpleNamespace(run=lambda **kwargs: pytest.fail("protocol test must not execute"))
    port = SandboxCandidateExecutionPort(runner, probe_plan=prepared.probe_plan, finite_spec=spec)
    tasks = port._tasks(source)
    boundary = next(task for task in tasks if task.name == "boundary")
    assert boundary.expected == "reject"
    assert boundary.wire.submission == next(w.submission for w in _programs(goal)[4] if w.name == "hardcoded_stdout")
    assert not any(task.name == "finite_state_boundary_control" for task in tasks)
    assert set(required_probes(source, finite_spec=spec)) - {"scorer_counterexample", "public_hidden_isolation"} == {task.name for task in tasks}
    assert port.resource_plan(source).execution_seconds == len(tasks) * 10
    negative = next(task for task in tasks if task.name == "wrong_rejected")
    ids = [case["id"] for case in json.loads(negative.wire.visible_test_bundle_json)
           + json.loads(negative.wire.hidden_test_bundle_json)]
    failed_terminal = SimpleNamespace(result=SandboxResultV1.model_validate({
        "status": "success", "diagnostic_code": "item_supply_facts_v1",
        "stdout": json.dumps({"cases": [{"id": identity, "status": "failed", "code": "python_terminal"}
                                      for identity in ids]})}))
    assert port._probe_status(source, negative, failed_terminal) == "pending"
    assert port._probe_status(source, boundary, failed_terminal) == "pending"
    # Direct scoring protocol only: no runner/seal or actual execution claim.
    semantic_negative = SimpleNamespace(result=SandboxResultV1.model_validate({
        "status": "success", "diagnostic_code": "item_supply_facts_v1",
        "stdout": json.dumps({"cases": [{"id": identity, "status": "success", "code": "python_terminal",
            "stdout": python_state_expected_stdout(goal), "goal_contract_id": "python-state-update-v1",
            "goal_contract_hash": goal.target_hash, "goal_status": "unsatisfied", "goal_satisfied": False}
            for identity in ids]})}))
    assert port._probe_status(source, boundary, semantic_negative) == "passed"
    assert validate_candidate(source, finite_spec=spec).safe_reasons == ("trusted_execution_unavailable",)
    changed_plan = prepared.probe_plan.model_copy(update={"server_fixture_hash": "0" * 64})
    with pytest.raises(ValueError, match="candidate_probe_finite_plan_stale"):
        SandboxCandidateExecutionPort(runner, probe_plan=changed_plan, finite_spec=spec)._tasks(source)
    assert all(t["input_json"]["goal_contract"] == goal.model_dump(mode="json") for t in compiled)
    assert source.private.content.tests[0].input_json == {}  # no source rewrite
    assert not any("hardcoded_stdout" in p.name for p in prepared.probe_plan.probes)
    wire = json.loads(prepared.probe_plan.probes[0].cases_json)
    assert all("expected_output_json" not in case for case in wire)
    data = source.model_dump(mode="json")
    data["private"]["content"]["tests"][0]["expected_output_json"]["stdout"] = "999\n"
    with pytest.raises(ValueError, match="expectation_mismatch"):
        prepare_finite_candidate_validation(LearningItemSourceV1.model_validate_json(json.dumps(data)), spec=spec, materials=materials)


def test_sql_predicate_validates_proposed_truth_and_uses_unchanged_candidate_on_independent_data():
    spec, materials = _context("sqlite-predicate-order-v1", slot=2)
    target = spec.sql_target
    public = spec.public_template.content
    hidden = LearningItemSqlDatasetV2.model_validate_json(json.dumps({"tables": [{"table": "entries", "rows": [
        [1, "hidden-one", 1, 0, 5], [2, "hidden-both", 1, 1, None], [3, "hidden-null", None, 1, 3]]}]}))
    datasets = (public.public_dataset, hidden)
    tests = [dict(id="proposed-" + str(i), case_type="visible" if i == 0 else "hidden",
        dataset=data.model_dump(mode="json"), expected_output=sqlite_oracle(target, data).model_dump(mode="json"),
        order_index=i) for i, data in enumerate(datasets)]
    query = sqlite_private_fixture(target).equivalent_queries[0]
    source = _source(spec, dict(type="sql_v2", standard_query=query, tests=tests,
        score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0)))
    prepared = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    plan = prepared.probe_plan
    assert plan.boundary == query and source.private.content.standard_query == query
    runner = SimpleNamespace(run=lambda **kwargs: pytest.fail("protocol test must not execute"))
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan, finite_spec=spec)
    tasks = port._tasks(source)
    boundary = next(task for task in tasks if task.name == "boundary")
    assert boundary.wire.submission == query and boundary.expected == "pass"
    assert json.loads(boundary.wire.hidden_test_bundle_json) == json.loads(plan.boundary_cases_json)
    assert port.resource_plan(source).execution_seconds == len(tasks) * 10
    assert "joins" not in {task.name for task in tasks}  # out of this single-table target
    needed = required_probes(source, finite_spec=spec)
    assert set(needed) - {"scorer_counterexample", "public_hidden_isolation"} == {task.name for task in tasks}
    assert required_probes(source) == COMMON_PROBES + SQL_PROBES  # no-spec legacy routing unchanged
    assert {"read_only", "single_statement", "bounded_setup"} <= set(needed)
    controls = {task.name: task for task in tasks}
    assert controls["read_only"].wire.submission == "DELETE FROM entries"
    assert ";" in controls["single_statement"].wire.submission
    setup_case = json.loads(controls["bounded_setup"].wire.visible_test_bundle_json)[0]
    assert len(setup_case["dataset"]["tables"][0]["rows"]) == 257
    negatives = [p for p in plan.probes if p.name.startswith("finite_sql_negative_")]
    assert len(negatives) == len(sqlite_private_fixture(target).counterexamples)
    assert all(len(json.loads(p.cases_json)) == len(sqlite_private_fixture(target).private_cases) for p in negatives)
    assert validate_candidate(source, finite_spec=spec).safe_reasons == ("trusted_execution_unavailable",)
    changed_spec = spec.model_copy(update={"target_definition_hash": "0" * 64})
    with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
        SandboxCandidateExecutionPort(runner, probe_plan=plan, finite_spec=changed_spec)._tasks(source)
    assert len(json.loads(plan.boundary_cases_json)) >= 2
    assert "generic_sql_probe_mapping_pending" not in prepared.pending_boundaries
    assert all("expected_output" not in case for case in json.loads(plan.boundary_cases_json))
    changed = source.model_dump(mode="json")
    changed["private"]["content"]["tests"][1]["expected_output"]["rows"] = []
    with pytest.raises(ValueError, match="finite_sql_private_expectation_mismatch"):
        prepare_finite_candidate_validation(LearningItemSourceV1.model_validate_json(json.dumps(changed)), spec=spec, materials=materials)


def test_static_kc_unique_semantic_answer_reordered_options_and_no_os_receipt():
    spec, materials = _context("python-kc-binding-v1")
    question, truth = _spec("trace", False), _truth("trace", False)
    accepted = {o.label: (o.rhs, o.saved, o.observation, o.reason) == truth for o in question.options}
    options = spec.public_template.content.options
    correct = next(o.option_id for o in options if accepted[o.label])
    source = _source(spec, dict(type="knowledge_check", accepted_answers=[correct],
        answer_explanation_markdown=question.explanation,
        tests=[dict(id="option." + o.option_id, case_type="visible" if i == 0 else "hidden",
            input_json={"answer": o.option_id}, expected_output_json={"accepted": accepted[o.label]},
            order_index=i, is_critical=True) for i, o in enumerate(options)],
        score_policy=dict(kind="static_exact", policy_version="static_exact_v1", threshold=1.0)))
    prepared = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    facts = prepared.static_facts
    assert facts.correct_option_id == correct
    assert sum(option.accepted for option in facts.options) == 1
    assert facts.validation.mode == "static" and facts.validation.state == "machine_verified"
    assert facts.execution_status == "not_run_static" and facts.validation.execution_evidence is None
    assert prepared.probe_plan is None and not facts.admission_eligible
    bad = source.model_dump(mode="json")
    bad["private"]["content"]["accepted_answers"] = [next(o.option_id for o in options if o.option_id != correct)]
    with pytest.raises(ValueError, match="finite_kc_answer_mismatch"):
        prepare_finite_candidate_validation(LearningItemSourceV1.model_validate_json(json.dumps(bad)), spec=spec, materials=materials)
