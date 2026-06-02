from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from app.services.managed_compiled_runner import (
    ManagedCompiledCommandResult,
    execute_managed_compiled_with_tests,
)
from app.services.runtime_runner import run_exercise


def _cases() -> list[dict[str, object]]:
    return [
        {
            "id": "visible_increment",
            "case_type": "visible",
            "input_json": {"args": [1]},
            "expected_output_json": {"return": 2},
            "weight": 1,
            "is_critical": True,
        },
        {
            "id": "hidden_secret_edge",
            "case_type": "hidden",
            "input_json": {"args": [2]},
            "expected_output_json": {"return": 999},
            "weight": 2,
            "is_critical": True,
        },
    ]


def _exercise(language: str = "java") -> dict[str, object]:
    return {
        "runtime_profile": {
            "runtime_tier": "managed_compiled_test",
            "language": language,
            "runner": "compiled",
        },
        "metadata_json": {"entry_function": "increment"},
        "test_cases": _cases(),
    }


def _commands_for(language: str) -> dict[str, str]:
    if language == "java":
        return {"javac": "javac", "java": "java"}
    if language == "go":
        return {"go": "go"}
    return {"dotnet": "dotnet"}


def _success_payload() -> str:
    return "__AEARN_RESULT__" + json.dumps(
        {
            "status": "success",
            "stdout": "runner stdout",
            "error": None,
            "test_results": [
                {
                    "case_id": "visible_increment",
                    "case_type": "visible",
                    "passed": True,
                    "weight": 1,
                    "is_critical": True,
                    "message": "Passed",
                    "duration_ms": 1,
                },
                {
                    "case_id": "hidden_secret_edge",
                    "case_type": "hidden",
                    "passed": True,
                    "weight": 2,
                    "is_critical": True,
                    "message": "Hidden passed",
                    "duration_ms": 1,
                },
            ],
        },
    )


