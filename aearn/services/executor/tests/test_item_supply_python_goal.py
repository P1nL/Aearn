from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

HARNESS = Path(__file__).resolve().parents[3] / "infra/executor/harnesses/item_supply"


def _load(name: str, filename: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HARNESS / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finite_goal_matches_two_complete_forms_not_same_stdout_or_dead_code() -> None:
    goal = _load("p6_goal_pure_test", "python_goal.py")
    assert goal.python_goal_satisfied("numbers = [3, -1, 0, 3]\nprint(sum(numbers))")
    assert goal.python_goal_satisfied(
        "# comment\nnumbers=[3,-1,0,3]\ntotal = sum(numbers)\nprint(total) # sum\n"
    )
    for source in (
        "print(5)",
        "numbers=[3,-1,0,3]\nprint(5)",
        "if False:\n numbers=[3,-1,0,3]\nprint(5)",
        '# numbers=[3,-1,0,3]; print(sum(numbers))\nprint(5)',
        '"numbers=[3,-1,0,3]; print(sum(numbers))"\nprint(5)',
        "numbers=[3,-1,0,3]\nprint(sum(numbers))\nopen('/tmp/extra', 'w')",
        "numbers=[3,-True,False,3]\nprint(sum(numbers))",
        "numbers=[3,-1,0,3]\nprint(sum(numbers)",
    ):
        assert not goal.python_goal_satisfied(source)


def test_adapter_goal_facts_are_parent_owned_and_unknown_contract_stops_before_io(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Only static parsing and mocked terminal facts; never run a candidate."""
    goal = _load("p6_goal_adapter_pure_test", "python_goal.py")
    monkeypatch.setitem(sys.modules, "python_goal", goal)
    monkeypatch.setitem(sys.modules, "python_state_goal", _load("p7_state_adapter_pure_test", "python_state_goal.py"))
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "resource", ModuleType("resource"))
    adapter = _load("p6_adapter_goal_pure_test", "runtime_adapter.py")

    def no_io(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("pure test must not perform execution IO")

    monkeypatch.setattr(adapter.subprocess, "run", no_io)
    monkeypatch.setattr(adapter, "_sql", no_io)
    monkeypatch.setattr(adapter, "_limits", no_io)
    terminal = {"id": "case", "status": "success", "code": "python_terminal", "stdout": "5\n"}
    calls: list[str] = []

    def fake_terminal(code: str, case: dict[str, Any]) -> dict[str, Any]:
        calls.append(code)
        return dict(terminal)

    monkeypatch.setattr(adapter, "_python_terminal", fake_terminal)
    code = "numbers=[3,-1,0,3]\nprint(sum(numbers))"
    case = {"id": "case", "goal_contract": goal.GOAL_CONTRACT_ID, "goal_satisfied": True}
    fact = adapter._python(code, case)
    assert fact == {**terminal, "goal_contract_id": goal.GOAL_CONTRACT_ID, "goal_satisfied": True}
    assert adapter._python("print(5)", case)["goal_satisfied"] is False
    terminal["status"] = "runtime_error"
    assert adapter._python(code, case)["goal_satisfied"] is False
    for legacy in ({"id": "case"}, {"id": "case", "goal_contract": None}, {"id": "case", "goal_contract": ""}):
        assert adapter._python(code, legacy) == terminal

    calls.clear()
    monkeypatch.setattr(adapter, "_protect_parent", lambda: True)
    monkeypatch.setattr(adapter.os, "getuid", lambda: 10001, raising=False)
    for runtime, declaration in (
        ("python-stdout-v1", "unknown-v1"),
        ("python-stdout-v1", True),
        ("python-stdout-v1", " python-assignment-sum-print-v1"),
        ("sqlite-query-v1", goal.GOAL_CONTRACT_ID),
    ):
        request = {
            "schema_version": "sandbox-input-v1", "runtime_id": runtime,
            "action": "test", "submission": code,
            "visible_test_bundle_json": json.dumps([{"id": "legacy"}]),
            "hidden_test_bundle_json": json.dumps([{"id": "invalid", "goal_contract": declaration}]),
        }
        monkeypatch.setenv("AEARN_RUNTIME_ID", runtime)
        monkeypatch.setattr(adapter.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())))
        assert adapter.main() == 0
        result = json.loads(capsys.readouterr().out)
        assert result["diagnostic_code"] == "sandbox_protocol_invalid"
        assert result["passed_test_count"] == result["total_test_count"] == 0
    assert calls == []


def test_adapter_state_contract_routes_parent_facts_without_child_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "python_goal", _load("legacy_goal_for_state_test", "python_goal.py"))
    state = _load("state_goal_for_adapter_test", "python_state_goal.py")
    monkeypatch.setitem(sys.modules, "python_state_goal", state)
    if sys.platform == "win32":
        monkeypatch.setitem(sys.modules, "resource", ModuleType("resource"))
    adapter = _load("state_adapter_test", "runtime_adapter.py")
    target = {"goal_contract_id": state.GOAL_CONTRACT_ID, "task_kind": "accumulate",
              "variables": {"total": "total", "increase": "increase", "decrease": "decrease"},
              "values": {"initial": 10, "increase": 4, "decrease": 3}}
    calls = []

    def terminal(code: str, case: dict[str, Any]) -> dict[str, Any]:
        calls.append(code)
        return {"id": case["id"], "status": "success", "code": "python_terminal", "stdout": "11\n"}

    monkeypatch.setattr(adapter, "_python_terminal", terminal)
    case = {"id": "state", "goal_contract": target, "goal_satisfied": True}
    actual = "total=10\nincrease=4\ndecrease=3\ntotal+=increase\ntotal-=decrease\nprint(total)"
    fact = adapter._python(actual, case)
    assert fact["goal_status"] == "satisfied" and fact["goal_satisfied"] is True
    assert fact["goal_contract_hash"] == state.inspect_python_state_goal(actual, target)["goal_contract_hash"]
    wrong = adapter._python("print(11)", case)
    assert wrong["goal_status"] == "unsatisfied" and wrong["goal_satisfied"] is False
    with pytest.raises(ValueError):
        adapter._python(actual, {**case, "goal_contract": {**target, "hidden_answers": []}})
    assert len(calls) == 2  # Invalid public contract stops before the terminal port.
