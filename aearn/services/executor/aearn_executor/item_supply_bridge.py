"""P6-only immutable launch bridge. Never queues jobs or publishes executor health."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, Protocol
from uuid import UUID

from aearn_shared.execution import (
    ExecutionJobState,
    ExecutionJobV1,
    RuntimeImageLockV1,
    RuntimeLimitProfileV1,
    SandboxInputV1,
    SandboxResultV1,
)

from aearn_executor.launch import build_launch_spec
from aearn_executor.runtime import ContainerRuntimeClient, RuntimeClientError

ITEM_SUPPLY_LIMITS = RuntimeLimitProfileV1(
    cpu_millis=500, memory_mb=128, pids_limit=32, nofile_limit=64,
    wall_clock_seconds=5, max_output_bytes=16384, work_tmpfs_mb=16, temp_tmpfs_mb=8,
)
RUNTIME_IDS = frozenset({"python-stdout-v1", "sqlite-query-v1"})
REVOKED_IMAGE_DIGESTS = frozenset({
    "sha256:dff872b9a69bbbb0cc992cb26153dd7e9bc43625b9af501c755fdc9ab8859541",
})


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class ReceiptLike(Protocol):
    def to_payload(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class ItemSupplyTerminalReceipt:
    run_id: UUID
    probe_name: str
    request_hash: str
    lock_fingerprint: str
    result: SandboxResultV1
    elapsed_seconds: float
    mode: Literal["live", "synthetic"]
    isolation: Literal["approved_os_boundary", "synthetic"]
    seal: str

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": "item_supply_runner_terminal_v1",
            "run_id": str(self.run_id), "probe_name": self.probe_name,
            "request_hash": self.request_hash, "lock_fingerprint": self.lock_fingerprint,
            "result": self.result.model_dump(mode="json"), "elapsed_seconds": self.elapsed_seconds,
            "mode": self.mode, "isolation": self.isolation, "seal": self.seal,
        }


class ItemSupplyRunnerBridge:
    """Injected runtime clients always produce synthetic receipts.

    Only from_docker creates the actual client and can attest a locally inspected
    candidate image. These candidate locks are not the production registry.
    """

    def __init__(self, *, locks: Mapping[str, RuntimeImageLockV1], runtime_client: ContainerRuntimeClient) -> None:
        self._locks = {key: RuntimeImageLockV1.model_validate(value.model_dump()) for key, value in locks.items()}
        for key, lock in self._locks.items():
            if key != lock.runtime_id or key not in RUNTIME_IDS or lock.image_reference.partition("@")[2] in REVOKED_IMAGE_DIGESTS or (
                lock.protocol_version != "sandbox-input-v1"
                or lock.fixed_entrypoint != ("/opt/aearn/entrypoint.py",)
                or lock.non_root_user != "10001:10001" or lock.limits != ITEM_SUPPLY_LIMITS
            ):
                raise ValueError("item_supply_candidate_lock_invalid")
        self._client = runtime_client
        self._live = False
        self._key = secrets.token_bytes(32)
        self._receipts: dict[tuple[UUID, str], ItemSupplyTerminalReceipt] = {}
        self._attempted: set[tuple[UUID, str]] = set()

    @classmethod
    def from_docker(cls, *, locks: Mapping[str, RuntimeImageLockV1]) -> ItemSupplyRunnerBridge:
        from aearn_executor.docker_client import DockerContainerRuntimeClient

        bridge = cls(locks=locks, runtime_client=DockerContainerRuntimeClient())
        bridge._live = True
        return bridge

    def _verify_image(self, lock: RuntimeImageLockV1) -> bool:
        if not self._client.verify_lock(lock):
            return False
        if not self._live:
            return True
        from docker.errors import DockerException

        from aearn_executor.docker_client import DockerContainerRuntimeClient

        if type(self._client) is not DockerContainerRuntimeClient:
            return False
        try:
            image = self._client._client.images.get(lock.image_reference)
            attrs = image.attrs
            config = attrs.get("Config", {})
            return (
                lock.image_reference in attrs.get("RepoDigests", [])
                and tuple(config.get("Entrypoint") or ()) == lock.fixed_entrypoint
                and config.get("User") == lock.non_root_user
                and not config.get("Volumes")
                and tuple(config.get("Cmd") or ()) in {(), ("python3",)}
            )
        except (DockerException, OSError, ValueError, TypeError, AttributeError):
            return False

    def run(self, *, request: SandboxInputV1, run_id: UUID, probe_name: str) -> ItemSupplyTerminalReceipt:
        request = SandboxInputV1.model_validate(request.model_dump())
        if not probe_name or len(probe_name) > 80 or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in probe_name):
            raise ValueError("probe_name_invalid")
        request_hash = _hash(request.model_dump(mode="json"))
        key = (run_id, probe_name)
        previous = self._receipts.get(key)
        if previous is not None:
            if previous.request_hash != request_hash:
                raise ValueError("probe_replay_conflict")
            return previous
        if key in self._attempted:
            raise RuntimeClientError("item_supply_launch_uncertain")
        lock = self._locks.get(request.runtime_id)
        if lock is None or not self._verify_image(lock):
            raise RuntimeClientError("item_supply_runtime_lock_unavailable")
        # This DTO is only immutable launch input, never a durable owner/job or
        # formal model-review/Attempt call. All identities are synthetic P6 IDs.
        job = ExecutionJobV1(
            job_id=f"p6-{run_id}-{probe_name}", intent_proof_id=f"p6-proof-{run_id}",
            user_id="p6-synthetic-actor", runtime_id=lock.runtime_id, lock_fingerprint=lock.fingerprint,
            state=ExecutionJobState.LAUNCH_RESERVED, owner_kind="model_review_validation",
            model_review_validation_id=f"p6-probe-{run_id}", conversation_id=f"p6-scope-{run_id}",
            run_id=str(run_id), launch_token=secrets.token_hex(16),
        )
        spec = build_launch_spec(job=job, lock=lock)
        # P6 keeps one bounded local log file. Docker rejects its default
        # compression with max-file=1; do not alter the daemon or public profile.
        spec = replace(spec, log_options={"max-size": "16k", "max-file": "1", "compress": "false"})
        lookup = self._client.find_matching(spec)
        if lookup.ambiguous or lookup.handle is not None:
            raise RuntimeClientError("item_supply_launch_uncertain")
        self._attempted.add(key)
        started = time.perf_counter()
        handle = None
        try:
            handle = self._client.create_and_start(spec=spec, sandbox_input=request)
            result = self._client.wait_for_result(handle=handle, spec=spec, lock=lock, should_cancel=lambda: False)
            result = SandboxResultV1.model_validate(result.model_dump())
        finally:
            if handle is None:
                recovery = self._client.find_matching(spec)
                handle = recovery.handle
            if handle is not None:
                self._client.cleanup(handle)
        elapsed = time.perf_counter() - started
        if not math.isfinite(elapsed) or elapsed < 0:
            raise RuntimeClientError("item_supply_usage_unknown")
        unsigned = ItemSupplyTerminalReceipt(
            run_id=run_id, probe_name=probe_name, request_hash=request_hash,
            lock_fingerprint=lock.fingerprint, result=result, elapsed_seconds=elapsed,
            mode="live" if self._live else "synthetic",
            isolation="approved_os_boundary" if self._live else "synthetic", seal="",
        )
        seal = self._seal(unsigned.to_payload())
        receipt = ItemSupplyTerminalReceipt(**{**unsigned.__dict__, "seal": seal})
        self._receipts[key] = receipt
        return receipt

    def _seal(self, payload: dict[str, object]) -> str:
        unsigned = {k: v for k, v in payload.items() if k != "seal"}
        return hmac.new(self._key, _hash(unsigned).encode(), hashlib.sha256).hexdigest()

    def verify(self, receipt: ReceiptLike, *, request: SandboxInputV1) -> bool:
        try:
            payload = receipt.to_payload()
            key = (UUID(str(payload["run_id"])), str(payload["probe_name"]))
            stored = self._receipts.get(key)
            lock = self._locks.get(request.runtime_id)
            return (
                stored is not None and lock is not None
                and stored.to_payload() == payload
                and payload["request_hash"] == _hash(request.model_dump(mode="json"))
                and payload["lock_fingerprint"] == lock.fingerprint
                and hmac.compare_digest(str(payload["seal"]), self._seal(payload))
                and payload["mode"] == ("live" if self._live else "synthetic")
                and payload["isolation"] == ("approved_os_boundary" if self._live else "synthetic")
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            return False


def candidate_locks(image_reference: str) -> dict[str, RuntimeImageLockV1]:
    """Construct only private P6 locks; does not register any public runtime."""
    return {runtime_id: RuntimeImageLockV1(
        runtime_id=runtime_id, protocol_version="sandbox-input-v1",
        image_reference=image_reference, fixed_entrypoint=("/opt/aearn/entrypoint.py",),
        non_root_user="10001:10001", limits=ITEM_SUPPLY_LIMITS,
    ) for runtime_id in sorted(RUNTIME_IDS)}