def test_managed_compiled_runner_maps_success_for_java_go_and_csharp() -> None:
    seen_workspaces: list[Path] = []

    def fake_runner(
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> ManagedCompiledCommandResult:
        del env, timeout_s
        seen_workspaces.append(cwd)
        if argv[0] == "javac":
            assert (cwd / "Main.java").exists()
            assert (cwd / "AearnHarness.java").exists()
            return ManagedCompiledCommandResult(returncode=0, stdout="", stderr="")
        if argv[0] == "go":
            assert (cwd / "submission.go").exists()
            assert (cwd / "aearn_harness.go").exists()
            return ManagedCompiledCommandResult(returncode=0, stdout=_success_payload(), stderr="")
        if argv[0] == "dotnet":
            assert (cwd / "Program.cs").exists()
            assert (cwd / "AearnCompiled.csproj").exists()
            return ManagedCompiledCommandResult(returncode=0, stdout=_success_payload(), stderr="")
        return ManagedCompiledCommandResult(returncode=0, stdout=_success_payload(), stderr="")

    for language, code in [
        ("java", "public class Main { public static int increment(int value) { return value + 1; } }"),
        ("go", "package main\n\nfunc increment(value int) int { return value + 1 }\n"),
        ("csharp", "public static class Submission { public static int increment(int value) { return value + 1; } }\n"),
    ]:
        result = execute_managed_compiled_with_tests(
            code,
            _cases(),
            language=language,
            entry_function="increment",
            commands=_commands_for(language),
            detect_commands=False,
            command_runner=fake_runner,
        )

        assert result.status == "success"
        assert result.stdout == "runner stdout"
        assert len(result.test_results) == 2

    assert seen_workspaces
    assert all("aearn-compiled-" in str(path) for path in seen_workspaces)


def test_managed_compiled_runner_missing_toolchain_is_non_crashing() -> None:
    result = execute_managed_compiled_with_tests(
        "public class Main {}",
        _cases(),
        language="java",
        entry_function="increment",
        commands={},
        detect_commands=False,
    )

    assert result.status == "missing_toolchain"
    assert "JDK" in (result.error or "")


def test_managed_compiled_runner_reports_compile_error_and_redacts_temp_path() -> None:
    def fake_runner(
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> ManagedCompiledCommandResult:
        del argv, env, timeout_s
        return ManagedCompiledCommandResult(returncode=1, stdout="", stderr=f"{cwd}\\Main.java: bad syntax")

    result = execute_managed_compiled_with_tests(
        "public class Main {",
        _cases(),
        language="java",
        entry_function="increment",
        commands=_commands_for("java"),
        detect_commands=False,
        command_runner=fake_runner,
    )

    assert result.status == "compile_error"
    assert "[temp workspace]" in (result.error or "")
    assert "aearn-compiled-" not in (result.error or "")


def test_managed_compiled_runner_reports_runtime_error_timeout_and_unsupported() -> None:
    def runtime_error_runner(
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> ManagedCompiledCommandResult:
        del cwd, env, timeout_s
        if argv[0] == "javac":
            return ManagedCompiledCommandResult(returncode=0, stdout="", stderr="")
        return ManagedCompiledCommandResult(returncode=1, stdout="", stderr="boom")

    runtime_error = execute_managed_compiled_with_tests(
        "public class Main { public static int increment(int value) { throw new RuntimeException(\"boom\"); } }",
        _cases(),
        language="java",
        entry_function="increment",
        commands=_commands_for("java"),
        detect_commands=False,
        command_runner=runtime_error_runner,
    )
    unsupported = execute_managed_compiled_with_tests(
        "int main() { return 0; }",
        _cases(),
        language="cpp",
        entry_function="increment",
    )

    def timeout_runner(
        argv: Sequence[str],
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> ManagedCompiledCommandResult:
        del cwd, env, timeout_s
        if argv[0] == "javac":
            return ManagedCompiledCommandResult(returncode=0, stdout="", stderr="")
        return ManagedCompiledCommandResult(returncode=0, stdout="", stderr="", timed_out=True)

    timeout = execute_managed_compiled_with_tests(
        "public class Main { public static int increment(int value) { while (true) {} } }",
        _cases(),
        language="java",
        entry_function="increment",
        commands=_commands_for("java"),
        detect_commands=False,
        command_runner=timeout_runner,
    )

    assert runtime_error.status == "runtime_error"
    assert timeout.status == "timeout"
    assert unsupported.status == "unsupported"


def test_managed_compiled_runtime_adapter_redacts_hidden_results(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.services import runner_registry
    from app.services.managed_compiled_runner import ManagedCompiledExecutionResult, ManagedCompiledTestCaseResult

    def fake_execute(*args, **kwargs):  # type: ignore[no-untyped-def]
        return ManagedCompiledExecutionResult(
            status="test_failure",
            stdout="",
            stderr="",
            error=None,
            test_results=[
                ManagedCompiledTestCaseResult(
                    case_id="visible_increment",
                    case_type="visible",
                    passed=True,
                    weight=1,
                    is_critical=True,
                    message="Passed",
                    duration_ms=1,
                ),
                ManagedCompiledTestCaseResult(
                    case_id="hidden_secret_edge",
                    case_type="hidden",
                    passed=False,
                    weight=2,
                    is_critical=True,
                    message="Expected 999, got 3",
                    duration_ms=1,
                ),
            ],
            total_duration_ms=2,
        )

    monkeypatch.setattr(runner_registry, "execute_managed_compiled_with_tests", fake_execute)

    result = run_exercise(_exercise(), "public class Main {}", {}, "visible_tests")
    serialized = repr(result.test_results)

    assert result.runtime_status == "test_failure"
    assert result.test_pass_rate < 1.0
    assert result.next_action == "show_hint"
    assert result.test_results[1]["case_id"] == "hidden_case_2"
    assert result.test_results[1]["message"] == "A hidden test failed. Recheck edge cases and boundary behavior."
    assert "hidden_secret_edge" not in serialized
    assert "999" not in serialized
