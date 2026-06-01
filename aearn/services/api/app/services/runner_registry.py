from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.services.language_capabilities import ExecutionMode, RunnerKey
from app.services.runtime_contracts import RuntimeExecutionResult
from app.services.sandbox import SandboxExecutionResult, execute_python_with_tests


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
        capability = self._by_runtime_tier.get(runtime_tier) if runtime_tier else None
        if capability is not None and capability is not UNSUPPORTED_RUNNER:
            return capability

        language = str(runtime_profile.get("language", "")).lower()
        if language in {"typescript", "ts"}:
            return NODE_TYPESCRIPT_RUNNER
        if language == "sql":
            return SQL_RUNNER
        if language in {"java", "go", "csharp", "c#", "rust", "cpp", "c++"}:
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
    supports_stdout=False,
    supports_preview=True,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={"network": "disabled", "filesystem": "readonly", "dom_access": True},
)

NODE_TYPESCRIPT_RUNNER = RunnerCapability(
    runner_key="node",
    execution="node_later",
    runtime_tiers=("node_later",),
    supports_execution=False,
    supports_tests=False,
    supports_stdout=False,
    supports_preview=False,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={"status": "planned", "network": "disabled"},
    unavailable_message="Node/TypeScript execution is planned later and is not available in this runtime.",
)

SQL_RUNNER = RunnerCapability(
    runner_key="sql",
    execution="sql_later",
    runtime_tiers=("sql_later",),
    supports_execution=False,
    supports_tests=False,
    supports_stdout=False,
    supports_preview=False,
    compile_required=False,
    timeout_ms=5000,
    memory_limit_mb=128,
    sandbox_policy={"status": "planned", "database": "ephemeral_required"},
    unavailable_message="SQL execution requires an isolated query runner and is not available in this runtime.",
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
            stdout=sandbox_result.stdout,
            stderr=sandbox_result.stderr,
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
            runtime_status="sandbox_error",
            stdout=sandbox_result.stdout,
            stderr=sandbox_result.stderr,
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, sandbox_result.error or "Sandbox error"),
            error_message=sandbox_result.error or "Sandbox execution failed.",
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    if sandbox_result.status == "error":
        return RuntimeExecutionResult(
            runtime_status="runtime_error",
            stdout=sandbox_result.stdout,
            stderr=sandbox_result.stderr,
            test_pass_rate=0.0,
            passed_test_count=0,
            total_test_count=len(test_cases),
            test_results=_build_failed_cases(exercise, sandbox_result.error or "Runtime error"),
            error_message=sandbox_result.error or "Code raised an error during execution.",
            next_action="explain_error",
            preview_html=None,
            core_blank_gate=False,
            any_blank_passed=False,
            logic_pass=False,
        )

    test_results = [
        {
            "case_id": tr.case_id,
            "case_type": tr.case_type,
            "passed": tr.passed,
            "weight": tr.weight,
            "is_critical": tr.is_critical,
            "duration_ms": tr.duration_ms,
            "message": tr.message,
        }
        for tr in sandbox_result.test_results
    ]

    total_weight = sum(tr.weight for tr in sandbox_result.test_results)
    passed_weight = sum(tr.weight for tr in sandbox_result.test_results if tr.passed)
    passed_count = sum(1 for tr in sandbox_result.test_results if tr.passed)
    total_count = len(sandbox_result.test_results) or len(test_cases)
    test_pass_rate = 0.0 if total_weight == 0 else round(passed_weight / total_weight, 4)

    logic_pass = test_pass_rate == 1.0
    next_action = _next_action_for_run(test_results, logic_pass, "python_stdout_test")

    return RuntimeExecutionResult(
        runtime_status="success",
        stdout=sandbox_result.stdout.rstrip("\n"),
        stderr=sandbox_result.stderr,
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
                "case_id": str(case.get("id") or f"case_{index + 1}"),
                "case_type": str(case.get("case_type", "visible")),
                "passed": False,
                "weight": float(case.get("weight", 1)),
                "is_critical": bool(case.get("is_critical", False)),
                "duration_ms": 0,
                "message": message,
            },
        )
    return failed_cases


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
