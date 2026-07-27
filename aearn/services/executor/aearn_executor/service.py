"""At-most-once coordinator for the dedicated privileged executor process."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol

from aearn_shared.execution import (
    ExecutionHealthV1,
    RuntimeCatalogRegistryV1,
    SafeExecutionResultV1,
    SafeExecutionStatus,
)

from aearn_executor.launch import build_launch_spec
from aearn_executor.runtime import (
    ClaimedExecutionJob,
    ContainerRuntimeClient,
    ExecutionJobStore,
    ExecutionJobStoreError,
    LaunchReservation,
    RuntimeClientError,
    RuntimeLaunchUncertainError,
    RuntimeUnavailableError,
    TrustedInputResolutionError,
    TrustedInputResolver,
)
from aearn_executor.settings import ExecutorSettings


class ExecutorClock(Protocol):
    def __call__(self) -> datetime: ...


class ExecutorService:
    """Claims durable jobs after commit and prefers uncertainty over duplicate launch."""

    def __init__(
        self,
        *,
        store: ExecutionJobStore,
        input_resolver: TrustedInputResolver,
        runtime_client: ContainerRuntimeClient,
        registry: RuntimeCatalogRegistryV1,
        settings: ExecutorSettings,
        clock: ExecutorClock | None = None,
    ) -> None:
        self._store = store
        self._input_resolver = input_resolver
        self._runtime_client = runtime_client
        self._registry = registry
        self._settings = settings
        self._clock = clock or (lambda: datetime.now(UTC))
        self._last_health: ExecutionHealthV1 | None = None

    def run_once(self) -> bool:
        """Refresh health and process at most one durable job or reserved recovery."""

        now = self._now()
        health = self._refresh_health(now=now)
        self._last_health = health
        if health.status != "available":
            return False

        recovered = self._store.claim_reserved_for_recovery(
            executor_id=self._settings.executor_id,
            now=now,
            lease_seconds=self._settings.lease_seconds,
        )
        if recovered is not None:
            if recovered.job.runtime_id not in health.verified_runtime_ids:
                self._store.mark_launch_uncertain(
                    reservation=LaunchReservation(job=recovered.job, claim=recovered.claim),
                    now=self._now(),
                )
                return True
            self._execute_claim(claimed=recovered, allow_create=False)
            return True

        claimed = self._store.claim_next(
            executor_id=self._settings.executor_id,
            now=now,
            lease_seconds=self._settings.lease_seconds,
        )
        if claimed is None:
            return False
        if claimed.job.runtime_id not in health.verified_runtime_ids:
            try:
                self._store.mark_unavailable(
                    claimed=claimed,
                    code="runtime_health_unavailable",
                    now=self._now(),
                )
            except ExecutionJobStoreError:
                pass
            return True
        lock = self._registry.lock_for(claimed.job.runtime_id)
        if lock is None or lock.fingerprint != claimed.job.lock_fingerprint:
            try:
                self._store.mark_unavailable(claimed=claimed, code="runtime_lock_unavailable", now=self._now())
            except ExecutionJobStoreError:
                pass
            return True
        try:
            reservation = self._store.reserve_launch(claimed=claimed, now=self._now())
        except ExecutionJobStoreError:
            # A newer executor reclaimed the expired pre-launch lease. It owns
            # the only permissible future reservation; this worker does nothing.
            return True
        if reservation is None:
            return True
        self._execute_reservation(reservation=reservation, lock=lock, allow_create=True)
        return True

    def _execute_claim(self, *, claimed: ClaimedExecutionJob, allow_create: bool) -> None:
        lock = self._registry.lock_for(claimed.job.runtime_id)
        if lock is None or lock.fingerprint != claimed.job.lock_fingerprint or not claimed.job.launch_token:
            reservation = LaunchReservation(job=claimed.job, claim=claimed.claim)
            self._store.mark_launch_uncertain(reservation=reservation, now=self._now())
            return
        self._execute_reservation(
            reservation=LaunchReservation(job=claimed.job, claim=claimed.claim),
            lock=lock,
            allow_create=allow_create,
        )

    def _execute_reservation(self, *, reservation: LaunchReservation, lock, allow_create: bool) -> None:
        spec = build_launch_spec(job=reservation.job, lock=lock)
        handle = None
        try:
            lookup = self._runtime_client.find_matching(spec)
            if lookup.ambiguous:
                self._store.mark_launch_uncertain(reservation=reservation, now=self._now())
                return
            handle = lookup.handle
            if handle is None:
                if not allow_create:
                    self._store.mark_launch_uncertain(reservation=reservation, now=self._now())
                    return
                sandbox_input = self._input_resolver.load(job=reservation.job)
                handle = self._runtime_client.create_and_start(spec=spec, sandbox_input=sandbox_input)
            self._store.mark_running(reservation=reservation, now=self._now())
            raw_result = self._runtime_client.wait_for_result(
                handle=handle,
                spec=spec,
                lock=lock,
                should_cancel=lambda: self._store.cancellation_requested(job_id=reservation.job.job_id),
            )
            self._store.complete(
                reservation=reservation,
                result=SafeExecutionResultV1.from_sandbox_result(raw_result),
                now=self._now(),
            )
        except TrustedInputResolutionError:
            self._store.complete(
                reservation=reservation,
                result=SafeExecutionResultV1(status=SafeExecutionStatus.FAILED, diagnostic_code="trusted_input_unavailable"),
                now=self._now(),
            )
        except RuntimeUnavailableError as exc:
            self._store.complete(
                reservation=reservation,
                result=SafeExecutionResultV1(status=SafeExecutionStatus.UNAVAILABLE, diagnostic_code=exc.code),
                now=self._now(),
            )
        except RuntimeLaunchUncertainError:
            self._store.mark_launch_uncertain(reservation=reservation, now=self._now())
        except RuntimeClientError as exc:
            self._store.complete(
                reservation=reservation,
                result=SafeExecutionResultV1(status=SafeExecutionStatus.FAILED, diagnostic_code=exc.code),
                now=self._now(),
            )
        finally:
            if handle is not None:
                try:
                    self._runtime_client.cleanup(handle)
                    self._store.record_cleanup(reservation=reservation, succeeded=True, now=self._now())
                except RuntimeClientError:
                    self._store.record_cleanup(reservation=reservation, succeeded=False, now=self._now())
                    if self._last_health is not None:
                        self._store.quarantine(health=self._last_health, code="cleanup_failed", now=self._now())

    def _refresh_health(self, *, now: datetime) -> ExecutionHealthV1:
        if not self._settings.enabled:
            health = self._health(status="unavailable", verified=(), code="executor_feature_disabled", now=now)
            self._store.record_health(health)
            return health
        if not self._registry.locks:
            health = self._health(status="unavailable", verified=(), code="runtime_lock_unavailable", now=now)
            self._store.record_health(health)
            return health
        verified = tuple(lock.runtime_id for lock in self._registry.locks if self._runtime_client.verify_lock(lock))
        health = self._health(
            status="available" if verified else "unavailable",
            verified=verified,
            code="executor_available" if verified else "runtime_image_unavailable",
            now=now,
        )
        self._store.record_health(health)
        return health

    def _health(
        self,
        *,
        status: Literal["available", "unavailable", "quarantined"],
        verified: tuple[str, ...],
        code: str,
        now: datetime,
    ) -> ExecutionHealthV1:
        return ExecutionHealthV1(
            executor_id=self._settings.executor_id,
            service_version=self._settings.service_version,
            registry_fingerprint=self._registry.fingerprint,
            status=status,
            verified_runtime_ids=verified,
            availability_code=code,
            last_heartbeat_at=now,
        )

    def _now(self) -> datetime:
        value = self._clock()
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
