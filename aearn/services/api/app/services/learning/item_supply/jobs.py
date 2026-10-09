"""P3 item-supply job state contracts and fencing identities."""

from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field, model_validator
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot
from app.services.learning.item_supply.policies import RetryPolicyV1
from app.services.learning.item_supply.storage_contracts import StorageContract

JobStage = Literal[
    "generating",
    "validating",
    "reviewing",
    "investigating",
    "revising",
    "simulating",
    "admitting",
]
JOB_STAGES: tuple[JobStage, ...] = (
    "generating",
    "validating",
    "reviewing",
    "investigating",
    "revising",
    "simulating",
    "admitting",
)
JobState = Literal[
    "queued",
    "leased",
    "generating",
    "validating",
    "reviewing",
    "investigating",
    "revising",
    "simulating",
    "admitting",
    "retry_wait",
    "preparing",
    "blocked",
    "completed",
    "cancelled",
    "superseded",
]


class JobLeaseV1(StorageContract):
    job_id: UUID
    visibility: Literal["public", "private"]
    owner_id: UUID | None = None
    owner_epoch: int | None = Field(default=None, ge=1)
    lease_owner: str = Field(
        min_length=3, max_length=160, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    generation: int = Field(ge=1)
    state_version: int = Field(ge=1)
    expires_at: datetime
    parent_deadline: datetime
    profile: FrozenProfileSnapshot
    retry_policy: RetryPolicyV1 | None = None

    @model_validator(mode="after")
    def valid_lease(self) -> "JobLeaseV1":
        if (
            self.expires_at.tzinfo is None
            or self.parent_deadline.tzinfo is None
            or self.expires_at > self.parent_deadline
        ):
            raise ValueError("invalid lease deadline")
        if self.profile.parent_deadline_at != self.parent_deadline:
            raise ValueError("lease snapshot deadline mismatch")
        if self.visibility == "public" and (
            self.owner_id is not None or self.owner_epoch is not None
        ):
            raise ValueError("lease namespace mismatch")
        if self.visibility == "private" and (
            self.owner_id is None or self.owner_epoch is None
        ):
            raise ValueError("lease namespace mismatch")
        return self


class CheckpointV1(StorageContract):
    stage: JobStage
    attempt: int = Field(ge=1, le=1000)
    status: Literal["completed", "failed", "blocked"]
    receipt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    safe_reason: str = Field(
        min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$"
    )


def first_missing_stage(completed: set[str]) -> JobStage | None:
    return next((stage for stage in JOB_STAGES if stage not in completed), None)
