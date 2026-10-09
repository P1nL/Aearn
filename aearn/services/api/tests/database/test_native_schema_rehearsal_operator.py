from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[5] / (
    ".trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/native-schemas-live-20261006.py"
)


@pytest.mark.parametrize("diagnostic", (False, True))
def test_default_and_diagnostic_plan_are_inert(monkeypatch, capsys, diagnostic):
    module = runpy.run_path(str(SCRIPT), run_name="native_schema_operator_test")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)] + (["--include-blind-diagnostic"] if diagnostic else []))
    assert module["main"]() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["status"] == "not_executed"
    assert plan["database_io"] is False
    expected = list(module["NAMES"])
    if diagnostic:
        expected.append(module["DIAGNOSTIC_FRAGMENT"])
    assert plan["fragments"] == expected


def test_execute_and_rollback_rehearsal_cannot_be_combined(monkeypatch, capsys):
    module = runpy.run_path(str(SCRIPT), run_name="native_schema_operator_test")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--execute", "--rehearse"])
    with pytest.raises(SystemExit) as error:
        module["main"]()
    assert error.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
