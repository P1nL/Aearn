from __future__ import annotations

import importlib.util
import io
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
from aearn_shared.execution import (
    ExecutionAction,
    RuntimeImageLockV1,
    SafeExecutionStatus,
    SandboxInputV1,
    SandboxResultV1,
)

from aearn_executor.item_supply_bridge import ITEM_SUPPLY_LIMITS, ItemSupplyRunnerBridge
from aearn_executor.launch import LaunchSpec
from aearn_executor.runtime import ContainerHandle, ContainerLookup, RuntimeClientError


def candidate_lock() -> RuntimeImageLockV1:
    return RuntimeImageLockV1(runtime_id="python-stdout-v1", protocol_version="sandbox-input-v1", image_reference="aearn-p6-candidate@sha256:" + "1234567890abcdef" * 4, fixed_entrypoint=("/opt/aearn/entrypoint.py",), non_root_user="10001:10001", limits=ITEM_SUPPLY_LIMITS)


def sandbox_input(code: str = "print(1)") -> SandboxInputV1:
    return SandboxInputV1(runtime_id="python-stdout-v1", action=ExecutionAction.TEST, submission=code, source_reference_hash="1" * 64, test_reference_hash="2" * 64)


class FakeRuntime:
    def __init__(self) -> None:
        self.launched = 0
        self.cleaned = 0
        self.spec: LaunchSpec | None = None

    def verify_lock(self, lock) -> bool:
        return True

    def find_matching(self, spec) -> ContainerLookup:
        return ContainerLookup(handle=None)

    def create_and_start(self, *, spec, sandbox_input) -> ContainerHandle:
        self.spec = spec
        self.launched += 1
        return ContainerHandle(container=object(), name=spec.container_name)

    def wait_for_result(self, *, handle, spec, lock, should_cancel) -> SandboxResultV1:
        return SandboxResultV1(status=SafeExecutionStatus.SUCCESS, diagnostic_code="item_supply_facts_v1", stdout='{"cases":[]}')

    def cleanup(self, handle) -> None:
        self.cleaned += 1


def test_fake_runtime_cannot_attest_live_replay_is_exact_and_launch_is_fixed() -> None:
    client = FakeRuntime()
    bridge = ItemSupplyRunnerBridge(locks={"python-stdout-v1": candidate_lock()}, runtime_client=client)
    request, run_id = sandbox_input(), uuid4()
    receipt = bridge.run(request=request, run_id=run_id, probe_name="reference")
    assert receipt.mode == receipt.isolation == "synthetic"
    assert bridge.verify(receipt, request=request)
    assert bridge.run(request=request, run_id=run_id, probe_name="reference") is receipt
    assert client.launched == client.cleaned == 1
    spec = client.spec
    assert spec is not None
    assert spec.network_mode == "none" and spec.read_only and not spec.privileged
    assert spec.user == "10001:10001" and spec.cap_drop == ("ALL",)
    assert spec.command == () and spec.security_opt == ("no-new-privileges:true",)
    assert set(spec.tmpfs) == {"/work", "/tmp"}
    assert spec.log_driver == "local"
    assert spec.log_options == {"max-size": "16k", "max-file": "1", "compress": "false"}
    assert "DATABASE_URL" not in spec.environment and "API_KEY" not in str(spec.environment)
    assert not bridge.verify(replace(receipt, mode="live", isolation="approved_os_boundary"), request=request)
    assert not bridge.verify(replace(receipt, elapsed_seconds=receipt.elapsed_seconds + 1.0), request=request)
    with pytest.raises(ValueError, match="replay_conflict"):
        bridge.run(request=sandbox_input("print(2)"), run_id=run_id, probe_name="reference")


