"""Terminal-only sandbox orchestration; no scorer, runner or formal owner IO."""
from __future__ import annotations

from uuid import UUID

from app.services.learning.item_supply.sandbox.contracts import (
    CollectorAuthority,
    ObservationV2,
    RunV2,
    ScenarioName,
    TerminalResolver,
)
from app.services.learning.item_supply.sandbox.observations import ObservationLedger
from app.services.learning.item_supply.sandbox.scenarios import scenario_profile


class SandboxOrchestrator:
    def __init__(
        self, resolver: TerminalResolver, *, ledger: ObservationLedger | None = None,
        collector: CollectorAuthority | None = None,
    ) -> None:
        # An injected ledger owns its own installed terminal/collector authority;
        # otherwise install the explicitly trusted server composition here.
        self.ledger = ledger if ledger is not None else ObservationLedger(resolver, collector=collector)

    def observe(
        self, *, run: RunV2, scenario: ScenarioName, attempt: int, terminal_receipt_id: UUID,
    ) -> ObservationV2:
        scenario_profile(scenario)
        return self.ledger.observe(run=run, scenario=scenario, attempt=attempt,
                                   terminal_receipt_id=terminal_receipt_id)
