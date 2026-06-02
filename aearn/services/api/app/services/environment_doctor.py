from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from app.services.language_capabilities import (
    ExecutionMode,
    RunnerKey,
    all_language_capabilities,
)
from app.services.runner_registry import get_runner_registry


CommandStatus = Literal["ready", "missing", "error"]
ComponentStatus = Literal["ready", "missing", "error", "planned"]
ComponentKind = Literal[
    "service",
    "startup",
    "runtime",
    "package_manager",
    "container",
    "compiled_toolchain",
    "database_tooling",
]
OverallStatus = Literal["ready", "needs_attention", "blocked"]
ProductStatus = Literal["executable", "planned", "static_review", "unsupported"]
GuidanceSeverity = Literal["required", "recommended", "optional"]


class EnvironmentPlatform(TypedDict):
    system: str
    release: str
    python_executable: str


class EnvironmentSummary(TypedDict):
    overall_status: OverallStatus
    ready_count: int
    missing_required_count: int
    planned_runner_count: int


class ComponentDiagnostic(TypedDict):
    command: str | None
    args: list[str]
    exit_code: int | None
    stdout: str
    stderr: str


class EnvironmentComponent(TypedDict):
    component_id: str
    label: str
    kind: ComponentKind
    status: ComponentStatus
    version: str | None
    executable_path: str | None
    required_for: list[str]
    guidance_id: str | None
    message: str
    diagnostic: ComponentDiagnostic


class LanguageRunnerStatus(TypedDict):
    language_id: str
    display_name: str
    runner_key: RunnerKey
    execution: ExecutionMode
    capability_state: str
    supports_execution: bool
    toolchain_status: ComponentStatus
    product_status: ProductStatus
    guidance_id: str | None
    disclosure: str


class GuidanceTemplatePayload(TypedDict):
    guidance_id: str
    title: str
    applies_to: list[str]
    severity: GuidanceSeverity
    summary: str
    windows_steps: list[str]
    verification_commands: list[str]
    safety_notes: list[str]
    source: Literal["static_template"]


class EnvironmentDoctorReport(TypedDict):
    generated_at: str
    platform: EnvironmentPlatform
    summary: EnvironmentSummary
    components: list[EnvironmentComponent]
    language_runners: list[LanguageRunnerStatus]
    guidance: list[GuidanceTemplatePayload]


@dataclass(frozen=True, slots=True)
class CommandProbeResult:
    status: CommandStatus
    version: str | None
    executable_path: str | None
    message: str
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""


CommandRunner = Callable[[str, tuple[str, ...], float], CommandProbeResult]


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    component_id: str
    label: str
    kind: ComponentKind
    command: str
    args: tuple[str, ...]
    required_for: tuple[str, ...]
    guidance_id: str | None


@dataclass(frozen=True, slots=True)
class GuidanceTemplate:
    guidance_id: str
    title: str
    applies_to: tuple[str, ...]
    severity: GuidanceSeverity
    summary: str
    windows_steps: tuple[str, ...]
    verification_commands: tuple[str, ...]
    safety_notes: tuple[str, ...]

    def as_payload(self) -> GuidanceTemplatePayload:
        return {
            "guidance_id": self.guidance_id,
            "title": self.title,
            "applies_to": list(self.applies_to),
            "severity": self.severity,
            "summary": self.summary,
            "windows_steps": list(self.windows_steps),
            "verification_commands": list(self.verification_commands),
            "safety_notes": list(self.safety_notes),
            "source": "static_template",
        }


