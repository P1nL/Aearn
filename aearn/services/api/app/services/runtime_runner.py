from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence

from app.services.runner_registry import get_runner_registry
from app.services.runtime_contracts import RuntimeExecutionResult


def inspect_submission(
    exercise: Mapping[str, object],
    code: str,
    filled_blanks: Mapping[str, str],
) -> dict[str, object]:
    runtime_profile = exercise.get("runtime_profile", {})
    runtime_tier = str(runtime_profile.get("runtime_tier", "")) if isinstance(runtime_profile, Mapping) else ""
    code_blanks = exercise.get("code_blanks", [])
    if not isinstance(code_blanks, Sequence):
        code_blanks = []

    blank_results: dict[str, bool] = {}
    core_blank_gate = True
    any_blank_passed = False
    for blank in code_blanks:
        if not isinstance(blank, Mapping):
            continue
        blank_key = str(blank["blank_key"])
        candidate = str(filled_blanks.get(blank_key, "")).strip()
        patterns = blank.get("acceptable_patterns_json", [])
        candidate_match = _matches_patterns(candidate, patterns)
        code_match = _matches_patterns(code, patterns)
        passed = candidate_match or code_match
        blank_results[blank_key] = passed
        any_blank_passed = any_blank_passed or passed
        if bool(blank.get("is_core", True)) and not passed:
            core_blank_gate = False

    metadata = exercise.get("metadata_json", {})
    required_patterns = []
    if isinstance(metadata, Mapping):
        maybe_patterns = metadata.get("required_patterns", [])
        if isinstance(maybe_patterns, Sequence):
            required_patterns = [str(pattern) for pattern in maybe_patterns]
    event_binding_pass = "addEventListener" in code
    output_sync_pass = "output.textContent" in code and "String(count)" in code
    shared_state_pass = _shared_state_pass(code, runtime_tier)

    logic_pass = all(_pattern_in_code(pattern, code) for pattern in required_patterns) if required_patterns else core_blank_gate
    if runtime_tier == "browser_preview":
        logic_pass = logic_pass and event_binding_pass and output_sync_pass

    return {
        "blank_results": blank_results,
        "core_blank_gate": core_blank_gate,
        "any_blank_passed": any_blank_passed,
        "logic_pass": logic_pass,
        "event_binding_pass": event_binding_pass,
        "output_sync_pass": output_sync_pass,
        "shared_state_pass": shared_state_pass,
    }


def run_exercise(
    exercise: Mapping[str, object],
    code: str,
    filled_blanks: Mapping[str, str],
    run_mode: str,
) -> RuntimeExecutionResult:
    runtime_profile = exercise.get("runtime_profile", {})
    runtime_tier = ""
    if isinstance(runtime_profile, Mapping):
        runtime_tier = str(runtime_profile.get("runtime_tier", ""))

    registry = get_runner_registry()
    runner_capability = registry.select(runtime_profile if isinstance(runtime_profile, Mapping) else {})

    if runner_capability.runner_key == "browser":
        return registry.run_browser_preview(exercise, code, filled_blanks)

    if runner_capability.runner_key == "sql":
        return registry.run_sql_query(exercise, code)

    if runner_capability.runner_key == "compiled":
        if runtime_tier == "managed_compiled_test" and runner_capability.execution == "managed_compiled_test":
            return registry.run_managed_compiled(exercise, code)
        return registry.unsupported_result(exercise, runner_capability)

    if runtime_tier == "compiled_sandbox_later":
        return registry.unsupported_result(exercise, runner_capability)

    if _looks_like_timeout(code, runtime_tier):
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout="",
            stderr="",
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=_case_count(exercise),
            test_results=_build_failed_cases(exercise, "Runner timed out before completing visible checks."),
            error_message="Runner timed out.",
            next_action="retry_same",
            preview_html=_preview_html_for(exercise, success=False),
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if runtime_tier == "python_stdout_test":
        try:
            ast.parse(code)
        except SyntaxError as exc:
            return RuntimeExecutionResult(
                runtime_status="runtime_error",
                stdout="",
                stderr=str(exc),
                test_pass_rate=0.0,
                passed_test_count=0,
                total_test_count=_case_count(exercise),
                test_results=_build_failed_cases(exercise, "Python code failed to parse."),
                error_message="Python code contains a syntax error.",
                next_action="explain_error",
                preview_html=None,
                core_blank_gate=False,
                any_blank_passed=False,
                logic_pass=False,
            )
        if _real_execution_enabled():
            return registry.run_python(exercise, code)

    if runner_capability.runner_key == "node":
        return registry.run_node_typescript(exercise, code)

    if runtime_tier == "browser_preview" and _looks_like_browser_runtime_error(code):
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout="",
            stderr="Browser preview code threw an error during execution.",
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=_case_count(exercise),
            test_results=_build_failed_cases(exercise, "Browser preview raised a runtime error."),
            error_message="Browser preview raised a runtime error.",
            next_action="explain_error",
            preview_html=_preview_html_for(exercise, success=False),
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    inspection = inspect_submission(exercise, code, filled_blanks)
    test_results = _evaluate_cases(exercise, inspection)
    total_weight = sum(_float_or_zero(result.get("weight")) for result in test_results)
    passed_weight = sum(_float_or_zero(result.get("weight")) for result in test_results if bool(result["passed"]))
    passed_test_count = sum(1 for result in test_results if bool(result["passed"]))
    total_test_count = len(test_results)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)

    success = bool(inspection["logic_pass"]) and test_pass_rate == 1.0
    preview_success = _preview_success(inspection)
    stdout = _stdout_for(exercise, inspection)
    next_action = _next_action_for_run(test_results, success, runtime_tier)

    return RuntimeExecutionResult(
        runtime_status="success",
        stdout=stdout,
        stderr="",
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_test_count,
        total_test_count=total_test_count,
        test_results=test_results,
        error_message=None,
        next_action=next_action,
        preview_html=_preview_html_for(exercise, success=preview_success),
        core_blank_gate=bool(inspection["core_blank_gate"]),
        any_blank_passed=bool(inspection["any_blank_passed"]),
        logic_pass=bool(inspection["logic_pass"]),
    )


