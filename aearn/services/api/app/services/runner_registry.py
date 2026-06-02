from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.services.browser_preview_runner import (
    BrowserPreviewExecutionResult,
    execute_browser_preview_with_tests,
)
from app.services.language_capabilities import ExecutionMode, RunnerKey
from app.services.managed_compiled_runner import (
    ManagedCompiledExecutionResult,
    execute_managed_compiled_with_tests,
)
from app.services.node_typescript_runner import NodeExecutionResult, execute_node_typescript_with_tests
from app.services.runtime_contracts import RuntimeExecutionResult
from app.services.sandbox import SandboxExecutionResult, execute_python_with_tests
from app.services.sql_query_runner import SqlExecutionResult, execute_sql_query_with_tests

MAX_RUNNER_STDOUT_CHARS = 4000
MAX_RUNNER_STDERR_CHARS = 2000
MAX_RUNNER_ERROR_CHARS = 500
MANAGED_COMPILED_LANGUAGE_IDS = {"java", "go", "csharp", "c#"}
STATIC_COMPILED_LANGUAGE_IDS = {"rust", "cpp", "c++"}

RUNTIME_EXCEPTION_PREFIXES = (
    "ArithmeticError:",
    "AttributeError:",
    "IndexError:",
    "KeyError:",
    "NameError:",
    "RecursionError:",
    "RuntimeError:",
    "StopIteration:",
    "TypeError:",
    "ValueError:",
    "ZeroDivisionError:",
)


@dataclass(frozen=True, slots=True)
class RunnerCapability:
    runner_key: RunnerKey
    execution: ExecutionMode
    runtime_tiers: tuple[str, ...]
    supports_execution: bool
    supports_tests: bool
    supports_stdout: bool
    supports_preview: bool
    compile_required: bool
    timeout_ms: int
    memory_limit_mb: int
    sandbox_policy: Mapping[str, object]
    unavailable_message: str | None = None