COMMAND_CHECKS: tuple[ComponentDefinition, ...] = (
    ComponentDefinition(
        component_id="uv",
        label="uv",
        kind="package_manager",
        command="uv",
        args=("--version",),
        required_for=("api", "worker", "python_runner", "local_startup"),
        guidance_id="python_uv_windows",
    ),
    ComponentDefinition(
        component_id="node",
        label="Node.js",
        kind="runtime",
        command="node",
        args=("--version",),
        required_for=("desktop", "browser_runner", "node_typescript_runner", "local_startup"),
        guidance_id="node_typescript_windows",
    ),
    ComponentDefinition(
        component_id="pnpm",
        label="pnpm",
        kind="package_manager",
        command="pnpm",
        args=("--version",),
        required_for=("desktop", "local_startup"),
        guidance_id="pnpm_windows",
    ),
    ComponentDefinition(
        component_id="docker",
        label="Docker",
        kind="container",
        command="docker",
        args=("--version",),
        required_for=("postgres", "redis", "local_startup"),
        guidance_id="docker_desktop_windows",
    ),
    ComponentDefinition(
        component_id="docker_compose",
        label="Docker Compose",
        kind="container",
        command="docker",
        args=("compose", "version"),
        required_for=("postgres", "redis", "local_startup"),
        guidance_id="docker_desktop_windows",
    ),
    ComponentDefinition(
        component_id="jdk",
        label="JDK",
        kind="compiled_toolchain",
        command="javac",
        args=("-version",),
        required_for=("java_runner_planned",),
        guidance_id="jdk_windows",
    ),
    ComponentDefinition(
        component_id="go",
        label="Go",
        kind="compiled_toolchain",
        command="go",
        args=("version",),
        required_for=("go_runner_planned",),
        guidance_id="go_windows",
    ),
    ComponentDefinition(
        component_id="dotnet",
        label=".NET SDK",
        kind="compiled_toolchain",
        command="dotnet",
        args=("--version",),
        required_for=("csharp_runner_planned",),
        guidance_id="dotnet_windows",
    ),
    ComponentDefinition(
        component_id="postgres_client",
        label="PostgreSQL client",
        kind="database_tooling",
        command="psql",
        args=("--version",),
        required_for=("database_debug",),
        guidance_id="sql_database_windows",
    ),
)


GUIDANCE_TEMPLATES: tuple[GuidanceTemplate, ...] = (
    GuidanceTemplate(
        guidance_id="python_uv_windows",
        title="Install Python and uv on Windows",
        applies_to=("python_runtime", "uv", "python"),
        severity="required",
        summary="Aearn API, worker, bootstrap, and Python exercises rely on Python plus uv.",
        windows_steps=(
            "Install Python 3.11 or 3.12 from python.org or winget.",
            "Install uv from Astral's official installer or package manager.",
            "Restart PowerShell so PATH changes are visible before starting Aearn.",
        ),
        verification_commands=("python --version", "uv --version"),
        safety_notes=(
            "Do not let the Agent edit global PATH automatically.",
            "Keep project dependencies managed by uv inside aearn/services/api.",
        ),
    ),
    GuidanceTemplate(
        guidance_id="node_typescript_windows",
        title="Install Node.js and TypeScript tooling on Windows",
        applies_to=("node", "typescript", "javascript", "html", "css"),
        severity="required",
        summary="The desktop app, browser-style exercises, and TypeScript function runner require Node.js and local TypeScript tooling.",
        windows_steps=(
            "Install the Node.js LTS release.",
            "Enable or install pnpm for the Aearn workspace.",
            "Install TypeScript tooling only as a manual setup step; Aearn must not auto-install it.",
        ),
        verification_commands=("node --version", "pnpm --version", "tsc --version"),
        safety_notes=(
            "Detected Node.js alone is not enough for TypeScript execution; the local TypeScript compiler must also be available.",
            "Do not run npm, pnpm, or corepack mutation commands automatically from the doctor.",
        ),
    ),
    GuidanceTemplate(
        guidance_id="pnpm_windows",
        title="Install pnpm for the desktop workspace",
        applies_to=("pnpm", "desktop"),
        severity="required",
        summary="Aearn desktop scripts use pnpm from the aearn workspace.",
        windows_steps=(
            "Install pnpm through Node's package-manager flow or a trusted package manager.",
            "Run commands from the repository root with pnpm --dir .\\aearn ...",
        ),
        verification_commands=("pnpm --version", "pnpm --dir .\\aearn desktop:check"),
        safety_notes=("Do not run global package-manager mutation commands without user confirmation.",),
    ),
    GuidanceTemplate(
        guidance_id="docker_desktop_windows",
        title="Install and start Docker Desktop for local PostgreSQL and Redis",
        applies_to=("docker", "docker_compose", "postgres", "redis"),
        severity="required",
        summary="Local startup uses Docker Compose for PostgreSQL and Redis.",
        windows_steps=(
            "Install Docker Desktop for Windows.",
            "Start Docker Desktop manually and wait until it reports ready.",
            "Use pnpm --dir .\\aearn dev or docker compose -f .\\aearn\\infra\\docker-compose.yml ps to verify local services.",
        ),
        verification_commands=("docker --version", "docker compose version", "docker compose -f .\\aearn\\infra\\docker-compose.yml ps"),
        safety_notes=(
            "The doctor must not start or stop Docker.",
            "The doctor must not change WSL or Docker Desktop settings.",
        ),
    ),
    GuidanceTemplate(
        guidance_id="jdk_windows",
        title="Install a JDK for planned Java exercises",
        applies_to=("jdk", "java"),
        severity="recommended",
        summary="Java execution is planned and still static-review only in the current Aearn runner contract.",
        windows_steps=("Install a current LTS JDK such as Temurin 21.", "Restart PowerShell before checking javac."),
        verification_commands=("java --version", "javac -version"),
        safety_notes=("Detected JDK does not make Java execution available until the compiled runner task is complete.",),
    ),
    GuidanceTemplate(
        guidance_id="go_windows",
        title="Install Go for planned Go exercises",
        applies_to=("go",),
        severity="recommended",
        summary="Go execution is planned and not yet available in Aearn.",
        windows_steps=("Install Go from the official installer or trusted package manager.", "Restart PowerShell before checking go."),
        verification_commands=("go version",),
        safety_notes=("Detected Go does not make Go execution available until the compiled runner task is complete.",),
    ),
    GuidanceTemplate(
        guidance_id="dotnet_windows",
        title="Install .NET SDK for planned C# exercises",
        applies_to=("dotnet", "csharp"),
        severity="recommended",
        summary="C# execution is planned and not yet available in Aearn.",
        windows_steps=("Install a supported .NET SDK.", "Restart PowerShell before checking dotnet."),
        verification_commands=("dotnet --version",),
        safety_notes=("Detected .NET SDK does not make C# execution available until the compiled runner task is complete.",),
    ),
    GuidanceTemplate(
        guidance_id="sql_database_windows",
        title="Understand the SQLite teaching dialect for SQL exercises",
        applies_to=("sql", "postgres_client", "database_debug"),
        severity="optional",
        summary="SQL exercises use Python's bundled SQLite module in an isolated per-run teaching database; psql is only useful for debugging Aearn's PostgreSQL app database.",
        windows_steps=(
            "No separate SQL server is required for SQL exercises.",
            "Use Docker Desktop for the Aearn PostgreSQL service only when running the app database.",
            "Install PostgreSQL client tools only if you need local database debugging.",
        ),
        verification_commands=("python -c \"import sqlite3; print(sqlite3.sqlite_version)\"", "docker compose -f .\\aearn\\infra\\docker-compose.yml ps"),
        safety_notes=("SQL exercises must not run learner queries against Aearn's PostgreSQL app database.",),
    ),
)