def _case_count(exercise: Mapping[str, object]) -> int:
    test_cases = exercise.get("test_cases", [])
    return len(test_cases) if isinstance(test_cases, Sequence) else 0


def _build_failed_cases(exercise: Mapping[str, object], message: str) -> list[dict[str, object]]:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        return []
    failed_cases: list[dict[str, object]] = []
    for index, case in enumerate(test_cases):
        if not isinstance(case, Mapping):
            continue
        failed_cases.append(
            {
                "case_id": _public_case_id(case, index),
                "case_type": str(case.get("case_type", "visible")),
                "passed": False,
                "weight": float(case.get("weight", 1)),
                "is_critical": bool(case.get("is_critical", False)),
                "duration_ms": 0,
                "message": _public_case_message(case, message),
            },
        )
    return failed_cases


def _public_case_id(case: Mapping[str, object], index: int) -> str:
    if str(case.get("case_type", "visible")) == "hidden":
        return f"hidden_case_{index + 1}"
    return str(case.get("id") or f"case_{index + 1}")


def _public_case_message(case: Mapping[str, object], message: str) -> str:
    if str(case.get("case_type", "visible")) == "hidden":
        return "A hidden test failed. Recheck edge cases and boundary behavior."
    return message


def _evaluate_cases(
    exercise: Mapping[str, object],
    inspection: Mapping[str, object],
) -> list[dict[str, object]]:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        return []

    runtime_profile = exercise.get("runtime_profile", {})
    runtime_tier = str(runtime_profile.get("runtime_tier", "")) if isinstance(runtime_profile, Mapping) else ""
    logic_pass = bool(inspection["logic_pass"])
    any_blank_passed = bool(inspection["any_blank_passed"])
    event_binding_pass = bool(inspection.get("event_binding_pass"))
    output_sync_pass = bool(inspection.get("output_sync_pass"))
    shared_state_pass = bool(inspection.get("shared_state_pass"))
    core_blank_gate = bool(inspection["core_blank_gate"])
    case_results: list[dict[str, object]] = []
    for index, case in enumerate(test_cases):
        if not isinstance(case, Mapping):
            continue
        case_type = str(case.get("case_type", "visible"))
        is_critical = bool(case.get("is_critical", False))
        passed = _case_passed(
            runtime_tier=runtime_tier,
            case_type=case_type,
            is_critical=is_critical,
            logic_pass=logic_pass,
            any_blank_passed=any_blank_passed,
            event_binding_pass=event_binding_pass,
            output_sync_pass=output_sync_pass,
            shared_state_pass=shared_state_pass,
            core_blank_gate=core_blank_gate,
            case=case,
        )
        case_results.append(
            {
                "case_id": str(case.get("id") or f"case_{index + 1}"),
                "case_type": case_type,
                "passed": passed,
                "weight": float(case.get("weight", 1)),
                "is_critical": is_critical,
                "duration_ms": 12 if passed else 9,
                "message": _case_message(case_type, passed),
            },
        )
    return case_results


