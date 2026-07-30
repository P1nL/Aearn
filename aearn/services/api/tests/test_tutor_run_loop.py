from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.agents.harness.context_builder import TutorContextBuilder, TutorContextBuilderConfig
from app.agents.harness.contracts import (
    CONTEXT_SECTION_PRIORITY,
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionRequest,
    TutorContextInput,
    TutorContextSource,
    TutorDecision,
    TutorEffectProposal,
    TutorEffectStatus,
    TutorInputEvent,
    TutorLease,
    TutorPolicySnapshot,
    TutorProviderResult,
    TutorRunResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
)
from app.services.tutor.ports import (
    AllowTutorDecisionGate,
    DefaultDenyCapabilityGateway,
    FixedClock,
    InMemoryTutorCompactionPublisher,
    InMemoryTutorContextLoader,
    InMemoryTutorRunStore,
    RecordingEffectCommitter,
    SequenceCapabilityGateway,
    TutorLifecycleConflict,
    SequenceTutorProvider,
)
from app.services.tutor.run_loop import TutorHarnessService, TutorRunLoop


NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)


class OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


def _policy(**overrides: object) -> TutorPolicySnapshot:
    values: dict[str, object] = {
        "deadline": datetime(2030, 1, 1, tzinfo=timezone.utc),
        "max_iterations": 3,
        "max_model_calls": 3,
        "max_capability_calls": 1,
        "max_effects": 1,
        "context_token_budget": 8,
    }
    values.update(overrides)
    return TutorPolicySnapshot(**values)  # type: ignore[arg-type]


def _snapshot(*, policy: TutorPolicySnapshot | None = None, cancelled: bool = False) -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-loop",
        conversation_id="conversation-loop",
        user_id="user-loop",
        origin="interactive",
        input_revision=0,
        policy=policy or _policy(),
        cancelled=cancelled,
    )


def _context(revision: int) -> TutorContextInput:
    return TutorContextInput(
        run_id="run-loop",
        conversation_id="conversation-loop",
        input_revision=revision,
        system_descriptors=(TutorContextSource("system", {"rule": "bounded"}),),
        recent_messages=(TutorContextSource(f"message-{revision}", {"role": "user", "content": "I need help with scope."}),),
    )


def _builder(*, high_water_ratio: float = 1.0) -> TutorContextBuilder:
    return TutorContextBuilder(
        estimator=OneTokenEstimator(),
        config=TutorContextBuilderConfig(
            section_item_limits=tuple((section, 1) for section in CONTEXT_SECTION_PRIORITY),
            high_water_ratio=high_water_ratio,
        ),
    )


def _loop(
    *,
    store: InMemoryTutorRunStore,
    contexts: dict[tuple[str, int], TutorContextInput],
    provider: SequenceTutorProvider,
    capability_gateway: object | None = None,
    effect_committer: RecordingEffectCommitter | None = None,
    publisher: InMemoryTutorCompactionPublisher | None = None,
    builder: TutorContextBuilder | None = None,
    lifecycle: object | None = None,
) -> tuple[TutorRunLoop, InMemoryTutorCompactionPublisher]:
    resolved_publisher = publisher or InMemoryTutorCompactionPublisher()
    loop = TutorRunLoop(
        store=store,
        context_loader=InMemoryTutorContextLoader(contexts),
        context_builder=builder or _builder(),
        provider=provider,
        capability_gateway=capability_gateway or DefaultDenyCapabilityGateway(),  # type: ignore[arg-type]
        effect_committer=effect_committer or RecordingEffectCommitter(status=TutorEffectStatus.DENIED),
        clock=FixedClock(NOW),
        compaction_publisher=resolved_publisher,
        decision_gate=AllowTutorDecisionGate(),
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )
    return loop, resolved_publisher


