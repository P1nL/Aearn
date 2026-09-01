from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aearn_shared.execution import (
    ExecutionAction,
    ExecutionHealthV1,
    ExecutionJobClaimV1,
    ExecutionJobState,
    ExecutionJobV1,
    RuntimeImageLockV1,
    SafeExecutionResultV2,
    SandboxInputV1,
    SandboxResultV1,
    SandboxTestFeedbackV1,
    load_runtime_catalog_registry,
)

from aearn_executor.runtime import (
    ClaimedExecutionJob,
    ContainerHandle,
    ContainerLookup,
    LaunchReservation,
)
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


class _ExecutingStore:
    def __init__(self, claimed: ClaimedExecutionJob) -> None:
        self._claimed: ClaimedExecutionJob | None = claimed
        self.health: list[ExecutionHealthV1] = []
        self.completed: SafeExecutionResultV2 | None = None
        self.cleanup_succeeded = False

    def record_health(self, health: ExecutionHealthV1) -> None:
        self.health.append(health)

    def claim_reserved_for_recovery(self, **_kwargs):
        return None

    def claim_next(self, **_kwargs):
        claimed = self._claimed
        self._claimed = None
        return claimed

    def reserve_launch(self, *, claimed: ClaimedExecutionJob, **_kwargs):
        return LaunchReservation(
            job=claimed.job.model_copy(
                update={
                    "state": ExecutionJobState.LAUNCH_RESERVED,
                    "launch_token": "launch-token-v2",
                    "launch_generation": claimed.claim.lease_generation,
                }
            ),
            claim=claimed.claim,
        )

    def mark_running(self, *, reservation: LaunchReservation, **_kwargs):
        return reservation.job.model_copy(update={"state": ExecutionJobState.RUNNING})

    def complete(self, *, result: SafeExecutionResultV2, **_kwargs) -> None:
        self.completed = result

    def cancellation_requested(self, **_kwargs) -> bool:
        return False

    def record_cleanup(self, *, succeeded: bool, **_kwargs) -> None:
        self.cleanup_succeeded = succeeded

    def quarantine(self, **_kwargs) -> None:
        raise AssertionError("successful cleanup must not quarantine executor health")


class _ExecutingInputResolver:
    def __init__(self, runtime_id: str) -> None:
        self._runtime_id = runtime_id

    def load(self, **_kwargs) -> SandboxInputV1:
        return SandboxInputV1(
            runtime_id=self._runtime_id,
            action=ExecutionAction.RUN,
            submission="print(1)",
            source_reference_hash="d" * 64,
            test_reference_hash="e" * 64,
        )


class _ExecutingClient(_Client):
    def find_matching(self, spec):
        return ContainerLookup(handle=None)

    def create_and_start(self, **_kwargs):
        self.create_calls += 1
        return ContainerHandle(container=object(), name="executor-v2-test")

    def wait_for_result(self, **_kwargs) -> SandboxResultV1:
        return SandboxResultV1(
            status="success",
            test_feedback=(
                SandboxTestFeedbackV1(
                    case_id="private-hidden-id",
                    passed=True,
                    visibility="hidden",
                    message="expected private value",
                ),
            ),
            passed_test_count=1,
            total_test_count=1,
            diagnostic_code="completed",
        )

    def cleanup(self, _handle: ContainerHandle) -> None:
        return None


def test_completed_executor_job_writes_strict_v2_with_hidden_redaction() -> None:
    registry, lock = _registry_with_lock()
    job = ExecutionJobV1(
        job_id="job-v2",
        effect_id="effect-v2",
        intent_proof_id="proof-v2",
        user_id="user-v2",
        conversation_id="conversation-v2",
        run_id="run-v2",
        runtime_id=lock.runtime_id,
        lock_fingerprint=lock.fingerprint,
        state=ExecutionJobState.CLAIMED,
    )
    claim = ExecutionJobClaimV1(
        job_id=job.job_id,
        executor_id="test-executor",
        lease_generation=1,
        lease_expires_at=NOW,
    )
    store = _ExecutingStore(ClaimedExecutionJob(job=job, claim=claim))
    client = _ExecutingClient()
    service = ExecutorService(
        store=store,
        input_resolver=_ExecutingInputResolver(lock.runtime_id),
        runtime_client=client,
        registry=registry,
        settings=_settings(enabled=True),
        clock=lambda: NOW,
    )

    assert service.run_once() is True
    assert store.completed is not None
    assert store.completed.schema_version == "safe-execution-result-v2"
    assert store.completed.presentation.kind == "none"
    assert store.completed.test_feedback[0].case_id == "non-visible-1"
    assert store.completed.test_feedback[0].message == "A non-visible scenario passed."
    assert store.cleanup_succeeded is True