def test_missing_or_mutated_lock_fails_before_any_runtime_launch() -> None:
    client = FakeRuntime()
    with pytest.raises(RuntimeClientError, match="lock_unavailable"):
        ItemSupplyRunnerBridge(locks={}, runtime_client=client).run(request=sandbox_input(), run_id=uuid4(), probe_name="reference")
    wrong = candidate_lock().model_copy(update={"non_root_user": "10002:10002"})
    with pytest.raises(ValueError, match="candidate_lock_invalid"):
        ItemSupplyRunnerBridge(locks={wrong.runtime_id: wrong}, runtime_client=client)
    with pytest.raises(ValueError, match="digest"):
        RuntimeImageLockV1.model_validate({**candidate_lock().model_dump(), "image_reference": "python:latest"})
    # Revocation follows immutable image content, not a repository alias.
    unsafe_digest = "sha256:dff872b9a69bbbb0cc992cb26153dd7e9bc43625b9af501c755fdc9ab8859541"
    for repository in ("aearn-item-supply-sandbox", "renamed-p6-candidate"):
        revoked = candidate_lock().model_copy(update={"image_reference": f"{repository}@{unsafe_digest}"})
        with pytest.raises(ValueError, match="candidate_lock_invalid"):
            ItemSupplyRunnerBridge(locks={revoked.runtime_id: revoked}, runtime_client=client)
    assert client.launched == 0


def test_image_recipe_uses_only_fixed_harness_protocol_and_stdin_candidate_input() -> None:
    root = Path(__file__).resolve().parents[3] / "infra" / "executor"
    directory = root / "harnesses" / "item_supply"
    dockerfile = (directory / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM ${AEARN_RUNTIME_BASE_IMAGE}" in dockerfile
    assert dockerfile.count("COPY ") == 4 and "USER 10001:10001" in dockerfile
    assert "RUN " not in dockerfile and "COPY . " not in dockerfile
    assert "harnesses/item_supply/entrypoint.py" in dockerfile
    assert "harnesses/item_supply/python_goal.py /opt/aearn/python_goal.py" in dockerfile
    entry = (directory / "entrypoint.py").read_text(encoding="utf-8")
    assert "libc.prctl(4, ctypes.c_long(0)" in entry
    assert "completed.returncode != 0" in entry
    adapter = (directory / "runtime_adapter.py").read_text(encoding="utf-8")
    assert 'sqlite3.connect(":memory:")' in adapter
    assert "preexec_fn=_limits" in adapter and 'input=code.encode()' in adapter
    assert "shell=True" not in adapter and "expected_output" not in adapter
    assert "libc.prctl(4, ctypes.c_long(0)" in adapter
    protocol = json.loads((directory / "runtime-protocol.json").read_text(encoding="utf-8"))
    assert protocol["scope"] == "internal-p6-candidate-only"
    assert protocol["protocol_version"] == "sandbox-input-v1"
    assert json.loads((root / "image-locks.json").read_text(encoding="utf-8"))["locks"] == []


def test_killed_adapter_forged_output_is_rejected_before_json_decode(monkeypatch, capsys) -> None:
    """Pure return-code regression; no candidate or real subprocess on host."""
    entry_path = Path(__file__).resolve().parents[3] / "infra/executor/harnesses/item_supply/entrypoint.py"
    spec = importlib.util.spec_from_file_location("p6_entrypoint_pure_test", entry_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "_protect_parent", lambda: True)
    monkeypatch.setattr(module.Path, "is_file", lambda self: True)
    monkeypatch.setattr(module.os, "access", lambda *args: True)
    monkeypatch.setenv("AEARN_RUNTIME_ID", "python-stdout-v1")
    monkeypatch.setattr(module.sys, "stdin", type("Input", (), {"buffer": io.BytesIO(sandbox_input().wire_bytes())})())
    forged = b' {"schema_version":"sandbox-result-v1","status":"success","passed_test_count":1,"total_test_count":1}'
    fake_completed = type("Completed", (), {"returncode": -9, "stdout": forged})()
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: fake_completed)
    assert module.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["diagnostic_code"] == "runtime_adapter_failed"
    assert result["passed_test_count"] == result["total_test_count"] == 0
