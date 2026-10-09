"""Offline V3 producer/validator checks; no provider, OS, PG or admission proof."""
import hashlib
import json
from uuid import uuid4

import pytest

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import (
    FACTORY_VERSION, FLEXIBLE_FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2,
    FiniteSlotAllocationV2, allocation_from_blueprint, build_finite_candidate_spec,
    build_finite_generation_request, build_finite_slot_allocation, check_finite_public_spec,
    check_finite_source_spec, resolve_finite_slot_allocation,
)
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_review_descriptor import finite_review_context, finite_scoring_descriptor
from app.services.learning.item_supply.finite_task_ambiguity import build_finite_ambiguity_plan
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.finite_targets.python_kc import _spec, _truth
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.finite_targets.sqlite_predicates import sqlite_oracle, sqlite_private_fixture
from app.services.learning.item_supply.generation import generate_candidate
from app.services.learning.item_supply.generation_contracts import GenerationRequestV2
from tests.learning.test_item_supply_finite_candidate_validation import _context, _source
from tests.learning.test_item_supply_finite_public_spec_v2 import _args
from tests.learning.test_item_supply_generation import SyntheticAuthority, SyntheticProvider, make_request
from tests.learning.test_item_supply_v2_execution_review import binding_for

TARGETS = ("python-state-update-v1", "sqlite-predicate-order-v1", "python-kc-binding-v1")


def flexible_spec(target, *, slot="practice", slot_index=1, seed=1, family_index=0):
    old, materials = _context(target)
    allocation = build_finite_slot_allocation(target_id=target,
        family_id=families_for_course(target)[family_index].family_id, slot=slot, slot_index=slot_index)
    args = _args(old, materials)
    args.update(variant_id=allocation.variant_id, item_key=f"flexible.{target}.{slot}.{slot_index}.{seed}", seed=seed)
    return build_finite_candidate_spec(**args, public_spec_version=FLEXIBLE_FACTORY_VERSION,
        allocation=allocation), materials


def proposed_source(spec):
    """Test-only authored private output, never supplied to an author prompt."""
    if spec.python_goal is not None:
        goal = spec.python_goal
        private = dict(type="code", standard_answer=_programs(goal)[2],
            tests=[dict(id=kind, case_type=kind, order_index=i, input_json={},
                expected_output_json={"stdout": python_state_expected_stdout(goal)})
                for i, kind in enumerate(("visible", "hidden"))],
            score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0))
    elif spec.sql_target is not None:
        target = spec.sql_target
        datasets = (spec.public_template.content.public_dataset, sqlite_private_fixture(target).private_cases[0].dataset)
        private = dict(type="sql_v2", standard_query=sqlite_private_fixture(target).equivalent_queries[0],
            tests=[dict(id=f"case-{i}", case_type="visible" if i == 0 else "hidden", order_index=i,
                dataset=data.model_dump(mode="json"), expected_output=sqlite_oracle(target, data).model_dump(mode="json"))
                for i, data in enumerate(datasets)],
            score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0))
    else:
        kind = spec.allocation.family_id.rsplit(":", 1)[1]
        guided = spec.allocation.slot == "remediation"
        question, truth = _spec(kind, guided), _truth(kind, guided)
        accepted = {o.label: (o.rhs, o.saved, o.observation, o.reason) == truth for o in question.options}
        options = spec.public_template.content.options
        answer = next(o.option_id for o in options if accepted[o.label])
        private = dict(type="knowledge_check", accepted_answers=[answer], answer_explanation_markdown=question.explanation,
            tests=[dict(id="option." + o.option_id, case_type="visible" if i == 0 else "hidden", order_index=i,
                input_json={"answer": o.option_id}, expected_output_json={"accepted": accepted[o.label]})
                for i, o in enumerate(options)],
            score_policy=dict(kind="static_exact", policy_version="static_exact_v1", threshold=1.0))
    source = _source(spec, private)
    return source.model_copy(update={"public": source.public.model_copy(update={
        "title": "一步一步核对本题的状态与条件",
        "instruction_markdown": "请先阅读任务，再独立作答。\n\n" + source.public.instruction_markdown + "\n\n提交前核对题目要求。"})})


