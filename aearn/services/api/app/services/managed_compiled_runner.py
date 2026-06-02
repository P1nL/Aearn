from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


MAX_COMPILED_OUTPUT_CHARS = 4000
MAX_COMPILED_ERROR_CHARS = 2000
RESULT_PREFIX = "__AEARN_RESULT__"
SUPPORTED_LANGUAGES = {"java", "go", "csharp"}


@dataclass(slots=True)
class ManagedCompiledTestCaseResult:
    case_id: str
    case_type: str
    passed: bool
    weight: float
    is_critical: bool
    message: str
    duration_ms: int


@dataclass(slots=True)
class ManagedCompiledExecutionResult:
    status: str
    stdout: str
    stderr: str
    error: str | None
    test_results: list[ManagedCompiledTestCaseResult]
    total_duration_ms: int


@dataclass(frozen=True, slots=True)
class ManagedCompiledCommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str], float], ManagedCompiledCommandResult]


class UnsupportedCompiledExerciseError(ValueError):
    pass


def execute_managed_compiled_with_tests(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    *,
    language: str,
    entry_function: str | None = None,
    timeout_s: float = 10.0,
    commands: Mapping[str, str] | None = None,
    detect_commands: bool = True,
    command_runner: CommandRunner | None = None,
) -> ManagedCompiledExecutionResult:
    start = time.perf_counter()
    normalized_language = _normalize_language(language)
    if normalized_language not in SUPPORTED_LANGUAGES:
        return _result(
            "unsupported",
            start,
            error="Only Java, Go, and C# are supported by managed_compiled_test.",
        )

    if test_cases and not entry_function:
        return _result(
            "unsupported",
            start,
            error="Managed compiled exercises require metadata_json.entry_function for function-test harnesses.",
        )

    detected_commands = _resolve_commands(normalized_language, commands or {}, detect_commands)
    missing_message = _missing_toolchain_message(normalized_language, detected_commands)
    if missing_message is not None:
        return _result("missing_toolchain", start, error=missing_message)
    resolved_commands = {name: command for name, command in detected_commands.items() if command is not None}

    runner = command_runner or run_compiled_command
    try:
        with tempfile.TemporaryDirectory(prefix="aearn-compiled-") as temp_dir:
            workspace = Path(temp_dir)
            if normalized_language == "java":
                return _execute_java(
                    code,
                    test_cases,
                    entry_function or "main",
                    commands=resolved_commands,
                    runner=runner,
                    workspace=workspace,
                    timeout_s=timeout_s,
                    start=start,
                )
            if normalized_language == "go":
                return _execute_go(
                    code,
                    test_cases,
                    entry_function or "main",
                    commands=resolved_commands,
                    runner=runner,
                    workspace=workspace,
                    timeout_s=timeout_s,
                    start=start,
                )
            return _execute_csharp(
                code,
                test_cases,
                entry_function or "main",
                commands=resolved_commands,
                runner=runner,
                workspace=workspace,
                timeout_s=timeout_s,
                start=start,
            )
    except UnsupportedCompiledExerciseError as exc:
        return _result("unsupported", start, error=str(exc))


def run_compiled_command(
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    timeout_s: float,
) -> ManagedCompiledCommandResult:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd),
            env=dict(env),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ManagedCompiledCommandResult(
            returncode=124,
            stdout=_timeout_text(exc.stdout),
            stderr=_timeout_text(exc.stderr),
            timed_out=True,
        )
    except OSError as exc:
        return ManagedCompiledCommandResult(returncode=127, stdout="", stderr=f"Failed to start compiled runner: {exc}")

    return ManagedCompiledCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _execute_java(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    entry_function: str,
    *,
    commands: Mapping[str, str],
    runner: CommandRunner,
    workspace: Path,
    timeout_s: float,
    start: float,
) -> ManagedCompiledExecutionResult:
    (workspace / "Main.java").write_text(code, encoding="utf-8")
    (workspace / "AearnHarness.java").write_text(_java_harness(test_cases, entry_function), encoding="utf-8")
    env = _base_env(workspace)

    compile_result = runner([commands["javac"], "Main.java", "AearnHarness.java"], workspace, env, timeout_s)
    if compile_result.timed_out:
        return _timeout_result(start, compile_result, workspace)
    if compile_result.returncode != 0:
        return _compile_error_result(start, compile_result, workspace, "Java compile failed.")

    run_result = runner([commands["java"], "-cp", str(workspace), "AearnHarness"], workspace, env, timeout_s)
    return _runtime_result_from_command(start, run_result, workspace, "Java runner failed.")


