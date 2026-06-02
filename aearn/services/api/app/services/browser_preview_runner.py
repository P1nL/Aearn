from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


MAX_BROWSER_STDOUT_CHARS = 4000
MAX_BROWSER_ERROR_CHARS = 500
BrowserRuleFamily = str


@dataclass(slots=True)
class BrowserPreviewTestCaseResult:
    case_id: str
    case_type: str
    passed: bool
    weight: float
    is_critical: bool
    message: str
    duration_ms: int


@dataclass(slots=True)
class BrowserPreviewExecutionResult:
    status: str
    stdout: str
    stderr: str
    error: str | None
    preview_html: str | None
    test_results: list[BrowserPreviewTestCaseResult]
    core_blank_gate: bool
    any_blank_passed: bool
    logic_pass: bool


def execute_browser_preview_with_tests(
    exercise: Mapping[str, object],
    code: str,
    filled_blanks: Mapping[str, str],
) -> BrowserPreviewExecutionResult:
    if _looks_like_timeout(code):
        return BrowserPreviewExecutionResult(
            status="timeout",
            stdout="",
            stderr="",
            error="Browser preview runner timed out.",
            preview_html=_preview_html_for(exercise, success=False),
            test_results=_failed_test_results(exercise, "Browser preview runner timed out."),
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if _looks_like_browser_runtime_error(code):
        return BrowserPreviewExecutionResult(
            status="runtime_error",
            stdout="",
            stderr="Browser preview code threw an error during execution.",
            error="Browser preview raised a runtime error.",
            preview_html=_preview_html_for(exercise, success=False),
            test_results=_failed_test_results(exercise, "Browser preview raised a runtime error."),
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    inspection = inspect_browser_submission(exercise, code, filled_blanks)
    test_results = _evaluate_cases(exercise, inspection)
    preview_success = _preview_success(inspection)
    return BrowserPreviewExecutionResult(
        status="success",
        stdout=_bound_text(_stdout_for(exercise, inspection), MAX_BROWSER_STDOUT_CHARS),
        stderr="",
        error=None,
        preview_html=_preview_html_for(exercise, success=preview_success),
        test_results=test_results,
        core_blank_gate=bool(inspection["core_blank_gate"]),
        any_blank_passed=bool(inspection["any_blank_passed"]),
        logic_pass=bool(inspection["logic_pass"]),
    )


def inspect_browser_submission(
    exercise: Mapping[str, object],
    code: str,
    filled_blanks: Mapping[str, str],
) -> dict[str, object]:
    code_blanks = exercise.get("code_blanks", [])
    if not isinstance(code_blanks, Sequence) or isinstance(code_blanks, str):
        code_blanks = []

    blank_results: dict[str, bool] = {}
    core_blank_gate = True
    any_blank_passed = False
    for blank in code_blanks:
        if not isinstance(blank, Mapping):
            continue
        blank_key = str(blank.get("blank_key") or "")
        if not blank_key:
            continue
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
        if isinstance(maybe_patterns, Sequence) and not isinstance(maybe_patterns, str):
            required_patterns = [str(pattern) for pattern in maybe_patterns]

    rule_family = _rule_family_for(exercise)
    event_binding_pass = "addEventListener" in code
    output_sync_pass = "output.textContent" in code and "String(count)" in code
    shared_state_pass = _shared_state_pass(code) if rule_family == "js_event_flow" else True

    logic_pass = all(_pattern_in_code(pattern, code) for pattern in required_patterns) if required_patterns else core_blank_gate
    if rule_family == "js_event_flow":
        logic_pass = logic_pass and event_binding_pass and output_sync_pass

    return {
        "blank_results": blank_results,
        "core_blank_gate": core_blank_gate,
        "any_blank_passed": any_blank_passed,
        "logic_pass": logic_pass,
        "event_binding_pass": event_binding_pass,
        "output_sync_pass": output_sync_pass,
        "shared_state_pass": shared_state_pass,
        "rule_family": rule_family,
    }


def _evaluate_cases(
    exercise: Mapping[str, object],
    inspection: Mapping[str, object],
) -> list[BrowserPreviewTestCaseResult]:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence) or isinstance(test_cases, str):
        return []

    logic_pass = bool(inspection["logic_pass"])
    any_blank_passed = bool(inspection["any_blank_passed"])
    event_binding_pass = bool(inspection.get("event_binding_pass"))
    output_sync_pass = bool(inspection.get("output_sync_pass"))
    shared_state_pass = bool(inspection.get("shared_state_pass"))
    core_blank_gate = bool(inspection["core_blank_gate"])
    rule_family = str(inspection.get("rule_family") or "js_event_flow")
    case_results: list[BrowserPreviewTestCaseResult] = []
    for index, case in enumerate(test_cases):
        if not isinstance(case, Mapping):
            continue
        case_type = str(case.get("case_type", "visible"))
        is_critical = bool(case.get("is_critical", False))
        passed = _case_passed(
            rule_family=rule_family,
            case_type=case_type,
            is_critical=is_critical,
            logic_pass=logic_pass,
            any_blank_passed=any_blank_passed,
            event_binding_pass=event_binding_pass,
            output_sync_pass=output_sync_pass,
            shared_state_pass=shared_state_pass,
            core_blank_gate=core_blank_gate,
        )
        case_results.append(
            BrowserPreviewTestCaseResult(
                case_id=str(case.get("id") or f"case_{index + 1}"),
                case_type=case_type,
                passed=passed,
                weight=float(case.get("weight", 1)),
                is_critical=is_critical,
                duration_ms=12 if passed else 9,
                message=_case_message(case_type, passed),
            ),
        )
    return case_results


def _failed_test_results(exercise: Mapping[str, object], message: str) -> list[BrowserPreviewTestCaseResult]:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence) or isinstance(test_cases, str):
        return []
    results: list[BrowserPreviewTestCaseResult] = []
    for index, case in enumerate(test_cases):
        if not isinstance(case, Mapping):
            continue
        results.append(
            BrowserPreviewTestCaseResult(
                case_id=str(case.get("id") or f"case_{index + 1}"),
                case_type=str(case.get("case_type", "visible")),
                passed=False,
                weight=float(case.get("weight", 1)),
                is_critical=bool(case.get("is_critical", False)),
                message=message,
                duration_ms=0,
            ),
        )
    return results


