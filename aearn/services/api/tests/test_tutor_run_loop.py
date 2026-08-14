from __future__ import annotations

from dataclasses import replace
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
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContextInput,
    TutorContextSource,
    TutorContinuationKind,
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorEffectProposal,
    TutorEffectStatus,
    TutorInputEvent,
    TutorLease,
    TutorPolicySnapshot,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
    TutorProviderContextCapability,
    TutorProviderResult,
    TutorRunResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorTerminalOutcome,
)
from app.services.llm.contracts import LLMUsage
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
        current_input_required=True,
        current_input=TutorContextSource(f"message-current-{revision}", "I need help with scope."),
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
    decision_gate: object | None = None,
    clock: FixedClock | None = None,
) -> tuple[TutorRunLoop, InMemoryTutorCompactionPublisher]:
    resolved_publisher = publisher or InMemoryTutorCompactionPublisher()
    loop = TutorRunLoop(
        store=store,
        context_loader=InMemoryTutorContextLoader(contexts),
        context_builder=builder or _builder(),
        provider=provider,
        capability_gateway=capability_gateway or DefaultDenyCapabilityGateway(),  # type: ignore[arg-type]
        effect_committer=effect_committer or RecordingEffectCommitter(status=TutorEffectStatus.DENIED),
        clock=clock or FixedClock(NOW),
        compaction_publisher=resolved_publisher,
        decision_gate=decision_gate or AllowTutorDecisionGate(),  # type: ignore[arg-type]
        lifecycle=lifecycle,  # type: ignore[arg-type]
    )
    return loop, resolved_publisher



def test_required_current_input_failure_is_typed_and_stops_before_provider_call() -> None:
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(context_token_budget=1))])
    provider = SequenceTutorProvider([])
    invalid_context = TutorContextInput(
        run_id="run-loop",
        conversation_id="conversation-loop",
        input_revision=0,
        current_input=TutorContextSource("message-current", "x"),
        current_input_required=True,
    )

    class UnrepresentableEstimator:
        def estimate_tokens(self, value: object) -> int:
            del value
            return 2

    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): invalid_context},
        provider=provider,
        builder=TutorContextBuilder(estimator=UnrepresentableEstimator()),
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.FAILED
    assert result.terminal_outcome is TutorTerminalOutcome.FAILED
    assert result.diagnostic_code == "TUTOR_CURRENT_INPUT_UNREPRESENTABLE"
    assert result.model_call_count == 0
    assert provider.calls == []


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


def test_one_iteration_completes_an_ordinary_turn_without_graph_semantics() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    provider = SequenceTutorProvider([
        TutorProviderResult(
            decision=TutorDecision(
                public_message="先确认变量在哪个作用域。",
                public_thinking_steps=(
                    "我先区分变量声明位置与实际读取位置。",
                    "接着用一次回调执行验证闭包是否保留外层绑定。",
                ),
            )
        )
    ])
    loop, _ = _loop(store=store, contexts={("run-loop", 0): _context(0)}, provider=provider)

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert result.iteration_count == 1
    assert result.model_call_count == 1
    assert result.public_thinking_steps == (
        "我先区分变量声明位置与实际读取位置。",
        "接着用一次回调执行验证闭包是否保留外层绑定。",
    )
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


def test_late_provider_result_renews_unclaimed_expired_lease_and_persists_terminal() -> None:
    clock = FixedClock(NOW)
    store = InMemoryTutorRunStore([_snapshot(policy=_policy(lease_duration_seconds=30))])

    def finish_after_lease_expiry(run: TutorRunSnapshot, context: object) -> None:
        del run, context
        clock.advance(seconds=45)

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    public_message="租约过期后仍应安全完成。",
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )
        ],
        on_decide=finish_after_lease_expiry,
    )
    loop, _publisher = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        clock=clock,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-slow-provider")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.public_message == "租约过期后仍应安全完成。"
    assert result.diagnostic_code is None
    assert store.results == [result]


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
    # Input revision refresh happens immediately after the provider boundary, before
    # effect dispatch. No stale effect receipt or handler invocation is permitted.
    assert result.effect_results == ()
    assert effect_committer.calls == []
    assert context_loader.loaded_revisions == [("run-loop", 0), ("run-loop", 1)]