def _execute_go(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    entry_function: str,
    *,
    commands: Mapping[str, str],
    runner: CommandRunner,
    workspace: Path,
    timeout_s: float,
    start: float,
) -> ManagedCompiledExecutionResult:
    if "package " not in code:
        raise UnsupportedCompiledExerciseError("Go managed compiled exercises must provide a single package source file.")
    (workspace / "submission.go").write_text(code, encoding="utf-8")
    (workspace / "aearn_harness.go").write_text(_go_harness(test_cases, entry_function), encoding="utf-8")
    env = _base_env(workspace)
    env["GO111MODULE"] = "off"

    run_result = runner([commands["go"], "run", "submission.go", "aearn_harness.go"], workspace, env, timeout_s)
    if run_result.timed_out:
        return _timeout_result(start, run_result, workspace)
    if run_result.returncode != 0 and RESULT_PREFIX not in run_result.stdout:
        return _compile_or_runtime_error_from_go(start, run_result, workspace)
    return _runtime_result_from_command(start, run_result, workspace, "Go runner failed.")


def _execute_csharp(
    code: str,
    test_cases: Sequence[Mapping[str, object]],
    entry_function: str,
    *,
    commands: Mapping[str, str],
    runner: CommandRunner,
    workspace: Path,
    timeout_s: float,
    start: float,
) -> ManagedCompiledExecutionResult:
    (workspace / "AearnCompiled.csproj").write_text(_csharp_project(), encoding="utf-8")
    (workspace / "Program.cs").write_text(f"{code}\n\n{_csharp_harness(test_cases, entry_function)}", encoding="utf-8")
    env = _base_env(workspace)
    env["DOTNET_CLI_HOME"] = str(workspace / ".dotnet")
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1"
    env["NUGET_PACKAGES"] = str(workspace / ".nuget")

    run_result = runner(
        [
            commands["dotnet"],
            "run",
            "--project",
            "AearnCompiled.csproj",
            "--no-launch-profile",
            "-p:RestoreIgnoreFailedSources=true",
        ],
        workspace,
        env,
        timeout_s,
    )
    if run_result.timed_out:
        return _timeout_result(start, run_result, workspace)
    if run_result.returncode != 0 and RESULT_PREFIX not in run_result.stdout:
        return _compile_error_result(start, run_result, workspace, "C# compile or run failed.")
    return _runtime_result_from_command(start, run_result, workspace, "C# runner failed.")


def _runtime_result_from_command(
    start: float,
    completed: ManagedCompiledCommandResult,
    workspace: Path,
    fallback_error: str,
) -> ManagedCompiledExecutionResult:
    if completed.timed_out:
        return _timeout_result(start, completed, workspace)

    payload, public_stdout = _extract_payload(completed.stdout)
    stderr = _redact_and_bound(completed.stderr, workspace, MAX_COMPILED_ERROR_CHARS)
    if payload is None:
        error = completed.stderr or completed.stdout or fallback_error
        return ManagedCompiledExecutionResult(
            status="runtime_error",
            stdout=_redact_and_bound(public_stdout, workspace, MAX_COMPILED_OUTPUT_CHARS),
            stderr=stderr,
            error=_redact_and_bound(error, workspace, MAX_COMPILED_ERROR_CHARS),
            test_results=[],
            total_duration_ms=_elapsed_ms(start),
        )

    results = _parse_test_results(payload.get("test_results"), workspace)
    status = str(payload.get("status") or "runtime_error")
    if status == "success" and any(not result.passed for result in results):
        status = "test_failure"
    if status not in {"success", "runtime_error", "test_failure"}:
        status = "runtime_error"

    error_value = payload.get("error")
    stdout = str(payload.get("stdout") or "")
    if public_stdout.strip():
        stdout = f"{public_stdout.rstrip()}\n{stdout}".strip()

    return ManagedCompiledExecutionResult(
        status=status,
        stdout=_redact_and_bound(stdout, workspace, MAX_COMPILED_OUTPUT_CHARS),
        stderr=stderr,
        error=_redact_and_bound(str(error_value), workspace, MAX_COMPILED_ERROR_CHARS) if error_value else None,
        test_results=results,
        total_duration_ms=_elapsed_ms(start),
    )


