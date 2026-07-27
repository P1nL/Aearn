from __future__ import annotations

import os
from pathlib import Path

import pytest
from aearn_shared.execution import load_runtime_catalog_registry

EXECUTOR_ROOT = Path(__file__).resolve().parents[3] / "infra" / "executor"


def test_empty_reviewed_lock_registry_exercises_fail_closed_path_without_a_daemon() -> None:
    registry = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )

    assert registry.locks == ()
    assert registry.enabled_runtime_ids == ()


def test_real_docker_conformance_requires_explicit_opt_in_and_real_locks() -> None:
    if os.getenv("AEARN_EXECUTOR_CONFORMANCE") != "1":
        return
    registry = load_runtime_catalog_registry(
        catalog_path=EXECUTOR_ROOT / "runtime-catalog.json",
        image_locks_path=EXECUTOR_ROOT / "image-locks.json",
    )
    if len(registry.locks) != 7:
        pytest.skip("real Docker conformance requires seven reviewed immutable image locks; unit tests cover fail-closed behavior")
    pytest.fail("real image locks are present; add the reviewed per-runtime Docker conformance fixtures before enabling this test")
