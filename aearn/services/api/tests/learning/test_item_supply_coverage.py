"""Pure synthetic coverage tests: no real inventory/source/runtime claims."""
from dataclasses import replace
from datetime import timedelta

import pytest

from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CandidateAuthorityV1, ClauseCoverageV1,
    MinimumCoverageV1, ObjectiveClauseV1, ObjectiveCoverageProofV1, SourceAuthorizationFactsV1,
    SupplyScopeV1,
)
from app.services.learning.item_bank.contracts import LearningItemInteraction, LearningItemKind, LearningItemPurpose
from app.services.learning.item_supply.coverage import evaluate_supply
from app.services.runners.language_capabilities import LANGUAGE_CAPABILITIES
from app.services.learning.item_supply.exposure import ExposureRecordV1, ExposureSnapshotV1
from tests.learning.test_item_supply_contracts import (
    NOW, digest, make_blueprint, make_demand, make_scope, synthetic_candidate, synthetic_inventory,
)


def exposure_for(demand: AssessmentSupplyDemandV1) -> ExposureSnapshotV1:
    return ExposureSnapshotV1(learner_ref=demand.learner_ref, scope_hash=demand.scope.scope_hash)


def test_synthetic_exact_coverage_is_not_live_readiness() -> None:
    blueprint = make_blueprint(dependent=True)
    demand = make_demand(blueprint)
    result = evaluate_supply(demand, blueprint, synthetic_inventory(blueprint), exposure_for(demand), now=NOW)
    assert result.status == "ready_exact"
    assert len(result.selected_handles) == 5 and result.gaps == ()
    assert result.demand_hash == demand.demand_hash


