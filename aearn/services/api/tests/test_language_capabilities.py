from __future__ import annotations

from app.services.language_capabilities import (
    all_language_capabilities,
    capabilities_for_public_course_language,
    get_language_capability,
    public_course_language_ids,
    require_language_capability,
)


def test_language_capability_matrix_covers_target_mainstream_languages() -> None:
    language_ids = {capability.language_id for capability in all_language_capabilities()}

    assert language_ids == {
        "python",
        "javascript",
        "typescript",
        "java",
        "go",
        "csharp",
        "rust",
        "cpp",
        "sql",
        "html",
        "css",
    }


def test_current_public_course_languages_map_to_capabilities() -> None:
    assert public_course_language_ids() == ("javascript", "python", "java", "cpp", "html_css")
    assert [cap.language_id for cap in capabilities_for_public_course_language("javascript")] == ["javascript"]
    assert [cap.language_id for cap in capabilities_for_public_course_language("python")] == ["python"]
    assert [cap.language_id for cap in capabilities_for_public_course_language("java")] == ["java"]
    assert [cap.language_id for cap in capabilities_for_public_course_language("cpp")] == ["cpp"]
    assert [cap.language_id for cap in capabilities_for_public_course_language("html_css")] == ["html", "css"]


def test_python_capability_discloses_subprocess_not_container_sandbox() -> None:
    capability = require_language_capability("python")

    assert capability.enabled_for_public_selection is True
    assert capability.execution == "python_stdout_test"
    assert capability.runner_key == "python"
    assert capability.supports_execution is True
    assert capability.sandbox_boundary == "subprocess_restricted_not_container"
    assert "not OS-container isolation" in capability.ux_disclosure


def test_typescript_is_executable_but_not_public_selectable() -> None:
    typescript = require_language_capability("typescript")

    assert typescript.enabled_for_public_selection is False
    assert typescript.execution == "node_typescript_test"
    assert typescript.supports_execution is True
    assert typescript.supports_tests is True
    assert typescript.runner_key == "node"
    assert typescript.sandbox_boundary == "node_vm_restricted_not_container"


def test_planned_languages_do_not_claim_execution() -> None:
    sql = require_language_capability("sql")
    java = require_language_capability("java")
    go = require_language_capability("go")
    csharp = require_language_capability("csharp")
    rust = require_language_capability("rust")
    cpp = require_language_capability("cpp")

    assert sql.execution == "sql_query_test"
    assert sql.supports_execution is True
    assert sql.enabled_for_public_selection is False
    assert "SQLite teaching dialect" in sql.ux_disclosure
    assert java.execution == "managed_compiled_test"
    assert java.supports_execution is True
    assert java.enabled_for_public_selection is True
    assert go.execution == "managed_compiled_test"
    assert go.supports_execution is True
    assert go.enabled_for_public_selection is False
    assert csharp.execution == "managed_compiled_test"
    assert csharp.supports_execution is True
    assert csharp.enabled_for_public_selection is False
    assert rust.execution == "compiled_later"
    assert rust.supports_execution is False
    assert cpp.execution == "compiled_later"
    assert cpp.supports_execution is False


def test_alias_lookup_normalizes_common_language_names() -> None:
    assert require_language_capability("JS").language_id == "javascript"
    assert require_language_capability("C#").language_id == "csharp"
    assert require_language_capability("c++").language_id == "cpp"
    assert require_language_capability("golang").language_id == "go"
    assert get_language_capability("unknown-language") is None
