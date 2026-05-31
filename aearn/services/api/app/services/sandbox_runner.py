"""Subprocess entry point for sandboxed code execution.

Protocol:
- Reads JSON from stdin: {"code": "...", "test_cases": [...], "entry_function": "..."}
- Executes code in restricted namespace
- Writes JSON results to stdout
- Exit code 0 = normal completion, 1 = unrecoverable error
"""
from __future__ import annotations

import io
import json
import re
import sys
import traceback
from contextlib import redirect_stdout, redirect_stderr
from types import ModuleType


SAFE_BUILTINS = {
    "abs", "all", "any", "bin", "bool", "bytearray", "bytes", "callable",
    "chr", "complex", "dict", "divmod", "enumerate", "filter", "float",
    "format", "frozenset", "getattr", "hasattr", "hash", "hex", "id",
    "int", "isinstance", "issubclass", "iter", "len", "list", "map",
    "max", "min", "next", "object", "oct", "ord", "pow", "print",
    "property", "range", "repr", "reversed", "round", "set", "slice",
    "sorted", "staticmethod", "str", "sum", "super", "tuple", "type",
    "vars", "zip",
}

ALLOWED_IMPORTS = {
    "math", "random", "string", "collections", "itertools",
    "functools", "operator", "re", "json", "datetime", "typing",
    "decimal", "fractions", "heapq", "bisect", "copy",
}


