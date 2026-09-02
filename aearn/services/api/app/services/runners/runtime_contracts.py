from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeExecutionResult:
    runtime_status: str
    stdout: str
    stderr: str
    test_pass_rate: float
    passed_test_count: int
    total_test_count: int
    test_results: list[dict[str, object]]
    error_message: str | None
    next_action: str
    preview_html: str | None
    core_blank_gate: bool
    any_blank_passed: bool
    logic_pass: bool
    presentation: dict[str, object] | None = None
