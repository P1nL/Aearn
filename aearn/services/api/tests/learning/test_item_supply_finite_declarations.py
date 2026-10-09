"""Five pure declaration checks: no external IO, candidates or authority issuance."""
import ast
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.services.learning.item_supply import finite_course_targets as course_module
from app.services.learning.item_supply.finite_course_targets import (
    finite_course_targets,
    get_finite_course_target,
)
from app.services.learning.item_supply.finite_targets.contracts import (
    CLAUSE_IDS,
    TASK_KINDS,
    FiniteCourseTargetV1,
    FiniteFamilyPairDeclarationV1,
    FiniteSlotAllocationV1,
    FiniteTaskFamilyV1,
)
from app.services.learning.item_supply.finite_task_families import (
    declared_family_pair_matrix,
    families_for_course,
    initial_slot_allocations,
)


def test_exact_closed_lookup_and_complete_clause_references() -> None:
    targets = finite_course_targets()
    assert tuple(target.target_id for target in targets) == tuple(TASK_KINDS)
    assert len(targets) == 3
    for target in targets:
        assert get_finite_course_target(target.target_id) is target
        assert tuple(clause.clause_id for clause in target.clauses) == CLAUSE_IDS[target.target_id]
        families = families_for_course(target.target_id)
        assert tuple(family.task_kind for family in families) == TASK_KINDS[target.target_id]
        assert len(families) == 4
        for family in families:
            assert family.family_id == f"{target.target_id}:{family.task_kind}"
            assert family.target_definition_hash == target.definition_hash
            assert family.assessment_definition_hash == target.assessment.definition_hash
            assert family.clause_refs == target.clause_refs
        for alias in (target.display_id, target.goal_text, target.target_id.upper(),
                      f" {target.target_id}", target.required_capabilities[0]):
            with pytest.raises(KeyError):
                get_finite_course_target(alias)
            with pytest.raises(KeyError):
                families_for_course(alias)
    assert targets[0].assessment.definition_hash != targets[2].assessment.definition_hash


def test_each_clause_has_two_two_one_intents_and_distinct_remediation_variant() -> None:
    for target in finite_course_targets():
        allocations = initial_slot_allocations(target.target_id)
        families = families_for_course(target.target_id)
        assert len(allocations) == len({allocation.variant_id for allocation in allocations}) == 5
        for clause in target.clause_refs:
            assert Counter(allocation.slot for allocation in allocations
                           if clause in allocation.clause_refs) == {
                "practice": 2, "assessment": 2, "remediation": 1,
            }
        assert tuple(allocation.family_id for allocation in allocations) == (
            families[0].family_id, families[1].family_id, families[2].family_id,
            families[3].family_id, families[1].family_id,
        )
        practice, remedial = allocations[1], allocations[4]
        assert practice.definition_hash != remedial.definition_hash
        assert practice.family_definition_hash == remedial.family_definition_hash
        assert remedial.purpose == "remediation"
        assert remedial.binding_requirement == "purpose_child_scope"
        assert all(allocation.status == "declaration_pending" for allocation in allocations)
        assert not any(allocation.purpose == "transfer_check" for allocation in allocations)
        invalid = remedial.model_copy(update={"purpose": target.assessment.purpose})
        with pytest.raises(ValidationError):
            _ = invalid.definition_hash


def test_six_pairs_remain_pending_even_with_different_or_equal_signatures() -> None:
    for target in finite_course_targets():
        pairs = declared_family_pair_matrix(target.target_id)
        families = families_for_course(target.target_id)
        assert len(pairs) == len({(pair.left_family_id, pair.right_family_id) for pair in pairs}) == 6
        assert (pairs[-1].left_family_id, pairs[-1].right_family_id) == (
            families[2].family_id, families[3].family_id,
        )
        for pair in pairs:
            assert pair.status == "declaration_pending"
            assert len(pair.required_evidence) == 5
            assert "lawful_transfer_counterexamples" in pair.required_evidence
            assert "verified" not in pair.model_dump()
        identical_structure = FiniteFamilyPairDeclarationV1.model_validate(pairs[0].model_copy(
            update={"right_structure_signature": pairs[0].left_structure_signature},
        ))
        assert identical_structure.status == "declaration_pending"
        assert len({family.structure_signature for family in families}) == 4  # definitions only
        assert all(family.executable_fixture_hash is None for family in families)
        assert target.assessment.executable_profile_hash is None
    assert get_finite_course_target("python-kc-binding-v1").assessment.runtime_profile_id is None


def test_immutable_bounded_strict_hashes_revalidate_and_separate_domains() -> None:
    for target in finite_course_targets():
        assert FiniteCourseTargetV1.model_validate_json(target.model_dump_json()) == target
        assert FiniteCourseTargetV1.model_validate_json(target.model_dump_json()).definition_hash == target.definition_hash
        family = families_for_course(target.target_id)[0]
        assert FiniteTaskFamilyV1.model_validate_json(family.model_dump_json()).definition_hash == family.definition_hash
        allocation = initial_slot_allocations(target.target_id)[0]
        assert FiniteSlotAllocationV1.model_validate_json(allocation.model_dump_json()) == allocation
        assert len({family.definition_hash, family.structure_signature, family.public_task_hash,
                    family.fixture_specification_hash, target.definition_hash,
                    target.assessment.definition_hash, allocation.definition_hash}) == 7
        with pytest.raises(ValidationError):
            target.goal_text = "mutated"
        for update in ({"verified": True}, {"status": "ready"}, {"goal_text": "x" * 1201},
                       {"clauses": list(target.clauses)}, {"clauses": target.clauses[:2]},
                       {"definition_version": "unversioned"}):
            with pytest.raises(ValueError):
                _ = target.model_copy(update=update).definition_hash
        with pytest.raises(ValueError):
            _ = target.model_copy(update={
                "assessment": target.assessment.model_copy(update={"executable_profile_hash": "a" * 64}),
            }).definition_hash
        revised = FiniteTaskFamilyV1.model_validate(family.model_copy(update={
            "public_task": family.public_task + "（新的公开说明）",
        }))
        assert revised.definition_hash != family.definition_hash
        assert revised.public_task_hash != family.public_task_hash
        assert revised.structure_signature == family.structure_signature  # prose is not independence


def test_declaration_import_graph_has_no_runtime_or_language_plugin_dependency() -> None:
    root = Path(course_module.__file__).parent
    paths = (root / "finite_course_targets.py", root / "finite_task_families.py",
             root / "finite_targets" / "contracts.py", root / "finite_targets" / "__init__.py")
    allowed = {"__future__", "hashlib", "json", "types", "typing", "itertools", "pydantic",
               "finite_course_targets", "finite_targets.contracts"}
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module in allowed
