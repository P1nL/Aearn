"""Exact frozen private demand selection; canonical roots may have many demands."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1, SupplyScopeV1
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
from app.services.learning.item_supply.storage_contracts import checked_model


class GenerationDemandError(ValueError):
    """Stable safe codes only."""


def frozen_private_demand(
    conn: Connection[dict[str, Any]], *, lease: JobLeaseV1, scope_id: UUID,
    request: GenerationRequestV2,
) -> AssessmentSupplyDemandV1:
    """Caller first fences its live lease/scope in the same short transaction.

    New requests select the immutable id/hash frozen BEFORE provider IO. Legacy
    envelopes remain readable only when their scope has one unambiguous demand;
    they must never silently pick newest/oldest after another request arrives.
    """
    lease = checked_model(lease, JobLeaseV1)
    request = checked_model(request, GenerationRequestV2)
    if lease.visibility != "private" or lease.owner_id is None or lease.owner_epoch is None:
        raise GenerationDemandError("GENERATION_DEMAND_PRIVATE_REQUIRED")
    binding = request.demand_binding
    params: tuple[object, ...] = (lease.owner_id, lease.owner_epoch, scope_id)
    exact = ""
    if binding is not None:
        exact = " AND d.id=%s AND d.demand_hash=%s"
        params += (binding.demand_id, binding.demand_hash)
    rows = conn.execute(
        "SELECT d.id,d.snapshot_json,d.demand_hash,s.scope_hash,s.objective_hash,"
        "s.snapshot_json AS scope_json FROM tutor_item_supply_private_demands d "
        "JOIN tutor_item_supply_private_scopes s ON s.id=d.scope_id AND s.user_id=d.user_id AND s.epoch=d.epoch "
        "WHERE d.user_id=%s AND d.epoch=%s AND d.scope_id=%s" + exact + " LIMIT 2 FOR SHARE OF d,s",
        params,
    ).fetchall()
    if len(rows) != 1:
        raise GenerationDemandError("GENERATION_FROZEN_DEMAND_MISSING_OR_AMBIGUOUS")
    row = rows[0]
    scope = SupplyScopeV1.model_validate_json(json.dumps(row["scope_json"]))
    demand = AssessmentSupplyDemandV1.model_validate_json(json.dumps(row["snapshot_json"]))
    if (request.scope_hash != row["scope_hash"] or demand.scope != scope
            or demand.objective_hash != row["objective_hash"]
            or demand.demand_hash != row["demand_hash"]
            or demand.learner_ref != "user:" + str(lease.owner_id)):
        raise GenerationDemandError("GENERATION_DEMAND_IDENTITY_MISMATCH")
    obligation = CoverageObligationV1(
        blueprint_hash=demand.blueprint_hash, scope_hash=row["scope_hash"],
        objective_hash=demand.objective_hash, purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope), visibility="private",
        policy_version=demand.policy_version, owner_id=lease.owner_id,
    )
    root = conn.execute(
        "SELECT o.obligation_json,o.canonical_key,o.runtime_contract_hash "
        "FROM tutor_item_supply_private_jobs j JOIN tutor_item_supply_private_obligations o "
        "ON o.root_id=j.root_id AND o.user_id=j.user_id AND o.epoch=j.epoch AND o.scope_id=j.scope_id "
        "WHERE j.id=%s AND j.user_id=%s AND j.epoch=%s AND j.scope_id=%s FOR SHARE OF j,o",
        (lease.job_id, lease.owner_id, lease.owner_epoch, scope_id),
    ).fetchone()
    if (root is None or root["obligation_json"] != obligation.model_dump(mode="json")
            or root["canonical_key"] != obligation.canonical_key
            or root["runtime_contract_hash"] != obligation.runtime_contract_hash):
        raise GenerationDemandError("GENERATION_DEMAND_ROOT_MISMATCH")
    return demand
