"""Three pure shape checks. Synthetic materials/ports are NOT live C/provider proof."""
import json
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope, public_course_source_request
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import build_finite_candidate_spec, build_finite_generation_request
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_task_families import initial_slot_allocations
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.shared_pipeline_contracts import match_shared_request
from tests.grounding.test_public_course_binding import public_material
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request


def materials_for(target_id):
    """Synthetic coordinates rewritten exactly, never source-current authority."""
    target = get_finite_course_target(target_id)
    demand = public_course_demand(target_id)
    data = public_material().model_dump(mode="json")
    binding = data["binding"]
    coordinate = binding["evidence"][0]
    coordinate["subject_id"] = target.subject_id
    coordinate["binding"].update(scope=demand.scope.model_dump(mode="json"), demand_hash=demand.demand_hash)
    binding.update(target_id=target_id, target_definition_hash=target.definition_hash,
        course_goal_hash=canonical_hash({"goal": target.goal_text, "clauses": [c.definition_hash for c in target.clauses]}),
        demand=demand.model_dump(mode="json"))
    binding["binding_digest"] = canonical_hash({k: v for k, v in binding.items() if k != "binding_digest"})
    data["access_request"].update(scope=demand.scope.model_dump(mode="json"), demand_hash=demand.demand_hash)
    claim = data["exact_claims"][0]
    claim.update(binding=coordinate["binding"], scope=demand.scope.model_dump(mode="json"),
        execution_scope=public_course_execution_scope(target_id).model_dump(mode="json"),
        applicability=public_course_source_request(target_id)[2])
    return (PublicMaterialV2.model_validate_json(json.dumps(data)),)


def build(target_id, allocation, *, seed=0):
    base, _ = make_request()
    materials = materials_for(target_id)
    args = dict(target_id=target_id, variant_id=allocation.variant_id, seed=seed,
        item_key=f"finite-test.{target_id}.{allocation.variant_id.rsplit(':', 1)[1]}.s{seed}", version="v1",
        materials=materials, runtime_profile_hash=None if target_id == "python-kc-binding-v1" else "a"*64,
        scorer_version="static_exact_v1" if target_id == "python-kc-binding-v1" else "offline-declared-v1",
        assistance_policy_hash="b"*64, policy_version="fixture-v1", difficulty_profile=base.blueprint.difficulty_profile,
        publication_policy=base.blueprint.publication_policy)
    spec = build_finite_candidate_spec(**args)
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
        limits=base.limits, materials=materials)
    lease = JobLeaseV1(job_id=uuid4(), visibility="public", lease_owner="worker.finite.offline", generation=1,
        state_version=1, expires_at=base.profile.parent_deadline_at, parent_deadline=base.profile.parent_deadline_at,
        profile=base.profile)
    assert match_shared_request(request, spec.coverage_blueprint, lease).target_id == target_id
    assert request.demand_binding is None
    assert request.blueprint.source_references == request.public_template.source_references
    # Only a recording in-memory provider sees this; invalid empty output is
    # intentional so these checks never masquerade as generated/validated items.
    provider = SyntheticProvider({})
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert provider.calls == 1 and result.safe_reason == "invalid_candidate"
    prompt = json.loads(provider.messages[1]["content"])
    assert prompt["public_template"] == request.public_template.model_dump(mode="json")
    public_json = request.public_template.model_dump_json()
    for forbidden in ("standard_answer", "standard_query", "accepted_answers", "answer_explanation_markdown",
                      "private_cases", "expected_output", "correct_option_id", "option_facts", "fixture_hash",
                      "admission_eligible", "CURATED_FIXTURE", "REJECTED"):
        assert forbidden not in public_json
    return spec, request, args


