from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from aearn_shared.execution import (
    ExecutionEffectProposalV1,
    ExecutionJobV1,
    ExecutionJobState,
    RuntimeImageLockV1,
    load_runtime_catalog_registry,
)


API_ROOT = Path(__file__).resolve().parents[1]
AEARN_ROOT = API_ROOT.parents[1]
EXECUTOR_ROOT = AEARN_ROOT / "infra" / "executor"


def _registry():
    return load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )


def _lock_payload() -> dict[str, object]:
    entry = _registry().runtime("python-stdout-v1")
    return {
        "runtime_id": entry.runtime_id,
        "protocol_version": entry.protocol_version,
        "image_reference": f"registry.example/aearn/python@sha256:{'a' * 63}b",
        "fixed_entrypoint": list(entry.fixed_entrypoint),
        "non_root_user": entry.non_root_user,
        "limits": entry.limits.model_dump(mode="json"),
    }


def test_runtime_catalog_contains_exactly_the_seven_approved_protocols_and_no_locks() -> None:
    registry = _registry()

    assert tuple(runtime.runtime_id for runtime in registry.runtimes) == (
        "python-stdout-v1",
        "browser-preview-v1",
        "node-typescript-v1",
        "sqlite-query-v1",
        "java-managed-v1",
        "go-managed-v1",
        "dotnet-managed-v1",
    )
    assert registry.locks == ()
    assert registry.lock_for("python-stdout-v1") is None
    assert registry.lock_for("rust-managed-v1") is None
    assert registry.lock_for("cpp-managed-v1") is None


@pytest.mark.parametrize(
    "image_reference",
    (
        "registry.example/aearn/python:latest",
        "python:3.12",
        "sha256:abcdef",
        f"registry.example/aearn/python@sha256:{'0' * 64}",
        "registry.example/aearn/python@sha256:not-a-digest",
    ),
)
def test_runtime_image_locks_reject_tags_local_ids_and_placeholders(image_reference: str) -> None:
    payload = _lock_payload() | {"image_reference": image_reference}

    with pytest.raises(ValidationError):
        RuntimeImageLockV1.model_validate(payload)


def test_effect_payload_is_closed_to_one_opaque_server_proof_reference() -> None:
    parsed = ExecutionEffectProposalV1.model_validate({"intent_proof_id": "proof-123"})
    assert parsed.intent_proof_id == "proof-123"

    with pytest.raises(ValidationError):
        ExecutionEffectProposalV1.model_validate(
            {
                "intent_proof_id": "proof-123",
                "image": "registry.example/aearn/python:latest",
            }
        )


def test_durable_job_contract_cannot_carry_execution_targets_or_raw_input() -> None:
    forbidden = {"image", "image_reference", "command", "mount", "network", "path", "submission", "hidden_tests"}
    assert forbidden.isdisjoint(ExecutionJobV1.model_fields)
    assert ExecutionJobV1.model_fields["state"].annotation is ExecutionJobState


def test_catalog_loader_rejects_a_lock_that_does_not_match_the_runtime_entry(tmp_path: Path) -> None:
    catalog_path = tmp_path / "runtime-catalog.json"
    lock_path = tmp_path / "image-locks.json"
    catalog_path.write_text((EXECUTOR_ROOT / "runtime-catalog.json").read_text(encoding="utf-8"), encoding="utf-8")
    broken_lock = _lock_payload() | {"protocol_version": "sandbox-input-v2"}
    lock_path.write_text(
        json.dumps({"schema_version": "aearn-executor-image-locks-v1", "locks": [broken_lock]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="image lock does not match its reviewed runtime catalog entry"):
        load_runtime_catalog_registry(catalog_path=catalog_path, image_locks_path=lock_path)


def test_privilege_boundary_keeps_container_client_out_of_api_harness_worker_and_legacy_runners() -> None:
    protected_roots = (
        API_ROOT / "app" / "agents" / "harness",
        API_ROOT / "app" / "services" / "tutor",
        API_ROOT / "app" / "services" / "runners",
        API_ROOT / "app" / "routes",
        API_ROOT.parents[0] / "worker" / "aearn_worker",
    )
    forbidden = ("import docker", "from docker", "DOCKER_HOST", "docker.from_env", "docker.APIClient")
    for root in protected_roots:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(marker in source for marker in forbidden), path

    executor_sources = tuple((AEARN_ROOT / "services" / "executor" / "aearn_executor").glob("*.py"))
    docker_importers = [path.name for path in executor_sources if "import docker" in path.read_text(encoding="utf-8")]
    assert docker_importers == ["docker_client.py"]
