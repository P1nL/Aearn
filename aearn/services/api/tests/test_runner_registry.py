from __future__ import annotations

from app.services.runner_registry import get_runner_registry
from app.services.runtime_runner import run_exercise


def _python_exercise() -> dict[str, object]:
    return {
        "runtime_profile": {
            "runtime_tier": "python_stdout_test",
            "language": "python",
            "runner": "python",
        },
        "metadata_json": {"entry_function": "add"},
        "test_cases": [
            {
                "id": "visible_add",
                "case_type": "visible",
                "input_json": {"args": [2, 3]},
                "expected_output_json": {"return": 5},
                "weight": 1,
                "is_critical": True,
            },
        ],
    }


def test_runner_registry_selects_current_runtime_tiers() -> None:
    registry = get_runner_registry()

    assert registry.select({"runtime_tier": "python_stdout_test"}).runner_key == "python"
    assert registry.select({"runtime_tier": "browser_preview"}).runner_key == "browser"
    assert registry.select({"runtime_tier": "compiled_sandbox_later"}).runner_key == "compiled"
    assert registry.select({"language": "typescript"}).runner_key == "node"
    assert registry.select({"language": "sql"}).runner_key == "sql"
    assert registry.select({"language": "unknown"}).runner_key == "none"


def test_python_runner_adapter_executes_existing_subprocess_sandbox() -> None:
    result = run_exercise(
        _python_exercise(),
        "def add(a, b):\n    print('total=' + str(a + b))\n    return a + b\n",
        {},
        "visible_tests",
    )

    assert result.runtime_status == "success"
    assert result.stdout == ""
    assert result.test_pass_rate == 1.0
    assert result.passed_test_count == 1
    assert result.next_action == "advance_next"


def test_python_runner_adapter_preserves_syntax_error_shape() -> None:
    result = run_exercise(
        _python_exercise(),
        "def add(a, b)\n    return a + b\n",
        {},
        "visible_tests",
    )

    assert result.runtime_status == "runtime_error"
    assert result.test_pass_rate == 0.0
    assert result.next_action == "explain_error"
    assert result.error_message == "Python code contains a syntax error."


def test_planned_compiled_runner_returns_unsupported_fallback() -> None:
    exercise = {
        "runtime_profile": {
            "runtime_tier": "compiled_sandbox_later",
            "language": "java",
            "runner": "sandbox",
        },
        "test_cases": [
            {
                "id": "case_1",
                "case_type": "visible",
                "input_json": {},
                "expected_output_json": {},
                "weight": 1,
                "is_critical": True,
            },
        ],
    }

    result = run_exercise(exercise, "class Main {}", {}, "visible_tests")

    assert result.runtime_status == "unsupported"
    assert result.test_pass_rate == 0.0
    assert result.next_action == "retry_same"
    assert "planned later" in (result.error_message or "")
    assert result.test_results[0]["passed"] is False


def test_planned_sql_and_node_runners_do_not_claim_execution() -> None:
    registry = get_runner_registry()

    node = registry.select({"language": "typescript"})
    sql = registry.select({"language": "sql"})

    assert node.supports_execution is False
    assert node.execution == "node_later"
    assert "not available" in (node.unavailable_message or "")
    assert sql.supports_execution is False
    assert sql.execution == "sql_later"
    assert "isolated query runner" in (sql.unavailable_message or "")


def test_python_runner_capability_discloses_non_container_sandbox() -> None:
    capability = get_runner_registry().select({"runtime_tier": "python_stdout_test"})

    assert capability.supports_execution is True
    assert capability.supports_stdout is True
    assert capability.supports_preview is False
    assert capability.sandbox_policy["is_container_grade"] is False
