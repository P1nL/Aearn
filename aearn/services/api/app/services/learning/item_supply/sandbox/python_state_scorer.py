"""Unified Python state stdout AND goal scoring, after actual seal verification.

No terminal issuer lives here. Unsupported/missing/infrastructure facts stay
pending; neither pure fixtures nor caller dictionaries prove actual execution.
"""
from __future__ import annotations

from typing import Any

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_targets.python_state import (
    PYTHON_STATE_FIXTURE_HASH,
    PYTHON_STATE_GOAL_ID,
    PYTHON_STATE_GRAMMAR_SHA256,
    PythonStateTarget,
    parse_python_state_target,
    python_state_expected_stdout,
)
from app.services.runners.sandbox_runner import _run_single_test

PYTHON_STATE_SCORER_HASH = canonical_hash({
    "assessment_contract": PYTHON_STATE_GOAL_ID,
    "grammar_sha256": PYTHON_STATE_GRAMMAR_SHA256,
    "fixture_hash": PYTHON_STATE_FIXTURE_HASH,
    "facts": "sealed_actual_submission_public_contract_hash_strict_status_boolean",
    "pass": "successful_python_terminal_AND_existing_stdout_scorer_AND_satisfied_goal",
    "unsupported_or_infrastructure": "pending_not_negative",
})
PYTHON_STATE_SCORER_VERSION = "py-state-v1." + PYTHON_STATE_SCORER_HASH


def python_state_test_target(test: dict[str, Any]) -> PythonStateTarget:
    inputs = test.get("input_json")
    if not isinstance(inputs, dict) or set(inputs) != {"goal_contract"}:
        raise ValueError("python_state_test_contract_required")
    target = parse_python_state_target(inputs["goal_contract"])
    expected = test.get("expected_output_json")
    if (not isinstance(expected, dict) or set(expected) != {"stdout"}
            or type(expected["stdout"]) is not str
            or expected["stdout"] != python_state_expected_stdout(target)):
        raise ValueError("python_state_test_expectation_mismatch")
    if not isinstance(test.get("id"), str) or not 1 <= len(test["id"]) <= 120:
        raise ValueError("python_state_test_id_invalid")
    if test.get("case_type") not in {"visible", "hidden"}:
        raise ValueError("python_state_case_type_invalid")
    return target


def compile_python_state_test_bundle(tests: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    """Public-only wire with one exact target per candidate, never expectations."""
    if not 1 <= len(tests) <= 48:
        raise ValueError("python_state_case_bound")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    target_hash: str | None = None
    for test in tests:
        target = python_state_test_target(test)
        if test["id"] in seen:
            raise ValueError("python_state_duplicate_case")
        seen.add(test["id"])
        if target_hash is not None and target.target_hash != target_hash:
            raise ValueError("python_state_mixed_public_tasks")
        target_hash = target.target_hash
        cases.append({"id": test["id"], "case_type": test["case_type"],
                      "goal_contract": target.model_dump(mode="json")})
    return tuple(cases)


def score_python_state_case(test: dict[str, Any], fact: dict[str, Any]) -> bool | None:
    """Caller MUST first verify genuine runner seal/request/submission/case.

    This function is deliberately not wired into the old score_python_case;
    the integration owner routes the exact new contract without loosening it.
    """
    target = python_state_test_target(test)
    if (fact.get("id") != test["id"] or fact.get("status") != "success"
            or fact.get("code") != "python_terminal" or type(fact.get("stdout")) is not str
            or fact.get("goal_contract_id") != PYTHON_STATE_GOAL_ID
            or fact.get("goal_contract_hash") != target.target_hash):
        return None
    status, satisfied = fact.get("goal_status"), fact.get("goal_satisfied")
    if (type(satisfied) is not bool
            or (status, satisfied) not in (("satisfied", True), ("unsatisfied", False))):
        return None
    stdout_passed = _run_single_test({}, "unused", test, fact["stdout"])["passed"] is True
    return stdout_passed and satisfied
