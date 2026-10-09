"""Finite Python goal contract. Only consumes actual facts after runner verification.

No AST evaluator or caller-issued proof. The fixed in-image adapter owns target
inspection; expected stdout remains API-private. These pure bundle/scoring
interfaces are reusable by future consumers, not wired to the formal runner.
"""
from __future__ import annotations

from typing import Any

from app.services.learning.item_bank.contracts import LearningItemCodePrivateV1, LearningItemSourceV1, canonical_hash
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION
from app.services.runners.sandbox_runner import _run_single_test

PYTHON_GOAL_ID = "python-assignment-sum-print-v1"
PYTHON_GOAL_PROFILE = "python_assignment_sum_print_v1"
PYTHON_GOAL_INSTRUCTION = "先将列表 `[3, -1, 0, 3]` 赋值给变量 `numbers`，再使用 `sum(numbers)` 求和并用 `print` 仅输出总和。允许直接 `print(sum(numbers))`，或先将和赋值给 `total` 再 `print(total)`；仅限这两种顺序结构，不使用其他语句。"
PYTHON_GOAL_CAPABILITIES = ("python.assignment",)
PYTHON_GOAL_CORRECT = "numbers = [3, -1, 0, 3]\nprint(sum(numbers))"
PYTHON_GOAL_COUNTEREXAMPLE = "print(sum([3, -1, 0, 3]))"
PYTHON_GOAL_SCORER_HASH = canonical_hash({
    "version": "python_assignment_sum_print_scorer_v1", "goal_contract_id": PYTHON_GOAL_ID,
    "numbers": [3, -1, 0, 3], "forms": ["numbers_literal;print(sum(numbers))", "numbers_literal;total=sum(numbers);print(total)"],
    "facts_owner": "sealed_in_image_actual_submission_ast", "stdout_scorer": "existing_run_single_test",
    "pass": "normalized_stdout_and_exact_goal_id_and_strict_boolean_satisfied",
    "missing_facts": "pending", "wrong_control": "success_terminal_required",
})
# The full declaration hash is part of scope, evidence and scoring identity.
PYTHON_GOAL_SCORER_VERSION = "pygoal-v1." + PYTHON_GOAL_SCORER_HASH


def test_goal_contract(test: dict[str, Any]) -> str | None:
    inputs = test.get("input_json", {})
    if not isinstance(inputs, dict) or set(inputs) - {"goal_contract"}:
        raise ValueError("python_stdout_profile_required")
    goal = inputs.get("goal_contract")
    if goal is not None and goal != PYTHON_GOAL_ID:
        raise ValueError("python_goal_contract_unsupported")
    expected = test.get("expected_output_json")
    if not isinstance(expected, dict) or set(expected) != {"stdout"} or not isinstance(expected["stdout"], str):
        raise ValueError("python_stdout_profile_required")
    return goal


def compile_python_test_bundle(tests: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Compile trusted private tests, excluding expected outputs from the wire."""
    if any(isinstance(test.get("input_json", {}).get("goal_contract"), dict)
           for test in tests if isinstance(test.get("input_json", {}), dict)):
        from app.services.learning.item_supply.sandbox.python_state_scorer import compile_python_state_test_bundle

        return compile_python_state_test_bundle(tests)
    cases = []
    for test in tests:
        goal = test_goal_contract(test)
        case = {"id": test["id"], "case_type": test["case_type"]}
        if goal is not None:
            case["goal_contract"] = goal
        cases.append(case)
    return tuple(cases)


def score_python_case(test: dict[str, Any], fact: dict[str, Any]) -> bool | None:
    """None means missing/untrusted semantic facts, not a wrong-answer proof.

    Caller MUST verify actual runner seal/request before passing this fact.
    Neither this function nor a bool supplied to it is a receipt issuer.
    """
    inputs = test.get("input_json", {})
    if isinstance(inputs, dict) and isinstance(inputs.get("goal_contract"), dict):
        from app.services.learning.item_supply.sandbox.python_state_scorer import score_python_state_case

        return score_python_state_case(test, fact)
    goal = test_goal_contract(test)
    if goal is None:
        # Preserve the legacy guarded stdout semantics exactly.
        return _run_single_test({}, "unused", test, str(fact.get("stdout", "")))["passed"] is True
    if fact.get("status") != "success" or fact.get("code") != "python_terminal" or not isinstance(fact.get("stdout"), str):
        return None
    if goal is not None and (fact.get("goal_contract_id") != goal or type(fact.get("goal_satisfied")) is not bool):
        return None
    stdout_passed = _run_single_test({}, "unused", test, fact["stdout"])["passed"] is True
    return stdout_passed and (goal is None or fact["goal_satisfied"] is True)


def source_goal_contract(source: LearningItemSourceV1) -> str | None:
    private = source.private.content
    if not isinstance(private, LearningItemCodePrivateV1):
        return None
    from app.services.learning.item_supply.sandbox.finite_probe_plans import (
        native_python_tests, source_python_state_target,
    )
    from app.services.learning.item_supply.finite_targets.python_state import PYTHON_STATE_GOAL_ID

    if source_python_state_target(source) is not None:
        native_python_tests(source)
        return PYTHON_STATE_GOAL_ID
    explicit = source.public.instruction_markdown == PYTHON_GOAL_INSTRUCTION
    if explicit and source.blueprint.version != PYTHON_GOAL_SCORER_VERSION:
        raise ValueError("python_goal_blueprint_contract_mismatch")
    for test in private.tests:
        raw = test.model_dump(mode="json")
        declared = test_goal_contract(raw)
        if explicit:
            if "goal_contract" in test.input_json and declared != PYTHON_GOAL_ID:
                raise ValueError("python_goal_contract_contradiction")
        elif declared is not None:
            raise ValueError("python_goal_public_task_mismatch")
    return PYTHON_GOAL_ID if explicit else None


def compile_goal_tests(source: LearningItemSourceV1) -> tuple[dict[str, Any], ...]:
    """Server-owned exact task rule, not a field the author must know or choose.

    Does not mutate the staged source. Goal omission is filled only for the
    versioned explicit public task; contradictory declarations fail closed.
    """
    private = source.private.content
    if not isinstance(private, LearningItemCodePrivateV1):
        raise ValueError("python_stdout_profile_required")
    goal = source_goal_contract(source)
    from app.services.learning.item_supply.finite_targets.python_state import PYTHON_STATE_GOAL_ID

    if goal == PYTHON_STATE_GOAL_ID:
        from app.services.learning.item_supply.sandbox.finite_probe_plans import native_python_tests

        return native_python_tests(source)
    tests = []
    for test in private.tests:
        payload = test.model_dump(mode="json")
        if goal is not None:
            payload["input_json"] = {"goal_contract": goal}
        tests.append(payload)
    return tuple(tests)


def source_scorer_version(source: LearningItemSourceV1) -> str:
    from app.services.learning.item_supply.finite_targets.python_state import PYTHON_STATE_GOAL_ID
    from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION

    goal = source_goal_contract(source)
    if goal == PYTHON_STATE_GOAL_ID:
        return PYTHON_STATE_SCORER_VERSION
    return PYTHON_GOAL_SCORER_VERSION if goal else GATE_PASS_POLICY_VERSION
