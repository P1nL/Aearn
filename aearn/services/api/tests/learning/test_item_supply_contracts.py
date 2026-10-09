"""Pure contract tests. Every authority fact here is explicitly synthetic."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.services.learning.item_bank.contracts import (
    LearningItemInteraction, LearningItemKind, LearningItemPurpose, canonical_hash,
)
from app.services.learning.item_supply.matrix import build_support_matrix
from app.services.learning.item_supply.contracts import (
    AssessmentSupplyDemandV1, CandidateAuthorityV1, ClauseCoverageV1, CoverageBlueprintV1,
    MinimumCoverageV1, ObjectiveClauseV1, ObjectiveCoverageProofV1, Slot,
    SourceAuthorizationFactsV1, SupplyScopeV1, revalidate_contract,
)

NOW = datetime(2026, 9, 30, 10, tzinfo=timezone.utc)


def digest(value: str) -> str:
    return canonical_hash(value)


def make_scope(**updates: object) -> SupplyScopeV1:
    data = dict(
        course_family="python-core", course_version="1.0", knowledge_key="python.functions",
        language_id="python", subject_id="route.python", subject_version="1.0",
        required_facets=("functions",), runtime_profile_id="python-v1",
        runtime_profile_hash=digest("runtime"), item_kind=LearningItemKind.CODE,
        purpose=LearningItemPurpose.EXERCISE, interaction=LearningItemInteraction.EDIT,
        required_capabilities=("python_stdout_test",), assessment_contract_version="gate-v1",
        scorer_version="scorer-v1", assistance_policy_hash=digest("assistance"),
    )
    data.update(updates)
    return SupplyScopeV1.model_validate(data)


def make_blueprint(scope: SupplyScopeV1 | None = None, *, dependent: bool = False) -> CoverageBlueprintV1:
    clauses = (ObjectiveClauseV1(clause_id="functions", clause_hash=digest("functions")),)
    if dependent:
        clauses += (ObjectiveClauseV1(
            clause_id="composition", clause_hash=digest("composition"), prerequisite_clause_ids=("functions",),
        ),)
    return CoverageBlueprintV1(
        scope=scope or make_scope(), objective_hash=digest("objective"), clauses=clauses,
        matrix_hash=build_support_matrix().matrix_hash, policy_version="supply-v1",
    )


def make_demand(blueprint: CoverageBlueprintV1) -> AssessmentSupplyDemandV1:
    return AssessmentSupplyDemandV1(
        demand_id="synthetic-demand", learner_ref="learner-1", scope=blueprint.scope,
        objective_hash=blueprint.objective_hash, blueprint_hash=blueprint.blueprint_hash,
        matrix_hash=blueprint.matrix_hash, policy_version=blueprint.policy_version, input_revision=1,
    )


def synthetic_candidate(
    blueprint: CoverageBlueprintV1, index: int, slot: Slot,
    *, clauses: tuple[ClauseCoverageV1, ...] | None = None,
) -> CandidateAuthorityV1:
    """Trusted-caller fixture only; no source, publication or runner verification."""
    scope = blueprint.scope
    mapping = clauses or tuple(ClauseCoverageV1(clause_id=c.clause_id, clause_hash=c.clause_hash)
                               for c in blueprint.clauses)
    auth = SourceAuthorizationFactsV1(
        authorization_hash=digest(f"auth-{index}"), source_ref="synthetic-source", source_version="1.0",
        source_usage="assessment_evidence", scope_hash=scope.scope_hash,
        objective_hash=blueprint.objective_hash, content_hash=digest(f"content-{index}"),
        evidence_hash=digest(f"evidence-{index}"), checked_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(hours=1), active=True,
    )
    proof = ObjectiveCoverageProofV1(
        proof_id=f"synthetic-proof-{index}", blueprint_hash=blueprint.blueprint_hash,
        scope_hash=scope.scope_hash, objective_hash=blueprint.objective_hash,
        item_handle="li:" + digest(f"item-{index}"), content_hash=auth.content_hash,
        clauses=mapping, slot=slot, candidate_family_id=f"family-{index}",
        matrix_hash=blueprint.matrix_hash, policy_version=blueprint.policy_version,
        runtime_profile_id=scope.runtime_profile_id, runtime_profile_hash=scope.runtime_profile_hash,
        assessment_contract_version=scope.assessment_contract_version, scorer_version=scope.scorer_version,
        assistance_policy_hash=scope.assistance_policy_hash, source_ref=auth.source_ref,
        source_version=auth.source_version, source_usage=auth.source_usage, evidence_hash=auth.evidence_hash,
        authorization_hash=auth.authorization_hash, authorization_checked_at=auth.checked_at,
        authorization_valid_until=auth.valid_until, issuer_version="synthetic-v1",
        checked_at=auth.checked_at, valid_until=auth.valid_until,
    )
    return CandidateAuthorityV1(
        scope=scope, item_handle=proof.item_handle, content_hash=proof.content_hash,
        candidate_family_id=proof.candidate_family_id, objective_hash=proof.objective_hash,
        blueprint_hash=proof.blueprint_hash, matrix_hash=proof.matrix_hash, policy_version=proof.policy_version,
        slot=slot, clauses=mapping, source_ref=auth.source_ref, source_version=auth.source_version,
        source_usage=auth.source_usage, evidence_hash=auth.evidence_hash, visibility=scope.visibility,
        owner_ref=scope.owner_ref, proof=proof, current_authorization=auth,
        published=True, materialized=True, runtime_available=True,
        available_capabilities=scope.required_capabilities,
    )


def synthetic_inventory(blueprint: CoverageBlueprintV1) -> tuple[CandidateAuthorityV1, ...]:
    return tuple(synthetic_candidate(blueprint, index, slot) for index, slot in enumerate(
        ("practice", "practice", "assessment", "assessment", "remediation"), start=1,
    ))


@pytest.mark.parametrize("updates", [
    {"language_id": "py"}, {"subject_id": "python-core"}, {"subject_id": "route.sql"},
    {"required_facets": ("imaginary",)}, {"required_facets": ("functions", "functions")},
    {"required_facets": []}, {"required_facets": ("functions\n",)},
    {"required_capabilities": ("python_stdout_test", "python_stdout_test")},
    {"dialect": "sqlite"}, {"owner_ref": "learner-1"}, {"visibility": "private"},
    {"runtime_profile_hash": "A" * 64}, {"course_version": "1.0\n"},
    {"knowledge_key": "answer text"}, {"raw_answer": "never accepted"},
    {"item_kind": "code"},
])
def test_scope_strict_rejections(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_scope(**updates)


def test_sqlite_is_explicit_and_facets_are_node_scoped() -> None:
    scope = make_scope(language_id="sql", subject_id="route.sql", required_facets=("queries",), dialect="sqlite")
    assert scope.required_facets == ("queries",)
    with pytest.raises(ValidationError):
        make_scope(language_id="sql", subject_id="route.sql", required_facets=("queries",))


@pytest.mark.parametrize("field", ["practice", "assessment", "remediation"])
@pytest.mark.parametrize("value", [True, "2", 0, 17])
def test_minimum_is_strict_bounded(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        MinimumCoverageV1.model_validate({field: value})


def test_hashes_are_computed_and_cover_sensitive_coordinates() -> None:
    scope = make_scope()
    blueprint = make_blueprint(scope)
    demand = make_demand(blueprint)
    assert len(scope.scope_hash) == len(blueprint.blueprint_hash) == len(demand.demand_hash) == 64
    for field, value in (
        ("course_version", "2.0"), ("subject_version", "2.0"), ("required_facets", ("syntax",)),
        ("runtime_profile_hash", digest("other")), ("scorer_version", "scorer-v2"),
        ("assistance_policy_hash", digest("other")), ("knowledge_key", "python.other"),
        ("assessment_contract_version", "gate-v2"), ("required_capabilities", ("other-capability",)),
    ):
        assert make_scope(**{field: value}).scope_hash != scope.scope_hash
    with pytest.raises(ValidationError):
        CoverageBlueprintV1.model_validate({**blueprint.model_dump(), "blueprint_hash": digest("forged")})
    with pytest.raises(ValidationError):
        scope.language_id = "sql"


@pytest.mark.parametrize("clauses", [
    (ObjectiveClauseV1(clause_id="a", clause_hash=digest("a"), prerequisite_clause_ids=("missing",)),),
    (ObjectiveClauseV1(clause_id="a", clause_hash=digest("a"), prerequisite_clause_ids=("a",)),),
    (ObjectiveClauseV1(clause_id="a", clause_hash=digest("a"), prerequisite_clause_ids=("b",)),
     ObjectiveClauseV1(clause_id="b", clause_hash=digest("b"), prerequisite_clause_ids=("a",))),
    (ObjectiveClauseV1(clause_id="a", clause_hash=digest("a")),) * 2,
])
def test_invalid_graphs(clauses: tuple[ObjectiveClauseV1, ...]) -> None:
    with pytest.raises(ValidationError):
        CoverageBlueprintV1.model_validate({**make_blueprint().model_dump(), "clauses": clauses})


def test_nested_copy_construct_and_hidden_extra_revalidation() -> None:
    blueprint = make_blueprint()
    corrupted = blueprint.scope.model_copy(update={"required_facets": [["unsafe"]]})
    with pytest.raises(ValueError, match="^invalid supply contract$"):
        revalidate_contract(blueprint.model_copy(update={"scope": corrupted}), CoverageBlueprintV1)
    hidden = blueprint.scope.model_copy(update={"raw_answer": "secret"})
    with pytest.raises(ValueError, match="^invalid supply contract$"):
        revalidate_contract(blueprint.model_copy(update={"scope": hidden}), CoverageBlueprintV1)
    bypass = MinimumCoverageV1.model_construct(practice=True)
    with pytest.raises(ValueError, match="^invalid supply contract$"):
        revalidate_contract(blueprint.model_copy(update={"minimum": bypass}), CoverageBlueprintV1)


def test_times_are_aware_and_ordered() -> None:
    item = synthetic_candidate(make_blueprint(), 1, "practice")
    assert item.proof is not None
    for updates in ({"checked_at": NOW.replace(tzinfo=None)}, {"valid_until": NOW - timedelta(days=1)}):
        with pytest.raises(ValidationError):
            ObjectiveCoverageProofV1.model_validate({**item.proof.model_dump(), **updates})


def test_facts_default_to_deny() -> None:
    item = synthetic_candidate(make_blueprint(), 1, "practice")
    data = item.model_dump()
    for key in ("published", "materialized", "runtime_available", "proof", "current_authorization"):
        data.pop(key)
    denied = CandidateAuthorityV1.model_validate(data)
    assert not denied.published and not denied.materialized and not denied.runtime_available
    assert denied.proof is None and denied.current_authorization is None


@pytest.mark.parametrize("bypass", ["copy", "construct"])
def test_all_hash_boundaries_revalidate_forged_contracts(bypass: str) -> None:
    blueprint = make_blueprint()
    demand = make_demand(blueprint)
    proof = synthetic_candidate(blueprint, 1, "practice").proof
    assert proof is not None
    cases = (
        (blueprint.scope, "scope_hash", {"owner_ref": "private-in-public"}),
        (blueprint, "blueprint_hash", {"minimum": MinimumCoverageV1.model_construct(practice=True)}),
        (demand, "demand_hash", {"input_revision": True}),
        (proof, "proof_hash", {"checked_at": NOW.replace(tzinfo=None)}),
    )
    for value, property_name, updates in cases:
        forged = (
            value.model_copy(update=updates) if bypass == "copy"
            else type(value).model_construct(**(value.__dict__ | updates))
        )
        with pytest.raises(ValueError, match="^invalid supply contract$"):
            getattr(forged, property_name)
        assert getattr(value, property_name) == canonical_hash(value.model_dump(mode="json"))


def test_nested_subclass_extra_fields_cannot_be_serialized_away() -> None:
    class HiddenScope(SupplyScopeV1):
        raw_answer: str

    blueprint = make_blueprint()
    hidden = HiddenScope(**blueprint.scope.model_dump(mode="python"), raw_answer="secret-provider-error")
    forged = blueprint.model_copy(update={"scope": hidden})
    with pytest.raises(ValueError, match="^invalid supply contract$"):
        revalidate_contract(forged, CoverageBlueprintV1)
    with pytest.raises(ValueError, match="^invalid supply contract$"):
        _ = forged.blueprint_hash