def _compile_or_runtime_error_from_go(
    start: float,
    completed: ManagedCompiledCommandResult,
    workspace: Path,
) -> ManagedCompiledExecutionResult:
    raw_error = completed.stderr or completed.stdout or "Go compile or run failed."
    status = "compile_error" if "compile" in raw_error.lower() or ".go:" in raw_error else "runtime_error"
    return ManagedCompiledExecutionResult(
        status=status,
        stdout=_redact_and_bound(completed.stdout, workspace, MAX_COMPILED_OUTPUT_CHARS),
        stderr=_redact_and_bound(completed.stderr, workspace, MAX_COMPILED_ERROR_CHARS),
        error=_redact_and_bound(raw_error, workspace, MAX_COMPILED_ERROR_CHARS),
        test_results=[],
        total_duration_ms=_elapsed_ms(start),
    )


def _timeout_result(
    start: float,
    completed: ManagedCompiledCommandResult,
    workspace: Path,
) -> ManagedCompiledExecutionResult:
    return ManagedCompiledExecutionResult(
        status="timeout",
        stdout=_redact_and_bound(completed.stdout, workspace, MAX_COMPILED_OUTPUT_CHARS),
        stderr=_redact_and_bound(completed.stderr, workspace, MAX_COMPILED_ERROR_CHARS),
        error="Managed compiled runner timed out.",
        test_results=[],
        total_duration_ms=_elapsed_ms(start),
    )


def _compile_error_result(
    start: float,
    completed: ManagedCompiledCommandResult,
    workspace: Path,
    fallback_error: str,
) -> ManagedCompiledExecutionResult:
    raw_error = completed.stderr or completed.stdout or fallback_error
    return ManagedCompiledExecutionResult(
        status="compile_error",
        stdout=_redact_and_bound(completed.stdout, workspace, MAX_COMPILED_OUTPUT_CHARS),
        stderr=_redact_and_bound(completed.stderr, workspace, MAX_COMPILED_ERROR_CHARS),
        error=_redact_and_bound(raw_error, workspace, MAX_COMPILED_ERROR_CHARS),
        test_results=[],
        total_duration_ms=_elapsed_ms(start),
    )


def _result(
    status: str,
    start: float,
    *,
    error: str | None = None,
) -> ManagedCompiledExecutionResult:
    return ManagedCompiledExecutionResult(
        status=status,
        stdout="",
        stderr="",
        error=error,
        test_results=[],
        total_duration_ms=_elapsed_ms(start),
    )


def _extract_payload(stdout: str) -> tuple[Mapping[str, object] | None, str]:
    lines = stdout.splitlines()
    payload_line_index: int | None = None
    for index in range(len(lines) - 1, -1, -1):
        if lines[index].startswith(RESULT_PREFIX):
            payload_line_index = index
            break
    if payload_line_index is None:
        return None, stdout

    payload_text = lines[payload_line_index][len(RESULT_PREFIX) :]
    try:
        payload = json.loads(payload_text)
    except (TypeError, json.JSONDecodeError):
        return None, "\n".join(lines[:payload_line_index])
    if not isinstance(payload, Mapping):
        return None, "\n".join(lines[:payload_line_index])
    return payload, "\n".join(lines[:payload_line_index])


def _parse_test_results(raw_results: object, workspace: Path) -> list[ManagedCompiledTestCaseResult]:
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, str | bytes):
        return []
    results: list[ManagedCompiledTestCaseResult] = []
    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue
        results.append(
            ManagedCompiledTestCaseResult(
                case_id=str(raw.get("case_id", "unknown")),
                case_type=str(raw.get("case_type", "visible")),
                passed=bool(raw.get("passed", False)),
                weight=_float_or_default(raw.get("weight"), 1.0),
                is_critical=bool(raw.get("is_critical", False)),
                message=_redact_and_bound(str(raw.get("message") or ""), workspace, MAX_COMPILED_ERROR_CHARS),
                duration_ms=_int_or_default(raw.get("duration_ms"), 0),
            ),
        )
    return results


