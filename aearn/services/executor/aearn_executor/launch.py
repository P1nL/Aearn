"""Immutable fixed launch profile used only by the executor runtime client."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from aearn_shared.execution import ExecutionJobV1, RuntimeImageLockV1


@dataclass(frozen=True)
class LaunchSpec:
    """Fully derived launch settings; no caller can supply arbitrary overrides."""

    image_reference: str
    container_name: str
    labels: dict[str, str]
    network_mode: str
    read_only: bool
    user: str
    cap_drop: tuple[str, ...]
    security_opt: tuple[str, ...]
    privileged: bool
    pids_limit: int
    memory_limit: str
    nano_cpus: int
    nofile_limit: int
    tmpfs: dict[str, str]
    environment: dict[str, str]
    log_driver: str
    log_options: dict[str, str]
    command: tuple[str, ...]


def build_launch_spec(*, job: ExecutionJobV1, lock: RuntimeImageLockV1) -> LaunchSpec:
    """Build the sole accepted container profile from reviewed lock metadata."""

    if job.runtime_id != lock.runtime_id or job.lock_fingerprint != lock.fingerprint:
        raise ValueError("job does not match the reviewed runtime lock")
    if not job.launch_token:
        raise ValueError("launch reservation is required before building a launch profile")
    limits = lock.limits
    return LaunchSpec(
        image_reference=lock.image_reference,
        container_name=_container_name(job_id=job.job_id, launch_token=job.launch_token),
        labels={
            "aearn.execution.job": job.job_id,
            "aearn.execution.launch": job.launch_token,
            "aearn.execution.lock": lock.fingerprint,
            "aearn.execution.runtime": job.runtime_id,
        },
        network_mode="none",
        read_only=True,
        user=lock.non_root_user,
        cap_drop=("ALL",),
        security_opt=("no-new-privileges:true",),
        privileged=False,
        pids_limit=limits.pids_limit,
        memory_limit=f"{limits.memory_mb}m",
        nano_cpus=limits.cpu_millis * 1_000_000,
        nofile_limit=limits.nofile_limit,
        tmpfs={
            "/work": f"rw,exec,nosuid,nodev,size={limits.work_tmpfs_mb}m",
            "/tmp": f"rw,noexec,nosuid,nodev,size={limits.temp_tmpfs_mb}m",
        },
        environment={
            "AEARN_RUNTIME_ID": job.runtime_id,
            "AEARN_WALL_CLOCK_SECONDS": str(limits.wall_clock_seconds),
            "AEARN_MAX_OUTPUT_BYTES": str(limits.max_output_bytes),
            "HOME": "/tmp",
            "NO_PROXY": "*",
        },
        # Bound the daemon-side log buffer as a second guard behind the in-image
        # protocol cap, so a malformed harness cannot make the executor retain
        # unbounded output before it can project a safe failure.
        log_driver="local",
        log_options={"max-size": f"{limits.max_output_bytes}b", "max-file": "1"},
        # The reviewed image itself owns the fixed entrypoint. No command comes
        # from the model, learner, API request, job payload, or executor caller.
        command=(),
    )


def _container_name(*, job_id: str, launch_token: str) -> str:
    job_hash = hashlib.sha256(job_id.encode("utf-8")).hexdigest()[:20]
    token_hash = hashlib.sha256(launch_token.encode("utf-8")).hexdigest()[:20]
    return f"aearn-exec-{job_hash}-{token_hash}"