LANGUAGE_TOOLCHAINS: dict[str, str | None] = {
    "python": "python_runtime",
    "javascript": "node",
    "typescript": "node",
    "html": "node",
    "css": "node",
    "sql": "python_runtime",
    "java": "jdk",
    "go": "go",
    "csharp": "dotnet",
    "rust": None,
    "cpp": None,
}


LANGUAGE_GUIDANCE: dict[str, str | None] = {
    "python": "python_uv_windows",
    "javascript": "node_typescript_windows",
    "typescript": "node_typescript_windows",
    "html": "node_typescript_windows",
    "css": "node_typescript_windows",
    "sql": "sql_database_windows",
    "java": "jdk_windows",
    "go": "go_windows",
    "csharp": "dotnet_windows",
    "rust": None,
    "cpp": None,
}


def build_environment_doctor_report(
    *,
    command_runner: CommandRunner | None = None,
    now: datetime | None = None,
    aearn_root: Path | None = None,
) -> EnvironmentDoctorReport:
    effective_now = now or datetime.now(UTC)
    runner = command_runner or run_version_probe
    root = aearn_root or _default_aearn_root()
    components = _build_components(runner, root)
    component_by_id = {component["component_id"]: component for component in components}
    language_runners = _build_language_runners(component_by_id)
    summary = _build_summary(components, language_runners)
    return {
        "generated_at": effective_now.isoformat().replace("+00:00", "Z"),
        "platform": {
            "system": platform.system() or "unknown",
            "release": platform.release() or "unknown",
            "python_executable": sys.executable,
        },
        "summary": summary,
        "components": components,
        "language_runners": language_runners,
        "guidance": [template.as_payload() for template in GUIDANCE_TEMPLATES],
    }


