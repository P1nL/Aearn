from __future__ import annotations

from app.services.runners.browser_preview_runner import execute_browser_preview_with_tests
from app.services.runners.runtime_runner import run_exercise


def _javascript_event_exercise() -> dict[str, object]:
    return {
        "runtime_profile": {
            "runtime_tier": "browser_preview",
            "language": "javascript",
            "runner": "browser",
        },
        "metadata_json": {
            "required_patterns": ["addEventListener", "count += 1", "output.textContent"],
            "preview_html": {
                "success": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">1</p>",
                "failure": "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">0</p>",
            },
            "stdout_success": "Preview ready",
        },
        "code_blanks": [
            {
                "blank_key": "increment",
                "acceptable_patterns_json": [{"type": "literal", "value": "count += 1"}],
                "is_core": True,
            },
        ],
        "test_cases": [
            {
                "id": "visible_event_binding",
                "case_type": "visible",
                "input_json": {},
                "expected_output_json": {},
                "weight": 1,
                "is_critical": True,
            },
            {
                "id": "preview_output_sync",
                "case_type": "preview_assertion",
                "input_json": {"selector": "#counter-output"},
                "expected_output_json": {"textContent": "1"},
                "weight": 1,
                "is_critical": True,
            },
        ],
    }


def _html_css_static_exercise() -> dict[str, object]:
    return {
        "runtime_profile": {
            "runtime_tier": "browser_preview",
            "language": "html_css",
            "runner": "browser",
        },
        "metadata_json": {
            "required_patterns": ["pill active", "display: grid"],
            "preview_html": {
                "success": "<button class=\"pill active\">Preview ready</button>",
                "failure": "<button class=\"pill\">Preview missing active class</button>",
            },
        },
        "code_blanks": [
            {
                "blank_key": "active_class",
                "acceptable_patterns_json": [{"type": "literal", "value": "active"}],
                "is_core": True,
            },
        ],
        "test_cases": [
            {
                "id": "visible_static_structure",
                "case_type": "visible",
                "input_json": {"selector": ".pill.active"},
                "expected_output_json": {"exists": True},
                "weight": 1,
                "is_critical": True,
            },
            {
                "id": "preview_static_structure",
                "case_type": "preview_assertion",
                "input_json": {"selector": ".pill.active"},
                "expected_output_json": {"exists": True},
                "weight": 1,
                "is_critical": True,
            },
        ],
    }


def _passing_javascript_code() -> str:
    return (
        'const button = document.querySelector("#counter-button");\n'
        'const output = document.querySelector("#counter-output");\n'
        "let count = 0;\n"
        'button.addEventListener("click", () => {\n'
        "  count += 1;\n"
        "  output.textContent = String(count);\n"
        "});\n"
    )


def test_browser_preview_runner_executes_javascript_event_flow() -> None:
    result = execute_browser_preview_with_tests(
        _javascript_event_exercise(),
        _passing_javascript_code(),
        {"increment": "count += 1"},
    )

    assert result.status == "success"
    assert result.logic_pass is True
    assert result.stdout == "Preview ready"
    assert result.preview_html == "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">1</p>"
    assert all(test.passed for test in result.test_results)


def test_browser_preview_runner_allows_html_css_static_preview_without_js_event_binding() -> None:
    result = execute_browser_preview_with_tests(
        _html_css_static_exercise(),
        '<style>.card { display: grid; }</style><button class="pill active">Preview</button>',
        {"active_class": "active"},
    )

    assert result.status == "success"
    assert result.logic_pass is True
    assert result.preview_html == "<button class=\"pill active\">Preview ready</button>"
    assert all(test.passed for test in result.test_results)


def test_browser_preview_runner_reports_runtime_error() -> None:
    result = execute_browser_preview_with_tests(
        _javascript_event_exercise(),
        "throw new Error('boom');",
        {},
    )

    assert result.status == "runtime_error"
    assert result.error == "Browser preview raised a runtime error."
    assert result.preview_html == "<button id=\"counter-button\">Clicked</button><p id=\"counter-output\">0</p>"
    assert all(test.passed is False for test in result.test_results)


def test_browser_preview_runner_reports_timeout() -> None:
    result = execute_browser_preview_with_tests(
        _javascript_event_exercise(),
        "while (true) {}",
        {},
    )

    assert result.status == "timeout"
    assert result.error == "Browser preview runner timed out."
    assert all(test.passed is False for test in result.test_results)


def test_browser_preview_runtime_adapter_redacts_hidden_results() -> None:
    exercise = _javascript_event_exercise()
    exercise["test_cases"].append(
        {
            "id": "hidden_secret_shared_state_case",
            "case_type": "hidden",
            "input_json": {"selector": "#counter-output"},
            "expected_output_json": {"textContent": "999"},
            "weight": 2,
            "is_critical": True,
        },
    )

    result = run_exercise(
        exercise,
        'const button = document.querySelector("#counter-button");\n'
        'const output = document.querySelector("#counter-output");\n'
        'button.addEventListener("click", () => {\n'
        "  let count = 0;\n"
        "  count += 1;\n"
        "  output.textContent = String(count);\n"
        "});\n",
        {"increment": "count += 1"},
        "visible_tests",
    )
    serialized = repr(result.test_results)

    assert result.runtime_status == "success"
    assert result.test_pass_rate < 1.0
    assert "hidden_secret_shared_state_case" not in serialized
    assert "999" not in serialized
    assert any(item["case_id"] == "hidden_case_3" for item in result.test_results)
    assert any(item["message"] == "A hidden test failed. Recheck edge cases and boundary behavior." for item in result.test_results)
