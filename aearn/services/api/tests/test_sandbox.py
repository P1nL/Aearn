"""Tests for the real code execution sandbox."""
from __future__ import annotations

from app.services.sandbox import execute_python_with_tests


def test_simple_function_returns_correct_result():
    code = "def add(a, b):\n    return a + b\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [1, 2]}, "expected_output_json": {"return": 3}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="add")
    assert result.status == "success"
    assert len(result.test_results) == 1
    assert result.test_results[0].passed is True


def test_function_with_multiple_test_cases():
    code = "def multiply(x, y):\n    return x * y\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [3, 4]}, "expected_output_json": {"return": 12}, "weight": 1, "is_critical": False},
        {"id": "tc2", "case_type": "visible", "input_json": {"args": [0, 5]}, "expected_output_json": {"return": 0}, "weight": 1, "is_critical": False},
        {"id": "tc3", "case_type": "hidden", "input_json": {"args": [-1, 7]}, "expected_output_json": {"return": -7}, "weight": 1, "is_critical": True},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="multiply")
    assert result.status == "success"
    assert len(result.test_results) == 3
    assert all(tr.passed for tr in result.test_results)


def test_wrong_answer_fails_test():
    code = "def add(a, b):\n    return a - b\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [3, 2]}, "expected_output_json": {"return": 5}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="add")
    assert result.status == "success"
    assert result.test_results[0].passed is False
    assert "Expected" in result.test_results[0].message


def test_syntax_error_returns_error_status():
    code = "def add(a, b)\n    return a + b\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [1, 2]}, "expected_output_json": {"return": 3}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="add")
    assert result.status == "error"
    assert result.error is not None
    assert "SyntaxError" in result.error


def test_runtime_error_returns_error_status():
    code = "def divide(a, b):\n    return a / b\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [1, 0]}, "expected_output_json": {"return": 0}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="divide")
    assert result.status == "success"
    assert result.test_results[0].passed is False
    assert "ZeroDivisionError" in result.test_results[0].message


def test_timeout_returns_timeout_status():
    code = "def slow():\n    while True:\n        pass\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": []}, "expected_output_json": {"return": 1}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="slow", timeout_s=1.0)
    assert result.status == "timeout"
    assert result.error is not None


def test_import_os_blocked():
    code = "import os\ndef get_cwd():\n    return os.getcwd()\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": []}, "expected_output_json": {"return": ""}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="get_cwd")
    assert result.status == "sandbox_error"
    assert result.error is not None
    assert "Import" in result.error


def test_import_subprocess_blocked():
    code = "import subprocess\ndef run_cmd():\n    return subprocess.run(['echo', 'hi'], capture_output=True).stdout\n"
    test_cases = []
    result = execute_python_with_tests(code, test_cases, entry_function="run_cmd")
    assert result.status == "sandbox_error"
    assert "Import" in (result.error or "")


def test_open_file_blocked():
    code = "def read_file():\n    return open('/etc/passwd').read()\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": []}, "expected_output_json": {"return": ""}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="read_file")
    assert result.status == "success"
    assert result.test_results[0].passed is False
    assert "NameError" in result.test_results[0].message or "not defined" in result.test_results[0].message


def test_stdout_capture():
    code = "def greet(name):\n    print(f'Hello {name}')\n    return name\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": ["World"]}, "expected_output_json": {"return": "World", "stdout": "Hello World"}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="greet")
    assert result.status == "success"
    assert result.test_results[0].passed is True


def test_custom_assertion_code():
    code = "def make_list(n):\n    return list(range(n))\n"
    test_cases = [
        {
            "id": "tc1",
            "case_type": "visible",
            "input_json": {"args": [5]},
            "expected_output_json": {"return": [0, 1, 2, 3, 4]},
            "assertion_code": "assert len(result) == 5 and result[0] == 0",
            "weight": 1,
            "is_critical": False,
        },
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="make_list")
    assert result.status == "success"
    assert result.test_results[0].passed is True


def test_allowed_import_math():
    code = "import math\ndef circle_area(r):\n    return round(math.pi * r * r, 2)\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": [1]}, "expected_output_json": {"return": 3.14}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="circle_area")
    assert result.status == "success"
    assert result.test_results[0].passed is True


def test_function_not_defined():
    code = "x = 42\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": []}, "expected_output_json": {"return": 42}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="get_value")
    assert result.status == "success"
    assert result.test_results[0].passed is False
    assert "not defined" in result.test_results[0].message


def test_no_test_cases_just_executes():
    code = "x = 1 + 1\nprint(x)\n"
    result = execute_python_with_tests(code, [], entry_function="main")
    assert result.status == "success"
    assert "2" in result.stdout


def test_kwargs_support():
    code = "def greet(name, greeting='Hello'):\n    return f'{greeting}, {name}!'\n"
    test_cases = [
        {"id": "tc1", "case_type": "visible", "input_json": {"args": ["Alice"], "kwargs": {"greeting": "Hi"}}, "expected_output_json": {"return": "Hi, Alice!"}, "weight": 1, "is_critical": False},
    ]
    result = execute_python_with_tests(code, test_cases, entry_function="greet")
    assert result.status == "success"
    assert result.test_results[0].passed is True
