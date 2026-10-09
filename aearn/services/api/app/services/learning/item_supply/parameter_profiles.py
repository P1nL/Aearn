"""Explicit trusted-caller execution configs and immutable P3 job snapshots.

Evidence identifiers are references, not signatures. This pure boundary neither
loads config nor authenticates provider/preflight facts. There are no timeout or
round-count defaults, and legacy configs without full coordinates cannot tune.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest, Identifier
from app.services.learning.item_supply.storage_contracts import (
    StorageContract,
    checked_model,
)

ParameterName = Literal[
    "connection_timeout_ms",
    "first_token_timeout_ms",
    "stream_idle_timeout_ms",
    "request_timeout_ms",
    "stage_deadline_ms",
    "parent_deadline_ms",
    "discussion_rounds",
    "revision_rounds",
    "investigation_rounds",
]
PARAMETER_NAMES: tuple[ParameterName, ...] = (
    "connection_timeout_ms",
    "first_token_timeout_ms",
    "stream_idle_timeout_ms",
    "request_timeout_ms",
    "stage_deadline_ms",
    "parent_deadline_ms",
    "discussion_rounds",
    "revision_rounds",
    "investigation_rounds",
)
ProfileState = Literal["warmup", "proposed", "canary", "stable", "frozen", "blocked"]


class ProfileKeyV1(StorageContract):
    provider: Identifier
    model_version: Identifier
    agent_role: Identifier
    item_kind: Identifier
    risk_tier: Literal["low", "medium", "high"]
    difficulty: Literal["introductory", "basic", "intermediate", "advanced"]
    input_size_bucket: Identifier
    runtime: Identifier
    # Readable legacy configs do not silently gain permission to calibrate.
    provider_version: Identifier | None = None
    prompt_version: Identifier | None = None
    validator_version: Identifier | None = None
    output_size_bucket: Identifier | None = None
    load_bucket: Identifier | None = None
    complexity_version: Identifier | None = None

    @property
    def calibration_ready(self) -> bool:
        key = checked_model(self, ProfileKeyV1)
        return all(
            value is not None
            for value in (
                key.provider_version,
                key.prompt_version,
                key.validator_version,
                key.output_size_bucket,
                key.load_bucket,
                key.complexity_version,
            )
        )

    @property
    def key_hash(self) -> str:
        return canonical_hash(checked_model(self, ProfileKeyV1).model_dump(mode="json"))


class ParameterValuesV1(StorageContract):
    connection_timeout_ms: int = Field(ge=1, le=86_400_000)
    first_token_timeout_ms: int = Field(ge=1, le=86_400_000)
    stream_idle_timeout_ms: int = Field(ge=1, le=86_400_000)
    request_timeout_ms: int = Field(ge=1, le=86_400_000)
    stage_deadline_ms: int = Field(ge=1, le=604_800_000)
    parent_deadline_ms: int = Field(ge=1, le=2_592_000_000)
    discussion_rounds: int = Field(ge=1, le=64)
    revision_rounds: int = Field(ge=1, le=64)
    investigation_rounds: int = Field(ge=1, le=64)

    @model_validator(mode="after")
    def ordered(self) -> ParameterValuesV1:
        if (
            max(
                self.connection_timeout_ms,
                self.first_token_timeout_ms,
                self.stream_idle_timeout_ms,
            )
            > self.request_timeout_ms
        ):
            raise ValueError("request timeout must cover connection/first-token/idle")
        if (
            not self.request_timeout_ms
            <= self.stage_deadline_ms
            <= self.parent_deadline_ms
        ):
            raise ValueError("deadline order invalid")
        return self

    def value(self, name: ParameterName) -> int:
        if name not in PARAMETER_NAMES:
            raise ValueError("invalid parameter name")
        return int(getattr(self, name))

    def replace(self, name: ParameterName, value: int) -> ParameterValuesV1:
        checked = checked_model(self, ParameterValuesV1)
        checked.value(name)
        return ParameterValuesV1.model_validate(
            {**checked.model_dump(mode="python"), name: value},
            strict=True,
        )


class ExecutionParameterProfileV1(StorageContract):
    schema_version: Literal["execution_parameter_profile_v1"] = (
        "execution_parameter_profile_v1"
    )
    profile_key: ProfileKeyV1
    version: int = Field(ge=1)
    state: ProfileState
    initial: ParameterValuesV1
    current: ParameterValuesV1
    last_stable: ParameterValuesV1
    floor: ParameterValuesV1
    ceiling: ParameterValuesV1
    measurement_window_started_at: datetime
    measurement_window_ended_at: datetime | None = None
    change_reason: Identifier
    trusted_initial_evidence: tuple[Identifier, ...] = Field(
        min_length=1, max_length=16
    )
    cooldown_until: datetime | None = None
    parent_version: int | None = Field(default=None, ge=1)
    rollback_count: int = Field(default=0, ge=0, le=16)

    @model_validator(mode="after")
    def profile_bounds(self) -> ExecutionParameterProfileV1:
        times = (
            self.measurement_window_started_at,
            self.measurement_window_ended_at,
            self.cooldown_until,
        )
        if any(value is not None and value.tzinfo is None for value in times):
            raise ValueError("profile timestamps must be aware")
        if (
            self.measurement_window_ended_at is not None
            and self.measurement_window_ended_at < self.measurement_window_started_at
        ):
            raise ValueError("measurement window invalid")
        if self.parent_version is not None and self.parent_version >= self.version:
            raise ValueError("profile lineage must precede current version")
        if len(set(self.trusted_initial_evidence)) != len(
            self.trusted_initial_evidence
        ):
            raise ValueError("initial evidence references must be unique")
        for name in PARAMETER_NAMES:
            low, high = self.floor.value(name), self.ceiling.value(name)
            if low > high:
                raise ValueError("profile floor exceeds ceiling")
            if any(
                not low <= values.value(name) <= high
                for values in (self.initial, self.current, self.last_stable)
            ):
                raise ValueError("profile value outside bounds")
        if self.state in ("proposed", "canary"):
            changed = tuple(
                name
                for name in PARAMETER_NAMES
                if self.current.value(name) != self.last_stable.value(name)
            )
            if len(changed) != 1 or self.current.value(
                changed[0]
            ) >= self.last_stable.value(changed[0]):
                raise ValueError("canary must shrink exactly one stable dimension")
        return self

    @property
    def profile_hash(self) -> str:
        return canonical_hash(
            checked_model(self, ExecutionParameterProfileV1).model_dump(mode="json")
        )


class FrozenProfileSnapshot(StorageContract):
    profile_key_hash: Digest
    profile_version: int = Field(ge=1)
    profile_hash: Digest
    values: ParameterValuesV1
    bound_at: datetime
    parent_deadline_at: datetime

    @model_validator(mode="after")
    def aware(self) -> FrozenProfileSnapshot:
        if self.bound_at.tzinfo is None or self.parent_deadline_at.tzinfo is None:
            raise ValueError("bound time must be aware")
        if not (
            self.bound_at
            < self.parent_deadline_at
            <= self.bound_at + timedelta(milliseconds=self.values.parent_deadline_ms)
        ):
            raise ValueError("snapshot must retain its bounded parent deadline")
        return self

    def remaining_timeout_ms(self, name: ParameterName, *, now: datetime) -> int:
        """Each child/retry uses the original deadline; heartbeats cannot extend it."""
        snapshot = checked_model(self, FrozenProfileSnapshot)
        if now.tzinfo is None or now < snapshot.bound_at:
            raise ValueError("invalid snapshot clock")
        if name.endswith("rounds"):
            raise ValueError("rounds are not timeouts")
        remaining = max(
            0, int((snapshot.parent_deadline_at - now).total_seconds() * 1000)
        )
        return min(snapshot.values.value(name), remaining)


def freeze_profile(
    profile: ExecutionParameterProfileV1,
    *,
    bound_at: datetime,
    ancestor_deadline: datetime | None = None,
) -> FrozenProfileSnapshot:
    checked = checked_model(profile, ExecutionParameterProfileV1)
    if bound_at.tzinfo is None:
        raise ValueError("bound time must be aware")
    if checked.state in ("blocked", "proposed"):
        raise ValueError("profile is not executable")
    # A frozen controller can execute only its verified last_stable, not a canary.
    values = checked.last_stable if checked.state == "frozen" else checked.current
    deadline = bound_at + timedelta(milliseconds=values.parent_deadline_ms)
    if ancestor_deadline is not None:
        if ancestor_deadline.tzinfo is None:
            raise ValueError("ancestor deadline must be aware")
        deadline = min(deadline, ancestor_deadline)
    return FrozenProfileSnapshot(
        profile_key_hash=checked.profile_key.key_hash,
        profile_version=checked.version,
        profile_hash=checked.profile_hash,
        values=values,
        bound_at=bound_at,
        parent_deadline_at=deadline,
    )