def run_version_probe(command: str, args: tuple[str, ...], timeout_s: float) -> CommandProbeResult:
    executable = shutil.which(command)
    if executable is None and _is_path_command(command):
        candidate = Path(command)
        if candidate.exists():
            executable = str(candidate)
    if executable is None:
        return CommandProbeResult(
            status="missing",
            version=None,
            executable_path=None,
            message=f"{command} was not found on PATH.",
        )
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandProbeResult(
            status="error",
            version=None,
            executable_path=executable,
            message=f"{command} {' '.join(args)} timed out.",
        )
    except OSError as exc:
        return CommandProbeResult(
            status="error",
            version=None,
            executable_path=executable,
            message=f"{command} {' '.join(args)} failed: {_bound_text(str(exc), 160)}",
        )

    stdout = _bound_text(completed.stdout.strip(), 500)
    stderr = _bound_text(completed.stderr.strip(), 500)
    version = _first_line(stdout or stderr)
    if completed.returncode != 0:
        return CommandProbeResult(
            status="error",
            version=version,
            executable_path=executable,
            message=f"{command} {' '.join(args)} failed with exit code {completed.returncode}.",
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    return CommandProbeResult(
        status="ready",
        version=version,
        executable_path=executable,
        message=f"{command} is available.",
        exit_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _build_components(command_runner: CommandRunner, aearn_root: Path) -> list[EnvironmentComponent]:
    components = [
        _api_component(),
        _startup_script_component(aearn_root),
        _python_runtime_component(),
    ]
    components.extend(_component_from_probe(definition, command_runner(definition.command, definition.args, 3.0)) for definition in COMMAND_CHECKS)
    components.append(_typescript_compiler_component(command_runner, aearn_root))
    return components


def _api_component() -> EnvironmentComponent:
    return {
        "component_id": "api_service",
        "label": "Aearn API",
        "kind": "service",
        "status": "ready",
        "version": "0.1.0",
        "executable_path": None,
        "required_for": ["local_startup", "desktop"],
        "guidance_id": None,
        "message": "The environment doctor route is reachable.",
        "diagnostic": _empty_diagnostic(),
    }


def _startup_script_component(aearn_root: Path) -> EnvironmentComponent:
    script_path = aearn_root / "scripts" / "start-dev.ps1"
    exists = script_path.exists()
    return {
        "component_id": "startup_script",
        "label": "Aearn start-dev.ps1",
        "kind": "startup",
        "status": "ready" if exists else "missing",
        "version": None,
        "executable_path": str(script_path) if exists else None,
        "required_for": ["local_startup"],
        "guidance_id": None,
        "message": "Stable startup script is present." if exists else "aearn/scripts/start-dev.ps1 was not found.",
        "diagnostic": _empty_diagnostic(),
    }


def _python_runtime_component() -> EnvironmentComponent:
    return {
        "component_id": "python_runtime",
        "label": "Python runtime",
        "kind": "runtime",
        "status": "ready",
        "version": platform.python_version(),
        "executable_path": sys.executable,
        "required_for": ["api", "worker", "python_runner", "local_startup"],
        "guidance_id": "python_uv_windows",
        "message": "The API is running under this Python interpreter.",
        "diagnostic": _empty_diagnostic(),
    }


def _component_from_probe(definition: ComponentDefinition, probe: CommandProbeResult) -> EnvironmentComponent:
    return {
        "component_id": definition.component_id,
        "label": definition.label,
        "kind": definition.kind,
        "status": probe.status,
        "version": probe.version,
        "executable_path": probe.executable_path,
        "required_for": list(definition.required_for),
        "guidance_id": definition.guidance_id,
        "message": probe.message,
        "diagnostic": {
            "command": definition.command,
            "args": list(definition.args),
            "exit_code": probe.exit_code,
            "stdout": probe.stdout,
            "stderr": probe.stderr,
        },
    }


def _typescript_compiler_component(command_runner: CommandRunner, aearn_root: Path) -> EnvironmentComponent:
    definition = ComponentDefinition(
        component_id="typescript_compiler",
        label="TypeScript compiler",
        kind="runtime",
        command=_typescript_compiler_command(aearn_root),
        args=("--version",),
        required_for=("node_typescript_runner",),
        guidance_id="node_typescript_windows",
    )
    return _component_from_probe(definition, command_runner(definition.command, definition.args, 3.0))


def _build_language_runners(component_by_id: dict[str, EnvironmentComponent]) -> list[LanguageRunnerStatus]:
    registry = get_runner_registry()
    statuses: list[LanguageRunnerStatus] = []
    for capability in all_language_capabilities():
        runner_capability = registry.select(
            {
                "runtime_tier": capability.execution,
                "language": capability.language_id,
            },
        )
        toolchain_status = _toolchain_status_for(capability.language_id, component_by_id)
        statuses.append(
            {
                "language_id": capability.language_id,
                "display_name": capability.display_name,
                "runner_key": runner_capability.runner_key,
                "execution": capability.execution,
                "capability_state": capability.capability_state,
                "supports_execution": capability.supports_execution,
                "toolchain_status": toolchain_status,
                "product_status": _product_status_for(capability.exercise_generation, capability.execution),
                "guidance_id": LANGUAGE_GUIDANCE.get(capability.language_id),
                "disclosure": capability.ux_disclosure,
            },
        )
    return statuses


def _product_status_for(exercise_generation: str, execution: str) -> ProductStatus:
    if execution in {"browser_preview", "python_stdout_test", "node_typescript_test", "sql_query_test"}:
        return "executable"
    if exercise_generation == "static_review":
        return "static_review"
    if execution == "none":
        return "unsupported"
    return "planned"


def _toolchain_status_for(language_id: str, component_by_id: dict[str, EnvironmentComponent]) -> ComponentStatus:
    if language_id == "typescript":
        return _combined_component_status(("node", "typescript_compiler"), component_by_id)
    toolchain_component_id = LANGUAGE_TOOLCHAINS.get(language_id)
    if not toolchain_component_id:
        return "planned"
    return component_by_id.get(toolchain_component_id, _planned_component())["status"]


def _combined_component_status(component_ids: Sequence[str], component_by_id: dict[str, EnvironmentComponent]) -> ComponentStatus:
    statuses = [component_by_id.get(component_id, _planned_component())["status"] for component_id in component_ids]
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "missing" for status in statuses):
        return "missing"
    if any(status == "planned" for status in statuses):
        return "planned"
    return "ready"


def _build_summary(
    components: Sequence[EnvironmentComponent],
    language_runners: Sequence[LanguageRunnerStatus],
) -> EnvironmentSummary:
    ready_count = sum(1 for component in components if component["status"] == "ready")
    missing_required_count = sum(
        1
        for component in components
        if "local_startup" in component["required_for"] and component["status"] in {"missing", "error"}
    )
    planned_runner_count = sum(1 for runner in language_runners if runner["product_status"] == "planned")
    overall_status: OverallStatus = "ready"
    if missing_required_count:
        overall_status = "blocked"
    elif any(component["status"] in {"missing", "error"} for component in components) or planned_runner_count:
        overall_status = "needs_attention"
    return {
        "overall_status": overall_status,
        "ready_count": ready_count,
        "missing_required_count": missing_required_count,
        "planned_runner_count": planned_runner_count,
    }


def _empty_diagnostic() -> ComponentDiagnostic:
    return {"command": None, "args": [], "exit_code": None, "stdout": "", "stderr": ""}


def _planned_component() -> EnvironmentComponent:
    return {
        "component_id": "planned",
        "label": "Planned",
        "kind": "runtime",
        "status": "planned",
        "version": None,
        "executable_path": None,
        "required_for": [],
        "guidance_id": None,
        "message": "No local toolchain is required in this phase.",
        "diagnostic": _empty_diagnostic(),
    }


def _default_aearn_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _typescript_compiler_command(aearn_root: Path) -> str:
    found = shutil.which("tsc")
    if found:
        return "tsc"
    for candidate in _local_tsc_candidates(aearn_root):
        if candidate.exists():
            return str(candidate)
    return "tsc"


def _local_tsc_candidates(aearn_root: Path) -> tuple[Path, ...]:
    suffix = "tsc.CMD" if os.name == "nt" else "tsc"
    return (
        aearn_root / "node_modules" / ".pnpm" / "node_modules" / ".bin" / suffix,
        aearn_root / "apps" / "desktop" / "node_modules" / ".bin" / suffix,
    )


def _is_path_command(command: str) -> bool:
    return os.sep in command or (os.altsep is not None and os.altsep in command)


def _first_line(value: str) -> str | None:
    if not value:
        return None
    return value.splitlines()[0].strip() or None


def _bound_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 3] + "..."
