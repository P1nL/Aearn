"""Narrow exact-demand regression; these doubles are not live admission proof."""
from uuid import uuid4

import pytest

from app.services.learning.item_supply.contracts import AssessmentSupplyDemandV1
from app.services.learning.item_supply.generation_contracts import GenerationDemandBindingV1, GenerationRequestV2
from app.services.learning.item_supply.generation_demand import GenerationDemandError, frozen_private_demand
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import CoverageObligationV1, derive_runtime_contract_hash
from tests.learning.test_item_supply_contracts import digest, make_scope
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from app.services.learning.item_supply.generation import generate_candidate


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Store:
    def __init__(self, demands, obligation):
        self.demands, self.obligation = demands, obligation

    def execute(self, sql, params):
        if "FROM tutor_item_supply_private_demands d" in sql:
            rows = self.demands
            if "AND d.id=%s AND d.demand_hash=%s" in sql:
                rows = [r for r in rows if (r["id"], r["demand_hash"]) == params[-2:]]
            return Rows(rows[:2])
        assert "FROM tutor_item_supply_private_jobs j" in sql
        return Rows([self.obligation])


def setup_case():
    request, _ = make_request()
    owner, scope_id = uuid4(), uuid4()
    scope = make_scope(visibility="private", owner_ref="user:" + str(owner))
    demands = [AssessmentSupplyDemandV1(
        demand_id=f"request-{i}", learner_ref=scope.owner_ref, scope=scope,
        objective_hash=digest("objective"), blueprint_hash=digest("blueprint"),
        matrix_hash=digest("matrix"), policy_version="supply-v1", input_revision=1,
    ) for i in (1, 2)]
    rows = [dict(id=uuid4(), snapshot_json=d.model_dump(mode="json"), demand_hash=d.demand_hash,
                 scope_hash=request.scope_hash, objective_hash=d.objective_hash,
                 scope_json=scope.model_dump(mode="json")) for d in demands]
    obligation = CoverageObligationV1(
        blueprint_hash=demands[0].blueprint_hash, scope_hash=request.scope_hash,
        objective_hash=demands[0].objective_hash, purpose=scope.purpose.value,
        runtime_contract_hash=derive_runtime_contract_hash(scope), visibility="private",
        policy_version=demands[0].policy_version, owner_id=owner,
    )
    store = Store(rows, dict(obligation_json=obligation.model_dump(mode="json"),
                            canonical_key=obligation.canonical_key,
                            runtime_contract_hash=obligation.runtime_contract_hash))
    lease = JobLeaseV1(job_id=uuid4(), visibility="private", owner_id=owner, owner_epoch=1,
                       lease_owner="worker.test", generation=1, state_version=1,
                       expires_at=request.profile.parent_deadline_at,
                       parent_deadline=request.profile.parent_deadline_at, profile=request.profile)
    payload = request.model_dump()
    payload["demand_binding"] = GenerationDemandBindingV1(demand_id=rows[1]["id"], demand_hash=rows[1]["demand_hash"])
    return store, lease, scope_id, GenerationRequestV2.model_validate(payload), demands


def test_exact_second_demand_not_scope_uniqueness_or_latest():
    store, lease, scope, request, demands = setup_case()
    assert frozen_private_demand(store, lease=lease, scope_id=scope, request=request) == demands[1]
    store.demands.reverse()
    assert frozen_private_demand(store, lease=lease, scope_id=scope, request=request) == demands[1]


@pytest.mark.parametrize("corruption", ["hash", "root", "legacy_multiple"])
def test_wrong_binding_or_root_and_ambiguous_legacy_fail_closed(corruption):
    store, lease, scope, request, _ = setup_case()
    payload = request.model_dump()
    if corruption == "hash":
        payload["demand_binding"]["demand_hash"] = digest("wrong")
    elif corruption == "legacy_multiple":
        payload["demand_binding"] = None
    else:
        store.obligation["canonical_key"] = digest("other-root")
    with pytest.raises(GenerationDemandError):
        frozen_private_demand(store, lease=lease, scope_id=scope,
                              request=GenerationRequestV2.model_validate(payload))


def test_private_demand_locator_never_enters_provider_prompt():
    request, source = make_request()
    binding = GenerationDemandBindingV1(demand_id=uuid4(), demand_hash=digest("private-demand"))
    request = GenerationRequestV2.model_validate({**request.model_dump(), "demand_binding": binding})
    provider = SyntheticProvider(source)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged"
    messages = str(provider.messages)
    assert str(binding.demand_id) not in messages and binding.demand_hash not in messages
