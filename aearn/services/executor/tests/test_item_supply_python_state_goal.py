"""Standalone rule-module tests. ast.parse is the only candidate-code operation."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

HARNESS = Path(__file__).resolve().parents[3] / "infra/executor/harnesses/item_supply/python_state_goal.py"


def _goal() -> ModuleType:
    spec = importlib.util.spec_from_file_location("state_goal_executor_pure", HARNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _contract() -> dict:
    return {"goal_contract_id": "python-state-update-v1", "task_kind": "accumulate",
            "variables": {"total": "balance", "increase": "credit", "decrease": "debit"},
            "values": {"initial": 10, "increase": 4, "decrease": 3}}


def test_role_renaming_whitespace_comments_and_equivalent_structure() -> None:
    goal, contract = _goal(), _contract()
    code = "# legal variation\ndebit=3; balance = (10); credit=4\nbalance = credit + balance\nbalance -= debit\nprint( (balance) ) # final"
    assert goal.inspect_python_state_goal(code, contract)["goal_status"] == "satisfied"
    # Literal changes do not manufacture a different family or relax public binding.
    changed = {**contract, "values": {"initial": 11, "increase": 4, "decrease": 3}}
    assert goal.inspect_python_state_goal(code, changed)["goal_status"] == "unsatisfied"


def test_unsupported_syntax_bounds_and_invalid_wire_are_not_semantic_negatives() -> None:
    goal, contract = _goal(), _contract()
    for source in ("print(", "import os\nprint(11)", "if False:\n balance=10\nprint(11)",
                   "print(sum([10,4,-3]))", "print(unknown)", "#" * 8193,
                   "balance=True\nprint(balance)"):
        fact = goal.inspect_python_state_goal(source, contract)
        assert fact["goal_status"] == "unsupported" and fact["goal_satisfied"] is None
    for value in (None, "python-state-update-v1", {**contract, "expected": "11"},
                  {**contract, "values": {"initial": 1001, "increase": 4, "decrease": 3}}):
        with pytest.raises(ValueError):
            goal.inspect_python_state_goal("print(11)", value)


def test_finite_legal_wrong_dependencies_and_hardcoded_output_are_unsatisfied() -> None:
    goal, contract = _goal(), _contract()
    # Legal, defined-name Python programs; execution remains a later container probe.
    for source in (
        "print(11)",
        "balance=10\ncredit=4\ndebit=3\nbalance=credit\nbalance=balance-debit\nprint(balance)",
        "balance=10\ncredit=4\ndebit=3\nbalance+=credit\nbalance=10-debit\nprint(balance)",
        "balance=10\ncredit=4\ndebit=3\nbalance+=credit\nbalance-=debit\nprint(11)",
    ):
        facts = goal.inspect_python_state_goal(source, contract)
        assert facts["goal_status"] == "unsatisfied" and facts["goal_satisfied"] is False
