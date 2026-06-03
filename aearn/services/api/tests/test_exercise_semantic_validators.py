from __future__ import annotations

from app.services.exercises.syntax_validators import validate_exercise_semantics


def test_python_validator_requires_list_comprehension_for_tag() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "def summarize_scores(scores):\n"
                "    normalized = [score for score in scores]\n"
                "    return sum(normalized)\n"
            ),
            "metadata_json": {"target_skill_tags": ["list_comprehension"]},
        },
        knowledge_point={"skill_tags_json": ["python", "list_comprehension"]},
        runtime_profile={"language": "python", "runtime_tier": "python_stdout_test"},
    )

    assert report.passed is True
    assert report.matched_tags == ["list_comprehension"]
    assert report.missing_tags == []


def test_python_validator_rejects_generic_loop_for_list_comprehension_tag() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "def summarize_scores(scores):\n"
                "    total = 0\n"
                "    for score in scores:\n"
                "        total += score\n"
                "    return total\n"
            ),
            "metadata_json": {"target_skill_tags": ["python"]},
        },
        knowledge_point={"skill_tags_json": ["python", "list_comprehension"]},
        runtime_profile={"language": "python", "runtime_tier": "python_stdout_test"},
    )

    assert report.passed is False
    assert report.failure_code == "missing_required_skill"
    assert report.missing_tags == ["list_comprehension"]


def test_python_validator_requires_candidate_claim_for_checked_tag() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "def summarize_scores(scores):\n"
                "    normalized = [score for score in scores]\n"
                "    return sum(normalized)\n"
            ),
            "metadata_json": {"target_skill_tags": ["python"]},
        },
        knowledge_point={"skill_tags_json": ["python", "list_comprehension"]},
        runtime_profile={"language": "python", "runtime_tier": "python_stdout_test"},
    )

    assert report.passed is False
    assert report.failure_code == "missing_required_skill"
    assert report.missing_tags == ["list_comprehension"]


def test_sql_validator_checks_select_filtering_sorting_joins_and_aggregation() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "SELECT departments.name, COUNT(*) AS learner_count\n"
                "FROM learners\n"
                "JOIN departments ON departments.id = learners.department_id\n"
                "WHERE learners.track = 'sql'\n"
                "GROUP BY departments.name\n"
                "ORDER BY departments.name\n"
            ),
            "metadata_json": {"target_skill_tags": ["select", "filtering", "sorting", "joins", "aggregation"]},
        },
        knowledge_point={"skill_tags_json": ["sql", "select", "filtering", "sorting", "joins", "aggregation"]},
        runtime_profile={"language": "sql", "runtime_tier": "sql_query_test"},
    )

    assert report.passed is True
    assert report.matched_tags == ["select", "filtering", "sorting", "joins", "aggregation"]


def test_javascript_validator_checks_functions_and_dom_events() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "function updateCounter() {\n"
                "  const button = document.querySelector('#counter-button');\n"
                "  button.addEventListener('click', () => updateCounter());\n"
                "}\n"
            ),
            "metadata_json": {"target_skill_tags": ["functions", "dom_events"]},
        },
        knowledge_point={"skill_tags_json": ["functions", "dom_events"]},
        runtime_profile={"language": "javascript", "runtime_tier": "browser_preview"},
    )

    assert report.passed is True
    assert report.matched_tags == ["functions", "dom_events"]


def test_typescript_validator_checks_functions_and_types() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": "export function increment(value: number): number {\n  return value + 1;\n}\n",
            "metadata_json": {"target_skill_tags": ["functions", "types"]},
        },
        knowledge_point={"skill_tags_json": ["typescript", "functions", "types"]},
        runtime_profile={"language": "typescript", "runtime_tier": "node_typescript_test"},
    )

    assert report.passed is True
    assert report.matched_tags == ["functions", "types"]


def test_html_css_validator_checks_semantics_accessibility_layout_and_responsive_rules() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "<main class=\"dashboard active\">\n"
                "  <section aria-label=\"Progress\"><h1>Progress</h1><button>Continue</button></section>\n"
                "</main>\n"
                "<style>\n"
                ".dashboard { display: grid; padding: 1rem; }\n"
                ".dashboard.active { border: 1px solid #0f766e; }\n"
                "@media (max-width: 640px) { .dashboard { display: flex; } }\n"
                "</style>\n"
            ),
            "metadata_json": {
                "target_skill_tags": ["semantics", "accessibility", "selectors", "box_model", "state", "layout", "responsive"]
            },
        },
        knowledge_point={
            "skill_tags_json": ["html", "semantics", "accessibility", "selectors", "box_model", "state", "layout", "responsive"]
        },
        runtime_profile={"language": "html_css", "runtime_tier": "browser_preview"},
    )

    assert report.passed is True
    assert report.matched_tags == ["semantics", "accessibility", "selectors", "box_model", "state", "layout", "responsive"]


def test_html_css_validator_rejects_missing_responsive_marker() -> None:
    report = validate_exercise_semantics(
        candidate_payload={
            "solution_reference": (
                "<main class=\"dashboard\"><section><h1>Progress</h1></section></main>\n"
                "<style>.dashboard { display: grid; padding: 1rem; }</style>\n"
            ),
            "metadata_json": {"target_skill_tags": ["responsive"]},
        },
        knowledge_point={"skill_tags_json": ["css", "responsive"]},
        runtime_profile={"language": "html_css", "runtime_tier": "browser_preview"},
    )

    assert report.passed is False
    assert report.missing_tags == ["responsive"]


def test_managed_compiled_validators_check_java_go_and_csharp_function_types() -> None:
    cases = [
        (
            "java",
            "public class Main { public static int increment(int value) { return value + 1; } }",
        ),
        (
            "go",
            "package main\nfunc increment(value int) int {\n  return value + 1\n}\n",
        ),
        (
            "csharp",
            "public class Program { public static int Increment(int value) { return value + 1; } }",
        ),
    ]

    for language, solution_reference in cases:
        report = validate_exercise_semantics(
            candidate_payload={
                "solution_reference": solution_reference,
                "metadata_json": {"target_skill_tags": ["functions", "types"]},
            },
            knowledge_point={"skill_tags_json": [language, "functions", "types"]},
            runtime_profile={"language": language, "runtime_tier": "managed_compiled_test"},
        )

        assert report.passed is True
        assert report.matched_tags == ["functions", "types"]
