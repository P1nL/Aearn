from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunResult, TutorRunSnapshot, TutorRunStatus, TutorTerminalOutcome
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.services.tutor.capability_policy import DefaultDenyCapabilityPolicyResolver
from app.services.tutor.proactive import (
    ProactiveRunComposition,
    ProactiveRunReservation,
    TutorProactiveCandidate,
    TutorProactiveSchedulerConfig,
    TutorRunLoopProactiveExecutor,
)


_NOW = datetime(2026, 7, 28, tzinfo=UTC)


def _policy(*, max_effects: int = 0) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=datetime(2030, 1, 1, tzinfo=UTC),
        max_iterations=1,
        max_model_calls=1,
        max_capability_calls=0,
        max_effects=max_effects,
        context_token_budget=64,
    )


def _run(*, origin: str = "interactive") -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="proactive-policy-run",
        conversation_id="proactive-policy-conversation",
        user_id="proactive-policy-user",
        input_revision=0,
        policy=_policy(),
        origin=origin,  # type: ignore[arg-type]
    )


def _candidate() -> TutorProactiveCandidate:
    return TutorProactiveCandidate(
        candidate_id="candidate-1",
        signal_id="signal-1",
        user_id="proactive-policy-user",
        candidate_kind="review_due",
        dedupe_key="review-due-1",
        dedupe_bucket_at=_NOW,
        policy_version="tutor_proactive_policy_v1",
        policy_fingerprint="a" * 64,
        state="leased",
        no_action_code=None,
        not_before=_NOW,
        attempt_count=1,
        lease_owner_id="policy-worker",
        lease_generation=1,
        lease_expires_at=_NOW,
        run_id=None,
        run_started_at=None,
        terminal_at=None,
    )


def test_default_proactive_config_is_bounded_and_active_only_for_verified_users() -> None:
    config = TutorProactiveSchedulerConfig()

    assert config.enabled is True
    assert config.hard_paused is False
    assert config.cutover_eligible is True
    assert config.proactive_daily_budget == 1
    assert config.proactive_concurrency_limit == 1
    assert config.inferred_memory_enabled is False
    assert config.curation_daily_budget == 0


def test_tutor_run_origin_is_required_and_unknown_values_fail_closed() -> None:
    assert _run(origin="proactive").origin == "proactive"

    with pytest.raises(ValueError, match="origin"):
        _run(origin="unknown")


def test_default_policy_preserves_persisted_origin_and_mismatched_context_cannot_match() -> None:
    catalog = compile_published_skill_catalog()
    run = _run(origin="proactive")
    resolver = DefaultDenyCapabilityPolicyResolver()

    context = resolver.resolve(run=run, catalog=catalog)

    assert context.origin == "proactive"
    assert context.matches(run=run, catalog=catalog)
    assert not replace(context, origin="interactive").matches(run=run, catalog=catalog)
    assert context.allowed_origins == ()


def test_proactive_composition_rejects_runner_and_memory_but_allows_explicit_plan_activity_effects() -> None:
    catalog = compile_published_skill_catalog()

    with pytest.raises(ValueError, match="runner.execute"):
        ProactiveRunComposition(
            catalog=catalog,
            policy=_policy(),
            allowed_capability_ids=("runner.execute",),
        )
    with pytest.raises(ValueError, match="runner.execute"):
        ProactiveRunComposition(
            catalog=catalog,
            policy=_policy(max_effects=1),
            allowed_effect_types=("runner.execute",),
        )
    with pytest.raises(ValueError, match="learner-memory"):
        ProactiveRunComposition(
            catalog=catalog,
            policy=_policy(max_effects=1),
            allowed_effect_types=("tutor.memory.record",),
        )
    with pytest.raises(ValueError, match="effect authority"):
        ProactiveRunComposition(catalog=catalog, policy=_policy(max_effects=1))

    approved = ProactiveRunComposition(
        catalog=catalog,
        policy=_policy(max_effects=2),
        allowed_effect_types=("tutor.plan.activate", "tutor.activity.record"),
    )
    assert approved.allowed_effect_types == ("tutor.plan.activate", "tutor.activity.record")


class _ReservationStore:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def reserve_proactive_run(self, **kwargs: object) -> ProactiveRunReservation:
        self.calls.append(kwargs)
        return ProactiveRunReservation("proactive-run-1", "proactive-conversation-1", replayed=False)


class _FiniteLoop:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def run(self, *, run_id: str, lease_owner_id: str) -> TutorRunResult:
        self.calls.append((run_id, lease_owner_id))
        return TutorRunResult(
            run_id=run_id,
            status=TutorRunStatus.COMPLETED,
            input_revision=0,
            iteration_count=1,
            model_call_count=1,
            capability_call_count=0,
            effect_count=0,
            terminal_outcome=TutorTerminalOutcome.COMPLETED,
            diagnostic_code="completed",
        )


class _LoopFactory:
    def __init__(self, loop: _FiniteLoop) -> None:
        self.loop = loop
        self.calls: list[dict[str, object]] = []

    def build(self, **kwargs: object) -> _FiniteLoop:
        self.calls.append(kwargs)
        return self.loop


def test_proactive_executor_reserves_then_runs_only_the_existing_finite_loop() -> None:
    catalog = compile_published_skill_catalog()
    store = _ReservationStore()
    loop = _FiniteLoop()
    factory = _LoopFactory(loop)
    executor = TutorRunLoopProactiveExecutor(
        store=store,  # type: ignore[arg-type]
        composition=ProactiveRunComposition(catalog=catalog, policy=_policy()),
        loop_factory=factory,  # type: ignore[arg-type]
    )

    outcome = executor.execute(candidate=_candidate(), lease_owner_id="policy-worker", now=_NOW)

    assert outcome.state == "completed"
    assert outcome.run_id == "proactive-run-1"
    assert loop.calls == [("proactive-run-1", "policy-worker")]
    assert factory.calls[0]["allowed_capability_ids"] == ()
    assert factory.calls[0]["allowed_effect_types"] == ()



def test_retired_graph_route_streaming_and_desktop_sources_are_absent() -> None:
    api_root = Path(__file__).resolve().parents[2]
    retired_source_paths = (
        api_root / "app" / "agents" / "graphs" / "learning_graph.py",
        api_root / "app" / "agents" / "graphs" / "onboarding_graph.py",
        api_root / "app" / "agents" / "graphs" / "review_graph.py",
        api_root / "app" / "routes" / "dashboard.py",
        api_root / "app" / "routes" / "learning_sessions.py",
        api_root / "app" / "routes" / "notes.py",
        api_root / "app" / "routes" / "onboarding.py",
        api_root / "app" / "routes" / "plans.py",
        api_root / "app" / "routes" / "reviews.py",
        api_root / "app" / "services" / "streaming" / "".join(("graph", "_event_stream.py")),
        api_root.parent.parent / "apps" / "desktop" / "src" / "pages" / "LearningWorkspacePage.tsx",
        api_root.parent.parent / "apps" / "desktop" / "src" / "pages" / "OnboardingPage.tsx",
        api_root.parent.parent / "apps" / "desktop" / "src" / "pages" / "ReviewPage.tsx",
        api_root.parent.parent / "apps" / "desktop" / "src" / "pages" / "NotesPage.tsx",
    )
    assert all(not path.exists() for path in retired_source_paths), retired_source_paths
