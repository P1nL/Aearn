import pytest

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.assessment_contracts import (
    VerifiedClaim, authorize_assessment_claim, check_claim,
)
from tests.grounding.rag_material_helpers import (
    Authority, Claims, Executions, H, H2, NOW, SCOPE, Sources, access, assessment, binding,
    execution_receipt, receipt,
)


def claim(method="independent_source"):
    return VerifiedClaim(claim_hash=H, scope=SCOPE, binding=binding("assessment_evidence", "claim.001"),
                         claim_receipt_id="claim.001", applicability="Python 3.12 list indexing",
                         execution_scope=receipt(method).execution_scope)


def test_independent_corroboration_not_platform_votes_or_same_lineage():
    usages = ("main_teaching", "assessment_evidence")
    item = claim()
    assert check_claim(item, assessment(usages), source_resolver=Sources(usages),
                       claim_resolver=Claims(receipt())).allowed
    assert not check_claim(item, assessment(usages), source_resolver=Sources(usages), claim_resolver=None).allowed
    for altered in (receipt().model_copy(update={"independent_source_handle": "source.blog"}),
                    receipt().model_copy(update={"independent_lineage_verified": False}),
                    receipt().model_copy(update={"document_hash": H}),
                    receipt().model_copy(update={"revoked": True})):
        assert not check_claim(item, assessment(usages), source_resolver=Sources(usages),
                               claim_resolver=Claims(altered)).allowed


def test_execution_receipt_exact_semantics_and_actor_gate():
    usages = ("assessment_evidence",)
    item = claim("isolated_execution")
    result = authorize_assessment_claim(item, assessment(usages), request=access("consume", "assessment_evidence"),
                                        gates=AutonomousGates(evidence_consumer=True),
                                        authority_resolver=Authority("assessment_evidence"), source_resolver=Sources(usages),
                                        claim_resolver=Claims(receipt("isolated_execution")),
                                        execution_resolver=Executions(execution_receipt()), now=NOW)
    assert result.allowed
    stale = receipt("isolated_execution").model_copy(update={"execution_scope":
        receipt("isolated_execution").execution_scope.model_copy(update={"semantics_hash": H})})
    assert not check_claim(item, assessment(usages), source_resolver=Sources(usages),
                           claim_resolver=Claims(stale), execution_resolver=Executions(execution_receipt())).allowed
    assert not authorize_assessment_claim(item, assessment(usages), request=access("consume", "assessment_evidence").model_copy(
        update={"demand_hash": H2}), gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=Authority("assessment_evidence"), source_resolver=Sources(usages),
        claim_resolver=Claims(receipt("isolated_execution")),
                                        execution_resolver=Executions(execution_receipt()), now=NOW).allowed


@pytest.mark.parametrize("changes", [
    {"demand_hash": H2}, {"admission_receipt_id": "admission.other"},
    {"purpose": "main_teaching"}, {"primary_lineage_family": "family.other"},
    {"independent_lineage_family": "family.blog"},
    {"independent_document_revision": "v2"},
    {"independent_document_hash": H2},
    {"independent_document_handle": "document.other"},
    {"independent_source_handle": "source.blog"},
    {"independent_lineage_verified": False},
])
def test_assessment_receipt_requires_exact_demand_admission_and_current_independent_lineage(changes):
    usages = ("assessment_evidence",)
    altered = receipt().model_copy(update=changes)
    result = authorize_assessment_claim(
        claim(), assessment(usages), request=access("consume", "assessment_evidence"),
        gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=Authority("assessment_evidence"), source_resolver=Sources(usages),
        claim_resolver=Claims(altered), now=NOW,
    )
    assert not result.allowed


@pytest.mark.parametrize("changes", [
    {"receipt_id": "execution.other"}, {"claim_hash": H2}, {"demand_hash": H2},
    {"document_hash": H}, {"document_revision": "v2"},
    {"source_handle": "source.official"}, {"verified": False}, {"revoked": True},
    {"execution_scope": receipt("isolated_execution").execution_scope.model_copy(update={"input_hash": H2})},
])
def test_execution_requires_separate_exact_server_receipt(changes):
    usages = ("assessment_evidence",)
    item = claim("isolated_execution")
    assert not check_claim(item, assessment(usages), source_resolver=Sources(usages),
                           claim_resolver=Claims(receipt("isolated_execution"))).allowed
    result = authorize_assessment_claim(
        item, assessment(usages), request=access("consume", "assessment_evidence"),
        gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=Authority("assessment_evidence"), source_resolver=Sources(usages),
        claim_resolver=Claims(receipt("isolated_execution")),
        execution_resolver=Executions(execution_receipt().model_copy(update=changes)), now=NOW,
    )
    assert not result.allowed


def test_assessment_cannot_reuse_teaching_demand_even_if_receipt_matches_hash():
    usages = ("assessment_evidence",)
    result = authorize_assessment_claim(
        claim(), assessment(usages), request=access("consume"),
        gates=AutonomousGates(evidence_consumer=True), authority_resolver=Authority(),
        source_resolver=Sources(usages), claim_resolver=Claims(receipt()), now=NOW,
    )
    assert not result.allowed


def test_independent_corroboration_reloads_current_source_not_just_claim_metadata():
    from app.services.grounding.autonomous.source_policy import SourceAuthorization

    class ChangedIndependent(Sources):
        def resolve(self, source_handle, document_handle):
            current = super().resolve(source_handle, document_handle)
            if source_handle == "source.official":
                return current.model_copy(update={"lineage_family": "family.blog"})
            return current

    class RevokedIndependent(Sources):
        def resolve(self, source_handle, document_handle):
            current = super().resolve(source_handle, document_handle)
            if source_handle == "source.official":
                return current.model_copy(update={"revoked": True})
            return current

    class IncompleteIndependent(Sources):
        def resolve(self, source_handle, document_handle):
            current = super().resolve(source_handle, document_handle)
            if source_handle == "source.official":
                return SourceAuthorization.model_validate({**current.model_dump(), "admission_receipt_id": None})
            return current

    for sources in (ChangedIndependent(), RevokedIndependent(), IncompleteIndependent()):
        assert not check_claim(claim(), assessment(("assessment_evidence",)),
                               source_resolver=sources, claim_resolver=Claims(receipt())).allowed


def test_default_off_claim_boundary_never_calls_resolvers():
    class Bomb:
        def resolve(self, *args):
            raise AssertionError("closed gate invoked resolver")

    result = authorize_assessment_claim(
        claim(), assessment(("assessment_evidence",)),
        request=access("consume", "assessment_evidence"), gates=AutonomousGates(),
        authority_resolver=Bomb(), source_resolver=Bomb(), claim_resolver=Bomb(),
        execution_resolver=Bomb(), now=NOW,
    )
    assert result.reason == "GATE_CLOSED"