@pytest.mark.parametrize("target", TARGETS)
def test_v3_factory_generation_and_validation_bind_actual_prose_without_admission(target):
    spec, materials = flexible_spec(target)
    source = proposed_source(spec)
    original = source.model_dump_json()
    check_finite_public_spec(source.public, spec)
    # Use the pre-existing 8000-character DTO limit, no new presentation quota.
    check_finite_public_spec(source.public.model_copy(update={"instruction_markdown":
        "阅读题目后独立作答。" * 230 + source.public.instruction_markdown}), spec)
    check_finite_source_spec(source, spec)
    base, _ = make_request()
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
        limits=base.limits, materials=materials)
    request = GenerationRequestV2.model_validate_json(request.model_dump_json())
    assert allocation_from_blueprint(request.blueprint, target) == (spec.allocation, spec.seed)
    provider = SyntheticProvider(source.model_dump(mode="json"))
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.source == source and provider.calls == 1
    assert result.receipt.source_hash == source.source_hash and result.receipt.content_hash == source.content_hash
    system = provider.messages[0]["content"]
    assert "changing ONLY public.title and public.instruction_markdown" in system
    assert "All public prose/title must be consistent with the structured goal" in system
    assert "Do not leak correct options" in system and "all six item-review roles remain required" in system
    schema = json.loads(system.split("AUTHORITATIVE OUTPUT JSON SCHEMA:\n", 1)[1])
    assert "const" not in schema["properties"]["public"]
    pinned = schema["properties"]["public"]["allOf"][1]["properties"]
    assert set(pinned) == set(source.public.model_dump()) - {"title", "instruction_markdown"}
    user_prompt = provider.messages[1]["content"]
    assert "standard_answer" not in user_prompt and "accepted_answers" not in user_prompt and "standard_query" not in user_prompt
    inputs = prepare_finite_candidate_validation(result.source, spec=spec, materials=materials)
    assert inputs.public_task_hash == source.public.public_hash != spec.public_template.public_hash
    assert inputs.source_hash == source.source_hash and inputs.specification_hash == spec.specification_hash
    assert not inputs.publication_enabled and inputs.family_independence_status == "pending"
    ambiguity = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
    assert ambiguity.public_task_hash == source.public.public_hash
    if target == "python-kc-binding-v1":
        assert inputs.static_facts.execution_status == "not_run_static" and not inputs.static_facts.admission_eligible
        with finite_review_context(source, spec=spec, materials=materials):
            descriptor = finite_scoring_descriptor(source, inputs.static_facts.validation, binding_for(source))
            assert descriptor["actual_public_task_hash"] == source.public.public_hash
            assert descriptor["public_template_hash"] == source.public.public_hash
            assert descriptor["server_specification_template_hash"] == spec.public_template.public_hash
            assert "all six roles" in descriptor["presentation_review_boundary"]
    else:
        assert "real_sealed_candidate_execution_pending" in inputs.pending_boundaries
    assert source.model_dump_json() == original  # compiler never rewrites staged bytes


