"""Settings for the standalone executor process.

The executor deliberately reads only process environment. It does not load the
repository `.env` file, and its API/worker peers do not receive its runtime
client dependency.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes"}


def _int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if minimum <= value <= maximum else default


@dataclass(frozen=True)
class ExecutorSettings:
    database_url: str
    executor_id: str
    enabled: bool
    poll_interval_seconds: float
    lease_seconds: int
    health_interval_seconds: int
    service_version: str
    registry_root: Path

    @classmethod
    def from_environment(cls) -> ExecutorSettings:
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable",
            ).strip(),
            executor_id=os.getenv("AEARN_EXECUTOR_ID", "aearn-executor-local").strip() or "aearn-executor-local",
            enabled=_bool("TUTOR_EXECUTOR_ENABLED", False),
            poll_interval_seconds=_int("AEARN_EXECUTOR_POLL_SECONDS", 2, minimum=1, maximum=30),
            lease_seconds=_int("AEARN_EXECUTOR_LEASE_SECONDS", 30, minimum=5, maximum=120),
            health_interval_seconds=_int("AEARN_EXECUTOR_HEALTH_SECONDS", 15, minimum=5, maximum=120),
            service_version="container-executor-v1",
            registry_root=_registry_root(),
        )


def _registry_root() -> Path:
    for ancestor in Path(__file__).resolve().parents:
        candidate = ancestor / "infra" / "executor"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("executor infrastructure registry is missing")
