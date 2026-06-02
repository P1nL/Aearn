from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services.environment_doctor import (
    CommandProbeResult,
    build_environment_doctor_report,
)


def _aearn_root(tmp_path: Path) -> Path:
    root = tmp_path / "aearn"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "start-dev.ps1").write_text("param()\n", encoding="utf-8")
    return root


def _ready_runner(calls: list[tuple[str, tuple[str, ...]]]) -> Callable[[str, tuple[str, ...], float], CommandProbeResult]:
    def runner(command: str, args: tuple[str, ...], timeout_s: float) -> CommandProbeResult:
        calls.append((command, args))
        return CommandProbeResult(
            status="ready",
            version=f"{command} version",
            executable_path=f"C:/tools/{command}.exe",
            message=f"{command} is available.",
            exit_code=0,
            stdout=f"{command} version",
            stderr="",
        )

    return runner


def test_environment_doctor_reports_ready_components_and_static_guidance(tmp_path: Path) -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    report = build_environment_doctor_report(
        command_runner=_ready_runner(calls),
        aearn_root=_aearn_root(tmp_path),
    )

    components = {component["component_id"]: component for component in report["components"]}
    guidance = {item["guidance_id"]: item for item in report["guidance"]}

    assert components["api_service"]["status"] == "ready"
    assert components["startup_script"]["status"] == "ready"
    assert components["python_runtime"]["status"] == "ready"
    assert components["node"]["status"] == "ready"
    assert components["typescript_compiler"]["status"] == "ready"
    assert components["docker"]["status"] == "ready"
    assert report["summary"]["missing_required_count"] == 0
    assert all(item["source"] == "static_template" for item in guidance.values())
    assert guidance["node_typescript_windows"]["verification_commands"] == [
        "node --version",
        "pnpm --version",
        "tsc --version",
    ]
    assert all("install" not in args for _, args in calls)


def test_environment_doctor_reports_missing_required_tooling(tmp_path: Path) -> None:
    def runner(command: str, args: tuple[str, ...], timeout_s: float) -> CommandProbeResult:
        if command in {"node", "docker"}:
            return CommandProbeResult(
                status="missing",
                version=None,
                executable_path=None,
                message=f"{command} was not found on PATH.",
            )
        return CommandProbeResult(
            status="ready",
            version=f"{command} version",
            executable_path=f"C:/tools/{command}.exe",
            message=f"{command} is available.",
            exit_code=0,
        )

    report = build_environment_doctor_report(
        command_runner=runner,
        aearn_root=_aearn_root(tmp_path),
    )

    components = {component["component_id"]: component for component in report["components"]}
    runners = {item["language_id"]: item for item in report["language_runners"]}

    assert report["summary"]["overall_status"] == "blocked"
    assert report["summary"]["missing_required_count"] >= 2
    assert components["node"]["status"] == "missing"
    assert components["docker"]["status"] == "missing"
    assert runners["typescript"]["toolchain_status"] == "missing"
    assert runners["typescript"]["product_status"] == "executable"
    assert runners["typescript"]["supports_execution"] is True


def test_environment_doctor_preserves_command_errors(tmp_path: Path) -> None:
    def runner(command: str, args: tuple[str, ...], timeout_s: float) -> CommandProbeResult:
        if command == "docker":
            return CommandProbeResult(
                status="error",
                version=None,
                executable_path="C:/tools/docker.exe",
                message="docker --version failed with exit code 1.",
                exit_code=1,
                stderr="Docker daemon unavailable",
            )
        return CommandProbeResult(
            status="ready",
            version=f"{command} version",
            executable_path=f"C:/tools/{command}.exe",
            message=f"{command} is available.",
            exit_code=0,
        )

    report = build_environment_doctor_report(
        command_runner=runner,
        aearn_root=_aearn_root(tmp_path),
    )

    docker = next(component for component in report["components"] if component["component_id"] == "docker")

    assert docker["status"] == "error"
    assert docker["message"] == "docker --version failed with exit code 1."
    assert docker["diagnostic"]["stderr"] == "Docker daemon unavailable"


def test_environment_doctor_does_not_turn_detected_planned_tools_into_execution(tmp_path: Path) -> None:
    report = build_environment_doctor_report(
        command_runner=_ready_runner([]),
        aearn_root=_aearn_root(tmp_path),
    )

    runners = {item["language_id"]: item for item in report["language_runners"]}

    assert runners["python"]["product_status"] == "executable"
    assert runners["typescript"]["toolchain_status"] == "ready"
    assert runners["typescript"]["product_status"] == "executable"
    assert runners["typescript"]["supports_execution"] is True
    assert runners["sql"]["product_status"] == "executable"
    assert runners["sql"]["toolchain_status"] == "ready"
    assert "SQLite teaching dialect" in runners["sql"]["disclosure"]
    assert runners["java"]["product_status"] == "executable"
    assert runners["java"]["supports_execution"] is True
    assert runners["go"]["product_status"] == "executable"
    assert runners["go"]["supports_execution"] is True
    assert runners["csharp"]["product_status"] == "executable"
    assert runners["csharp"]["supports_execution"] is True
    assert runners["rust"]["product_status"] == "planned"
    assert runners["cpp"]["product_status"] == "static_review"


def test_environment_doctor_distinguishes_toolchain_missing_from_product_support(tmp_path: Path) -> None:
    def runner(command: str, args: tuple[str, ...], timeout_s: float) -> CommandProbeResult:
        del args, timeout_s
        if command in {"javac", "go", "dotnet"}:
            return CommandProbeResult(
                status="missing",
                version=None,
                executable_path=None,
                message=f"{command} was not found on PATH.",
            )
        return CommandProbeResult(
            status="ready",
            version=f"{command} version",
            executable_path=f"C:/tools/{command}.exe",
            message=f"{command} is available.",
            exit_code=0,
        )

    report = build_environment_doctor_report(
        command_runner=runner,
        aearn_root=_aearn_root(tmp_path),
    )

    runners = {item["language_id"]: item for item in report["language_runners"]}

    assert runners["java"]["product_status"] == "executable"
    assert runners["java"]["toolchain_status"] == "missing"
    assert runners["go"]["product_status"] == "executable"
    assert runners["go"]["toolchain_status"] == "missing"
    assert runners["csharp"]["product_status"] == "executable"
    assert runners["csharp"]["toolchain_status"] == "missing"
    assert runners["rust"]["product_status"] == "planned"
    assert runners["cpp"]["product_status"] == "static_review"


def test_environment_doctor_route_returns_contract() -> None:
    client = TestClient(app)

    response = client.get("/api/environment/doctor")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"generated_at", "platform", "summary", "components", "language_runners", "guidance"}
    assert payload["summary"]["overall_status"] in {"ready", "needs_attention", "blocked"}
    assert payload["components"]
    assert payload["language_runners"]
    assert payload["guidance"]