@pytest.mark.parametrize("target", TARGETS)
def test_three_same_family_training_slots_reachable_with_checked_allocation(target):
    built = [flexible_spec(target, slot=slot, slot_index=index, seed=seed,
                          family_index=1 if target == "python-kc-binding-v1" else 0) for slot, index, seed in
             (("practice", 1, 1), ("practice", 2, 2), ("remediation", 1, 3))]
    specs = [s for s, _ in built]
    assert len({s.allocation.family_id for s in specs}) == 1
    assert len({s.public_template.public_hash for s in specs}) == 3
    for spec, materials in built:
        checked = type(spec).model_validate_json(spec.model_dump_json())
        assert type(checked.allocation) is FiniteSlotAllocationV2
        assert checked.allocation.definition_hash == spec.allocation.definition_hash
        prepared = prepare_finite_candidate_validation(proposed_source(checked), spec=checked, materials=materials)
        assert prepared.family_independence_status == "pending"
        old, old_materials = _context(target)
        with pytest.raises(ValueError, match="finite_allocation_unregistered"):
            build_finite_candidate_spec(**{**_args(old, old_materials), "variant_id": spec.allocation.variant_id},
                allocation=spec.allocation)  # cannot silently relax V1


@pytest.mark.parametrize("target", TARGETS)
def test_v3_structured_content_and_goal_changes_fail_before_or_after_author(target):
    spec, materials = flexible_spec(target)
    source = proposed_source(spec)
    base, _ = make_request()
    request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile, limits=base.limits, materials=materials)
    changed = source.model_dump(mode="json")
    content = changed["public"]["content"]
    if target == "python-state-update-v1":
        content["starter_code"] += "\ntotal = 99"
    elif target == "sqlite-predicate-order-v1":
        content["public_dataset"]["tables"][0]["rows"][0][1] = "changed-task-data"
    else:
        content["options"][0]["label"] += "（改变了选项）"
    altered = LearningItemSourceV1.model_validate_json(json.dumps(changed))
    with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
        prepare_finite_candidate_validation(altered, spec=spec, materials=materials)
    denied = generate_candidate(request, provider=SyntheticProvider(changed), source_authority=SyntheticAuthority(), enabled=True)
    assert denied.safe_reason == "candidate_mismatch" and denied.source is None
    # Removing/changing the authoritative core cannot be rescued by neutral prose.
    public = source.public.model_copy(update={"instruction_markdown": source.public.instruction_markdown.replace(
        "finite-public-task-v3:start", "different-goal:start")})
    with pytest.raises(ValueError, match="finite_public_task_core_mismatch"):
        check_finite_public_spec(public, spec)
    bad_request = request.model_copy(update={"public_template": public})
    provider, authority = SyntheticProvider(changed), SyntheticAuthority()
    denied = generate_candidate(bad_request, provider=provider, source_authority=authority, enabled=True)
    assert denied.safe_reason == "invalid_request" and provider.calls == authority.calls == 0
    with pytest.raises(ValueError):
        prepare_finite_candidate_validation(source, spec=spec.model_copy(update={"seed": spec.seed + 1}), materials=materials)
    with pytest.raises(ValueError):
        check_finite_public_spec(source.public, spec.model_copy(update={"family_definition_hash": "0" * 64}))
    if spec.python_goal is not None:
        altered_goal = spec.python_goal.model_copy(update={"values": {**spec.python_goal.values, "initial": 99}})
        with pytest.raises(ValueError):
            prepare_finite_candidate_validation(source, spec=spec.model_copy(update={"python_goal": altered_goal}), materials=materials)
    elif spec.sql_target is not None:
        changed_schema = source.model_dump(mode="json")
        changed_schema["public"]["content"]["tables"][0]["columns"][3]["data_type"] = "REAL"
        with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
            prepare_finite_candidate_validation(LearningItemSourceV1.model_validate_json(json.dumps(changed_schema)), spec=spec, materials=materials)
        altered_goal = spec.sql_target.model_copy(update={"min_score": spec.sql_target.min_score + 1})
        with pytest.raises(ValueError):
            prepare_finite_candidate_validation(source, spec=spec.model_copy(update={"sql_target": altered_goal}), materials=materials)


