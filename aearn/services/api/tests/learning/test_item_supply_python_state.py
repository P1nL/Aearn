"""Seven focused tests across API/executor files; no candidate execution or IO."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from app.services.learning.item_supply.finite_targets.python_state import (
    PYTHON_STATE_GOAL_ID,
    PYTHON_STATE_GRAMMAR_SHA256,
    compile_python_state_tests,
    parse_python_state_target,
    python_state_expected_stdout,
    python_state_fixtures,
)
from app.services.learning.item_supply.sandbox.python_state_scorer import (
    PYTHON_STATE_SCORER_VERSION,
    compile_python_state_test_bundle,
    score_python_state_case,
)

HARNESS = Path(__file__).resolve().parents[4] / "infra/executor/harnesses/item_supply/python_state_goal.py"


def _goal_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("python_state_pure_api_test", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # Trusted rule module only, NEVER a candidate.
    return module


def test_four_fixtures_reference_equivalent_boundary_and_semantic_controls() -> None:
    goal = _goal_module()
    fixtures = python_state_fixtures()
    assert tuple(f.target.task_kind for f in fixtures) == ("accumulate", "refresh", "swap", "transfer")
    for fixture in fixtures:
        assert fixture.family_id == f"{PYTHON_STATE_GOAL_ID}:{fixture.target.task_kind}"
        target = fixture.target.model_dump(mode="json")
        test = compile_python_state_tests(fixture.target)[0]
        # These are synthetic pure facts, not live receipts or family proofs.
        terminal = {"id": test["id"], "status": "success", "code": "python_terminal",
                    "stdout": python_state_expected_stdout(fixture.target)}
        for source in (fixture.reference, fixture.equivalent, "# comment\n" + fixture.equivalent + "  # end\n"):
            fact = goal.inspect_python_state_goal(source, target)
            assert fact["goal_status"] == "satisfied"
            assert fact["goal_contract_hash"] == fixture.target.target_hash
            assert score_python_state_case(test, {**terminal, **fact}) is True
        assert goal.inspect_python_state_goal(fixture.starter_code, target)["goal_satisfied"] is False
        for wrong in fixture.wrong:
            fact = goal.inspect_python_state_goal(wrong.submission, target)
            assert fact["goal_status"] == "unsatisfied", wrong.name
            assert score_python_state_case(test, {**terminal, "stdout": wrong.expected_stdout, **fact}) is False
        boundary = fixture.boundary_target.model_dump(mode="json")
        for source in (fixture.boundary_reference, fixture.boundary_equivalent):
            assert goal.inspect_python_state_goal(source, boundary)["goal_satisfied"] is True
        assert fixture.boundary_expected_stdout == python_state_expected_stdout(fixture.boundary_target)


def test_wire_is_public_only_strict_and_one_exact_current_task() -> None:
    goal = _goal_module()
    fixture = python_state_fixtures()[0]
    tests = compile_python_state_tests(fixture.target)
    case = compile_python_state_test_bundle(tests)[0]
    assert set(case) == {"id", "case_type", "goal_contract"}
    assert set(case["goal_contract"]) == {"goal_contract_id", "task_kind", "variables", "values"}
    assert "expected_output_json" not in json.dumps(case)
    assert fixture.reference not in json.dumps(case)
    assert goal.normalize_python_state_contract(case["goal_contract"]) == case["goal_contract"]
    for changed in (
        {**case["goal_contract"], "hidden_answers": []},
        {**case["goal_contract"], "values": {**fixture.target.values, "initial": True}},
        {**case["goal_contract"], "variables": {**fixture.target.variables, "total": "print"}},
        {**case["goal_contract"], "variables": {**fixture.target.variables, "total": "increase"}},
        {**case["goal_contract"], "task_kind": "arbitrary"},
    ):
        with pytest.raises(ValueError):
            parse_python_state_target(changed)
        with pytest.raises(ValueError):
            goal.normalize_python_state_contract(changed)
    with pytest.raises(ValueError, match="expectation_mismatch"):
        compile_python_state_test_bundle(({**tests[0], "expected_output_json": {"stdout": "wrong"}},))
    second = compile_python_state_tests(python_state_fixtures()[1].target)[0]
    with pytest.raises(ValueError, match="mixed_public_tasks"):
        compile_python_state_test_bundle((tests[0], {**second, "id": "second"}))


def test_scorer_requires_successful_exact_strict_facts_and_stdout() -> None:
    fixture = python_state_fixtures()[0]
    test = compile_python_state_tests(fixture.target)[0]
    facts = _goal_module().inspect_python_state_goal(fixture.reference, fixture.target.model_dump(mode="json"))
    fact = {"id": test["id"], "status": "success", "code": "python_terminal", "stdout": "11\n", **facts}
    assert score_python_state_case(test, fact) is True
    assert score_python_state_case(test, {**fact, "stdout": "11 \n"}) is False
    for change in (
        {"status": "runtime_error"}, {"status": "timeout"}, {"code": "infrastructure"},
        {"goal_contract_id": "python-assignment-sum-print-v1"}, {"goal_contract_hash": "0" * 64},
        {"goal_satisfied": 1}, {"goal_satisfied": False}, {"id": "another-case"},
        {"goal_status": "unsupported", "goal_satisfied": None}, {"stdout": None},
    ):
        assert score_python_state_case(test, {**fact, **change}) is None
    assert score_python_state_case(test, {**fact, "goal_status": "unsatisfied", "goal_satisfied": False}) is False


def test_shared_bundle_and_score_router_preserves_exact_new_goal_boundary() -> None:
    from app.services.learning.item_supply.sandbox.python_goal_scorer import (
        compile_python_test_bundle, score_python_case,
    )

    fixture = python_state_fixtures()[0]
    tests = compile_python_state_tests(fixture.target)
    assert compile_python_test_bundle(tests) == compile_python_state_test_bundle(tests)
    facts = _goal_module().inspect_python_state_goal(fixture.reference, fixture.target.model_dump(mode="json"))
    terminal = {"id": tests[0]["id"], "status": "success", "code": "python_terminal", "stdout": "11\n", **facts}
    assert score_python_case(tests[0], terminal) is True
    assert score_python_case(tests[0], {**terminal, "goal_satisfied": False, "goal_status": "unsatisfied"}) is False
    assert score_python_case(tests[0], {**terminal, "goal_status": "unsupported", "goal_satisfied": None}) is None
    legacy = {**tests[0], "id": "legacy", "input_json": {}}
    with pytest.raises(ValueError):
        compile_python_test_bundle((tests[0], legacy))


def test_rule_hash_pin_public_instructions_and_common_scorer_domain() -> None:
    assert hashlib.sha256(HARNESS.read_bytes()).hexdigest() == PYTHON_STATE_GRAMMAR_SHA256
    assert PYTHON_STATE_SCORER_VERSION.startswith("py-state-v1.")
    assert len(PYTHON_STATE_SCORER_VERSION.split(".")[1]) == 64
    for fixture in python_state_fixtures():
        assert fixture.target.goal_contract_id == PYTHON_STATE_GOAL_ID
        assert fixture.reference not in fixture.public_instruction
        assert fixture.equivalent not in fixture.public_instruction
        assert fixture.public_task_hash != fixture.target.target_hash
    # No API/private fixture imports or candidate execution primitives in image module.
    import ast
    tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id in {"eval", "exec", "compile"} for n in ast.walk(tree))
    assert not any(isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app") for n in ast.walk(tree))