def _java_harness(test_cases: Sequence[Mapping[str, object]], entry_function: str) -> str:
    case_blocks = []
    for index, test_case in enumerate(test_cases):
        args, expected = _case_args_and_expected(test_case)
        call_args = ", ".join(_java_literal(arg) for arg in args)
        expected_literal = _java_literal(expected)
        case_blocks.append(
            f"""
        started = System.nanoTime();
        passed = false;
        message = "Passed";
        try {{
            Object actual = Main.{entry_function}({call_args});
            Object expected = {expected_literal};
            passed = java.util.Objects.deepEquals(actual, expected);
            if (!passed) {{
                message = "Expected " + safeString(expected) + ", got " + safeString(actual);
            }}
        }} catch (Throwable error) {{
            anyRuntimeError = true;
            message = error.getClass().getSimpleName() + ": " + String.valueOf(error.getMessage());
        }}
        results.add(caseJson("{_json_escape(_case_id(test_case, index))}", "{_json_escape(_case_type(test_case))}", passed, {_java_double(_weight(test_case))}, {_java_bool(_is_critical(test_case))}, message, durationMs(started)));
""",
        )
    return f"""
import java.util.ArrayList;
import java.util.List;

public class AearnHarness {{
    public static void main(String[] args) {{
        List<String> results = new ArrayList<>();
        boolean anyRuntimeError = false;
        long started;
        boolean passed;
        String message;
        {''.join(case_blocks)}
        String status = anyRuntimeError ? "runtime_error" : "success";
        System.out.println("{RESULT_PREFIX}" + "{{\\"status\\":\\"" + status + "\\",\\"stdout\\":\\"\\",\\"error\\":null,\\"test_results\\":[" + String.join(",", results) + "]}}");
    }}

    private static String caseJson(String caseId, String caseType, boolean passed, double weight, boolean critical, String message, int durationMs) {{
        return "{{\\"case_id\\":\\"" + json(caseId) + "\\",\\"case_type\\":\\"" + json(caseType) + "\\",\\"passed\\":" + passed + ",\\"weight\\":" + weight + ",\\"is_critical\\":" + critical + ",\\"message\\":\\"" + json(message) + "\\",\\"duration_ms\\":" + durationMs + "}}";
    }}

    private static int durationMs(long started) {{
        return (int) Math.max(0, (System.nanoTime() - started) / 1_000_000);
    }}

    private static String safeString(Object value) {{
        String text = String.valueOf(value);
        return text.length() > 500 ? text.substring(0, 500) : text;
    }}

    private static String json(String value) {{
        return value.replace("\\\\", "\\\\\\\\").replace("\\"", "\\\\\\"").replace("\\n", "\\\\n").replace("\\r", "\\\\r");
    }}
}}
"""


def _go_harness(test_cases: Sequence[Mapping[str, object]], entry_function: str) -> str:
    case_blocks = []
    for index, test_case in enumerate(test_cases):
        args, expected = _case_args_and_expected(test_case)
        call_args = ", ".join(_go_literal(arg) for arg in args)
        expected_literal = _go_literal(expected)
        case_blocks.append(
            f"""
    started = time.Now()
    passed = false
    message = "Passed"
    func() {{
        defer func() {{
            if recovered := recover(); recovered != nil {{
                anyRuntimeError = true
                message = fmt.Sprintf("panic: %v", recovered)
            }}
        }}()
        actual := {entry_function}({call_args})
        expected := {expected_literal}
        passed = reflect.DeepEqual(actual, expected)
        if !passed {{
            message = fmt.Sprintf("Expected %v, got %v", expected, actual)
        }}
    }}()
    results = append(results, testCaseResult{{CaseID: "{_json_escape(_case_id(test_case, index))}", CaseType: "{_json_escape(_case_type(test_case))}", Passed: passed, Weight: {_go_float(_weight(test_case))}, IsCritical: {_go_bool(_is_critical(test_case))}, Message: message, DurationMs: int(time.Since(started).Milliseconds())}})
""",
        )
    return f"""
package main

import (
    "encoding/json"
    "fmt"
    "reflect"
    "time"
)

type testCaseResult struct {{
    CaseID string `json:"case_id"`
    CaseType string `json:"case_type"`
    Passed bool `json:"passed"`
    Weight float64 `json:"weight"`
    IsCritical bool `json:"is_critical"`
    Message string `json:"message"`
    DurationMs int `json:"duration_ms"`
}}

func main() {{
    results := []testCaseResult{{}}
    anyRuntimeError := false
    var started time.Time
    var passed bool
    var message string
    {''.join(case_blocks)}
    status := "success"
    if anyRuntimeError {{
        status = "runtime_error"
    }}
    payload, _ := json.Marshal(map[string]interface{{}}{{
        "status": status,
        "stdout": "",
        "error": nil,
        "test_results": results,
    }})
    fmt.Println("{RESULT_PREFIX}" + string(payload))
}}
"""