def test_zero_iteration_budget_terminates_without_provider_call() -> None:
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(max_iterations=0))])
    provider = SequenceTutorProvider([])
    loop, publisher = _loop(store=store, contexts={}, provider=provider)

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.BUDGET_EXHAUSTED
    assert result.terminal_outcome is TutorTerminalOutcome.BUDGET_EXHAUSTED
    assert provider.calls == []
    assert store.lease_attempts == 1
    assert store.checkpoints[-1].reason is TutorCheckpointReason.TERMINAL
    assert {request.trigger.value for request in publisher.requests} == {"terminal"}


def test_one_iteration_waits_for_input_without_graph_semantics() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider([TutorProviderResult(decision=TutorDecision(public_message="先确认变量在哪个作用域。"))])
    loop, _ = _loop(store=store, contexts={("run-loop", 0): _context(0)}, provider=provider)

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.WAITING_FOR_INPUT
    assert result.terminal_outcome is None
    assert result.iteration_count == 1
    assert result.model_call_count == 1
    assert len(provider.calls) == 1


def test_multiple_bounded_iterations_continue_only_through_injected_capability_result() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    capability_requests=(TutorCapabilityRequest("cap-1", "safe-capability"),),
                )
            ),
            TutorProviderResult(decision=TutorDecision(terminal_outcome=TutorTerminalOutcome.COMPLETED)),
        ]
    )
    capabilities = SequenceCapabilityGateway(
        [TutorCapabilityResult("cap-1", TutorCapabilityStatus.COMPLETED, continue_run=True)]
    )
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        capability_gateway=capabilities,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.iteration_count == 2
    assert result.model_call_count == 2
    assert result.capability_call_count == 1
    assert len(capabilities.calls) == 1


def test_lease_and_cancellation_are_terminal_before_model_call() -> None:
    lease_store = InMemoryTutorRunStore([_snapshot()])
    lease_store.deny_leases = True
    lease_provider = SequenceTutorProvider([])
    lease_loop, _ = _loop(store=lease_store, contexts={}, provider=lease_provider)

    lease_result = lease_loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert lease_result.status is TutorRunStatus.BLOCKED_POLICY
    assert lease_result.diagnostic_code == "lease_unavailable"
    assert lease_provider.calls == []
    assert lease_store.checkpoints == []
    assert lease_store.results == []

    cancelled_store = InMemoryTutorRunStore([_snapshot(cancelled=True)])
    cancelled_provider = SequenceTutorProvider([])
    cancelled_loop, _ = _loop(store=cancelled_store, contexts={}, provider=cancelled_provider)

    cancelled_result = cancelled_loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert cancelled_result.status is TutorRunStatus.CANCELLED
    assert cancelled_store.lease_attempts == 1
    assert cancelled_provider.calls == []


def test_stale_effect_is_rejected_before_committer_and_context_rebuilds() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    effect_committer = RecordingEffectCommitter()
    calls = 0

    def accept_newer_input(run: TutorRunSnapshot, context: object) -> None:
        nonlocal calls
        del run, context
        calls += 1
        if calls == 1:
            store.accept_input(
                TutorInputEvent(
                    run_id="run-loop",
                    message_id="message-1",
                    revision=1,
                    content="I have a newer question.",
                    received_at=NOW,
                )
            )

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    effect_proposals=(TutorEffectProposal("effect-1", "save_note", expected_input_revision=0),),
                )
            ),
            TutorProviderResult(decision=TutorDecision(terminal_outcome=TutorTerminalOutcome.COMPLETED)),
        ],
        on_decide=accept_newer_input,
    )
    context_loader = InMemoryTutorContextLoader({("run-loop", 0): _context(0), ("run-loop", 1): _context(1)})
    publisher = InMemoryTutorCompactionPublisher()
    loop = TutorRunLoop(
        store=store,
        context_loader=context_loader,
        context_builder=_builder(),
        provider=provider,
        capability_gateway=DefaultDenyCapabilityGateway(),
        effect_committer=effect_committer,
        clock=FixedClock(NOW),
        compaction_publisher=publisher,
        decision_gate=AllowTutorDecisionGate(),
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert [item.status for item in result.effect_results] == [TutorEffectStatus.STALE_REJECTED]
    assert effect_committer.calls == []
    assert context_loader.loaded_revisions == [("run-loop", 0), ("run-loop", 1)]


def test_safe_checkpoint_and_high_water_publish_only_typed_idempotent_requests() -> None:
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(context_token_budget=2))])
    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    checkpoint_reason=TutorCheckpointReason.SAFE_PROGRESS,
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )
        ]
    )
    publisher = InMemoryTutorCompactionPublisher()
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        publisher=publisher,
        builder=_builder(high_water_ratio=0.5),
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert {request.trigger.value for request in publisher.requests} == {
        "context_high_water",
        "safe_checkpoint",
        "terminal",
    }
    assert len({request.idempotency_key for request in publisher.requests}) == 3
    assert [checkpoint.reason for checkpoint in store.checkpoints] == [
        TutorCheckpointReason.SAFE_PROGRESS,
        TutorCheckpointReason.TERMINAL,
    ]