def test_post_provider_terminal_outcome_is_rechecked_for_supersede() -> None:
    store = InMemoryTutorRunStore([_snapshot()])

    def supersede_after_provider(run: TutorRunSnapshot, context: object) -> None:
        del run, context
        store.supersede("run-loop")

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=None,
                terminal_outcome=TutorTerminalOutcome.MODEL_UNAVAILABLE,
                safe_code="provider_terminal_should_not_win",
            )
        ],
        on_decide=supersede_after_provider,
    )
    loop, _ = _loop(store=store, contexts={("run-loop", 0): _context(0)}, provider=provider)

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.CANCELLED
    assert result.terminal_outcome is TutorTerminalOutcome.CANCELLED
    assert result.diagnostic_code == "superseded"


def test_post_provider_supersede_stops_before_decision_capability_effect_or_terminal_write() -> None:
    store = InMemoryTutorRunStore([_snapshot()])
    effect_committer = RecordingEffectCommitter()
    capability_gateway = SequenceCapabilityGateway(
        [TutorCapabilityResult("capability-after-provider", TutorCapabilityStatus.COMPLETED)]
    )

    def supersede_after_provider(run: TutorRunSnapshot, context: object) -> None:
        del run, context
        store.supersede("run-loop")

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    public_message="这条旧结果绝不能发布给学习者。",
                    capability_requests=(TutorCapabilityRequest("capability-after-provider", "safe-capability"),),
                    effect_proposals=(TutorEffectProposal("effect-after-provider", "save_note", expected_input_revision=0),),
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            )
        ],
        on_decide=supersede_after_provider,
    )
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        capability_gateway=capability_gateway,
        effect_committer=effect_committer,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.CANCELLED
    assert result.terminal_outcome is TutorTerminalOutcome.CANCELLED
    assert result.diagnostic_code == "superseded"
    assert result.effect_results == ()
    assert capability_gateway.calls == []
    assert effect_committer.calls == []
    assert len(provider.calls) == 1


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
        self.provider_attempts: list[
            tuple[TutorRunSnapshot, int, tuple[TutorProviderAttemptReceipt, ...]]
        ] = []
        self.checkpoints: list[TutorCheckpoint] = []
        self.high_water: list[TutorCompactionRequest] = []
        self.terminals: list[tuple[TutorLease, TutorCheckpoint, TutorRunResult, TutorCompactionRequest]] = []
        self.waiting: list[TutorRunResult] = []
        self.interaction_requests: list[tuple[TutorDecision, TutorRunResult]] = []

    def persist_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None:
        del created_at
        self.provider_attempts.append((snapshot, decision_iteration, attempts))

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

    def persist_interaction_request(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision: TutorDecision,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        del snapshot, lease, created_at
        self.interaction_requests.append((decision, result))
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


def test_provider_attempt_receipts_persist_before_superseded_result_is_suppressed() -> None:
    store = InMemoryTutorRunStore([_snapshot()])

    def supersede_after_provider(run: TutorRunSnapshot, context: object) -> None:
        del run, context
        store.supersede("run-loop")

    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    public_message="这条旧结果绝不能发布给学习者。",
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                ),
                attempts=(
                    TutorProviderAttemptReceipt(
                        attempt_index=1,
                        outcome=TutorProviderAttemptOutcome.ACCEPTED,
                        provider_type="deepseek",
                        protocol="deepseek_responses",
                        model="deepseek-v4-flash",
                        usage=LLMUsage(
                            input_tokens=175_420,
                            cached_input_tokens=170_368,
                            output_tokens=2_223,
                            total_tokens=177_643,
                        ),
                    ),
                ),
            )
        ],
        on_decide=supersede_after_provider,
    )
    lifecycle = _RecordingLifecycle()
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        lifecycle=lifecycle,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-usage")

    assert result.status is TutorRunStatus.CANCELLED
    assert result.public_message is None
    assert len(lifecycle.provider_attempts) == 1
    snapshot, decision_iteration, attempts = lifecycle.provider_attempts[0]
    assert snapshot.input_revision == 0
    assert decision_iteration == 1
    assert attempts[0].usage is not None
    assert attempts[0].usage.uncached_input_tokens == 5_052
    assert len(lifecycle.terminals) == 1
    assert lifecycle.terminals[0][2].terminal_outcome is TutorTerminalOutcome.CANCELLED


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
        if path.name in {"proactive_worker.py", "interactive_worker.py"}:
            # Child 04 owns the one bounded API-side worker adapter. It may open
            # the target database connection, but never imports legacy Graph,
            # route, streaming, or product-conversation boundaries.
            forbidden_for_path = tuple(marker for marker in forbidden if marker != "app.db")
        if path.name in {"cutover.py", "thread_turn_cutover.py", "thread_turn_cutover_cli.py", "interactive.py"}:
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


