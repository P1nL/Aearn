"""Pure runtime-client protocol shared by executor orchestration and fakes."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from aearn_shared.execution import (
    ExecutionHealthV1,
    ExecutionJobClaimV1,
    ExecutionJobV1,
    RuntimeImageLockV1,
    SafeExecutionResultV2,
    SandboxInputV1,
    SandboxResultV1,
)

from aearn_executor.launch import LaunchSpec


class RuntimeClientError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RuntimeUnavailableError(RuntimeClientError):
    pass


class RuntimeLaunchUncertainError(RuntimeClientError):
    pass


class ExecutionJobStoreError(RuntimeError):
    """A stale or ineligible durable job transition that must not launch work."""


class TrustedInputResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ContainerHandle:
    """Live-only internal handle. It must never be serialized or logged."""

    container: Any
    name: str


@dataclass(frozen=True)
class ContainerLookup:
    handle: ContainerHandle | None
    ambiguous: bool = False


@dataclass(frozen=True)
class ClaimedExecutionJob:
    job: ExecutionJobV1
    claim: ExecutionJobClaimV1


@dataclass(frozen=True)
class LaunchReservation:
    job: ExecutionJobV1
    claim: ExecutionJobClaimV1


class TrustedInputResolver(Protocol):
    def load(self, *, job: ExecutionJobV1) -> SandboxInputV1: ...


class ExecutionJobStore(Protocol):
    def claim_next(self, *, executor_id: str, now: datetime, lease_seconds: int) -> ClaimedExecutionJob | None: ...

    def claim_reserved_for_recovery(
        self,
        *,
        executor_id: str,
        now: datetime,
        lease_seconds: int,
    ) -> ClaimedExecutionJob | None: ...

    def reserve_launch(self, *, claimed: ClaimedExecutionJob, now: datetime) -> LaunchReservation | None: ...

    def mark_running(self, *, reservation: LaunchReservation, now: datetime) -> ExecutionJobV1: ...

    def mark_unavailable(self, *, claimed: ClaimedExecutionJob, code: str, now: datetime) -> None: ...

    def mark_launch_uncertain(self, *, reservation: LaunchReservation, now: datetime) -> None: ...

    def complete(self, *, reservation: LaunchReservation, result: SafeExecutionResultV2, now: datetime) -> None: ...

    def record_cleanup(self, *, reservation: LaunchReservation, succeeded: bool, now: datetime) -> None: ...

    def cancellation_requested(self, *, job_id: str) -> bool: ...

    def record_health(self, health: ExecutionHealthV1) -> None: ...

    def quarantine(self, *, health: ExecutionHealthV1, code: str, now: datetime) -> None: ...


class ContainerRuntimeClient(Protocol):
    def verify_lock(self, lock: RuntimeImageLockV1) -> bool: ...

    def find_matching(self, spec: LaunchSpec) -> ContainerLookup: ...

    def create_and_start(self, *, spec: LaunchSpec, sandbox_input: SandboxInputV1) -> ContainerHandle: ...

    def wait_for_result(
        self,
        *,
        handle: ContainerHandle,
        spec: LaunchSpec,
        lock: RuntimeImageLockV1,
        should_cancel: Callable[[], bool],
    ) -> SandboxResultV1: ...

    def cleanup(self, handle: ContainerHandle) -> None: ...