def test_python_four_declared_families_and_distinct_guided_scope_public_only():
    target_id = "python-state-update-v1"
    allocations = initial_slot_allocations(target_id)
    built = [build(target_id, a) for a in allocations]
    specs = [entry[0] for entry in built]
    assert [s.python_goal.task_kind for s in specs] == ["accumulate", "refresh", "swap", "transfer", "refresh"]
    assert len({s.coverage_blueprint.blueprint_hash for s in specs[:4]}) == 1
    assert specs[-1].coverage_blueprint.scope.purpose.value == "remediation"
    assert specs[-1].coverage_blueprint.blueprint_hash != specs[1].coverage_blueprint.blueprint_hash
    assert specs[-1].public_template != specs[1].public_template
    assert specs[-1].python_goal.values != specs[1].python_goal.values
    assert specs[0].coverage_blueprint.scope.runtime_profile_id == "python-stdout-v1"
    assert "total = total + increase" not in specs[0].public_template.model_dump_json()
    changed, _, _ = build(target_id, allocations[0], seed=1)
    assert changed.family_definition_hash == specs[0].family_definition_hash
    assert changed.specification_hash != specs[0].specification_hash
    spec, request, args = built[0]
    forged = spec.model_copy(update={"public_template": spec.public_template.model_copy(update={"instruction_markdown": "Different goal"})})
    with pytest.raises(ValueError, match="finite_specification_mismatch"):
        build_finite_generation_request(forged, candidate_id=uuid4(), profile=request.profile,
            limits=request.limits, materials=args["materials"])


def test_sql_public_schema_dataset_and_common_scope_without_private_queries():
    target_id = "sqlite-predicate-order-v1"
    specs = [build(target_id, a)[0] for a in initial_slot_allocations(target_id)]
    assert [s.sql_target.task_kind for s in specs] == ["conjunction", "override_fallback", "exclusive", "keyset_after", "override_fallback"]
    assert len({s.coverage_blueprint.blueprint_hash for s in specs[:4]}) == 1
    for spec in specs:
        assert spec.coverage_blueprint.scope.runtime_profile_id == "sqlite-query-v1"
        assert spec.public_template.content.type == "sql_v2"
        assert spec.public_template.content.comparison == "ordered"
        assert spec.public_template.content.tables[0].name == "entries"
        assert spec.public_template.content.public_dataset.tables[0].rows
        assert spec.blueprint.runtime_profile_id == "sql_query_test"
    assert specs[4].allocation.slot == "remediation"
    assert specs[4].public_template.content.public_dataset != specs[1].public_template.content.public_dataset
    assert specs[4].coverage_blueprint.scope.purpose.value == "remediation"
    assert "表格由你填写" in specs[4].public_template.instruction_markdown


def test_kc_static_public_options_seed_is_not_family_independence():
    target_id = "python-kc-binding-v1"
    allocations = initial_slot_allocations(target_id)
    specs = [build(target_id, a)[0] for a in allocations]
    assert [s.allocation.family_id.rsplit(':', 1)[1] for s in specs] == ["trace", "diagnose", "repair", "counterexample", "diagnose"]
    assert len({s.coverage_blueprint.blueprint_hash for s in specs[:4]}) == 1
    for spec in specs:
        assert spec.python_goal is None and spec.sql_target is None and spec.blueprint.runtime_profile_id is None
        assert spec.coverage_blueprint.scope.runtime_profile_id == "static-exact-v1"
        assert spec.public_template.content.response_kind == "single_choice"
        assert tuple(o.option_id for o in spec.public_template.content.options) == ("choice-1", "choice-2", "choice-3", "choice-4")
    shifted, _, args = build(target_id, allocations[0], seed=1)
    assert shifted.family_definition_hash == specs[0].family_definition_hash
    assert shifted.public_template.content.options != specs[0].public_template.content.options
    assert specs[4].public_template.purpose.value == "remediation"
    assert "先填空表" in specs[4].public_template.content.prompt_markdown
    with pytest.raises(ValueError, match="static_runtime_lock_denied"):
        build_finite_candidate_spec(**{**args, "runtime_profile_hash": "a"*64})