@pytest.mark.parametrize("target", TARGETS)
def test_v3_nonpresentation_public_keys_and_foreign_family_forgery_denied(target):
    spec, _ = flexible_spec(target)
    source = proposed_source(spec)
    public = source.public.model_copy(update={"remediation_item_key": "unreviewed.item"})
    with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
        check_finite_public_spec(public, spec)
    public = source.public.model_copy(update={"instruction_markdown": source.public.instruction_markdown + spec.public_template.instruction_markdown})
    with pytest.raises(ValueError, match="finite_public_task_core_mismatch"):
        check_finite_public_spec(public, spec)
    with pytest.raises(ValueError, match="finite_explicit_allocation_invalid"):
        build_finite_slot_allocation(target_id=target, family_id="python-state-update-v1:unsupported", slot="practice")
    with pytest.raises(ValueError):
        resolve_finite_slot_allocation(target_id=target, variant_id=spec.allocation.variant_id,
            public_spec_version=FLEXIBLE_FACTORY_VERSION,
            allocation=spec.allocation.model_copy(update={"family_definition_hash": "0" * 64}))
    with pytest.raises(ValueError):
        build_finite_slot_allocation(target_id=target, family_id=spec.allocation.family_id, slot="practice", slot_index=3)


def test_legacy_default_exact_bytes_and_python_v2_strict_presentation():
    legacy = [_context("python-state-update-v1", slot=i) for i in range(5)]
    legacy += [_context(t) for t in ("sqlite-predicate-order-v1", "python-kc-binding-v1")]
    specs = [spec for spec, _ in legacy]
    assert hashlib.sha256("".join(s.model_dump_json() for s in specs).encode()).hexdigest() == (
        "5a60a1f4583acfcabaae32c14f0dfe5228cf758eef2dd76b9fd2ba14e7ffbef5")
    assert canonical_hash([s.model_dump(mode="json") for s in specs]) == "01fdbacf3c698b92bc257a3d89a3451b193abe4fca2138951bb28fcda4cc6428"
    for old, materials in legacy:
        assert build_finite_candidate_spec(**_args(old, materials), public_spec_version=FACTORY_VERSION).model_dump_json() == old.model_dump_json()
        with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
            check_finite_public_spec(proposed_source(old).public, old)
    old, materials = legacy[0]
    v2 = build_finite_candidate_spec(**_args(old, materials), public_spec_version=PYTHON_FACTORY_VERSION_V2)
    check_finite_public_spec(v2.public_template, v2)
    with pytest.raises(ValueError, match="finite_candidate_specification_mismatch"):
        check_finite_public_spec(proposed_source(v2).public, v2)


@pytest.mark.parametrize("target", TARGETS)
def test_every_supported_family_reaches_each_compatible_v3_slot(target):
    """Family declaration is task semantics, not a four-family supply quota."""
    for family_index, family in enumerate(families_for_course(target)):
        for slot, slot_index in (("practice", 1), ("practice", 2),
                                 ("assessment", 1), ("assessment", 2), ("remediation", 1)):
            if target == "python-kc-binding-v1" and slot == "remediation" and family.task_kind != "diagnose":
                with pytest.raises(ValueError, match="finite_explicit_allocation_mismatch"):
                    flexible_spec(target, slot=slot, slot_index=slot_index, family_index=family_index)
                continue
            spec, materials = flexible_spec(target, slot=slot, slot_index=slot_index, family_index=family_index)
            source = proposed_source(spec)
            base, _ = make_request()
            request = build_finite_generation_request(spec, candidate_id=uuid4(), profile=base.profile,
                limits=base.limits, materials=materials)
            result = generate_candidate(request, provider=SyntheticProvider(source.model_dump(mode="json")),
                source_authority=SyntheticAuthority(), enabled=True)
            assert result.state == "staged", (target, family.task_kind, slot, slot_index, result.safe_reason)
            prepared = prepare_finite_candidate_validation(result.source, spec=spec, materials=materials)
            ambiguity = build_finite_ambiguity_plan(result.source, spec=spec, inputs=prepared)
            assert ambiguity.public_task_hash == source.public.public_hash
            assert prepared.family_independence_status == "pending"