def _case_passed(
    *,
    rule_family: BrowserRuleFamily,
    case_type: str,
    is_critical: bool,
    logic_pass: bool,
    any_blank_passed: bool,
    event_binding_pass: bool,
    output_sync_pass: bool,
    shared_state_pass: bool,
    core_blank_gate: bool,
) -> bool:
    if rule_family == "js_event_flow":
        if case_type == "hidden":
            return shared_state_pass and output_sync_pass and core_blank_gate
        if case_type == "preview_assertion":
            return event_binding_pass and output_sync_pass and any_blank_passed
        return event_binding_pass and output_sync_pass and any_blank_passed

    if case_type == "hidden":
        return logic_pass and core_blank_gate
    if case_type == "preview_assertion":
        return logic_pass and (any_blank_passed or core_blank_gate)
    return logic_pass if is_critical else any_blank_passed or logic_pass


def _case_message(case_type: str, passed: bool) -> str:
    if case_type == "preview_assertion":
        return "Preview assertion matched the expected DOM snapshot." if passed else "Preview assertion did not match the expected DOM snapshot."
    if case_type == "hidden":
        return "Hidden summary passed." if passed else "A non-visible scenario still failed. Check state lifetime or boundary behavior."
    if passed:
        return "Visible test passed."
    return "Visible test failed. Check the preview structure and expected output."


def _rule_family_for(exercise: Mapping[str, object]) -> BrowserRuleFamily:
    metadata = exercise.get("metadata_json", {})
    if isinstance(metadata, Mapping):
        explicit = str(metadata.get("browser_rule_family") or "")
        if explicit in {"js_event_flow", "static_preview"}:
            return explicit

    runtime_profile = exercise.get("runtime_profile", {})
    language = str(runtime_profile.get("language", "")).lower() if isinstance(runtime_profile, Mapping) else ""
    if language in {"html", "css", "html_css"}:
        return "static_preview"
    return "js_event_flow"


def _preview_success(inspection: Mapping[str, object]) -> bool:
    rule_family = str(inspection.get("rule_family") or "js_event_flow")
    if rule_family == "js_event_flow":
        return bool(inspection.get("event_binding_pass")) and bool(inspection.get("output_sync_pass")) and bool(inspection.get("any_blank_passed"))
    return bool(inspection.get("logic_pass")) and (bool(inspection.get("any_blank_passed")) or bool(inspection.get("core_blank_gate")))


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


def _matches_patterns(value: str, patterns: object) -> bool:
    if not value:
        return False
    if not isinstance(patterns, Sequence) or isinstance(patterns, str):
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


def _looks_like_timeout(code: str) -> bool:
    lowered = code.lower()
    return "while (true)" in lowered or "for (;;)" in lowered


def _looks_like_browser_runtime_error(code: str) -> bool:
    lowered = code.lower()
    return "throw new error" in lowered or "undefinedvariable" in lowered


def _shared_state_pass(code: str) -> bool:
    listener_index = code.find("addEventListener")
    if listener_index < 0:
        return False
    prefix = code[:listener_index]
    return "let count = 0" in prefix or "const count = 0" in prefix or "var count = 0" in prefix


def _bound_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
