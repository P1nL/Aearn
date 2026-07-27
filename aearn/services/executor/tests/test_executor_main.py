from __future__ import annotations

from pathlib import Path

import psycopg

import aearn_executor.main as executor_main
from aearn_executor.settings import ExecutorSettings

EXECUTOR_ROOT = Path(__file__).resolve().parents[3] / "infra" / "executor"


def test_main_returns_a_safe_failure_for_a_known_operational_error(monkeypatch, capsys) -> None:
    settings = ExecutorSettings(
        database_url="postgresql://unused",
        executor_id="test-executor",
        enabled=False,
        poll_interval_seconds=1,
        lease_seconds=30,
        health_interval_seconds=15,
        service_version="container-executor-v1",
        registry_root=EXECUTOR_ROOT,
    )

    monkeypatch.setattr(
        executor_main.ExecutorSettings,
        "from_environment",
        classmethod(lambda cls: settings),
    )
    monkeypatch.setattr(executor_main, "load_runtime_catalog_registry", lambda **kwargs: object())

    def fail_connect(*args, **kwargs):
        raise psycopg.OperationalError("database connection details must stay private")

    monkeypatch.setattr(executor_main.psycopg, "connect", fail_connect)

    assert executor_main.main(["--once"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