def _csharp_harness(test_cases: Sequence[Mapping[str, object]], entry_function: str) -> str:
    case_blocks = []
    for index, test_case in enumerate(test_cases):
        args, expected = _case_args_and_expected(test_case)
        call_args = ", ".join(_csharp_literal(arg) for arg in args)
        expected_literal = _csharp_literal(expected)
        case_blocks.append(
            f"""
        started = Stopwatch.StartNew();
        passed = false;
        message = "Passed";
        try
        {{
            object? actual = Submission.{entry_function}({call_args});
            object? expected = {expected_literal};
            passed = object.Equals(actual, expected);
            if (!passed)
            {{
                message = $"Expected {{SafeString(expected)}}, got {{SafeString(actual)}}";
            }}
        }}
        catch (Exception error)
        {{
            anyRuntimeError = true;
            message = error.GetType().Name + ": " + error.Message;
        }}
        started.Stop();
        results.Add(new TestCaseResult("{_json_escape(_case_id(test_case, index))}", "{_json_escape(_case_type(test_case))}", passed, {_csharp_double(_weight(test_case))}, {_csharp_bool(_is_critical(test_case))}, message, (int)started.ElapsedMilliseconds));
""",
        )
    return f"""
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;

public sealed record TestCaseResult(
    [property: JsonPropertyName("case_id")] string CaseID,
    [property: JsonPropertyName("case_type")] string CaseType,
    [property: JsonPropertyName("passed")] bool Passed,
    [property: JsonPropertyName("weight")] double Weight,
    [property: JsonPropertyName("is_critical")] bool IsCritical,
    [property: JsonPropertyName("message")] string Message,
    [property: JsonPropertyName("duration_ms")] int DurationMs
);

public static class AearnHarness
{{
    public static int Main()
    {{
        var results = new List<TestCaseResult>();
        var anyRuntimeError = false;
        Stopwatch started;
        bool passed;
        string message;
        {''.join(case_blocks)}
        var payload = new
        {{
            status = anyRuntimeError ? "runtime_error" : "success",
            stdout = "",
            error = (string?)null,
            test_results = results,
        }};
        Console.WriteLine("{RESULT_PREFIX}" + JsonSerializer.Serialize(payload));
        return 0;
    }}

    private static string SafeString(object? value)
    {{
        var text = Convert.ToString(value) ?? "null";
        return text.Length > 500 ? text[..500] : text;
    }}
}}
"""


def _csharp_project() -> str:
    return """
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <RestoreIgnoreFailedSources>true</RestoreIgnoreFailedSources>
  </PropertyGroup>
</Project>
"""


def _case_args_and_expected(test_case: Mapping[str, object]) -> tuple[tuple[object, ...], object]:
    input_json = test_case.get("input_json", {})
    expected_json = test_case.get("expected_output_json", {})
    if not isinstance(input_json, Mapping) or not isinstance(expected_json, Mapping):
        raise UnsupportedCompiledExerciseError("Managed compiled test cases must use JSON object input and expected output.")
    raw_args = input_json.get("args")
    if isinstance(raw_args, Sequence) and not isinstance(raw_args, str | bytes):
        args = tuple(raw_args)
    else:
        args = tuple(value for key, value in input_json.items() if key != "stdin")
    if "return" not in expected_json:
        raise UnsupportedCompiledExerciseError("Managed compiled test cases must use expected_output_json.return.")
    expected = expected_json["return"]
    for value in (*args, expected):
        if not _is_supported_scalar(value):
            raise UnsupportedCompiledExerciseError("Managed compiled tests currently support scalar int, float, bool, and string values only.")
    return args, expected


