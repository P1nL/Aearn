from __future__ import annotations

import json
from pathlib import Path

from aearn_shared.execution import (
    ExecutionJobState,
    ExecutionJobV1,
    RuntimeImageLockV1,
    load_runtime_catalog_registry,
)

from aearn_executor.launch import build_launch_spec

EXECUTOR_ROOT = Path(__file__).resolve().parents[3] / "infra" / "executor"


def _lock_and_job() -> tuple[RuntimeImageLockV1, ExecutionJobV1]:
    registry = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    entry = registry.runtime("python-stdout-v1")
    lock = RuntimeImageLockV1(
        runtime_id=entry.runtime_id,
        protocol_version=entry.protocol_version,
        image_reference=f"registry.example/aearn/python@sha256:{'a' * 63}b",
        fixed_entrypoint=entry.fixed_entrypoint,
        non_root_user=entry.non_root_user,
        limits=entry.limits,
    )
    return lock, ExecutionJobV1(
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


def test_common_launch_profile_is_strict_and_has_no_host_mount_or_network_escape() -> None:
    lock, job = _lock_and_job()
    spec = build_launch_spec(job=job, lock=lock)

    assert spec.image_reference == lock.image_reference
    assert spec.command == ()
    assert spec.network_mode == "none"
    assert spec.read_only is True
    assert spec.user == "10001:10001"
    assert spec.cap_drop == ("ALL",)
    assert spec.security_opt == ("no-new-privileges:true",)
    assert spec.privileged is False
    assert set(spec.tmpfs) == {"/work", "/tmp"}
    assert "/work" in spec.tmpfs and "exec" in spec.tmpfs["/work"]
    assert spec.labels["aearn.execution.lock"] == lock.fingerprint
    assert "@sha256:" in spec.image_reference


def test_all_runtime_definitions_share_the_fixed_protocol_and_exclude_rust_cpp() -> None:
    catalog = json.loads((EXECUTOR_ROOT / "runtime-catalog.json").read_text(encoding="utf-8"))
    runtime_ids = tuple(entry["runtime_id"] for entry in catalog["runtimes"])

    assert runtime_ids == (
        "python-stdout-v1",
        "browser-preview-v1",
        "node-typescript-v1",
        "sqlite-query-v1",
        "java-managed-v1",
        "go-managed-v1",
        "dotnet-managed-v1",
    )
    assert not any("rust" in runtime_id or "cpp" in runtime_id for runtime_id in runtime_ids)
    for runtime_id in runtime_ids:
        runtime_dir = EXECUTOR_ROOT / "runtimes" / runtime_id
        protocol = json.loads((runtime_dir / "runtime-protocol.json").read_text(encoding="utf-8"))
        dockerfile = (runtime_dir / "Dockerfile").read_text(encoding="utf-8")
        assert protocol["runtime_id"] == runtime_id
        assert protocol["protocol_version"] == "sandbox-input-v1"
        assert protocol["network"] == "none"
        assert protocol["package_install"] == "forbidden"
        assert "USER 10001:10001" in dockerfile
        assert "ENTRYPOINT [\"/opt/aearn/entrypoint.py\"]" in dockerfile
        assert "RUN " not in dockerfile