class _RecordingLifecycle:
    def __init__(self) -> None:
        self.checkpoints: list[TutorCheckpoint] = []
        self.high_water: list[TutorCompactionRequest] = []
        self.terminals: list[tuple[TutorLease, TutorCheckpoint, TutorRunResult, TutorCompactionRequest]] = []
        self.waiting: list[TutorRunResult] = []

    def persist_safe_checkpoint(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        compaction_request: TutorCompactionRequest,
    ) -> None:
        del snapshot, lease, compaction_request
        self.checkpoints.append(checkpoint)

    def persist_context_high_water(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        request: TutorCompactionRequest,
        created_at: datetime,
    ) -> None:
        del snapshot, lease, created_at
        self.high_water.append(request)

    def persist_terminal(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        compaction_request: TutorCompactionRequest,
    ) -> TutorRunResult:
        del snapshot
        self.terminals.append((lease, checkpoint, result, compaction_request))
        return result

    def persist_waiting_result(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        del snapshot, lease, created_at
        self.waiting.append(result)
        return result


def test_lifecycle_adapter_owns_terminal_persistence_when_explicitly_composed() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider([TutorProviderResult(decision=TutorDecision(terminal_outcome=TutorTerminalOutcome.COMPLETED))])
    lifecycle = _RecordingLifecycle()
    loop, publisher = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        lifecycle=lifecycle,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-atomic")

    assert result.status is TutorRunStatus.COMPLETED
    assert len(lifecycle.terminals) == 1
    assert lifecycle.terminals[0][2] == result
    assert store.checkpoints == []
    assert store.results == []
    assert publisher.requests == []


class _ConflictedTerminalLifecycle:
    def __init__(self) -> None:
        self.calls = 0

    def persist_terminal(self, **kwargs) -> TutorRunResult:
        del kwargs
        self.calls += 1
        raise TutorLifecycleConflict("lease ownership changed")


def test_lifecycle_conflict_returns_nonpersistent_lease_unavailable_without_retrying_terminal_write() -> None:
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(max_iterations=0))])
    provider = SequenceTutorProvider([])
    lifecycle = _ConflictedTerminalLifecycle()
    loop, publisher = _loop(
        store=store,
        contexts={},
        provider=provider,
        lifecycle=lifecycle,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-conflicted")

    assert result.status is TutorRunStatus.BLOCKED_POLICY
    assert result.diagnostic_code == "lease_unavailable"
    assert lifecycle.calls == 1
    assert store.checkpoints == []
    assert store.results == []
    assert publisher.requests == []


def test_harness_service_runs_without_a_feature_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider([])
    loop, _ = _loop(store=store, contexts={}, provider=provider)
    expected = TutorRunResult(
        run_id="run-loop",
        status=TutorRunStatus.COMPLETED,
        input_revision=0,
        iteration_count=0,
        model_call_count=0,
        capability_call_count=0,
        effect_count=0,
    )
    calls: list[tuple[str, str]] = []

    def delegated_run(*, run_id: str, lease_owner_id: str) -> TutorRunResult:
        calls.append((run_id, lease_owner_id))
        return expected

    monkeypatch.setattr(loop, "run", delegated_run)
    service = TutorHarnessService.enabled(loop=loop)

    result = service.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result is expected
    assert calls == [("run-loop", "worker-1")]


def test_harness_and_tutor_modules_do_not_depend_on_retired_runtime_or_storage_boundaries() -> None:
    api_root = Path(__file__).resolve().parents[1]
    files = [
        *sorted((api_root / "app" / "agents" / "harness").glob("*.py")),
        *sorted((api_root / "app" / "services" / "tutor").glob("*.py")),
    ]
    retired_agent_packages = (
        "graphs",
        "learning",
        "notes",
        "onboarding",
        "review",
        "runtime",
        "tooling",
    )
    retired_source_paths = tuple(
        api_root / "app" / "agents" / package_name / "__init__.py"
        for package_name in retired_agent_packages
    ) + (
        api_root / "app" / "services" / "streaming" / "".join(("graph", "_event_stream.py")),
    )
    assert all(not path.exists() for path in retired_source_paths), retired_source_paths

    retired_module_prefixes = tuple(
        ".".join(("app", "agents", package_name)) for package_name in retired_agent_packages
    )
    forbidden = (
        "".join(("lang", "graph")),
        "app.routes",
        "app.db",
        "app.services.worker",
        "route_message",
        "learning_stage",
    )

    for path in files:
        source = path.read_text(encoding="utf-8")
        forbidden_for_path = forbidden
        if path.name == "proactive_worker.py":
            # Child 04 owns the one bounded API-side worker adapter. It may open
            # the target database connection, but never imports legacy Graph,
            # route, streaming, or product-conversation boundaries.
            forbidden_for_path = tuple(marker for marker in forbidden if marker != "app.db")
        if path.name in {"cutover.py", "interactive.py"}:
            # Children 06/07 own these target database-backed adapters. Their
            # explicit database access is allowed; Graph, route, and legacy
            # conversation dependencies remain forbidden.
            forbidden_for_path = tuple(marker for marker in forbidden if marker != "app.db")
        assert not any(marker in source for marker in retired_module_prefixes), path
        assert not any(marker in source for marker in forbidden_for_path), path


def test_retired_runtime_paths_and_rollout_flags_are_absent() -> None:
    api_root = Path(__file__).resolve().parents[1]
    retired_source_paths = (
        *(
            api_root / "app" / "routes" / filename
            for filename in (
                "dashboard.py",
                "learning_sessions.py",
                "notes.py",
                "onboarding.py",
                "plans.py",
                "reviews.py",
            )
        ),
        *(
            api_root / "app" / "services" / "conversations" / filename
            for filename in (
                "learning_conversation.py",
                "onboarding_conversation.py",
                "review_conversation.py",
            )
        ),
        api_root / "app" / "services" / "streaming" / "".join(("graph", "_event_stream.py")),
        *(
            api_root.parents[1] / "apps" / "desktop" / "src" / "pages" / filename
            for filename in (
                "LearningWorkspacePage.tsx",
                "NotesPage.tsx",
                "OnboardingPage.tsx",
                "ReviewPage.tsx",
                "SettingsPage.tsx",
            )
        ),
    )
    assert all(not path.exists() for path in retired_source_paths), retired_source_paths

    settings_source = (api_root / "app" / "core" / "config.py").read_text(encoding="utf-8")
    retired_setting_names = (
        "_".join(("".join(("lang", "graph")), "enabled")),
        "_".join(("tutor", "harness", "enabled")),
    )
    assert not any(setting_name in settings_source for setting_name in retired_setting_names)
