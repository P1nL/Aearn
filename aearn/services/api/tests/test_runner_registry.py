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


def test_python_function_runtime_error_maps_to_runtime_error() -> None:
    result = run_exercise(
        _python_exercise(),
        "def add(a, b):\n    return a / 0\n",
        {},
        "visible_tests",
    )

    assert result.runtime_status == "runtime_error"
    assert result.test_pass_rate == 0.0
    assert result.next_action == "explain_error"
    assert "ZeroDivisionError" in (result.error_message or "")


def test_python_hidden_test_results_are_redacted_in_public_runner_output() -> None:
    exercise = {
        "runtime_profile": {
            "runtime_tier": "python_stdout_test",
            "language": "python",
            "runner": "python",
        },
        "metadata_json": {"entry_function": "solve"},
        "test_cases": [
            {
                "id": "visible_increment",
                "case_type": "visible",
                "input_json": {"args": [1]},
                "expected_output_json": {"return": 2},
                "weight": 1,
                "is_critical": True,
            },
            {
                "id": "hidden_secret_edge_case",
                "case_type": "hidden",
                "input_json": {"args": [2]},
                "expected_output_json": {"return": 999},
                "weight": 2,
                "is_critical": True,
            },
        ],
    }

    result = run_exercise(exercise, "def solve(value):\n    return value + 1\n", {}, "visible_tests")
    serialized = repr(result.test_results)

    assert result.runtime_status == "success"
    assert result.test_pass_rate < 1.0
    assert "hidden_secret_edge_case" not in serialized
    assert "999" not in serialized
    assert any(item["case_id"] == "hidden_case_2" for item in result.test_results)
    assert any(item["message"] == "A hidden test failed. Recheck edge cases and boundary behavior." for item in result.test_results)


def test_python_visible_test_failure_keeps_useful_public_message() -> None:
    result = run_exercise(
        _python_exercise(),
        "def add(a, b):\n    return a - b\n",
        {},
        "visible_tests",
    )

    assert result.runtime_status == "success"
    assert result.test_results[0]["case_id"] == "visible_add"
    assert "Expected 5" in str(result.test_results[0]["message"])


def test_python_public_stdout_is_bounded() -> None:
    exercise = {
        "runtime_profile": {
            "runtime_tier": "python_stdout_test",
            "language": "python",
            "runner": "python",
        },
        "metadata_json": {"entry_function": "main"},
        "test_cases": [],
    }

    result = run_exercise(exercise, "print('x' * 10000)\n", {}, "visible_tests")

    assert result.runtime_status == "success"
    assert len(result.stdout) == 4000
