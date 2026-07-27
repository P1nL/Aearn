"""The only Aearn module that imports and controls the container client."""
from __future__ import annotations

import socket
import time
from collections.abc import Callable
from typing import Any

import docker
from aearn_shared.execution import (
    RuntimeImageLockV1,
    SafeExecutionStatus,
    SandboxInputV1,
    SandboxResultV1,
)
from docker.errors import APIError, DockerException, NotFound
from docker.types import LogConfig, Ulimit

from aearn_executor.launch import LaunchSpec
from aearn_executor.runtime import (
    ContainerHandle,
    ContainerLookup,
    RuntimeClientError,
    RuntimeLaunchUncertainError,
    RuntimeUnavailableError,
)


class DockerContainerRuntimeClient:
    """Fixed-profile client. It never pulls images or runs a host subprocess."""

    def __init__(self, client: docker.DockerClient | None = None) -> None:
        self._client = client or docker.from_env()

    def verify_lock(self, lock: RuntimeImageLockV1) -> bool:
        try:
            self._client.ping()
            self._client.images.get(lock.image_reference)
        except (DockerException, APIError, NotFound):
            return False
        return True

    def find_matching(self, spec: LaunchSpec) -> ContainerLookup:
        try:
            candidates = self._client.containers.list(all=True, filters={"name": spec.container_name})
        except DockerException as exc:
            raise RuntimeLaunchUncertainError("container_lookup_failed") from exc
        matching = []
        for container in candidates:
            labels = getattr(container, "labels", {}) or {}
            if all(labels.get(key) == value for key, value in spec.labels.items()):
                matching.append(container)
        if not matching:
            return ContainerLookup(handle=None)
        if len(matching) != 1:
            return ContainerLookup(handle=None, ambiguous=True)
        return ContainerLookup(handle=ContainerHandle(container=matching[0], name=spec.container_name))

    def create_and_start(self, *, spec: LaunchSpec, sandbox_input: SandboxInputV1) -> ContainerHandle:
        try:
            container = self._client.containers.create(
                image=spec.image_reference,
                command=list(spec.command) or None,
                name=spec.container_name,
                labels=dict(spec.labels),
                stdin_open=True,
                tty=False,
                network_mode=spec.network_mode,
                read_only=spec.read_only,
                user=spec.user,
                cap_drop=list(spec.cap_drop),
                security_opt=list(spec.security_opt),
                privileged=spec.privileged,
                pids_limit=spec.pids_limit,
                mem_limit=spec.memory_limit,
                nano_cpus=spec.nano_cpus,
                ulimits=[Ulimit(name="nofile", soft=spec.nofile_limit, hard=spec.nofile_limit)],
                tmpfs=dict(spec.tmpfs),
                environment=dict(spec.environment),
                log_config=LogConfig(type=spec.log_driver, config=dict(spec.log_options)),
                auto_remove=False,
            )
            container.start()
        except (DockerException, APIError) as exc:
            raise RuntimeUnavailableError("container_start_unavailable") from exc
        handle = ContainerHandle(container=container, name=spec.container_name)
        try:
            self._write_input(handle=handle, payload=sandbox_input.wire_bytes())
        except (DockerException, APIError, OSError) as exc:
            # Container creation may already have crossed the external-effect
            # boundary; a replacement must inspect/adopt, never create again.
            raise RuntimeLaunchUncertainError("container_input_uncertain") from exc
        return handle

    def wait_for_result(
        self,
        *,
        handle: ContainerHandle,
        spec: LaunchSpec,
        lock: RuntimeImageLockV1,
        should_cancel: Callable[[], bool],
    ) -> SandboxResultV1:
        deadline = time.monotonic() + lock.limits.wall_clock_seconds
        try:
            while True:
                if should_cancel():
                    self._stop(handle)
                    return _result(status=SafeExecutionStatus.CANCELLED, code="execution_cancelled")
                handle.container.reload()
                state = getattr(handle.container, "attrs", {}).get("State", {})
                if not bool(state.get("Running")):
                    break
                if time.monotonic() >= deadline:
                    self._kill(handle)
                    return _result(status=SafeExecutionStatus.TIMEOUT, code="runtime_wall_clock_exceeded")
                time.sleep(0.05)
            raw_output = _bounded_logs(handle.container, maximum=lock.limits.max_output_bytes)
        except (DockerException, APIError) as exc:
            raise RuntimeLaunchUncertainError("container_wait_uncertain") from exc
        if raw_output is None:
            return _result(status=SafeExecutionStatus.FAILED, code="runtime_output_limit_exceeded")
        try:
            return SandboxResultV1.model_validate_json(raw_output.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _result(status=SafeExecutionStatus.FAILED, code="sandbox_protocol_invalid")

    def cleanup(self, handle: ContainerHandle) -> None:
        try:
            handle.container.remove(force=True)
        except (DockerException, APIError) as exc:
            raise RuntimeClientError("container_cleanup_failed") from exc

    @staticmethod
    def _write_input(*, handle: ContainerHandle, payload: bytes) -> None:
        socket_handle = handle.container.attach_socket(params={"stdin": 1, "stream": 1})
        raw_socket = getattr(socket_handle, "_sock", socket_handle)
        raw_socket.sendall(payload)
        raw_socket.shutdown(socket.SHUT_WR)
        raw_socket.close()

    @staticmethod
    def _stop(handle: ContainerHandle) -> None:
        try:
            handle.container.stop(timeout=1)
        except (DockerException, APIError):
            try:
                handle.container.kill()
            except (DockerException, APIError):
                return

    @staticmethod
    def _kill(handle: ContainerHandle) -> None:
        try:
            handle.container.kill()
        except (DockerException, APIError):
            return


def _bounded_logs(container: Any, *, maximum: int) -> bytes | None:
    """Collect at most the reviewed output ceiling without retaining an oversize body."""

    output = bytearray()
    chunks = container.logs(stdout=True, stderr=True, stream=True)
    for chunk in chunks:
        if not isinstance(chunk, bytes) or len(output) + len(chunk) > maximum:
            return None
        output.extend(chunk)
    return bytes(output)


def _result(*, status: SafeExecutionStatus, code: str) -> SandboxResultV1:
    return SandboxResultV1(status=status, diagnostic_code=code)
