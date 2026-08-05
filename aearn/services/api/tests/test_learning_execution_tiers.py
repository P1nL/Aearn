from __future__ import annotations

from aearn_shared.execution import RuntimeImageLockV1

from app.services.learning.contracts import ExecutionComposition, ExecutionTier
from app.services.learning.execution_tiers import ExecutionTierInputs, ExecutionTierResolver, StaticExecutorAvailability
from app.services.runners.language_capabilities import get_language_capability
from app.services.tutor.execution import default_runtime_registry


def _language(language_id: str):
    capability = get_language_capability(language_id)
    assert capability is not None
    return capability


def _registry_with_python_lock():
    source = default_runtime_registry()
    entry = source.runtime("python-stdout-v1")
    lock = RuntimeImageLockV1(
        runtime_id=entry.runtime_id,
        protocol_version=entry.protocol_version,
        image_reference=f"registry.example/aearn/python@sha256:{'a' * 63}b",
        fixed_entrypoint=entry.fixed_entrypoint,
        non_root_user=entry.non_root_user,
        limits=entry.limits,
    )
    return source.__class__(
        runtimes=source.runtimes,
        locks=(lock,),
        catalog_fingerprint=source.catalog_fingerprint,
        fingerprint="b" * 64,
    )


def test_development_local_runner_is_teaching_only() -> None:
    projection = ExecutionTierResolver().resolve(
        language=_language("python"),
        inputs=ExecutionTierInputs(
            composition=ExecutionComposition.DEVELOPMENT,
            local_runner_available=True,
            runtime_registry=default_runtime_registry(),
            executor_availability=StaticExecutorAvailability(),
        ),
    )
    assert projection.tier is ExecutionTier.TEACHING_LOCAL
    assert "not a public container-isolation claim" in projection.disclosure


def test_public_without_reviewed_lock_fails_closed_to_static_only() -> None:
    projection = ExecutionTierResolver().resolve(
        language=_language("python"),
        inputs=ExecutionTierInputs(
            composition=ExecutionComposition.PUBLIC,
            local_runner_available=True,
            runtime_registry=default_runtime_registry(),
            executor_availability=StaticExecutorAvailability(frozenset({"python-stdout-v1"})),
        ),
    )
    assert projection.tier is ExecutionTier.STATIC_ONLY
    assert projection.runtime_id is None


def test_public_requires_both_reviewed_lock_and_compatible_health() -> None:
    registry = _registry_with_python_lock()
    unavailable = ExecutionTierResolver().resolve(
        language=_language("python"),
        inputs=ExecutionTierInputs(
            composition=ExecutionComposition.PUBLIC,
            local_runner_available=False,
            runtime_registry=registry,
            executor_availability=StaticExecutorAvailability(),
        ),
    )
    available = ExecutionTierResolver().resolve(
        language=_language("python"),
        inputs=ExecutionTierInputs(
            composition=ExecutionComposition.PUBLIC,
            local_runner_available=False,
            runtime_registry=registry,
            executor_availability=StaticExecutorAvailability(frozenset({"python-stdout-v1"})),
        ),
    )
    assert unavailable.tier is ExecutionTier.STATIC_ONLY
    assert available.tier is ExecutionTier.CONTAINER_VERIFIED
    assert available.runtime_id == "python-stdout-v1"


def test_planned_languages_do_not_overstate_capabilities() -> None:
    inputs = ExecutionTierInputs(
        composition=ExecutionComposition.PUBLIC,
        local_runner_available=False,
        runtime_registry=default_runtime_registry(),
        executor_availability=StaticExecutorAvailability(),
    )
    resolver = ExecutionTierResolver()
    assert resolver.resolve(language=_language("cpp"), inputs=inputs).tier is ExecutionTier.STATIC_ONLY
    assert resolver.resolve(language=_language("rust"), inputs=inputs).tier is ExecutionTier.UNAVAILABLE