class RunnerRegistry:
    def __init__(self, capabilities: Sequence[RunnerCapability]) -> None:
        self._capabilities = tuple(capabilities)
        self._by_runtime_tier = {
            runtime_tier: capability
            for capability in self._capabilities
            for runtime_tier in capability.runtime_tiers
        }

    def select(self, runtime_profile: Mapping[str, object]) -> RunnerCapability:
        runtime_tier = str(runtime_profile.get("runtime_tier", ""))
        language = str(runtime_profile.get("language", "")).lower()
        if runtime_tier == "managed_compiled_test" and language and language not in MANAGED_COMPILED_LANGUAGE_IDS:
            if language in STATIC_COMPILED_LANGUAGE_IDS:
                return COMPILED_LANGUAGE_RUNNER
            return UNSUPPORTED_RUNNER
        capability = self._by_runtime_tier.get(runtime_tier) if runtime_tier else None
        if capability is not None and capability is not UNSUPPORTED_RUNNER:
            return capability

        if language in {"typescript", "ts"}:
            return NODE_TYPESCRIPT_RUNNER
        if language == "sql":
            return SQL_RUNNER
        if language in MANAGED_COMPILED_LANGUAGE_IDS:
            return MANAGED_COMPILED_RUNNER
        if language in STATIC_COMPILED_LANGUAGE_IDS:
            return COMPILED_LANGUAGE_RUNNER
        return UNSUPPORTED_RUNNER

    def unsupported_result(self, exercise: Mapping[str, object], capability: RunnerCapability) -> RuntimeExecutionResult:
        message = capability.unavailable_message or "This language runtime is not available yet."
        return RuntimeExecutionResult(
            runtime_status="unsupported",
            stdout="",
            stderr="",
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=_case_count(exercise),
            test_results=_build_failed_cases(exercise, message),
            error_message=message,
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    def run_python(self, exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
        return _run_python_sandbox(exercise, code)

    def run_browser_preview(self, exercise: Mapping[str, object], code: str, filled_blanks: Mapping[str, str]) -> RuntimeExecutionResult:
        return _run_browser_preview(exercise, code, filled_blanks)

    def run_node_typescript(self, exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
        return _run_node_typescript(exercise, code)

    def run_sql_query(self, exercise: Mapping[str, object], query: str) -> RuntimeExecutionResult:
        return _run_sql_query(exercise, query)

    def run_managed_compiled(self, exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
        return _run_managed_compiled(exercise, code)


PYTHON_RUNNER = RunnerCapability(
    runner_key="python",
    execution="python_stdout_test",
    runtime_tiers=("python_stdout_test",),
    supports_execution=True,
    supports_tests=True,
    supports_stdout=True,
    supports_preview=False,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={
        "network": "disabled",
        "filesystem": "readonly",
        "max_processes": 1,
        "is_container_grade": False,
    },
)

BROWSER_PREVIEW_RUNNER = RunnerCapability(
    runner_key="browser",
    execution="browser_preview",
    runtime_tiers=("browser_preview",),
    supports_execution=True,
    supports_tests=True,
    supports_stdout=True,
    supports_preview=True,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={"network": "disabled", "filesystem": "readonly", "dom_access": True},
)

NODE_TYPESCRIPT_RUNNER = RunnerCapability(
    runner_key="node",
    execution="node_typescript_test",
    runtime_tiers=("node_typescript_test", "node_later"),
    supports_execution=True,
    supports_tests=True,
    supports_stdout=True,
    supports_preview=False,
    compile_required=True,
    timeout_ms=10000,
    memory_limit_mb=128,
    sandbox_policy={
        "network": "disabled",
        "filesystem": "temporary_workspace",
        "max_processes": 1,
        "is_container_grade": False,
    },
    unavailable_message="Node/TypeScript execution requires local Node.js and TypeScript tooling.",
)

SQL_RUNNER = RunnerCapability(
    runner_key="sql",
    execution="sql_query_test",
    runtime_tiers=("sql_query_test",),
    supports_execution=True,
    supports_tests=True,
    supports_stdout=True,
    supports_preview=False,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={
        "dialect": "sqlite",
        "database": "per_run_ephemeral",
        "network": "disabled",
        "filesystem": "none",
        "app_database_access": False,
        "is_container_grade": False,
    },
    unavailable_message="SQL runs through the SQLite teaching dialect in an isolated per-run local database.",
)

MANAGED_COMPILED_RUNNER = RunnerCapability(
    runner_key="compiled",
    execution="managed_compiled_test",
    runtime_tiers=("managed_compiled_test",),
    supports_execution=True,
    supports_tests=True,
    supports_stdout=True,
    supports_preview=False,
    compile_required=True,
    timeout_ms=10000,
    memory_limit_mb=256,
    sandbox_policy={
        "network": "disabled",
        "filesystem": "temporary_workspace",
        "max_processes": 1,
        "package_managers": "disabled",
        "external_dependencies": "disabled",
        "is_container_grade": False,
    },
    unavailable_message="Java, Go, and C# use local teaching-grade managed compiled runners when the matching toolchain is installed.",
)

COMPILED_LANGUAGE_RUNNER = RunnerCapability(
    runner_key="compiled",
    execution="compiled_later",
    runtime_tiers=("compiled_sandbox_later", "compiled_later"),
    supports_execution=False,
    supports_tests=False,
    supports_stdout=False,
    supports_preview=False,
    compile_required=True,
    timeout_ms=10000,
    memory_limit_mb=256,
    sandbox_policy={"status": "planned", "network": "disabled", "filesystem": "readonly"},
    unavailable_message="Current language compile-and-run sandbox is planned later and is not executable yet.",
)

UNSUPPORTED_RUNNER = RunnerCapability(
    runner_key="none",
    execution="none",
    runtime_tiers=("none", ""),
    supports_execution=False,
    supports_tests=False,
    supports_stdout=False,
    supports_preview=False,
    compile_required=False,
    timeout_ms=0,
    memory_limit_mb=0,
    sandbox_policy={"status": "unsupported"},
    unavailable_message="This language runtime is not supported.",
)


DEFAULT_RUNNER_REGISTRY = RunnerRegistry(
    (
        PYTHON_RUNNER,
        BROWSER_PREVIEW_RUNNER,
        NODE_TYPESCRIPT_RUNNER,
        SQL_RUNNER,
        MANAGED_COMPILED_RUNNER,
        COMPILED_LANGUAGE_RUNNER,
        UNSUPPORTED_RUNNER,
    )
)


def get_runner_registry() -> RunnerRegistry:
    return DEFAULT_RUNNER_REGISTRY


def _run_python_sandbox(exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    metadata = exercise.get("metadata_json", {})
    entry_function: str | None = None
    if isinstance(metadata, Mapping):
        ef = metadata.get("entry_function")
        if ef:
            entry_function = str(ef)

    sandbox_result: SandboxExecutionResult = execute_python_with_tests(
        code,
        test_cases,
        entry_function=entry_function,
        timeout_s=10.0,
    )

    if sandbox_result.status == "timeout":
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout=_bound_text(sandbox_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(sandbox_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, "Execution timed out."),
            error_message="Code execution timed out.",
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if sandbox_result.status == "sandbox_error":
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=_bound_text(sandbox_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(sandbox_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, sandbox_result.error or "Sandbox error"),
            error_message=_bound_text(sandbox_result.error or "Sandbox execution failed.", MAX_RUNNER_ERROR_CHARS),
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if sandbox_result.status == "error":
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=_bound_text(sandbox_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(sandbox_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, sandbox_result.error or "Runtime error"),
            error_message=_bound_text(sandbox_result.error or "Code raised an error during execution.", MAX_RUNNER_ERROR_CHARS),
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    test_results = [_public_test_result(tr, index) for index, tr in enumerate(sandbox_result.test_results)]

    total_weight = sum(tr.weight for tr in sandbox_result.test_results)
    passed_weight = sum(tr.weight for tr in sandbox_result.test_results if tr.passed)
    passed_count = sum(1 for tr in sandbox_result.test_results if tr.passed)
    total_count = len(sandbox_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)
    runtime_error_message = _function_runtime_error_message(sandbox_result.test_results)
    has_runtime_error = runtime_error_message is not None

    logic_pass = not has_runtime_error and test_pass_rate == 1.0
    next_action = "explain_error" if has_runtime_error else _next_action_for_run(test_results, logic_pass, "python_stdout_test")

    return RuntimeExecutionResult(
        runtime_status="runtime_error" if has_runtime_error else "success",
        stdout=_bound_text(sandbox_result.stdout.rstrip("\n"), MAX_RUNNER_STDOUT_CHARS),
        stderr=_bound_text(sandbox_result.stderr, MAX_RUNNER_STDERR_CHARS),
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_count,
        total_test_count=total_count,
        test_results=test_results,
        error_message=runtime_error_message,
        next_action=next_action,
        preview_html=None,
        core_blank_gate=logic_pass,
        any_blank_passed=passed_count > 0,
        logic_pass=logic_pass,
    )


def _run_browser_preview(exercise: Mapping[str, object], code: str, filled_blanks: Mapping[str, str]) -> RuntimeExecutionResult:
    browser_result = execute_browser_preview_with_tests(exercise, code, filled_blanks)
    return _browser_result_to_runtime_result(exercise, browser_result)


def _browser_result_to_runtime_result(
    exercise: Mapping[str, object],
    browser_result: BrowserPreviewExecutionResult,
) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    test_results = [_public_test_result(result, index) for index, result in enumerate(browser_result.test_results)]
    total_weight = sum(result.weight for result in browser_result.test_results)
    passed_weight = sum(result.weight for result in browser_result.test_results if result.passed)
    passed_count = sum(1 for result in browser_result.test_results if result.passed)
    total_count = len(browser_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)

    if browser_result.status == "timeout":
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout=_bound_text(browser_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(browser_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=total_count,
            test_results=test_results,
            error_message="Browser preview runner timed out.",
            next_action="retry_same",
            preview_html=browser_result.preview_html,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if browser_result.status == "runtime_error":
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=_bound_text(browser_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(browser_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=total_count,
            test_results=test_results,
            error_message=_bound_text(browser_result.error or "Browser preview raised a runtime error.", MAX_RUNNER_ERROR_CHARS),
            next_action="explain_error",
            preview_html=browser_result.preview_html,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    logic_pass = browser_result.logic_pass and test_pass_rate == 1.0
    next_action = _next_action_for_run(test_results, logic_pass, "browser_preview")
    return RuntimeExecutionResult(
        runtime_status="success",
        stdout=_bound_text(browser_result.stdout, MAX_RUNNER_STDOUT_CHARS),
        stderr=_bound_text(browser_result.stderr, MAX_RUNNER_STDERR_CHARS),
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_count,
        total_test_count=total_count,
        test_results=test_results,
        error_message=None,
        next_action=next_action,
        preview_html=browser_result.preview_html,
        core_blank_gate=browser_result.core_blank_gate,
        any_blank_passed=browser_result.any_blank_passed,
        logic_pass=browser_result.logic_pass,
    )


def _run_node_typescript(exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    metadata = exercise.get("metadata_json", {})
    entry_function: str | None = None
    if isinstance(metadata, Mapping):
        ef = metadata.get("entry_function")
        if ef:
            entry_function = str(ef)

    node_result = execute_node_typescript_with_tests(
        code,
        test_cases,
        entry_function=entry_function,
        timeout_s=10.0,
    )
    return _node_result_to_runtime_result(exercise, node_result)


def _run_sql_query(exercise: Mapping[str, object], query: str) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    metadata = exercise.get("metadata_json", {})
    sql_result = execute_sql_query_with_tests(
        query,
        test_cases,
        metadata=metadata if isinstance(metadata, Mapping) else {},
        timeout_s=5.0,
    )
    return _sql_result_to_runtime_result(exercise, sql_result)


def _run_managed_compiled(exercise: Mapping[str, object], code: str) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    runtime_profile = exercise.get("runtime_profile", {})
    language = ""
    if isinstance(runtime_profile, Mapping):
        language = str(runtime_profile.get("language") or "")

    metadata = exercise.get("metadata_json", {})
    entry_function: str | None = None
    if isinstance(metadata, Mapping):
        ef = metadata.get("entry_function")
        if ef:
            entry_function = str(ef)

    compiled_result = execute_managed_compiled_with_tests(
        code,
        test_cases,
        language=language,
        entry_function=entry_function,
        timeout_s=10.0,
    )
    return _managed_compiled_result_to_runtime_result(exercise, compiled_result)


def _managed_compiled_result_to_runtime_result(
    exercise: Mapping[str, object],
    compiled_result: ManagedCompiledExecutionResult,
) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    if compiled_result.status == "timeout":
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout=_bound_text(compiled_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(compiled_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, "Managed compiled execution timed out."),
            error_message="Managed compiled execution timed out.",
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if compiled_result.status in {"missing_toolchain", "unsupported", "compile_error", "runtime_error"}:
        message = compiled_result.error or "Managed compiled execution failed."
        next_action = "retry_same" if compiled_result.status in {"missing_toolchain", "unsupported"} else "explain_error"
        return RuntimeExecutionResult(
            runtime_status=compiled_result.status,
            stdout=_bound_text(compiled_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(compiled_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, message),
            error_message=_bound_text(message, MAX_RUNNER_ERROR_CHARS),
            next_action=next_action,
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    test_results = [_public_test_result(result, index) for index, result in enumerate(compiled_result.test_results)]
    total_weight = sum(result.weight for result in compiled_result.test_results)
    passed_weight = sum(result.weight for result in compiled_result.test_results if result.passed)
    passed_count = sum(1 for result in compiled_result.test_results if result.passed)
    total_count = len(compiled_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)
    logic_pass = compiled_result.status == "success" and test_pass_rate == 1.0
    runtime_status = "success" if logic_pass else "test_failure"
    next_action = _next_action_for_run(test_results, logic_pass, "managed_compiled_test")

    return RuntimeExecutionResult(
        runtime_status=runtime_status,
        stdout=_bound_text(compiled_result.stdout.rstrip("\n"), MAX_RUNNER_STDOUT_CHARS),
        stderr=_bound_text(compiled_result.stderr, MAX_RUNNER_STDERR_CHARS),
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_count,
        total_test_count=total_count,
        test_results=test_results,
        error_message=compiled_result.error,
        next_action=next_action,
        preview_html=None,
        core_blank_gate=logic_pass,
        any_blank_passed=passed_count > 0,
        logic_pass=logic_pass,
    )


def _sql_result_to_runtime_result(exercise: Mapping[str, object], sql_result: SqlExecutionResult) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    if sql_result.status == "timeout":
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout=_bound_text(sql_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(sql_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, "SQL query timed out."),
            error_message="SQL query timed out.",
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if sql_result.status in {"missing_toolchain", "unsupported"}:
        message = sql_result.error or "SQLite support is required for SQL exercises."
        return RuntimeExecutionResult(
            runtime_status="unsupported",
            stdout="",
            stderr="",
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, message),
            error_message=_bound_text(message, MAX_RUNNER_ERROR_CHARS),
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if sql_result.status == "runtime_error":
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=_bound_text(sql_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(sql_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, sql_result.error or "SQL query failed."),
            error_message=_bound_text(sql_result.error or "SQL query failed.", MAX_RUNNER_ERROR_CHARS),
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    test_results = [_public_test_result(result, index) for index, result in enumerate(sql_result.test_results)]
    total_weight = sum(result.weight for result in sql_result.test_results)
    passed_weight = sum(result.weight for result in sql_result.test_results if result.passed)
    passed_count = sum(1 for result in sql_result.test_results if result.passed)
    total_count = len(sql_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)
    logic_pass = test_pass_rate == 1.0
    next_action = _next_action_for_run(test_results, logic_pass, "sql_query_test")

    return RuntimeExecutionResult(
        runtime_status="success",
        stdout=_bound_text(sql_result.stdout.rstrip("\n"), MAX_RUNNER_STDOUT_CHARS),
        stderr=_bound_text(sql_result.stderr, MAX_RUNNER_STDERR_CHARS),
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_count,
        total_test_count=total_count,
        test_results=test_results,
        error_message=None,
        next_action=next_action,
        preview_html=None,
        core_blank_gate=logic_pass,
        any_blank_passed=passed_count > 0,
        logic_pass=logic_pass,
    )


def _node_result_to_runtime_result(exercise: Mapping[str, object], node_result: NodeExecutionResult) -> RuntimeExecutionResult:
    test_cases = exercise.get("test_cases", [])
    if not isinstance(test_cases, Sequence):
        test_cases = []

    if node_result.status == "timeout":
        return RuntimeExecutionResult(
            runtime_status="timeout",
            stdout=_bound_text(node_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(node_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, "Node/TypeScript execution timed out."),
            error_message="Node/TypeScript execution timed out.",
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if node_result.status == "missing_toolchain":
        message = node_result.error or "Node.js and TypeScript compiler are required for this exercise."
        return RuntimeExecutionResult(
            runtime_status="unsupported",
            stdout="",
            stderr="",
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, message),
            error_message=_bound_text(message, MAX_RUNNER_ERROR_CHARS),
            next_action="retry_same",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if node_result.status in {"compile_error", "sandbox_error"}:
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=_bound_text(node_result.stdout, MAX_RUNNER_STDOUT_CHARS),
            stderr=_bound_text(node_result.stderr, MAX_RUNNER_STDERR_CHARS),
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, node_result.error or "Node/TypeScript execution failed."),
            error_message=_bound_text(node_result.error or "Node/TypeScript execution failed.", MAX_RUNNER_ERROR_CHARS),
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    test_results = [_public_test_result(result, index) for index, result in enumerate(node_result.test_results)]
    total_weight = sum(result.weight for result in node_result.test_results)
    passed_weight = sum(result.weight for result in node_result.test_results if result.passed)
    passed_count = sum(1 for result in node_result.test_results if result.passed)
    total_count = len(node_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)
    runtime_error_message = _node_runtime_error_message(node_result)
    has_runtime_error = node_result.status == "runtime_error" or runtime_error_message is not None

    logic_pass = not has_runtime_error and test_pass_rate == 1.0
    next_action = "explain_error" if has_runtime_error else _next_action_for_run(test_results, logic_pass, "node_typescript_test")

    return RuntimeExecutionResult(
        runtime_status="runtime_error" if has_runtime_error else "success",
        stdout=_bound_text(node_result.stdout.rstrip("\n"), MAX_RUNNER_STDOUT_CHARS),
        stderr=_bound_text(node_result.stderr, MAX_RUNNER_STDERR_CHARS),
        test_pass_rate=test_pass_rate,
        passed_test_count=passed_count,
        total_test_count=total_count,
        test_results=test_results,
        error_message=runtime_error_message,
        next_action=next_action,
        preview_html=None,
        core_blank_gate=logic_pass,
        any_blank_passed=passed_count > 0,
        logic_pass=logic_pass,
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


def _public_test_result(result: object, index: int) -> dict[str, object]:
    case_type = str(getattr(result, "case_type", "visible"))
    passed = bool(getattr(result, "passed", False))
    raw_message = str(getattr(result, "message", ""))
    return {
        "case_id": f"hidden_case_{index + 1}" if case_type == "hidden" else str(getattr(result, "case_id", f"case_{index + 1}")),
        "case_type": case_type,
        "passed": passed,
        "weight": float(getattr(result, "weight", 1)),
        "is_critical": bool(getattr(result, "is_critical", False)),
        "duration_ms": int(getattr(result, "duration_ms", 0)),
        "message": _hidden_message(passed) if case_type == "hidden" else _bound_text(raw_message, MAX_RUNNER_ERROR_CHARS),
    }


def _function_runtime_error_message(results: Sequence[object]) -> str | None:
    for result in results:
        message = str(getattr(result, "message", ""))
        if message.startswith(RUNTIME_EXCEPTION_PREFIXES):
            if str(getattr(result, "case_type", "")) == "hidden":
                return "A hidden Python test raised a runtime error."
            error_name = message.split(":", 1)[0]
            return f"Python code raised {error_name} during visible tests."
    return None


def _node_runtime_error_message(result: NodeExecutionResult) -> str | None:
    if result.error:
        return _bound_text(result.error, MAX_RUNNER_ERROR_CHARS)
    for test_result in result.test_results:
        if not test_result.passed and ":" in test_result.message:
            if test_result.case_type == "hidden":
                return "A hidden TypeScript test raised a runtime error."
            error_name = test_result.message.split(":", 1)[0]
            return f"TypeScript code raised {error_name} during visible tests."
    return None


def _public_case_id(case: Mapping[str, object], index: int) -> str:
    case_type = str(case.get("case_type", "visible"))
    if case_type == "hidden":
        return f"hidden_case_{index + 1}"
    return str(case.get("id") or f"case_{index + 1}")


def _public_case_message(case: Mapping[str, object], message: str) -> str:
    case_type = str(case.get("case_type", "visible"))
    if case_type == "hidden":
        return _hidden_message(False)
    return _bound_text(message, MAX_RUNNER_ERROR_CHARS)


def _hidden_message(passed: bool) -> str:
    if passed:
        return "Hidden test passed."
    return "A hidden test failed. Recheck edge cases and boundary behavior."


def _bound_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."


def _next_action_for_run(
    test_results: Sequence[Mapping[str, object]],
    success: bool,
    runtime_tier: str,
) -> str:
    if runtime_tier in {"compiled_sandbox_later", "compiled_later"}:
        return "retry_same"
    if success:
        return "advance_next"
    failed_results = [result for result in test_results if not bool(result.get("passed"))]
    if any(str(result.get("case_type")) == "visible" and bool(result.get("is_critical")) for result in failed_results):
        return "explain_error"
    if failed_results:
        return "show_hint"
    return "retry_same"
