"""Exact sandbox identities and terminal provenance, never learner authority."""
from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

Origin = Literal["simulation", "deterministic_probe", "real_learner"]
ScenarioName = Literal[
    "independent_correct", "typical_error", "partially_correct", "equivalent_solution",
    "boundary_ambiguity", "after_hint", "answer_request", "after_remediation",
    "refresh_replay", "stale_scope", "provider_executor_failure",
]
TerminalOutcome = Literal[
    "correct", "incorrect", "partial", "equivalent", "ambiguous", "answer_requested",
    "stale_scope", "provider_failed", "executor_failed", "timeout", "cancelled",
]
AuthorityKind = Literal[
    "sandbox_executor", "sandbox_provider", "sandbox_scenario", "learner_collector",
]


class SandboxObservationDenied(ValueError):
    def __init__(self, reason: str = "sandbox_observation_denied") -> None:
        super().__init__(reason)


class RunV2(StorageContract):
    schema_version: Literal["sandbox_run_v2"] = "sandbox_run_v2"
    source_run: UUID
    namespace: Identifier
    tenant_id: UUID
    actor_id: UUID
    scope_hash: Digest
    content_hash: Digest
    profile_hash: Digest
    origin: Origin
    collector_identity: Identifier | None = None
    session_id: UUID | None = None

    @model_validator(mode="after")
    def isolated_identity(self) -> RunV2:
        if not self.namespace.startswith("sandbox.") or self.namespace == "sandbox.":
            raise ValueError("sandbox namespace required")
        if self.origin == "real_learner":
            if self.collector_identity is None or self.session_id is None:
                raise ValueError("learner collector identity required")
        elif self.collector_identity is not None or self.session_id is not None:
            raise ValueError("synthetic run cannot claim learner identity")
        return self


def run_digest(run: RunV2) -> str:
    return canonical_hash(checked_model(run, RunV2).model_dump(mode="json"))


class TerminalReceiptV2(StorageContract):
    schema_version: Literal["sandbox_terminal_receipt_v2"] = "sandbox_terminal_receipt_v2"
    terminal_receipt_id: UUID
    source_run: UUID
    run_hash: Digest
    scenario: ScenarioName
    attempt: int = Field(ge=1, le=1_000_000)
    origin: Origin
    outcome: TerminalOutcome
    authority_kind: AuthorityKind
    authority_identity: Identifier
    evidence_hash: Digest
    duration_ms: int = Field(ge=0, le=86_400_000)

    @model_validator(mode="after")
    def distinct_authority(self) -> TerminalReceiptV2:
        if (self.origin == "real_learner") != (self.authority_kind == "learner_collector"):
            raise ValueError("terminal origin authority mismatch")
        return self


def terminal_digest(receipt: TerminalReceiptV2) -> str:
    return canonical_hash(checked_model(receipt, TerminalReceiptV2).model_dump(mode="json"))


class CollectorReceiptV2(StorageContract):
    collector_identity: Identifier
    session_id: UUID
    actor_id: UUID
    run_hash: Digest
    terminal_hash: Digest


class ObservationV2(StorageContract):
    schema_version: Literal["sandbox_observation_v2"] = "sandbox_observation_v2"
    run: RunV2
    terminal_receipt: TerminalReceiptV2
    collector_receipt: CollectorReceiptV2 | None = None

    @model_validator(mode="after")
    def exact_provenance(self) -> ObservationV2:
        run, receipt = self.run, self.terminal_receipt
        if (receipt.source_run != run.source_run or receipt.run_hash != run_digest(run)
                or receipt.origin != run.origin):
            raise ValueError("terminal run binding mismatch")
        collector = self.collector_receipt
        if run.origin != "real_learner":
            if collector is not None:
                raise ValueError("synthetic observation cannot claim collector")
        elif (collector is None or collector.collector_identity != run.collector_identity
                or collector.session_id != run.session_id or collector.actor_id != run.actor_id
                or collector.run_hash != run_digest(run)
                or collector.terminal_hash != terminal_digest(receipt)
                or receipt.authority_identity != collector.collector_identity):
            raise ValueError("collector binding mismatch")
        return self

    @property
    def source_run(self) -> UUID:
        return self.run.source_run

    @property
    def scenario(self) -> ScenarioName:
        return self.terminal_receipt.scenario

    @property
    def attempt(self) -> int:
        return self.terminal_receipt.attempt

    @property
    def origin(self) -> Origin:
        return self.run.origin

    @property
    def unique_key(self) -> tuple[UUID, ScenarioName, int]:
        return self.source_run, self.scenario, self.attempt


class TerminalResolver(Protocol):
    """Server-installed authority, not a model-supplied receipt or completion flag.

    Implementations must resolve and verify immutable execution/provider terminal
    facts (including exact run/content/profile/actor/namespace identity). A digest
    alone does not establish execution; missing/nonterminal records must raise.
    """

    def resolve(
        self, *, run: RunV2, scenario: ScenarioName, attempt: int, terminal_receipt_id: UUID,
    ) -> TerminalReceiptV2: ...

    def verify(self, *, run: RunV2, receipt: TerminalReceiptV2) -> bool:
        """Verify original terminal/scorer facts, not model outcome or actor labels."""
        ...


class CollectorAuthority(Protocol):
    """Trusted current collector/session/actor/terminal authority; absent in P6."""

    def authorize(
        self, *, run: RunV2, terminal_receipt: TerminalReceiptV2,
    ) -> CollectorReceiptV2: ...
