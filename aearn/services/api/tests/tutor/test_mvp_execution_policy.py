"""Zero-HTTP tests for the explicit new-admission MVP execution envelope."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextInput, TutorContextSource, TutorDecision, TutorExecutionProfile, TutorInputEvent,
    TutorPolicySnapshot, TutorProviderResult, TutorRunSnapshot, TutorTerminalOutcome,
)
from app.services.tutor.mvp_policy import MVPExecutionStopped, MVP_SOFT_CLOSE_HINT, teaching_admission_policy
from app.services.tutor.persistence.mapping import _policy_payload, _snapshot_from_row
from app.services.tutor.ports import (
    AllowTutorDecisionGate, DefaultDenyCapabilityGateway, FixedClock, InMemoryTutorCompactionPublisher,
    InMemoryTutorContextLoader, InMemoryTutorRunStore, RecordingEffectCommitter,
)
from app.services.tutor.provider_gateway import PRIMARY_PROVIDER_DECISION_ATTEMPTS, _build_messages
from app.services.tutor.run_loop import TutorRunLoop

NOW = datetime(2026, 10, 18, tzinfo=UTC)


def policy(*, seconds: int = 2400) -> TutorPolicySnapshot:
    return replace(teaching_admission_policy(now=NOW, context_token_budget=4096, context_budget_policy=None,
        execution_profile=TutorExecutionProfile.MVP_TEACHING_V1), deadline=NOW + timedelta(seconds=seconds))


def snapshot(selected: TutorPolicySnapshot | None = None) -> TutorRunSnapshot:
    return TutorRunSnapshot(run_id="mvp-run", conversation_id="mvp-conversation", user_id="mvp-user",
        origin="interactive", input_revision=0, policy=selected or policy())


def context() -> TutorContextInput:
    return TutorContextInput(run_id="mvp-run", conversation_id="mvp-conversation", input_revision=0,
        current_input_required=True, current_input=TutorContextSource("mvp-message", "Explain the next step."))


class ExecutionDouble:
    """No transport: verifies run wiring, shared counter and original callback fences."""
    instances: list[ExecutionDouble] = []
    current: ExecutionDouble | None = None

    def __init__(self, *, before_send: Any, renew_lease: Any, on_attempt: Any = None, max_attempts: int = 16) -> None:
        self.before_send, self.renew_lease, self.on_attempt = before_send, renew_lease, on_attempt
        self.max_attempts, self.physical_attempts = max_attempts, 0
        self.timeouts: list[float] = []
        self.instances.append(self)

    def send(self) -> None:
        if self.physical_attempts >= self.max_attempts:
            raise MVPExecutionStopped(TutorTerminalOutcome.BUDGET_EXHAUSTED, "physical_attempts_exhausted")
        timeout = self.before_send()
        self.physical_attempts += 1
        if self.on_attempt is not None:
            self.on_attempt(self.physical_attempts)
        self.timeouts.append(timeout)


@contextmanager
def execution_scope(execution: ExecutionDouble) -> Any:
    ExecutionDouble.current = execution
    try:
        yield execution
    finally:
        ExecutionDouble.current = None


@pytest.fixture
def execution_double(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.llm.http_execution as http_execution

    ExecutionDouble.instances = []
    monkeypatch.setattr(http_execution, "LLMHTTPExecution", ExecutionDouble)
    monkeypatch.setattr(http_execution, "use_http_execution", execution_scope)


def loop(*, store: InMemoryTutorRunStore, clock: FixedClock, provider: Any,
         loader: Any = None, fence: Any = None, observer: Any = None, gateway: Any = None, lifecycle: Any = None) -> TutorRunLoop:
    return TutorRunLoop(store=store, clock=clock,
        context_loader=loader or InMemoryTutorContextLoader({("mvp-run", 0): context()}),
        context_builder=TutorContextBuilder(), provider=provider,
        capability_gateway=gateway or DefaultDenyCapabilityGateway(), effect_committer=RecordingEffectCommitter(),
        compaction_publisher=InMemoryTutorCompactionPublisher(), decision_gate=AllowTutorDecisionGate(),
        mvp_grant_fence=fence, mvp_on_physical_attempt=observer, lifecycle=lifecycle)


class SendingProvider:
    def __init__(self, *, sends: int = 1) -> None:
        self.sends, self.calls = sends, 0

    def decide(self, **_kwargs: Any) -> TutorProviderResult:
        self.calls += 1
        assert ExecutionDouble.current is not None
        for _ in range(self.sends):
            ExecutionDouble.current.send()
        return TutorProviderResult(decision=TutorDecision(public_message="A bounded teaching segment."))


def test_policy_payload_roundtrip_preserves_legacy_absent_shape_and_explicit_profile() -> None:
    legacy = teaching_admission_policy(now=NOW, context_token_budget=4096, context_budget_policy=None)
    assert (legacy.deadline - NOW).total_seconds() == 300
    assert (legacy.max_iterations, legacy.max_model_calls, legacy.max_capability_calls, legacy.max_effects, legacy.lease_duration_seconds) == (4, 3, 2, 2, 30)
    assert "execution_profile" not in _policy_payload(legacy)
    for selected in (legacy, policy()):
        stored = _policy_payload(selected)
        restored = _snapshot_from_row({"id": "mvp-run", "user_id": "mvp-user", "conversation_id": "mvp-conversation",
            "input_revision": 0, "origin": "interactive", "status": "queued", "policy_json": stored})
        assert restored.policy == selected
    explicit = policy()
    assert (explicit.deadline - NOW).total_seconds() == 2400
    assert (explicit.max_iterations, explicit.max_model_calls, explicit.max_capability_calls, explicit.max_effects, explicit.lease_duration_seconds) == (8, 8, 6, 2, 30)
    assert _policy_payload(explicit)["execution_profile"] == "mvp_teaching_v1"


def test_profile_without_real_fence_never_calls_provider() -> None:
    provider = SendingProvider()
    result = loop(store=InMemoryTutorRunStore([snapshot()]), clock=FixedClock(NOW), provider=provider).run(run_id="mvp-run", lease_owner_id="owner")
    assert result.diagnostic_code == "mvp_grant_fence_required"
    assert provider.calls == 0


@pytest.mark.usefixtures("execution_double")
def test_slow_context_does_not_send_into_finish_reserve() -> None:
    clock = FixedClock(NOW)
    store = InMemoryTutorRunStore([snapshot(policy(seconds=400))])

    class SlowLoader:
        def load_context(self, *_args: Any, **_kwargs: Any) -> TutorContextInput:
            clock.advance(seconds=110)
            return context()

    result = loop(store=store, clock=clock, provider=SendingProvider(), loader=SlowLoader(), fence=lambda: None).run(run_id="mvp-run", lease_owner_id="owner")
    assert result.diagnostic_code == "mvp_finish_reserve_required"
    assert ExecutionDouble.instances[0].physical_attempts == 0


@pytest.mark.usefixtures("execution_double")
@pytest.mark.parametrize("change", ["deadline", "input", "lease"])
def test_slow_current_fence_rechecks_deadline_input_and_owner_generation(change: str) -> None:
    clock, store = FixedClock(NOW), InMemoryTutorRunStore([snapshot(policy(seconds=400))])

    def fence() -> None:
        if change == "deadline":
            clock.advance(seconds=401)
        elif change == "input":
            store.accept_input(TutorInputEvent(message_id="new-input", run_id="mvp-run", revision=1, content="Changed", received_at=clock.now()))
        else:
            clock.advance(seconds=31)
            assert store.acquire_lease("mvp-run", owner_id="replacement", now=clock.now(), duration_seconds=30) is not None

    result = loop(store=store, clock=clock, provider=SendingProvider(), fence=fence).run(run_id="mvp-run", lease_owner_id="owner")
    assert result.diagnostic_code in {"deadline_exhausted", "mvp_input_revision_changed", "lease_expired"}
    assert ExecutionDouble.instances[0].physical_attempts == 0


@pytest.mark.usefixtures("execution_double")
def test_each_send_recomputes_timeout_without_clamping_run_to_cap_window() -> None:
    clock = FixedClock(NOW)
    store = InMemoryTutorRunStore([snapshot()])
    observations: list[int] = []

    def fence() -> datetime:
        clock.advance(seconds=7)
        return NOW + timedelta(seconds=200)

    result = loop(store=store, clock=clock, provider=SendingProvider(sends=2), fence=fence, observer=observations.append).run(run_id="mvp-run", lease_owner_id="owner")
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert observations == [1, 2]
    assert ExecutionDouble.instances[0].timeouts == [193.0, 186.0]
    assert store._leases["mvp-run"].expires_at == clock.now() + timedelta(seconds=30)


@pytest.mark.usefixtures("execution_double")
def test_same_run_decisions_share_one_execution_and_sixteen_physical_budget() -> None:
    from app.agents.harness.contracts import TutorCapabilityRequest, TutorCapabilityResult, TutorCapabilityStatus

    class ReadGateway:
        def dispatch(self, *, request: Any, **_kwargs: Any) -> TutorCapabilityResult:
            return TutorCapabilityResult(request_id=request.request_id, status=TutorCapabilityStatus.COMPLETED, continue_run=True)

    class GateRebuildProvider:
        calls = 0

        def decide(self, **_kwargs: Any) -> TutorProviderResult:
            self.calls += 1
            assert ExecutionDouble.current is not None
            for _ in range(3):
                ExecutionDouble.current.send()
            # A capability request causes the ordinary loop to make another decision.
            return TutorProviderResult(decision=TutorDecision(capability_requests=(TutorCapabilityRequest(request_id="read-" + str(self.calls), capability_id="read"),)))

    provider = GateRebuildProvider()
    result = loop(store=InMemoryTutorRunStore([snapshot()]), clock=FixedClock(NOW), provider=provider, fence=lambda: None, gateway=ReadGateway()).run(run_id="mvp-run", lease_owner_id="owner")
    assert len(ExecutionDouble.instances) == 1
    assert ExecutionDouble.instances[0].max_attempts == 16
    assert ExecutionDouble.instances[0].physical_attempts == 16
    assert provider.calls == 6
    assert result.terminal_outcome is TutorTerminalOutcome.BUDGET_EXHAUSTED


def test_soft_close_only_explicit_profile_after_six_logical_decisions() -> None:
    run = snapshot()
    selection = TutorContextBuilder().build(context(), token_budget=4096)
    assert PRIMARY_PROVIDER_DECISION_ATTEMPTS == 2
    assert MVP_SOFT_CLOSE_HINT not in str(_build_messages(run=replace(run, model_call_count=5), context=selection))
    assert _build_messages(run=replace(run, model_call_count=6), context=selection)[-1] == {"role": "system", "content": MVP_SOFT_CLOSE_HINT}
    legacy = replace(run, policy=replace(run.policy, execution_profile=None), model_call_count=6)
    assert MVP_SOFT_CLOSE_HINT not in str(_build_messages(run=legacy, context=selection))


@pytest.mark.usefixtures("execution_double")
def test_periodic_callback_renews_original_thirty_second_owner_lease() -> None:
    clock, store = FixedClock(NOW), InMemoryTutorRunStore([snapshot()])

    class QuietProvider:
        def decide(self, **_kwargs: Any) -> TutorProviderResult:
            execution = ExecutionDouble.current
            assert execution is not None
            execution.send()
            for _ in range(6):
                clock.advance(seconds=20)
                execution.renew_lease()
                assert store._leases["mvp-run"].generation == 1
                assert store._leases["mvp-run"].expires_at == clock.now() + timedelta(seconds=30)
            return TutorProviderResult(decision=TutorDecision(public_message="One bounded segment."))

    result = loop(store=store, clock=clock, provider=QuietProvider(), fence=lambda: None).run(run_id="mvp-run", lease_owner_id="owner")
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert ExecutionDouble.instances[0].physical_attempts == 1


@pytest.mark.usefixtures("execution_double")
def test_slow_heartbeat_cannot_start_http_with_only_five_seconds_of_original_lease() -> None:
    clock = FixedClock(NOW)

    class SlowHeartbeatStore(InMemoryTutorRunStore):
        def heartbeat_lease(self, *args: Any, **kwargs: Any) -> Any:
            renewed = super().heartbeat_lease(*args, **kwargs)
            clock.advance(seconds=25)
            return renewed

    store = SlowHeartbeatStore([snapshot()])
    result = loop(store=store, clock=clock, provider=SendingProvider(), fence=lambda: None).run(
        run_id="mvp-run", lease_owner_id="owner",
    )
    assert result.diagnostic_code == "lease_expired"
    assert ExecutionDouble.instances[0].physical_attempts == 0
    assert (store._leases["mvp-run"].expires_at - clock.now()).total_seconds() == 5


@pytest.mark.usefixtures("execution_double")
def test_transport_unknown_receipt_is_durable_before_lost_lease_mvp_stop() -> None:
    from app.agents.harness.context_budget import build_tutor_context_budget_policy
    from app.core.config import Settings
    from app.services.llm.contracts import LLMUsage
    from app.services.llm.http_execution import LLMHTTPExecutionError
    from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway

    clock = FixedClock(NOW)
    settings = Settings(_env_file=None, llm_type="disabled",  # type: ignore[call-arg]
        tutor_default_context_window_tokens=12288, tutor_default_output_reserve_tokens=4096)
    selected = replace(policy(), context_budget_policy=build_tutor_context_budget_policy(settings))
    store = InMemoryTutorRunStore([snapshot(selected)])
    events: list[str] = []
    usage = LLMUsage(input_tokens=3, output_tokens=2, total_tokens=5)

    class Client:
        model = "offline-model"
        calls = 0

        def complete_json(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            execution = ExecutionDouble.current
            assert execution is not None
            execution.send()
            clock.advance(seconds=31)
            store.acquire_lease("mvp-run", owner_id="replacement", now=clock.now(), duration_seconds=30)
            try:
                execution.renew_lease()
            except MVPExecutionStopped as cause:
                error = LLMHTTPExecutionError("lease_lost", outcome_unknown=True, physical_attempts=1)
                error.usage = usage
                raise error from cause
            raise AssertionError("stale lease must stop")

    class Lifecycle:
        def persist_provider_attempts(self, **kwargs: Any) -> None:
            attempts = kwargs["attempts"]
            assert len(attempts) == 1 and attempts[0].usage == usage
            assert "unknown" in attempts[0].diagnostic_code
            events.append("durable_provider_attempt")

        def persist_terminal(self, **kwargs: Any) -> Any:
            events.append("terminal")
            return kwargs["result"]

    client = Client()
    result = loop(store=store, clock=clock, provider=PrimaryTutorProviderGateway(settings=settings, client=client),
        fence=lambda: None, lifecycle=Lifecycle()).run(run_id="mvp-run", lease_owner_id="owner")
    assert client.calls == 1  # No semantic repair after scoped transport UNKNOWN.
    assert events == ["durable_provider_attempt", "terminal"]
    assert result.diagnostic_code == "lease_expired"


def test_determinate_http_failure_keeps_one_semantic_receipt_without_repair() -> None:
    from app.agents.harness.context_budget import build_tutor_context_budget_policy
    from app.core.config import Settings
    from app.services.llm.http_execution import LLMHTTPExecutionError
    from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway

    settings = Settings(_env_file=None, llm_type="disabled",  # type: ignore[call-arg]
        tutor_default_context_window_tokens=12288, tutor_default_output_reserve_tokens=4096)
    run = snapshot(replace(policy(), context_budget_policy=build_tutor_context_budget_policy(settings)))
    selection = TutorContextBuilder().build(context(), token_budget=4096)

    class Client:
        model = "offline-model"
        calls = 0

        def complete_json(self, *_args: Any, **_kwargs: Any) -> Any:
            self.calls += 1
            raise LLMHTTPExecutionError("http_error", outcome_unknown=False, physical_attempts=1)

    client = Client()
    result = PrimaryTutorProviderGateway(settings=settings, client=client).decide(run=run, context=selection)
    assert client.calls == 1 and len(result.attempts) == 1
    assert result.attempts[0].usage is None and result.attempts[0].diagnostic_code == "mvp_http_http_error"