@pytest.mark.parametrize("field,value,reason", [
    ("published", False, "not_published"), ("materialized", False, "not_materialized"),
    ("runtime_available", False, "runtime_unavailable"), ("proof", None, "proof_missing"),
    ("current_authorization", None, "authorization_missing"),
    ("item_handle", "li:" + digest("other-item"), "proof_mismatch"),
    ("content_hash", digest("other-content"), "proof_mismatch"),
    ("candidate_family_id", "other-family", "proof_mismatch"),
    ("source_ref", "other-source", "proof_mismatch"),
    ("source_version", "2.0", "proof_mismatch"),
    ("source_usage", "supplementary_explanation", "proof_mismatch"),
    ("evidence_hash", digest("other-evidence"), "proof_mismatch"),
    ("objective_hash", digest("other-objective"), "identity_mismatch"),
    ("matrix_hash", digest("other-matrix"), "identity_mismatch"),
    ("policy_version", "supply-v2", "identity_mismatch"),
    ("blueprint_hash", digest("other-blueprint"), "identity_mismatch"),
])
def test_actual_item_fact_must_match_proof(field: str, value: object, reason: str) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    bad = CandidateAuthorityV1.model_validate({**items[0].model_dump(), field: value})
    result = evaluate_supply(demand, blueprint, (bad, *items[1:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and reason in result.reasons


@pytest.mark.parametrize("field,value", [
    ("scope_hash", digest("other-scope")), ("scorer_version", "scorer-v2"),
    ("runtime_profile_id", "other-runtime"), ("runtime_profile_hash", digest("other-runtime")),
    ("assessment_contract_version", "gate-v2"), ("assistance_policy_hash", digest("other-assistance")),
    ("authorization_hash", digest("revoked-hash")),
    ("authorization_checked_at", NOW - timedelta(minutes=1)),
    ("authorization_valid_until", NOW + timedelta(minutes=1)),
])
def test_proof_coordinates_are_exact(field: str, value: object) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    assert items[0].proof is not None
    proof = ObjectiveCoverageProofV1.model_validate({**items[0].proof.model_dump(), field: value})
    bad = items[0].model_copy(update={"proof": proof})
    result = evaluate_supply(demand, blueprint, (bad, *items[1:]), exposure_for(demand), now=NOW)
    assert result.status != "ready_exact"
    assert "proof_mismatch" in result.reasons or "authorization_mismatch" in result.reasons


@pytest.mark.parametrize("field,value", [
    ("authorization_hash", digest("current-successor")), ("source_ref", "other-source"),
    ("source_version", "2.0"), ("source_usage", "main_teaching"),
    ("scope_hash", digest("other-scope")), ("objective_hash", digest("other-objective")),
    ("content_hash", digest("other-content")), ("evidence_hash", digest("other-material")),
])
def test_current_authorization_is_not_a_boolean(field: str, value: object) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    assert items[0].current_authorization is not None
    auth = SourceAuthorizationFactsV1.model_validate({**items[0].current_authorization.model_dump(), field: value})
    result = evaluate_supply(demand, blueprint, (items[0].model_copy(update={"current_authorization": auth}),
                             *items[1:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "authorization_mismatch" in result.reasons


def test_stale_future_and_inactive_facts_cannot_count() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    for now in (NOW + timedelta(hours=1), NOW - timedelta(hours=2)):
        result = evaluate_supply(demand, blueprint, items, exposure_for(demand), now=now)
        assert result.status == "stale" and result.selected_handles == ()
    assert items[0].current_authorization is not None
    auth = items[0].current_authorization.model_copy(update={"active": False})
    result = evaluate_supply(demand, blueprint, (items[0].model_copy(update={"current_authorization": auth}),
                             *items[1:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "authorization_inactive" in result.reasons


@pytest.mark.parametrize("field,value", [
    ("objective_hash", digest("same-key-other-objective")), ("blueprint_hash", digest("other-blueprint")),
    ("matrix_hash", digest("other-matrix")), ("policy_version", "supply-v2"),
    ("scope", make_scope(course_version="2.0")),
])
def test_demand_mismatch_rejects_all(field: str, value: object) -> None:
    blueprint = make_blueprint()
    demand = AssessmentSupplyDemandV1.model_validate({**make_demand(blueprint).model_dump(), field: value})
    result = evaluate_supply(demand, blueprint, synthetic_inventory(blueprint), exposure_for(demand), now=NOW)
    assert result.status == "gap" and result.selected_handles == ()


def test_exact_clause_mapping_not_titles_or_keys() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    mapping = (ClauseCoverageV1(clause_id="functions", clause_hash=digest("wrong-objective")),)
    assert items[0].proof is not None
    bad = items[0].model_copy(update={"clauses": mapping, "proof": items[0].proof.model_copy(update={"clauses": mapping})})
    result = evaluate_supply(demand, blueprint, (bad, *items[1:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "proof_mismatch" in result.reasons


def test_replay_item_content_and_family_do_not_inflate_independence() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    # Repeat exactly one assessment and omit the other.
    result = evaluate_supply(demand, blueprint, (*items[:3], items[2], items[4]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "duplicate_candidate" in result.reasons
    for field in ("candidate_family_id", "content_hash"):
        assert items[3].proof is not None and items[3].current_authorization is not None
        value = getattr(items[2], field)
        updates = {field: value, "proof": items[3].proof.model_copy(update={field: value})}
        if field == "content_hash":
            updates["current_authorization"] = items[3].current_authorization.model_copy(update={field: value})
        bad = items[3].model_copy(update=updates)
        result = evaluate_supply(demand, blueprint, (*items[:3], bad, items[4]), exposure_for(demand), now=NOW)
        assert result.status == "gap" and "duplicate_candidate" in result.reasons


def test_unmet_prerequisite_prevents_effective_child_coverage() -> None:
    blueprint = make_blueprint(dependent=True)
    demand = make_demand(blueprint)
    child = blueprint.clauses[1]
    mapping = (ClauseCoverageV1(clause_id=child.clause_id, clause_hash=child.clause_hash),)
    items = tuple(item.model_copy(update={"clauses": mapping, "proof": item.proof.model_copy(update={"clauses": mapping})})
                  for item in synthetic_inventory(blueprint) if item.proof is not None)
    result = evaluate_supply(demand, blueprint, items, exposure_for(demand), now=NOW)
    assert result.status == "gap" and result.selected_handles == ()
    assert all(gap.available == 0 for gap in result.gaps)
    assert "prerequisite_gap" in result.reasons


@pytest.mark.parametrize("kind", ["attempted", "hint", "direct_answer"])
def test_assessment_exposure_does_not_invalidate_ordinary_practice(kind: str) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    records = tuple(ExposureRecordV1.model_validate(dict(
        event_id=f"event-{index}", learner_ref=demand.learner_ref, scope_hash=demand.scope.scope_hash,
        item_handle=item.item_handle, candidate_family_id=item.candidate_family_id,
        kind=kind, occurred_at=NOW,
    )) for index, item in enumerate(items[:3]))
    exposure = ExposureSnapshotV1(learner_ref=demand.learner_ref, scope_hash=demand.scope.scope_hash, records=records)
    result = evaluate_supply(demand, blueprint, items, exposure, now=NOW)
    assert result.status == "gap" and "exposure_denied" in result.reasons
    assert items[0].item_handle in result.selected_handles and items[1].item_handle in result.selected_handles
    assert items[2].item_handle not in result.selected_handles


def test_wrong_exposure_identity_and_private_owner() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    exposure = ExposureSnapshotV1(learner_ref="other-learner", scope_hash=demand.scope.scope_hash)
    assert evaluate_supply(demand, blueprint, synthetic_inventory(blueprint), exposure, now=NOW).status == "gap"
    private = make_blueprint(make_scope(visibility="private", owner_ref="learner-1"))
    own_demand = make_demand(private)
    assert evaluate_supply(own_demand, private, synthetic_inventory(private), exposure_for(own_demand), now=NOW).status == "ready_exact"
    wrong_demand = own_demand.model_copy(update={"learner_ref": "other-learner"})
    result = evaluate_supply(wrong_demand, private, synthetic_inventory(private), exposure_for(wrong_demand), now=NOW)
    assert result.status == "gap" and "private_owner_mismatch" in result.reasons


def test_function_boundary_revalidates_before_graph_or_set() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    poisoned_clause = ObjectiveClauseV1.model_construct(
        clause_id=["secret"], clause_hash=digest("secret"), prerequisite_clause_ids=(["secret"],),
    )
    for corrupted in (
        blueprint.model_copy(update={"clauses": (poisoned_clause,)}),
        blueprint.model_copy(update={"scope": blueprint.scope.model_copy(update={"required_facets": [["secret"]]})}),
    ):
        with pytest.raises(ValueError, match="^invalid supply input$"):
            evaluate_supply(demand, corrupted, (), exposure_for(demand), now=NOW)
    for now in (NOW.replace(tzinfo=None), "2026-09-30"):
        with pytest.raises(ValueError, match="^invalid supply input$"):
            evaluate_supply(demand, blueprint, (), exposure_for(demand), now=now)
    with pytest.raises(ValueError, match="^invalid supply input$"):
        evaluate_supply(demand, blueprint, synthetic_inventory(blueprint) * 52, exposure_for(demand), now=NOW)


def test_partial_inventory_returns_explicit_slot_gaps() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    result = evaluate_supply(demand, blueprint, synthetic_inventory(blueprint)[:2], exposure_for(demand), now=NOW)
    assert result.status == "gap" and len(result.selected_handles) == 2
    assert {(gap.slot, gap.required, gap.available) for gap in result.gaps} == {
        ("assessment", 2, 0), ("remediation", 1, 0),
    }


@pytest.mark.parametrize("usage", ["main_teaching", "supplementary_explanation"])
def test_consistent_but_wrong_source_usage_cannot_authorize_assessment(usage: str) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    item = items[2]
    assert item.proof is not None and item.current_authorization is not None
    bad = item.model_copy(update={
        "source_usage": usage,
        "proof": item.proof.model_copy(update={"source_usage": usage}),
        "current_authorization": item.current_authorization.model_copy(update={"source_usage": usage}),
    })
    result = evaluate_supply(demand, blueprint, (*items[:2], bad, *items[3:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "source_usage_denied" in result.reasons


@pytest.mark.parametrize("capabilities", [(), ("unrelated",)])
def test_runtime_boolean_cannot_replace_actual_available_capabilities(capabilities: tuple[str, ...]) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    items = synthetic_inventory(blueprint)
    bad = items[0].model_copy(update={"available_capabilities": capabilities})
    result = evaluate_supply(demand, blueprint, (bad, *items[1:]), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "capability_missing" in result.reasons



def test_consistent_obsolete_matrix_cannot_self_issue_current_support() -> None:
    blueprint = make_blueprint().model_copy(update={"matrix_hash": digest("obsolete-matrix")})
    demand = make_demand(blueprint)
    result = evaluate_supply(demand, blueprint, synthetic_inventory(blueprint), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "identity_mismatch" in result.reasons
    assert result.selected_handles == ()


def test_nested_authority_booleans_cannot_bypass_strict_validation() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    item = synthetic_inventory(blueprint)[0]
    assert item.current_authorization is not None and item.proof is not None
    for poisoned in (
        item.model_copy(update={"published": "true"}),
        item.model_copy(update={"current_authorization": item.current_authorization.model_copy(update={"active": 1})}),
        item.model_copy(update={"proof": item.proof.model_copy(update={"checked_at": NOW.replace(tzinfo=None)})}),
    ):
        with pytest.raises(ValueError, match="^invalid supply input$"):
            evaluate_supply(demand, blueprint, (poisoned,), exposure_for(demand), now=NOW)


def test_owned_modules_have_no_io_imports_or_environment_reads() -> None:
    import ast
    from pathlib import Path
    import sys

    from app.services.learning.item_supply import contracts, coverage

    forbidden_imports = {
        "os", "socket", "httpx", "requests", "psycopg", "redis", "celery", "subprocess",
        "dotenv", "app.config", "app.core.config", "app.services.runners.runtime_profiles",
    }
    for module in (contracts, coverage):
        assert module.__file__ is not None
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not any(name == blocked or name.startswith(blocked + ".") for blocked in forbidden_imports)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"getenv", "now", "utcnow", "connect", "execute", "get_settings"}
    # The pure whitelist import closure did not load application IO owners.
    assert not any(name.split(".")[0] in {"psycopg", "redis", "celery", "dotenv"} for name in sys.modules)



def with_exact_coordinates(item: CandidateAuthorityV1, **updates: object) -> CandidateAuthorityV1:
    """Synthetic coordinated mutation; it does not authorize real source facts."""
    assert item.proof is not None and item.current_authorization is not None
    return item.model_copy(update={
        **updates,
        "proof": item.proof.model_copy(update=updates),
        "current_authorization": item.current_authorization.model_copy(update={
            key: value for key, value in updates.items()
            if key in SourceAuthorizationFactsV1.model_fields
        }),
    })


def test_collisions_cannot_hide_a_complete_independent_pair() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    inventory = synthetic_inventory(blueprint)
    first, second, third = sorted(
        (synthetic_candidate(blueprint, index, "assessment") for index in (30, 31, 32)),
        key=lambda item: item.item_handle,
    )
    first = with_exact_coordinates(first, content_hash=digest("shared-content"), candidate_family_id="shared-family")
    second = with_exact_coordinates(second, content_hash=digest("shared-content"), candidate_family_id="other-family")
    third = with_exact_coordinates(third, content_hash=digest("other-content"), candidate_family_id="shared-family")
    items = (*inventory[:2], first, second, third, inventory[4])
    result = evaluate_supply(demand, blueprint, items, exposure_for(demand), now=NOW)
    assert result.status == "ready_exact" and result.gaps == ()
    assert first.item_handle not in result.selected_handles
    assert second.item_handle in result.selected_handles and third.item_handle in result.selected_handles
    assert evaluate_supply(demand, blueprint, tuple(reversed(items)), exposure_for(demand), now=NOW) == result


def test_independent_matching_can_reassign_a_chain_for_configured_redundancy() -> None:
    blueprint = make_blueprint().model_copy(update={"minimum": MinimumCoverageV1(assessment=3)})
    demand = make_demand(blueprint)
    inventory = synthetic_inventory(blueprint)
    contents = sorted(digest(f"matching-content-{index}") for index in range(3))
    pairs = ((contents[0], "a"), (contents[0], "b"), (contents[1], "a"),
             (contents[1], "c"), (contents[2], "b"))
    assessments = tuple(with_exact_coordinates(
        synthetic_candidate(blueprint, index, "assessment"),
        content_hash=content, candidate_family_id=family,
    ) for index, (content, family) in enumerate(pairs, start=20))
    result = evaluate_supply(demand, blueprint, (*inventory[:2], *assessments, inventory[4]), exposure_for(demand), now=NOW)
    assert result.status == "ready_exact" and len(result.selected_handles) == 6
    chosen = [item for item in assessments if item.item_handle in result.selected_handles]
    assert len({item.content_hash for item in chosen}) == len({item.candidate_family_id for item in chosen}) == 3


@pytest.mark.parametrize("updates", [
    {"source_ref": "conflicting-source"}, {"source_version": "2.0"},
    {"evidence_hash": digest("different-evidence")},
])
def test_same_handle_conflicting_immutable_source_invalidates_all_copies(updates: dict[str, object]) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    inventory = synthetic_inventory(blueprint)
    conflict = with_exact_coordinates(inventory[2], **updates)
    result = evaluate_supply(demand, blueprint, (*inventory, conflict), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "identity_mismatch" in result.reasons
    assert inventory[2].item_handle not in result.selected_handles
    assert {(gap.slot, gap.available) for gap in result.gaps} == {("assessment", 1)}


def test_refreshed_authorization_is_not_an_immutable_item_conflict() -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    inventory = synthetic_inventory(blueprint)
    item = inventory[2]
    assert item.proof is not None and item.current_authorization is not None
    auth = item.current_authorization.model_copy(update={
        "authorization_hash": digest("fresh-authorization"), "checked_at": NOW,
        "valid_until": NOW + timedelta(minutes=5),
    })
    refreshed = item.model_copy(update={
        "current_authorization": auth,
        "proof": item.proof.model_copy(update={
            "authorization_hash": auth.authorization_hash,
            "authorization_checked_at": auth.checked_at, "authorization_valid_until": auth.valid_until,
            "checked_at": NOW, "valid_until": auth.valid_until,
        }),
    })
    assert evaluate_supply(demand, blueprint, (*inventory, refreshed), exposure_for(demand), now=NOW).status == "ready_exact"
    assert evaluate_supply(demand, blueprint, (*inventory[:2], refreshed, *inventory[3:]), exposure_for(demand), now=auth.valid_until).status == "stale"


def test_supply_rejects_nested_subclass_extra_instead_of_laundering_it() -> None:
    class HiddenScope(SupplyScopeV1):
        raw_answer: str

    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    inventory = synthetic_inventory(blueprint)
    hidden = HiddenScope(**blueprint.scope.model_dump(mode="python"), raw_answer="secret-provider-error")
    with pytest.raises(ValueError, match="^invalid supply input$"):
        evaluate_supply(demand, blueprint.model_copy(update={"scope": hidden}), inventory, exposure_for(demand), now=NOW)


def test_demo_cannot_manufacture_formal_assessment_by_scorer_strings_and_booleans() -> None:
    blueprint = make_blueprint(make_scope(
        item_kind=LearningItemKind.DEMO, purpose=LearningItemPurpose.DEMONSTRATION,
        interaction=LearningItemInteraction.OBSERVE, scorer_version="synthetic-scorer",
    ))
    demand = make_demand(blueprint)
    inventory = tuple(item.model_copy(update={"materialized": False}) for item in synthetic_inventory(blueprint))
    result = evaluate_supply(demand, blueprint, inventory, exposure_for(demand), now=NOW)
    assert result.status == "gap" and "assessment_unsupported" in result.reasons
    assert {(gap.slot, gap.available) for gap in result.gaps} == {("assessment", 0)}
    assert all(item.item_handle not in result.selected_handles for item in inventory if item.slot == "assessment")


def test_planned_declaration_cannot_be_promoted_by_caller_runtime_booleans(monkeypatch: pytest.MonkeyPatch) -> None:
    # A registry declaration may change, but no new runtime/Subject is invented.
    monkeypatch.setitem(LANGUAGE_CAPABILITIES, "python", replace(
        LANGUAGE_CAPABILITIES["python"], capability_state="planned",
    ))
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    result = evaluate_supply(demand, blueprint, synthetic_inventory(blueprint), exposure_for(demand), now=NOW)
    assert result.status == "gap" and "language_unsupported" in result.reasons
    assert result.selected_handles == ()


@pytest.mark.parametrize("language", ["rust", "cpp"])
def test_current_planned_languages_have_no_canonical_subject_supply_scope(language: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_scope(language_id=language, subject_id=f"route.{language}")
