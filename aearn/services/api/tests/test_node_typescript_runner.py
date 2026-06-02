from __future__ import annotations

from app.services.runners.node_typescript_runner import execute_node_typescript_with_tests


def test_node_typescript_runner_executes_function_tests() -> None:
    result = execute_node_typescript_with_tests(
        "function add(a: number, b: number): number {\n  return a + b;\n}\n",
        [
            {
                "id": "visible_add",
                "case_type": "visible",
                "input_json": {"args": [2, 3]},
                "expected_output_json": {"return": 5},
                "weight": 1,
                "is_critical": True,
            },
            {
                "id": "hidden_negative",
                "case_type": "hidden",
                "input_json": {"args": [-2, 3]},
                "expected_output_json": {"return": 1},
                "weight": 2,
                "is_critical": True,
            },
        ],
        entry_function="add",
    )

    assert result.status == "success"
    assert len(result.test_results) == 2
    assert all(test.passed for test in result.test_results)


def test_node_typescript_runner_reports_compile_error() -> None:
    result = execute_node_typescript_with_tests(
        "function add(a: number, b: number): number {\n  return a + ;\n}\n",
        [],
        entry_function="add",
    )

    assert result.status == "compile_error"
    assert result.error is not None


def test_node_typescript_runner_reports_function_runtime_error() -> None:
    result = execute_node_typescript_with_tests(
        "function explode(): number {\n  throw new Error('boom');\n}\n",
        [
            {
                "id": "visible_explode",
                "case_type": "visible",
                "input_json": {"args": []},
                "expected_output_json": {"return": 1},
                "weight": 1,
                "is_critical": True,
            },
        ],
        entry_function="explode",
    )

    assert result.status == "runtime_error"
    assert result.test_results[0].passed is False
    assert "Error: boom" in result.test_results[0].message


def test_node_typescript_runner_missing_toolchain_is_non_crashing() -> None:
    result = execute_node_typescript_with_tests(
        "function add(a: number, b: number): number { return a + b; }\n",
        [],
        entry_function="add",
        node_command=None,
        tsc_command=None,
        detect_commands=False,
    )

    assert result.status == "missing_toolchain"
    assert result.error is not None
