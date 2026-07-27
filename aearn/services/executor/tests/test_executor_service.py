from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aearn_shared.execution import (
    ExecutionHealthV1,
    ExecutionJobClaimV1,
    ExecutionJobState,
    ExecutionJobV1,
    RuntimeImageLockV1,
    load_runtime_catalog_registry,
)

from aearn_executor.runtime import ClaimedExecutionJob, ContainerLookup
from aearn_executor.service import ExecutorService
from aearn_executor.settings import ExecutorSettings

EXECUTOR_ROOT = Path(__file__).resolve().parents[3] / "infra" / "executor"
NOW = datetime(2026, 7, 27, tzinfo=UTC)


class _Store:
    def __init__(self, *, recovered: ClaimedExecutionJob | None = None) -> None:
        self.recovered = recovered
        self.health: list[ExecutionHealthV1] = []
        self.create_claim_calls = 0
        self.uncertain = 0

    def record_health(self, health: ExecutionHealthV1) -> None:
        self.health.append(health)

    def claim_reserved_for_recovery(self, **kwargs):
        value = self.recovered
        self.recovered = None
        return value

    def claim_next(self, **kwargs):
        self.create_claim_calls += 1

    def mark_launch_uncertain(self, **kwargs) -> None:
        self.uncertain += 1

    def quarantine(self, **kwargs) -> None:
        raise AssertionError("cleanup quarantine should not run")


class _InputResolver:
    def load(self, **kwargs):
        raise AssertionError("reserved recovery without a live container must not load raw input")


class _Client:
    def __init__(self, *, lock_available: bool = True) -> None:
        self.lock_available = lock_available
        self.verify_calls = 0
        self.create_calls = 0

    def verify_lock(self, lock) -> bool:
        self.verify_calls += 1
        return self.lock_available

    def find_matching(self, spec):
        return ContainerLookup(handle=None)

    def create_and_start(self, **kwargs):
        self.create_calls += 1
        raise AssertionError("uncertain recovery must never create a second container")


def _registry_with_lock():
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
        fingerprint="c" * 64,
    ), lock


def _settings(*, enabled: bool) -> ExecutorSettings:
    return ExecutorSettings(
        database_url="postgresql://unused",
        executor_id="test-executor",
        enabled=enabled,
        poll_interval_seconds=1,
        lease_seconds=30,
        health_interval_seconds=15,
        service_version="container-executor-v1",
        registry_root=EXECUTOR_ROOT,
    )


def test_feature_off_executor_records_safe_health_without_constructing_runtime_work() -> None:
    registry, _ = _registry_with_lock()
    store = _Store()
    client = _Client()
    service = ExecutorService(
        store=store,
        input_resolver=_InputResolver(),
        runtime_client=client,
        registry=registry,
        settings=_settings(enabled=False),
        clock=lambda: NOW,
    )

    assert service.run_once() is False
    assert client.verify_calls == 0
    assert client.create_calls == 0
    assert store.create_claim_calls == 0
    assert store.health[-1].status == "unavailable"
    assert store.health[-1].availability_code == "executor_feature_disabled"


def test_enabled_executor_with_empty_lock_registry_never_probes_or_starts_a_runtime() -> None:
    registry = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    store = _Store()
    client = _Client()
    service = ExecutorService(
        store=store,
        input_resolver=_InputResolver(),
        runtime_client=client,
        registry=registry,
        settings=_settings(enabled=True),
        clock=lambda: NOW,
    )

    assert service.run_once() is False
    assert client.verify_calls == 0
    assert client.create_calls == 0
    assert store.create_claim_calls == 0
    assert store.health[-1].status == "unavailable"
    assert store.health[-1].availability_code == "runtime_lock_unavailable"


def test_docker_unavailable_health_never_claims_or_uses_a_host_fallback() -> None:
    registry, _ = _registry_with_lock()
    store = _Store()
    client = _Client(lock_available=False)
    service = ExecutorService(
        store=store,
        input_resolver=_InputResolver(),
        runtime_client=client,
        registry=registry,
        settings=_settings(enabled=True),
        clock=lambda: NOW,
    )

    assert service.run_once() is False
    assert client.verify_calls == 1
    assert client.create_calls == 0
    assert store.create_claim_calls == 0
    assert store.health[-1].status == "unavailable"
    assert store.health[-1].availability_code == "runtime_image_unavailable"


def test_reserved_launch_without_a_matching_container_becomes_uncertain_without_second_start() -> None:
    registry, lock = _registry_with_lock()
    job = ExecutionJobV1(
        job_id="job-1",
        effect_id="effect-1",
        intent_proof_id="proof-1",
        user_id="user-1",
        conversation_id="conversation-1",
        run_id="run-1",
        runtime_id=lock.runtime_id,
        lock_fingerprint=lock.fingerprint,
        state=ExecutionJobState.LAUNCH_RESERVED,
        launch_token="launch-token-1",
        launch_generation=1,
    )
    claim = ExecutionJobClaimV1(
        job_id=job.job_id,
        executor_id="previous-executor",
        lease_generation=1,
        lease_expires_at=NOW,
    )
    store = _Store(recovered=ClaimedExecutionJob(job=job, claim=claim))
    client = _Client()
    service = ExecutorService(
        store=store,
        input_resolver=_InputResolver(),
        runtime_client=client,
        registry=registry,
        settings=_settings(enabled=True),
        clock=lambda: NOW,
    )

    assert service.run_once() is True
    assert store.uncertain == 1
    assert client.create_calls == 0
