from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from aearn_shared.execution import RuntimeImageLockV1, load_runtime_catalog_registry
from app.services.tutor.execution import ExecutionIntentRepository


API_ROOT = Path(__file__).resolve().parents[1]
AEARN_ROOT = API_ROOT.parents[1]
EXECUTOR_ROOT = AEARN_ROOT / "infra" / "executor"


class _Result:
    def __init__(self, value):
        self._value = value

    def fetchone(self):
        return self._value


class _Connection:
    def __init__(self, result=None) -> None:
        self.result = result
        self.calls: list[tuple[str, object]] = []

    def execute(self, query: str, params=None):
        self.calls.append((query, params))
        return _Result(self.result)


def _registry_with_lock(tmp_path) -> object:
    source = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    entry = source.runtime("python-stdout-v1")
    lock = RuntimeImageLockV1(
        runtime_id=entry.runtime_id,
        protocol_version=entry.protocol_version,
        image_reference=f"registry.example/aearn/python@sha256:{'b' * 63}c",
        fixed_entrypoint=entry.fixed_entrypoint,
        non_root_user=entry.non_root_user,
        limits=entry.limits,
    )
    return source.__class__(
        runtimes=source.runtimes,
        locks=(lock,),
        catalog_fingerprint=source.catalog_fingerprint,
        fingerprint="f" * 64,
    )


def test_feature_off_gate_denies_before_any_health_database_read(tmp_path) -> None:
    connection = _Connection()
    repository = ExecutionIntentRepository(
        connection,  # type: ignore[arg-type]
        registry=_registry_with_lock(tmp_path),
        executor_enabled=lambda: False,
    )

    availability = repository.availability_for_runtime("python-stdout-v1")

    assert availability.available is False
    assert availability.code == "executor_feature_disabled"
    assert connection.calls == []


def test_empty_lock_registry_fails_closed_before_any_health_database_read() -> None:
    connection = _Connection()
    registry = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    repository = ExecutionIntentRepository(
        connection,  # type: ignore[arg-type]
        registry=registry,
        executor_enabled=lambda: True,
    )

    availability = repository.availability_for_runtime("python-stdout-v1")

    assert availability.available is False
    assert availability.code == "runtime_lock_unavailable"
    assert connection.calls == []


def test_stale_or_missing_executor_heartbeat_is_unavailable(tmp_path) -> None:
    registry = _registry_with_lock(tmp_path)
    now = datetime(2026, 7, 27, tzinfo=UTC)
    connection = _Connection(
        {
            "status": "available",
            "registry_fingerprint": registry.fingerprint,
            "verified_runtime_ids_json": ["python-stdout-v1"],
            "availability_code": "executor_available",
            "last_heartbeat_at": now - timedelta(seconds=91),
        }
    )
    repository = ExecutionIntentRepository(
        connection,  # type: ignore[arg-type]
        registry=registry,
        executor_enabled=lambda: True,
        clock=lambda: now,
    )

    availability = repository.availability_for_runtime("python-stdout-v1")

    assert availability.available is False
    assert availability.code == "executor_health_stale"
