"""Pure synthetic terminal-authority tests: no DB, Docker, collector or provider IO."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.services.learning.item_supply.sandbox.contracts import (
    CollectorReceiptV2,
    ObservationV2,
    Origin,
    RunV2,
    SandboxObservationDenied,
    ScenarioName,
    TerminalOutcome,
    TerminalReceiptV2,
    run_digest,
    terminal_digest,
)
from app.services.learning.item_supply.sandbox.observations import ObservationLedger
from app.services.learning.item_supply.sandbox.orchestrator import SandboxOrchestrator
from app.services.learning.item_supply.sandbox.scenarios import SCENARIOS


def make_run(*, origin: Origin = "simulation", source_run: UUID | None = None) -> RunV2:
    return RunV2(
        source_run=source_run or uuid4(), namespace="sandbox.fixture.v2",
        tenant_id=uuid4(), actor_id=uuid4(), scope_hash="1" * 64,
        content_hash="2" * 64, profile_hash="3" * 64, origin=origin,
        collector_identity="collector.fixture" if origin == "real_learner" else None,
        session_id=uuid4() if origin == "real_learner" else None,
    )


def make_terminal(
    run: RunV2, *, scenario: ScenarioName = "independent_correct", attempt: int = 1,
    outcome: TerminalOutcome = "correct",
) -> TerminalReceiptV2:
    return TerminalReceiptV2(
        terminal_receipt_id=uuid4(), source_run=run.source_run, run_hash=run_digest(run),
        scenario=scenario, attempt=attempt, origin=run.origin, outcome=outcome,
        authority_kind="learner_collector" if run.origin == "real_learner" else "sandbox_scenario",
        authority_identity="collector.fixture" if run.origin == "real_learner" else "scenario.fixture",
        evidence_hash="4" * 64, duration_ms=10,
    )


class FixtureTerminalResolver:
    """Explicitly synthetic installed authority; never establishes live execution."""

    def __init__(self) -> None:
        self.receipts: dict[UUID, TerminalReceiptV2] = {}
        self.calls = 0

    def add(self, terminal: TerminalReceiptV2) -> None:
        self.receipts[terminal.terminal_receipt_id] = terminal

    def resolve(
        self, *, run: RunV2, scenario: ScenarioName, attempt: int, terminal_receipt_id: UUID,
    ) -> TerminalReceiptV2:
        self.calls += 1
        if terminal_receipt_id not in self.receipts:
            raise ValueError("terminal unavailable")
        return self.receipts[terminal_receipt_id]

    def verify(self, *, run: RunV2, receipt: TerminalReceiptV2) -> bool:
        return (self.receipts.get(receipt.terminal_receipt_id) == receipt
                and receipt.run_hash == run_digest(run))


def record_terminal(
    orchestrator: SandboxOrchestrator, run: RunV2, terminal: TerminalReceiptV2,
) -> ObservationV2:
    return orchestrator.observe(
        run=run, scenario=terminal.scenario, attempt=terminal.attempt,
        terminal_receipt_id=terminal.terminal_receipt_id,
    )


def test_fixed_profiles_count_only_resolved_terminal_outcomes() -> None:
    assert len(SCENARIOS) == len({profile.scenario for profile in SCENARIOS}) == 11
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    assert orchestrator.ledger.aggregate(run=run).sample_count == 0
    for profile in SCENARIOS:
        terminal = make_terminal(run, scenario=profile.scenario, outcome=profile.expected_outcome)
        resolver.add(terminal)
        record_terminal(orchestrator, run, terminal)
    counts = orchestrator.ledger.aggregate(run=run)
    assert (counts.sample_count, counts.terminal_count, counts.completed_count,
            counts.passed_count, counts.failed_count) == (11, 11, 7, 5, 1)
    assert resolver.calls == 11
    provider_failure = make_terminal(run, scenario="provider_executor_failure", attempt=2,
                                     outcome="provider_failed")
    resolver.add(provider_failure)
    record_terminal(orchestrator, run, provider_failure)
    counts = orchestrator.ledger.aggregate(run=run)
    assert (counts.sample_count, counts.completed_count, counts.failed_count) == (12, 7, 2)


def test_refresh_replay_returns_original_and_never_increments_counts() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    terminal = make_terminal(run, scenario="refresh_replay")
    resolver.add(terminal)
    first = record_terminal(orchestrator, run, terminal)
    before = orchestrator.ledger.aggregate(run=run)
    assert record_terminal(orchestrator, run, terminal) is first
    assert orchestrator.ledger.record(first) is first
    assert orchestrator.ledger.aggregate(run=run) == before


def test_distinct_attempts_are_independent_terminal_samples() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    for attempt in (1, 2):
        terminal = make_terminal(run, attempt=attempt)
        resolver.add(terminal)
        record_terminal(orchestrator, run, terminal)
    assert orchestrator.ledger.aggregate(run=run).sample_count == 2


def test_simulation_and_probe_use_distinct_run_bound_ledgers() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    simulation, probe = make_run(), make_run(origin="deterministic_probe")
    for run in (simulation, probe):
        terminal = make_terminal(run)
        resolver.add(terminal)
        observation = record_terminal(orchestrator, run, terminal)
        assert observation.origin == run.origin
        assert orchestrator.ledger.aggregate(run=run).sample_count == 1
    assert orchestrator.ledger.observations(run=simulation)[0].run != probe


def test_changed_scope_content_or_profile_cannot_reuse_a_run() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    original = make_terminal(run)
    resolver.add(original)
    record_terminal(orchestrator, run, original)
    for field in ("scope_hash", "content_hash", "profile_hash"):
        changed = RunV2.model_validate({**run.model_dump(), field: "f" * 64})
        terminal = make_terminal(changed, scenario="after_hint")
        resolver.add(terminal)
        with pytest.raises(SandboxObservationDenied, match="sandbox_run_immutable"):
            record_terminal(orchestrator, changed, terminal)
    fresh = RunV2.model_validate({**run.model_dump(), "source_run": uuid4(), "content_hash": "f" * 64})
    terminal = make_terminal(fresh)
    resolver.add(terminal)
    record_terminal(orchestrator, fresh, terminal)
    assert orchestrator.ledger.aggregate(run=run).sample_count == 1
    assert orchestrator.ledger.aggregate(run=fresh).sample_count == 1


def test_same_unique_key_cannot_change_origin_or_terminal() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    terminal = make_terminal(run)
    resolver.add(terminal)
    original = record_terminal(orchestrator, run, terminal)
    relabeled = RunV2.model_validate({**run.model_dump(), "origin": "deterministic_probe"})
    replacement = make_terminal(relabeled)
    resolver.add(replacement)
    with pytest.raises(SandboxObservationDenied, match="observation_origin_immutable"):
        record_terminal(orchestrator, relabeled, replacement)
    conflicting = make_terminal(run, outcome="incorrect")
    resolver.add(conflicting)
    with pytest.raises(SandboxObservationDenied, match="observation_replay_conflict"):
        record_terminal(orchestrator, run, conflicting)
    assert orchestrator.ledger.observations(run=run) == (original,)


def test_model_sample_completed_and_origin_claims_are_not_contract_fields() -> None:
    run = make_run()
    terminal = make_terminal(run)
    with pytest.raises(ValidationError):
        TerminalReceiptV2.model_validate({**terminal.model_dump(), "completed": True})
    with pytest.raises(ValidationError):
        ObservationV2.model_validate({"run": run, "terminal_receipt": terminal, "sample_count": 99})
    with pytest.raises(ValidationError):
        make_run(origin="human")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        RunV2.model_validate({**run.model_dump(), "namespace": "production.users"})


def test_forged_terminal_cannot_enter_ledger_by_constructing_observation() -> None:
    resolver = FixtureTerminalResolver()
    ledger = ObservationLedger(resolver)
    run = make_run()
    terminal = make_terminal(run)
    resolver.add(terminal)
    forged = TerminalReceiptV2.model_validate({**terminal.model_dump(), "evidence_hash": "f" * 64})
    observation = ObservationV2(run=run, terminal_receipt=forged)
    with pytest.raises(SandboxObservationDenied, match="terminal_authority_mismatch"):
        ledger.record(observation)
    assert ledger.aggregate(run=run).sample_count == 0


def test_unavailable_and_wrong_run_terminals_fail_closed() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    run = make_run()
    with pytest.raises(SandboxObservationDenied, match="terminal_authority_unavailable"):
        orchestrator.observe(run=run, scenario="independent_correct", attempt=1,
                             terminal_receipt_id=uuid4())
    wrong = make_terminal(make_run())
    resolver.add(wrong)
    with pytest.raises(SandboxObservationDenied, match="terminal_binding_mismatch"):
        record_terminal(orchestrator, run, wrong)
    assert orchestrator.ledger.aggregate(run=run).sample_count == 0

    class UnverifiedResolver(FixtureTerminalResolver):
        def verify(self, *, run: RunV2, receipt: TerminalReceiptV2) -> bool:
            return False

    unverified = UnverifiedResolver()
    terminal = make_terminal(run)
    unverified.add(terminal)
    refused = SandboxOrchestrator(unverified)
    with pytest.raises(SandboxObservationDenied, match="terminal_verification_denied"):
        record_terminal(refused, run, terminal)
    assert refused.ledger.aggregate(run=run).sample_count == 0


def test_missing_real_collector_rejects_complete_self_report_without_resolver_io() -> None:
    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver)
    synthetic = make_run()
    synthetic_terminal = make_terminal(synthetic)
    resolver.add(synthetic_terminal)
    original = record_terminal(orchestrator, synthetic, synthetic_terminal)
    real = make_run(origin="real_learner", source_run=synthetic.source_run)
    terminal = make_terminal(real)
    assert real.session_id is not None
    collector = CollectorReceiptV2(
        collector_identity="collector.fixture", session_id=real.session_id,
        actor_id=real.actor_id, run_hash=run_digest(real), terminal_hash=terminal_digest(terminal),
    )
    forged_observation = ObservationV2(run=real, terminal_receipt=terminal, collector_receipt=collector)
    before = resolver.calls
    with pytest.raises(SandboxObservationDenied, match="learner_collector_unavailable"):
        orchestrator.ledger.record(forged_observation)
    with pytest.raises(SandboxObservationDenied, match="learner_collector_unavailable"):
        record_terminal(orchestrator, real, terminal)
    assert resolver.calls == before
    assert orchestrator.ledger.observations(run=synthetic) == (original,)


def test_collector_authority_must_bind_current_actor_session_and_terminal() -> None:
    class WrongCollector:
        def authorize(self, *, run: RunV2, terminal_receipt: TerminalReceiptV2) -> CollectorReceiptV2:
            assert run.session_id is not None and run.collector_identity is not None
            return CollectorReceiptV2(
                collector_identity=run.collector_identity, session_id=run.session_id,
                actor_id=uuid4(), run_hash=run_digest(run), terminal_hash=terminal_digest(terminal_receipt),
            )

    resolver = FixtureTerminalResolver()
    orchestrator = SandboxOrchestrator(resolver, collector=WrongCollector())
    run = make_run(origin="real_learner")
    terminal = make_terminal(run)
    resolver.add(terminal)
    with pytest.raises(ValidationError, match="collector binding mismatch"):
        record_terminal(orchestrator, run, terminal)
    assert orchestrator.ledger.aggregate(run=run).sample_count == 0