class _InsufficientContextOnceGate:
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, *, run: TutorRunSnapshot, decision: TutorDecision) -> TutorDecisionGateResult:
        del run, decision
        self.calls += 1
        if self.calls == 1:
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.REBUILD_CONTEXT,
                diagnostic_code="insufficient_context",
            )
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)


def test_controlled_insufficient_context_rebuild_upgrades_exactly_one_mode() -> None:
    capability = TutorProviderContextCapability(
        context_window_tokens=10_000,
        max_output_reserve_tokens=1_000,
        protocol_reserve_tokens=32,
        safety_margin_tokens=64,
        maximum_dynamic_target_tokens=4_000,
        capability_version="run-loop-capability-v1",
    )
    budget_policy = TutorContextBudgetPolicy(
        capability=capability,
        mode_targets=(
            (TutorContextBudgetMode.COMPACT, 500),
            (TutorContextBudgetMode.NORMAL, 1_000),
            (TutorContextBudgetMode.COMPLEX, 2_000),
            (TutorContextBudgetMode.EXTENDED, 4_000),
        ),
        max_expansions=1,
    )
    store = InMemoryTutorRunStore(
        [
            _snapshot(
                policy=_policy(
                    max_iterations=3,
                    max_model_calls=3,
                    context_token_budget=4_000,
                    context_budget_policy=budget_policy,
                )
            )
        ]
    )
    provider = SequenceTutorProvider(
        [
            TutorProviderResult(decision=TutorDecision(public_message="Need more context.")),
            TutorProviderResult(decision=TutorDecision(public_message="Use the narrower scope.")),
        ]
    )
    gate = _InsufficientContextOnceGate()
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        decision_gate=gate,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.model_call_count == 2
    assert len(provider.calls) == 2
    first_metadata = provider.calls[0][1].checkpoint_metadata
    second_metadata = provider.calls[1][1].checkpoint_metadata
    assert first_metadata.budget_mode is TutorContextBudgetMode.COMPACT
    assert first_metadata.expansion_count == 0
    assert second_metadata.budget_mode is TutorContextBudgetMode.NORMAL
    assert second_metadata.expansion_count == 1


def test_full_serialized_required_overflow_stops_before_provider_call() -> None:
    capability = TutorProviderContextCapability(
        context_window_tokens=500,
        max_output_reserve_tokens=200,
        protocol_reserve_tokens=10,
        safety_margin_tokens=10,
        maximum_dynamic_target_tokens=100,
        capability_version="tiny-capability-v1",
    )
    budget_policy = TutorContextBudgetPolicy(
        capability=capability,
        mode_targets=(
            (TutorContextBudgetMode.COMPACT, 25),
            (TutorContextBudgetMode.NORMAL, 50),
            (TutorContextBudgetMode.COMPLEX, 75),
            (TutorContextBudgetMode.EXTENDED, 100),
        ),
        max_expansions=1,
    )
    store = InMemoryTutorRunStore(
        [
            _snapshot(
                policy=_policy(
                    context_token_budget=100,
                    context_budget_policy=budget_policy,
                )
            )
        ]
    )
    provider = SequenceTutorProvider([])
    loop, _ = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.FAILED
    assert result.diagnostic_code == "TUTOR_CONTEXT_REQUIRED_OVERFLOW"
    assert result.model_call_count == 0
    assert provider.calls == []


def test_thread_turn_v2_continuation_completes_source_and_persists_typed_request() -> None:
    snapshot = replace(_snapshot(), interaction_protocol_version="thread_turn_v2")
    store = InMemoryTutorRunStore([snapshot])
    decision = TutorDecision(
        public_message="请说明你当前最想解决的问题。",
        checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
        continuation_kind=TutorContinuationKind.CLARIFICATION,
    )
    provider = SequenceTutorProvider([TutorProviderResult(decision=decision)])
    lifecycle = _RecordingLifecycle()
    loop, _publisher = _loop(
        store=store,
        contexts={("run-loop", 0): _context(0)},
        provider=provider,
        lifecycle=lifecycle,
    )

    result = loop.run(run_id="run-loop", lease_owner_id="worker-request")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert result.completion_reason is not None
    assert result.completion_reason.value == "awaiting_user"
    assert result.continuation_kind is None
    assert lifecycle.interaction_requests == [(decision, result)]
    assert lifecycle.waiting == []
    assert store.results == []
