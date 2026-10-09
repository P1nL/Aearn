"""Internal P6 execution ports; no runtime/DB dependency or model authority."""
from __future__ import annotations

from typing import Literal, Protocol
from uuid import UUID

from aearn_shared.execution import SandboxInputV1, SandboxResultV1
from pydantic import Field, model_validator

from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.storage_contracts import StorageContract

RUNNER_VERSION = "item_supply_os_runner_v1"
PROBE_PROFILE_VERSION = "item_supply_probe_profile_v1"
EXECUTION_WALL_SECONDS = 5


class IndependentProbeV1(StorageContract):
    """Server-owned case/oracle pair. Not a provider response or pass receipt."""

    name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")
    submission: str = Field(min_length=1, max_length=48_000)
    expected: Literal["pass", "reject", "sql_setup_invalid"]
    cases_json: str = Field(min_length=2, max_length=80_000)
    tests_json: str = Field(default="[]", max_length=80_000)


class CandidateProbePlanV1(StorageContract):
    """Trusted independent alternatives, frozen to an exact candidate source."""

    source_hash: Digest
    equivalent: str = Field(min_length=1, max_length=48_000)
    wrong: str = Field(min_length=1, max_length=48_000)
    boundary: str = Field(min_length=1, max_length=48_000)
    boundary_case_ids: tuple[str, ...] = Field(default=(), max_length=48)
    profile_id: str | None = Field(default=None, min_length=1, max_length=80)
    server_fixture_hash: Digest | None = None
    # Independent, predeclared inputs/oracles; never returned to candidate children.
    boundary_cases_json: str | None = Field(default=None, max_length=80_000)
    boundary_tests_json: str | None = Field(default=None, max_length=80_000)
    probes: tuple[IndependentProbeV1, ...] = Field(default=(), max_length=40)

    @model_validator(mode="after")
    def distinct_alternatives(self) -> CandidateProbePlanV1:
        if self.equivalent == self.wrong or self.boundary == self.wrong:
            raise ValueError("probe_alternatives_not_independent")
        if (self.boundary_cases_json is None) != (self.boundary_tests_json is None):
            raise ValueError("probe_boundary_bundle_incomplete")
        names = [probe.name for probe in self.probes]
        if len(names) != len(set(names)):
            raise ValueError("probe_names_duplicate")
        return self


class RunnerTerminalReceipt(Protocol):
    """Structural receipt owned and sealed by the standalone executor bridge."""

    @property
    def run_id(self) -> UUID: ...
    @property
    def probe_name(self) -> str: ...
    @property
    def request_hash(self) -> str: ...
    @property
    def lock_fingerprint(self) -> str: ...
    @property
    def result(self) -> SandboxResultV1: ...
    @property
    def elapsed_seconds(self) -> float: ...
    @property
    def mode(self) -> Literal["live", "synthetic"]: ...
    @property
    def isolation(self) -> Literal["approved_os_boundary", "synthetic"]: ...
    @property
    def seal(self) -> str: ...

    def to_payload(self) -> dict[str, object]: ...


class RunnerPort(Protocol):
    def run(self, *, request: SandboxInputV1, run_id: UUID, probe_name: str) -> RunnerTerminalReceipt: ...

    def verify(self, receipt: RunnerTerminalReceipt, *, request: SandboxInputV1) -> bool: ...
