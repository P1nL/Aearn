from __future__ import annotations

from aearn_shared.execution import (
    SafeExecutionResultV1,
    SafeExecutionStatus,
    SandboxResultV1,
    SandboxTestFeedbackV1,
)
from app.services.tutor.execution import safe_result_to_runtime_execution_result


def test_safe_result_projection_removes_code_hidden_test_container_and_path_markers() -> None:
    raw = SandboxResultV1(
        status=SafeExecutionStatus.RUNTIME_ERROR,
        stdout="42\nC:\\work\\submission.py\ndef leaked():\n    return 1",
        stderr="Error response from daemon: container aearn-exec-123\nTraceback (most recent call last):",
        test_feedback=(
            SandboxTestFeedbackV1(
                case_id="visible-1",
                passed=False,
                visibility="visible",
                message="File '/work/main.py' failed against expected value 9",
            ),
            SandboxTestFeedbackV1(
                case_id="hidden-1",
                passed=False,
                visibility="hidden",
                message="hidden test expected secret value and source def leaked(): pass",
            ),
        ),
        passed_test_count=0,
        total_test_count=2,
        diagnostic_code="runtime_error",
    )

    safe = SafeExecutionResultV1.from_sandbox_result(raw)
    serialized = safe.model_dump_json()

    assert safe.stdout == "42"
    assert safe.stderr == ""
    assert safe.test_feedback[0].message == ""
    assert safe.test_feedback[1].message == "A non-visible scenario still failed."
    for marker in ("daemon", "container", "C:\\work", "/work", "hidden test", "expected value", "def leaked"):
        assert marker.lower() not in serialized.lower()


def test_safe_result_adapter_uses_existing_result_shape_without_legacy_execution_fallback() -> None:
    raw = SandboxResultV1(
        status=SafeExecutionStatus.SUCCESS,
        stdout="answer=42",
        test_feedback=(
            SandboxTestFeedbackV1(
                case_id="visible-1",
                passed=True,
                visibility="visible",
                message="Visible test passed.",
            ),
        ),
        passed_test_count=1,
        total_test_count=1,
        diagnostic_code="completed",
    )
    safe = SafeExecutionResultV1.from_sandbox_result(raw)

    adapted = safe_result_to_runtime_execution_result(safe)

    assert adapted.runtime_status == "success"
    assert adapted.stdout == "answer=42"
    assert adapted.test_pass_rate == 1.0
    assert adapted.next_action == "advance_next"
