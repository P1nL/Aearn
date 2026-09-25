"""Offline RAG Celery wakeup boundary: no broker, database or provider required."""

import sys
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest

from aearn_worker import worker_app


COMPOSITION_MODULE = "app.services.grounding.autonomous.worker_composition"


def _settings(
    monkeypatch: pytest.MonkeyPatch, *, discovery: bool, intake: bool
) -> None:
    from app.core import config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            rag_source_discovery_enabled=discovery,
            rag_auto_intake_enabled=intake,
        ),
    )


def _composition(monkeypatch: pytest.MonkeyPatch, callback: object) -> None:
    module = ModuleType(COMPOSITION_MODULE)
    module.run_rag_worker_operation = callback  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, COMPOSITION_MODULE, module)


def test_explicit_routes_are_isolated_and_unscheduled() -> None:
    app = worker_app.celery_app
    names = {
        "rag.discovery.dispatch",
        "rag.candidate.intake",
        "rag.candidate.retention",
    }
    assert names <= set(app.tasks)
    assert {app.conf.task_routes[name]["queue"] for name in names} == {"rag-controlled"}
    assert all(item["task"] not in names for item in app.conf.beat_schedule.values())
    assert all(not key.startswith("rag.") for key in app.conf.beat_schedule)


@pytest.mark.parametrize(
    ("task", "argument"),
    [
        (worker_app.dispatch_rag_discovery, "https://example.com/private?token=abc"),
        (worker_app.dispatch_rag_discovery, "not-a-uuid"),
        (worker_app.intake_rag_candidate, "HTTPS://example.com"),
        (worker_app.retain_rag_candidates, True),
        (worker_app.retain_rag_candidates, 0),
        (worker_app.retain_rag_candidates, 101),
        (worker_app.retain_rag_candidates, "10"),
    ],
)
def test_invalid_payload_blocks_before_composition(
    task: object, argument: object
) -> None:
    assert task.run(argument) == {  # type: ignore[attr-defined]
        "status": "blocked_policy",
        "code": "rag_worker_invalid_arguments",
        "processed": 0,
    }


def test_default_off_gates_do_not_call_discovery_or_intake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    _composition(monkeypatch, lambda **kwargs: calls.append(kwargs))
    job_id, candidate_id = str(uuid4()), str(uuid4())

    _settings(monkeypatch, discovery=False, intake=False)
    for result in (
        worker_app.dispatch_rag_discovery.run(job_id),
        worker_app.intake_rag_candidate.run(candidate_id),
    ):
        assert result["status"] == "blocked_policy"
        assert result["code"] == "rag_worker_gate_closed"
    assert calls == []
    # Retention has its own operator approval in the API composition. Turning
    # off discovery/intake must not strand already persisted candidate bodies.
    assert worker_app.retain_rag_candidates.run(10)["code"] == "rag_worker_composition_failed"
    assert calls == [
        {"operation": "retention", "job_id": None, "candidate_id": None, "limit": 10}
    ]
    _settings(monkeypatch, discovery=True, intake=False)
    assert (
        worker_app.dispatch_rag_discovery.run(job_id)["code"]
        == "rag_worker_composition_failed"
    )
    assert (
        worker_app.intake_rag_candidate.run(candidate_id)["code"]
        == "rag_worker_gate_closed"
    )
    assert worker_app.retain_rag_candidates.run(10)["code"] == "rag_worker_composition_failed"
    assert calls == [
        {"operation": "retention", "job_id": None, "candidate_id": None, "limit": 10},
        {"operation": "dispatch", "job_id": job_id, "candidate_id": None, "limit": None},
        {"operation": "retention", "job_id": None, "candidate_id": None, "limit": 10},
    ]


def test_retention_independent_of_unavailable_discovery_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import config

    def unavailable() -> None:
        raise RuntimeError("discovery settings unavailable")

    monkeypatch.setattr(config, "get_settings", unavailable)
    _composition(
        monkeypatch,
        lambda **_: {"status": "completed", "processed": 1},
    )
    assert worker_app.retain_rag_candidates.run(2) == {
        "status": "completed", "processed": 1,
    }
    assert worker_app.dispatch_rag_discovery.run(str(uuid4()))["code"] == (
        "rag_worker_settings_unavailable"
    )


def test_missing_api_composition_remains_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch, discovery=True, intake=True)
    monkeypatch.setitem(sys.modules, COMPOSITION_MODULE, None)
    result = worker_app.dispatch_rag_discovery.run(str(uuid4()))
    assert result == {
        "status": "blocked_policy",
        "code": "rag_worker_composition_unavailable",
        "processed": 0,
    }


def test_only_opaque_bounded_arguments_cross_api_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings(monkeypatch, discovery=True, intake=True)
    received: list[dict[str, object]] = []

    def composition(**kwargs: object) -> dict[str, object]:
        received.append(kwargs)
        return {"status": "completed", "processed": 1, "raw_url": "secret"}

    _composition(monkeypatch, composition)
    job_id, candidate_id = str(uuid4()), str(uuid4())
    assert worker_app.dispatch_rag_discovery.run(job_id) == {
        "status": "completed",
        "processed": 1,
    }
    assert worker_app.intake_rag_candidate.run(candidate_id) == {
        "status": "completed",
        "processed": 1,
    }
    assert worker_app.retain_rag_candidates.run(2) == {
        "status": "completed",
        "processed": 1,
    }
    assert received == [
        {
            "operation": "dispatch",
            "job_id": job_id,
            "candidate_id": None,
            "limit": None,
        },
        {
            "operation": "intake",
            "job_id": None,
            "candidate_id": candidate_id,
            "limit": None,
        },
        {"operation": "retention", "job_id": None, "candidate_id": None, "limit": 2},
    ]
    with pytest.raises(TypeError):
        worker_app.dispatch_rag_discovery.run(job_id, url="https://example.com")


@pytest.mark.parametrize(
    "outcome",
    [
        {"status": "completed", "processed": 999, "body": "secret"},
        {"status": "unexpected", "processed": 1},
        {"status": "blocked_policy", "processed": 0, "code": "raw-secret"},
    ],
)
def test_composition_outcomes_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, outcome: dict[str, object]
) -> None:
    _settings(monkeypatch, discovery=True, intake=True)
    _composition(monkeypatch, lambda **_: outcome)
    result = worker_app.intake_rag_candidate.run(str(uuid4()))
    assert result["status"] == "blocked_policy"
    assert "secret" not in repr(result)


def test_composition_exception_is_not_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    _settings(monkeypatch, discovery=True, intake=True)

    def fail(**_: object) -> None:
        raise RuntimeError("secret-provider-url")

    _composition(monkeypatch, fail)
    assert worker_app.dispatch_rag_discovery.run(str(uuid4())) == {
        "status": "blocked_policy",
        "code": "rag_worker_composition_failed",
        "processed": 0,
    }
