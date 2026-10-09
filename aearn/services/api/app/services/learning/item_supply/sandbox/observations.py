"""Append-only split-origin observations, derived only from trusted terminals."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.learning.item_supply.sandbox.contracts import (
    CollectorAuthority,
    CollectorReceiptV2,
    ObservationV2,
    Origin,
    RunV2,
    SandboxObservationDenied,
    ScenarioName,
    TerminalReceiptV2,
    TerminalResolver,
    run_digest,
)
from app.services.learning.item_supply.storage_contracts import checked_model

_COMPLETED = frozenset(("correct", "incorrect", "partial", "equivalent"))
_PASSED = frozenset(("correct", "equivalent"))
_FAILED = frozenset(("provider_failed", "executor_failed", "timeout", "cancelled"))


@dataclass(frozen=True)
class ObservationCountsV2:
    source_run: UUID
    run_hash: str
    origin: Origin
    sample_count: int
    terminal_count: int
    completed_count: int
    passed_count: int
    failed_count: int


class ObservationLedger:
    """Pure internal ledger; durable uniqueness belongs to the storage adapter.

    Every record, including a replay, is resolved through installed authority.
    Constructing a strict ObservationV2 alone never grants count authority.
    """

    def __init__(
        self, resolver: TerminalResolver, *, collector: CollectorAuthority | None = None,
    ) -> None:
        self._resolver = resolver
        self._collector = collector
        self._runs: dict[UUID, str] = {}
        self._keys: dict[tuple[UUID, ScenarioName, int], ObservationV2] = {}
        self._ledgers: dict[Origin, dict[tuple[UUID, ScenarioName, int], ObservationV2]] = {
            "simulation": {}, "deterministic_probe": {}, "real_learner": {},
        }

    def _resolve(
        self, *, run: RunV2, scenario: ScenarioName, attempt: int, terminal_receipt_id: UUID,
    ) -> TerminalReceiptV2:
        try:
            receipt = checked_model(self._resolver.resolve(
                run=run, scenario=scenario, attempt=attempt,
                terminal_receipt_id=terminal_receipt_id,
            ), TerminalReceiptV2)
        except (ValueError, TypeError, AttributeError):
            raise SandboxObservationDenied("terminal_authority_unavailable") from None
        if (receipt.source_run != run.source_run or receipt.run_hash != run_digest(run)
                or receipt.origin != run.origin or receipt.scenario != scenario
                or receipt.attempt != attempt or receipt.terminal_receipt_id != terminal_receipt_id):
            raise SandboxObservationDenied("terminal_binding_mismatch")
        try:
            verified = self._resolver.verify(run=run, receipt=receipt)
        except (ValueError, TypeError, AttributeError):
            raise SandboxObservationDenied("terminal_verification_unavailable") from None
        if verified is not True:
            raise SandboxObservationDenied("terminal_verification_denied")
        return receipt

    def _collector_receipt(
        self, run: RunV2, terminal: TerminalReceiptV2,
    ) -> CollectorReceiptV2 | None:
        if run.origin != "real_learner":
            return None
        if self._collector is None:
            raise SandboxObservationDenied("learner_collector_unavailable")
        try:
            return checked_model(self._collector.authorize(
                run=run, terminal_receipt=terminal,
            ), CollectorReceiptV2)
        except (ValueError, TypeError, AttributeError):
            raise SandboxObservationDenied("learner_collector_unavailable") from None

    def observe(
        self, *, run: RunV2, scenario: ScenarioName, attempt: int, terminal_receipt_id: UUID,
    ) -> ObservationV2:
        run = checked_model(run, RunV2)
        if run.origin == "real_learner" and self._collector is None:
            raise SandboxObservationDenied("learner_collector_unavailable")
        terminal = self._resolve(run=run, scenario=scenario, attempt=attempt,
                                 terminal_receipt_id=terminal_receipt_id)
        collector = self._collector_receipt(run, terminal)
        return self._append(ObservationV2(
            run=run, terminal_receipt=terminal, collector_receipt=collector,
        ))

    def record(self, observation: ObservationV2) -> ObservationV2:
        observation = checked_model(observation, ObservationV2)
        if observation.origin == "real_learner" and self._collector is None:
            raise SandboxObservationDenied("learner_collector_unavailable")
        terminal = self._resolve(
            run=observation.run, scenario=observation.scenario, attempt=observation.attempt,
            terminal_receipt_id=observation.terminal_receipt.terminal_receipt_id,
        )
        if terminal != observation.terminal_receipt:
            raise SandboxObservationDenied("terminal_authority_mismatch")
        collector = self._collector_receipt(observation.run, terminal)
        if collector != observation.collector_receipt:
            raise SandboxObservationDenied("collector_authority_mismatch")
        return self._append(observation)

    def _append(self, observation: ObservationV2) -> ObservationV2:
        digest = run_digest(observation.run)
        existing = self._keys.get(observation.unique_key)
        if existing is not None:
            if existing.origin != observation.origin:
                raise SandboxObservationDenied("observation_origin_immutable")
            if existing != observation:
                raise SandboxObservationDenied("observation_replay_conflict")
            return existing
        if self._runs.get(observation.source_run, digest) != digest:
            raise SandboxObservationDenied("sandbox_run_immutable")
        self._runs[observation.source_run] = digest
        self._keys[observation.unique_key] = observation
        self._ledgers[observation.origin][observation.unique_key] = observation
        return observation

    def observations(self, *, run: RunV2) -> tuple[ObservationV2, ...]:
        run = checked_model(run, RunV2)
        digest = run_digest(run)
        if self._runs.get(run.source_run, digest) != digest:
            raise SandboxObservationDenied("sandbox_run_immutable")
        return tuple(row for row in self._ledgers[run.origin].values()
                     if row.source_run == run.source_run)

    def aggregate(self, *, run: RunV2) -> ObservationCountsV2:
        rows = self.observations(run=run)
        outcomes = tuple(row.terminal_receipt.outcome for row in rows)
        return ObservationCountsV2(
            source_run=run.source_run, run_hash=run_digest(run), origin=run.origin,
            sample_count=len(rows), terminal_count=len(rows),
            completed_count=sum(outcome in _COMPLETED for outcome in outcomes),
            passed_count=sum(outcome in _PASSED for outcome in outcomes),
            failed_count=sum(outcome in _FAILED for outcome in outcomes),
        )
