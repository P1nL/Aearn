"""P3 server-owned item-supply authority and retry policies; no IO."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import (
    Digest,
    Identifier,
    SupplyScopeV1,
    revalidate_contract,
)
from app.services.learning.item_supply.storage_contracts import (
    StorageContract,
    checked_model,
)

Visibility = Literal["public", "private"]
PoolClass = Literal["base", "enhancement"]
ResourceKind = Literal[
    "requests",
    "input_tokens",
    "output_tokens",
    "execution_seconds",
    "fetches",
    "candidates",
    "revision_rounds",
    "investigation_rounds",
]
RESOURCE_KINDS: tuple[ResourceKind, ...] = (
    "requests",
    "input_tokens",
    "output_tokens",
    "execution_seconds",
    "fetches",
    "candidates",
    "revision_rounds",
    "investigation_rounds",
)


class SupplyRuntimeError(ValueError):
    """Bounded runtime denial; messages are stable safe codes."""


class FailureClass(StrEnum):
    TRANSIENT = "transient"
    RATE_LIMITED = "rate_limited"
    DETERMINISTIC = "deterministic"
    SAFETY = "safety"
    SCORING = "scoring"


class CoverageObligationV1(StorageContract):
    schema_version: Literal["coverage_obligation_v1"] = "coverage_obligation_v1"
    blueprint_hash: Digest | None = None
    scope_hash: Digest
    objective_hash: Digest
    purpose: Identifier
    runtime_contract_hash: Digest
    visibility: Visibility
    policy_version: Identifier
    owner_id: UUID | None = None

    @model_validator(mode="after")
    def namespace(self) -> "CoverageObligationV1":
        if (self.visibility == "private") != (self.owner_id is not None):
            raise ValueError("obligation namespace mismatch")
        if self.visibility == "public" and self.blueprint_hash is None:
            raise ValueError("public obligation requires blueprint")
        return self

    @property
    def canonical_key(self) -> str:
        return canonical_hash(
            checked_model(self, CoverageObligationV1).model_dump(mode="json")
        )


def derive_runtime_contract_hash(scope: SupplyScopeV1) -> str:
    value = revalidate_contract(scope, SupplyScopeV1)
    return canonical_hash(
        {
            "runtime_profile_id": value.runtime_profile_id,
            "runtime_profile_hash": value.runtime_profile_hash,
            "required_capabilities": list(value.required_capabilities),
            "assessment_contract_version": value.assessment_contract_version,
            "scorer_version": value.scorer_version,
            "assistance_policy_hash": value.assistance_policy_hash,
        }
    )


class ResourceAmounts(StorageContract):
    requests: int = Field(default=0, ge=0, le=1_000_000)
    input_tokens: int = Field(default=0, ge=0, le=10_000_000_000)
    output_tokens: int = Field(default=0, ge=0, le=10_000_000_000)
    execution_seconds: int = Field(default=0, ge=0, le=31_536_000)
    fetches: int = Field(default=0, ge=0, le=1_000_000)
    candidates: int = Field(default=0, ge=0, le=1_000_000)
    revision_rounds: int = Field(default=0, ge=0, le=100_000)
    investigation_rounds: int = Field(default=0, ge=0, le=100_000)

    def as_dict(self) -> dict[ResourceKind, int]:
        return {kind: int(getattr(self, kind)) for kind in RESOURCE_KINDS}

    def positive(self) -> tuple[tuple[ResourceKind, int], ...]:
        return tuple(
            (kind, amount) for kind, amount in self.as_dict().items() if amount > 0
        )


class RetryPolicyV1(StorageContract):
    schema_version: Literal["item_supply_retry_policy_v1"] = (
        "item_supply_retry_policy_v1"
    )
    max_transient_attempts: int = Field(ge=1, le=12)
    initial_backoff_ms: int = Field(ge=1, le=3_600_000)
    maximum_backoff_ms: int = Field(ge=1, le=3_600_000)

    @model_validator(mode="after")
    def bounds(self) -> "RetryPolicyV1":
        if self.initial_backoff_ms > self.maximum_backoff_ms:
            raise ValueError("retry backoff order invalid")
        return self

    def next_retry_at(
        self,
        *,
        failure: FailureClass,
        attempt: int,
        now: datetime,
        parent_deadline: datetime,
        retry_after_seconds: int | None = None,
    ) -> datetime | None:
        checked_model(self, RetryPolicyV1)
        if now.tzinfo is None or parent_deadline.tzinfo is None:
            raise SupplyRuntimeError("AWARE_TIME_REQUIRED")
        if (
            not isinstance(failure, FailureClass)
            or type(attempt) is not int
            or attempt < 1
        ):
            raise SupplyRuntimeError("INVALID_RETRY")
        if retry_after_seconds is not None and (
            type(retry_after_seconds) is not int
            or not 0 <= retry_after_seconds <= 2_592_000
        ):
            raise SupplyRuntimeError("INVALID_RETRY_AFTER")
        if (
            failure
            in {FailureClass.DETERMINISTIC, FailureClass.SAFETY, FailureClass.SCORING}
            or attempt >= self.max_transient_attempts
        ):
            return None
        delay_ms = min(
            self.maximum_backoff_ms,
            self.initial_backoff_ms * (2 ** max(0, attempt - 1)),
        )
        if failure == FailureClass.RATE_LIMITED and retry_after_seconds is not None:
            delay_ms = max(delay_ms, retry_after_seconds * 1000)
        candidate = now + timedelta(milliseconds=delay_ms)
        return candidate if candidate < parent_deadline else None
