"""Default-off, owner-scoped claim/reservation entrypoint; never runs handlers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.core.config import Settings
from app.services.learning.item_supply.budget import ItemSupplyBudgetRepository
from app.services.learning.item_supply.jobs import JOB_STAGES, JobLeaseV1, JobStage
from app.services.learning.item_supply.policies import (
    ResourceAmounts,
    SupplyRuntimeError,
)
from app.services.learning.item_supply.repository import ItemSupplyRuntimeRepository
from app.services.learning.item_supply.storage_contracts import checked_model


@dataclass(frozen=True)
class OwnerPartition:
    visibility: Literal["public", "private"]
    root_id: UUID
    user_id: UUID | None = None
    epoch: int | None = None


@dataclass(frozen=True)
class SchedulerBatch:
    state: str
    leases: tuple[JobLeaseV1, ...] = ()
    reservations: tuple[UUID, ...] = ()


def claim_bounded(
    *,
    settings: Settings,
    repository: ItemSupplyRuntimeRepository,
    owner: OwnerPartition | None,
    worker_id: str,
    now: datetime,
    limit: int,
    lease_seconds: int,
    registered_handlers: frozenset[JobStage],
    budget: ItemSupplyBudgetRepository | None = None,
    stage_budgets: Mapping[JobStage, ResourceAmounts] | None = None,
) -> SchedulerBatch:
    if not (
        settings.learning_item_supply_enabled
        and settings.learning_item_generation_enabled
        and settings.learning_item_supply_scheduler_enabled
    ):
        return SchedulerBatch("disabled")
    if owner is None:
        return SchedulerBatch("owner_required")
    if (
        owner.visibility not in {"public", "private"}
        or (
            owner.visibility == "private"
            and (
                owner.user_id is None or type(owner.epoch) is not int or owner.epoch < 1
            )
        )
        or (
            owner.visibility == "public"
            and (owner.user_id is not None or owner.epoch is not None)
        )
    ):
        return SchedulerBatch("invalid_owner")
    if type(limit) is not int or not 1 <= limit <= 16:
        return SchedulerBatch("invalid_limit")
    if budget is None or stage_budgets is None or set(stage_budgets) != set(JOB_STAGES):
        return SchedulerBatch("budget_required")
    if budget.conn is not repository.conn:
        raise SupplyRuntimeError("CALLER_TRANSACTION_MISMATCH")
    plans = {
        stage: checked_model(value, ResourceAmounts)
        for stage, value in stage_budgets.items()
    }
    if any(not amount.positive() for amount in plans.values()):
        return SchedulerBatch("budget_required")
    leases: list[JobLeaseV1] = []
    reservations: list[UUID] = []
    for _ in range(limit):
        lease = repository.claim(
            root_id=owner.root_id,
            lease_owner=worker_id,
            now=now,
            lease_seconds=lease_seconds,
            visibility=owner.visibility,
            user_id=owner.user_id,
            epoch=owner.epoch,
        )
        if lease is None:
            break
        stage = repository.next_stage(lease)
        if stage is None or stage not in registered_handlers:
            repository.mark_preparing(lease, reason="handler_not_registered", now=now)
            continue
        # Reserve ALL missing mandatory stages, not just a generator call that
        # could consume the entire envelope and strand review/execution/delivery.
        remaining = JOB_STAGES[JOB_STAGES.index(stage) :]
        totals = {
            kind: sum(plans[item].as_dict()[kind] for item in remaining)
            for kind in plans[remaining[0]].as_dict()
        }
        amount = ResourceAmounts.model_validate(totals, strict=True)
        result = budget.reserve(
            lease=lease,
            reservation_key=f"pipeline.{lease.generation}",
            amounts=amount,
            now=now,
        )
        if not result.allowed:
            repository.mark_preparing(lease, reason="budget_unavailable", now=now)
            continue
        assert result.reservation_id is not None
        leases.append(lease)
        reservations.append(result.reservation_id)
    return SchedulerBatch(
        "claimed" if leases else "preparing", tuple(leases), tuple(reservations)
    )