def _resolve_commands(
    language: str,
    commands: Mapping[str, str],
    detect_commands: bool,
) -> dict[str, str | None]:
    if language == "java":
        return {
            "javac": commands.get("javac") or (_find_command("javac") if detect_commands else None),
            "java": commands.get("java") or (_find_command("java") if detect_commands else None),
        }
    if language == "go":
        return {"go": commands.get("go") or (_find_command("go") if detect_commands else None)}
    return {"dotnet": commands.get("dotnet") or (_find_command("dotnet") if detect_commands else None)}


def _missing_toolchain_message(language: str, commands: Mapping[str, str | None]) -> str | None:
    missing = [name for name, value in commands.items() if not value]
    if not missing:
        return None
    if language == "java":
        return "A local JDK with javac and java is required for managed_compiled_test Java exercises."
    if language == "go":
        return "A local Go toolchain is required for managed_compiled_test Go exercises."
    return "A local .NET SDK is required for managed_compiled_test C# exercises."


def _find_command(command: str) -> str | None:
    return shutil.which(command)


def _base_env(workspace: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for key in (
        "PATH",
        "SystemRoot",
        "SYSTEMROOT",
        "WINDIR",
        "PATHEXT",
        "COMSPEC",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "ProgramFiles",
        "ProgramFiles(x86)",
    ):
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["TEMP"] = str(workspace)
    env["TMP"] = str(workspace)
    return env


def _normalize_language(language: str) -> str:
    normalized = language.strip().lower().replace("-", "").replace("_", "")
    if normalized in {"c#", "cs"}:
        return "csharp"
    return normalized


def _java_literal(value: object) -> str:
    if isinstance(value, bool):
        return "Boolean.TRUE" if value else "Boolean.FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if value is None:
        return "null"
    raise UnsupportedCompiledExerciseError("Unsupported Java test literal.")


def _go_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise UnsupportedCompiledExerciseError("Unsupported Go test literal.")


def _csharp_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if value is None:
        return "null"
    raise UnsupportedCompiledExerciseError("Unsupported C# test literal.")


def _is_supported_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | bool | int | float)


def _case_id(test_case: Mapping[str, object], index: int) -> str:
    return str(test_case.get("id") or f"case_{index + 1}")


def _case_type(test_case: Mapping[str, object]) -> str:
    return str(test_case.get("case_type", "visible"))


def _weight(test_case: Mapping[str, object]) -> float:
    return _float_or_default(test_case.get("weight"), 1.0)


def _is_critical(test_case: Mapping[str, object]) -> bool:
    return bool(test_case.get("is_critical", False))


def _json_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _java_bool(value: bool) -> str:
    return "true" if value else "false"


def _go_bool(value: bool) -> str:
    return "true" if value else "false"


def _csharp_bool(value: bool) -> str:
    return "true" if value else "false"


def _java_double(value: float) -> str:
    return f"{value:.6f}"


def _go_float(value: float) -> str:
    return f"{value:.6f}"


def _csharp_double(value: float) -> str:
    return f"{value:.6f}"


def _float_or_default(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _int_or_default(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float | str):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def _redact_and_bound(value: str, workspace: Path, max_chars: int) -> str:
    redacted = _redact_workspace(value, workspace)
    if len(redacted) <= max_chars:
        return redacted
    return redacted[: max_chars - 3] + "..."


def _redact_workspace(value: str, workspace: Path) -> str:
    workspace_text = str(workspace)
    redacted = value.replace(workspace_text, "[temp workspace]")
    redacted = redacted.replace(workspace_text.replace("\\", "\\\\"), "[temp workspace]")
    redacted = redacted.replace(workspace_text.replace("\\", "/"), "[temp workspace]")
    return redacted


def _timeout_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