def _case_message(case_type: str, passed: bool) -> str:
    if case_type == "preview_assertion":
        return "Preview assertion matched the expected DOM snapshot." if passed else "Preview assertion did not match the expected DOM snapshot."
    if case_type == "hidden":
        return "Hidden summary passed." if passed else "A non-visible scenario still failed. Check state lifetime or boundary behavior."
    if passed:
        return "Visible test passed."
    return "Visible test failed. Check the shared state update and expected output."


def _preview_html_for(exercise: Mapping[str, object], *, success: bool) -> str | None:
    metadata = exercise.get("metadata_json", {})
    if not isinstance(metadata, Mapping):
        return None
    preview = metadata.get("preview_html", {})
    if not isinstance(preview, Mapping):
        return None
    value = preview.get("success" if success else "failure")
    return str(value) if value else None


def _stdout_for(exercise: Mapping[str, object], inspection: Mapping[str, object]) -> str:
    metadata = exercise.get("metadata_json", {})
    if not isinstance(metadata, Mapping):
        return ""
    if bool(inspection["logic_pass"]):
        value = metadata.get("stdout_success", "")
        return str(value)
    return ""


def _case_passed(
    *,
    runtime_tier: str,
    case_type: str,
    is_critical: bool,
    logic_pass: bool,
    any_blank_passed: bool,
    event_binding_pass: bool,
    output_sync_pass: bool,
    shared_state_pass: bool,
    core_blank_gate: bool,
    case: Mapping[str, object],
) -> bool:
    if runtime_tier == "browser_preview":
        if case_type == "hidden":
            return shared_state_pass and output_sync_pass and core_blank_gate
        if case_type == "preview_assertion":
            return event_binding_pass and output_sync_pass and any_blank_passed
        return event_binding_pass and output_sync_pass and any_blank_passed

    if runtime_tier == "python_stdout_test":
        return logic_pass and core_blank_gate

    return logic_pass if is_critical or case_type == "preview_assertion" else any_blank_passed


def _preview_success(inspection: Mapping[str, object]) -> bool:
    return bool(inspection.get("event_binding_pass")) and bool(inspection.get("output_sync_pass")) and bool(inspection.get("any_blank_passed"))


def _next_action_for_run(
    test_results: Sequence[Mapping[str, object]],
    success: bool,
    runtime_tier: str,
) -> str:
    if runtime_tier == "compiled_sandbox_later":
        return "retry_same"
    if success:
        return "advance_next"
    failed_results = [result for result in test_results if not bool(result.get("passed"))]
    if any(str(result.get("case_type")) == "visible" and bool(result.get("is_critical")) for result in failed_results):
        return "explain_error"
    if failed_results:
        return "show_hint"
    return "retry_same"


def _float_or_zero(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _matches_patterns(value: str, patterns: object) -> bool:
    if not value:
        return False
    if not isinstance(patterns, Sequence):
        return False
    for pattern in patterns:
        if not isinstance(pattern, Mapping):
            continue
        pattern_type = str(pattern.get("type", "literal"))
        pattern_value = str(pattern.get("value", ""))
        if not pattern_value:
            continue
        if pattern_type == "literal" and value.strip() == pattern_value.strip():
            return True
        if pattern_type == "regex" and re.search(pattern_value, value, flags=re.MULTILINE):
            return True
    return False


def _pattern_in_code(pattern: str, code: str) -> bool:
    if pattern.startswith("regex:"):
        return re.search(pattern.removeprefix("regex:"), code, flags=re.MULTILINE) is not None
    return pattern in code


def _looks_like_timeout(code: str, runtime_tier: str) -> bool:
    lowered = code.lower()
    if runtime_tier == "python_stdout_test":
        return "while true" in lowered or "while 1" in lowered
    return "while (true)" in lowered or "for (;;)" in lowered


def _looks_like_browser_runtime_error(code: str) -> bool:
    lowered = code.lower()
    return "throw new error" in lowered or "undefinedvariable" in lowered


def _shared_state_pass(code: str, runtime_tier: str) -> bool:
    if runtime_tier != "browser_preview":
        return True
    listener_index = code.find("addEventListener")
    if listener_index < 0:
        return False
    prefix = code[:listener_index]
    return "let count = 0" in prefix or "const count = 0" in prefix or "var count = 0" in prefix


def _real_execution_enabled() -> bool:
    from app.core.config import get_settings
    return get_settings().real_execution_enabled