def _make_restricted_import(allowed: set[str]):
    def _restricted_import(name: str, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level not in allowed:
            raise ImportError(f"Import of '{name}' is not allowed in the sandbox")
        return __builtins__.__import__(name, *args, **kwargs) if isinstance(__builtins__, ModuleType) else __import__(name, *args, **kwargs)
    return _restricted_import


def _build_restricted_globals(allowed_imports: set[str]) -> dict:
    import builtins
    safe = {k: getattr(builtins, k) for k in SAFE_BUILTINS if hasattr(builtins, k)}
    safe["__import__"] = _make_restricted_import(allowed_imports)
    return {"__builtins__": safe}


def _detect_entry_function(code: str) -> str:
    """Auto-detect the first user-defined function in the code."""
    match = re.search(r"^def\s+(\w+)\s*\(", code, re.MULTILINE)
    return match.group(1) if match else "main"


def _exec_user_code(code: str, restricted_globals: dict) -> tuple[str, str, str | None]:
    """Execute user code, return (stdout, stderr, error_message)."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exec(compile(code, "<user_code>", "exec"), restricted_globals)
        return stdout_buf.getvalue(), stderr_buf.getvalue(), None
    except SyntaxError as exc:
        return stdout_buf.getvalue(), stderr_buf.getvalue(), f"SyntaxError: {exc}"
    except ImportError as exc:
        return stdout_buf.getvalue(), stderr_buf.getvalue(), f"ImportError: {exc}"
    except Exception as exc:
        tb = traceback.format_exc()
        return stdout_buf.getvalue(), stderr_buf.getvalue(), f"{type(exc).__name__}: {exc}\n{tb}"


def _run_single_test(
    restricted_globals: dict,
    entry_function: str,
    test_case: dict,
    exec_stdout: str,
) -> dict:
    """Run a single test case against the user's code namespace."""
    input_data = test_case.get("input_json", {})
    if not isinstance(input_data, dict):
        input_data = {}
    expected = test_case.get("expected_output_json", {})
    if not isinstance(expected, dict):
        expected = {}
    assertion_code = test_case.get("assertion_code")
    case_id = test_case.get("id", "unknown")
    case_type = test_case.get("case_type", "visible")
    weight = float(test_case.get("weight", 1))
    is_critical = bool(test_case.get("is_critical", False))

    expected_return = expected.get("return")
    expected_stdout = expected.get("stdout")

    is_stdout_only = expected_return is None and expected_stdout is not None

    if is_stdout_only:
        actual_stdout = exec_stdout.rstrip("\n")
        expected_str = str(expected_stdout).rstrip("\n")
        passed = actual_stdout == expected_str
        message = "Stdout matches expected" if passed else f"Expected stdout '{expected_str}', got '{actual_stdout}'"
        return {
            "case_id": case_id,
            "case_type": case_type,
            "passed": passed,
            "weight": weight,
            "is_critical": is_critical,
            "message": message,
            "actual": actual_stdout,
            "expected": expected_str,
        }

    if "args" in input_data:
        args = input_data["args"]
        kwargs = input_data.get("kwargs", {})
    else:
        args = []
        kwargs = {k: v for k, v in input_data.items() if k != "stdout"}

    if entry_function not in restricted_globals:
        return {
            "case_id": case_id,
            "case_type": case_type,
            "passed": False,
            "weight": weight,
            "is_critical": is_critical,
            "message": f"Function '{entry_function}' not defined in user code",
            "actual": None,
            "expected": expected_return,
        }

    fn = restricted_globals[entry_function]
    if not callable(fn):
        return {
            "case_id": case_id,
            "case_type": case_type,
            "passed": False,
            "weight": weight,
            "is_critical": is_critical,
            "message": f"'{entry_function}' is not callable",
            "actual": None,
            "expected": expected_return,
        }

    stdout_buf = io.StringIO()
    try:
        with redirect_stdout(stdout_buf):
            result = fn(*args, **kwargs)
    except Exception as exc:
        return {
            "case_id": case_id,
            "case_type": case_type,
            "passed": False,
            "weight": weight,
            "is_critical": is_critical,
            "message": f"{type(exc).__name__}: {exc}",
            "actual": None,
            "expected": expected_return,
        }

    captured_stdout = stdout_buf.getvalue()

    if assertion_code:
        try:
            assertion_ns = {"result": result, "expected": expected_return, "stdout": captured_stdout}
            exec(compile(assertion_code, "<assertion>", "exec"), assertion_ns)
            passed = True
            message = "Custom assertion passed"
        except AssertionError as exc:
            passed = False
            message = f"AssertionError: {exc}" if str(exc) else "Assertion failed"
        except Exception as exc:
            passed = False
            message = f"Assertion error: {type(exc).__name__}: {exc}"
    else:
        passed = True
        message = "Passed"
        if expected_return is not None:
            if result != expected_return:
                passed = False
                message = f"Expected {repr(expected_return)}, got {repr(result)}"
        if expected_stdout is not None and passed:
            if captured_stdout.rstrip("\n") != str(expected_stdout).rstrip("\n"):
                passed = False
                message = f"Expected stdout '{expected_stdout}', got '{captured_stdout.rstrip()}'"

    return {
        "case_id": case_id,
        "case_type": case_type,
        "passed": passed,
        "weight": weight,
        "is_critical": is_critical,
        "message": message,
        "actual": _safe_repr(result),
        "expected": _safe_repr(expected_return),
    }


def _safe_repr(value: object) -> str | None:
    if value is None:
        return None
    try:
        r = repr(value)
        return r[:500] if len(r) > 500 else r
    except Exception:
        return "<unrepresentable>"


def main() -> None:
    try:
        raw_input = sys.stdin.read()
        payload = json.loads(raw_input)
    except (json.JSONDecodeError, ValueError) as exc:
        json.dump({"status": "sandbox_error", "error": f"Invalid input: {exc}"}, sys.stdout)
        sys.exit(1)

    code = payload.get("code", "")
    test_cases = payload.get("test_cases", [])
    entry_function = payload.get("entry_function") or _detect_entry_function(code)

    restricted_globals = _build_restricted_globals(ALLOWED_IMPORTS)

    exec_stdout, exec_stderr, exec_error = _exec_user_code(code, restricted_globals)

    if exec_error:
        if "SyntaxError" in exec_error:
            status = "error"
        elif "ImportError" in exec_error:
            status = "sandbox_error"
        else:
            status = "error"
        json.dump({
            "status": status,
            "stdout": exec_stdout[:4000],
            "stderr": exec_stderr[:4000],
            "error": exec_error[:2000],
            "test_results": [],
        }, sys.stdout)
        return

    if not test_cases:
        json.dump({
            "status": "success",
            "stdout": exec_stdout[:4000],
            "stderr": exec_stderr[:4000],
            "error": None,
            "test_results": [],
        }, sys.stdout)
        return

    test_results = []
    for tc in test_cases:
        result = _run_single_test(restricted_globals, entry_function, tc, exec_stdout)
        test_results.append(result)

    json.dump({
        "status": "success",
        "stdout": exec_stdout[:4000],
        "stderr": exec_stderr[:4000],
        "error": None,
        "test_results": test_results,
    }, sys.stdout)


if __name__ == "__main__":
    main()
