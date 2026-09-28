"""Offline C claim review: fakes demonstrate the required trusted ports only."""
import pytest
from pydantic import ValidationError

from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.claim_verification import (
    IndependentLineageReview, review_claim,
)
from tests.grounding.rag_material_helpers import (
    H, H2, SCOPE, Claims, Executions, Sources, assessment, binding, execution_receipt, receipt,
)


class Lineages:
    def __init__(self, value):
        self.value = value

    def resolve(self, receipt_id):
        return self.value


def claim(method="independent_source"):
    return VerifiedClaim(claim_hash=H, scope=SCOPE, binding=binding("assessment_evidence", "claim.001"),
                         claim_receipt_id="claim.001", applicability="Python 3.12 list indexing",
                         execution_scope=receipt(method).execution_scope)


def lineage(**changes):
    values = dict(claim_receipt_id="claim.001", claim_hash=H, demand_hash=H, scope=SCOPE,
                  primary_source_handle="source.blog", primary_document_handle="document.001",
                  primary_document_revision="v1", primary_document_hash=H2,
                  primary_lineage_family="family.blog", independent_source_handle="source.official",
                  independent_document_handle="document.official", independent_document_revision="v1",
                  independent_document_hash=H, independent_lineage_family="family.official",
                  review_receipt_id="lineage.001", status="confirmed")
    return IndependentLineageReview(**(values | changes))


def decide(*, claim_item=None, claim_receipt=None, lineage_review=None, execution=None, usages=None):
    claim_item = claim_item or claim()
    claim_receipt = claim_receipt or receipt()
    usages = usages or ("assessment_evidence",)
    return review_claim(
        claim_item, assessment(usages), source_resolver=Sources(usages),
        claim_resolver=Claims(claim_receipt),
        lineage_resolver=Lineages(lineage() if lineage_review is None else lineage_review),
        execution_resolver=Executions(execution) if execution is not None else None,
    )


def test_distinct_current_lineage_and_existing_a_check_required():
    assert decide().allowed
    assert not review_claim(claim(), assessment(("assessment_evidence",)),
                            source_resolver=Sources(("assessment_evidence",)),
                            claim_resolver=None, lineage_resolver=Lineages(lineage()),
                            execution_resolver=None).allowed
    assert not review_claim(claim(), assessment(("assessment_evidence",)),
                            source_resolver=Sources(("assessment_evidence",)),
                            claim_resolver=Claims(receipt()), lineage_resolver=None,
                            execution_resolver=None).allowed
    assert not decide(usages=("main_teaching",)).allowed


@pytest.mark.parametrize("change", [
    {"claim_hash": H2}, {"demand_hash": H2}, {"primary_document_revision": "v2"},
    {"primary_document_hash": H}, {"independent_document_hash": H2},
    {"independent_document_revision": "v2"}, {"independent_source_handle": "source.blog"},
    {"independent_lineage_family": "family.blog"}, {"status": "unresolved"},
    {"status": "revoked"},
])
def test_lineage_receipt_must_match_exact_claim_and_distinct_family(change):
    assert decide(lineage_review=lineage(**change)).reason == "INDEPENDENCE_UNVERIFIED"


def test_same_family_or_stale_a_claim_receipt_cannot_pass_with_good_lineage():
    for changed in ({"independent_lineage_family": "family.blog"},
                    {"verified": False}, {"revoked": True}, {"claim_hash": H2}):
        assert not decide(claim_receipt=receipt().model_copy(update=changed)).allowed


def test_actual_scoped_execution_receipt_mandatory_and_exact():
    execution_claim = claim("isolated_execution")
    execution_claim_receipt = receipt("isolated_execution")
    assert not decide(claim_item=execution_claim, claim_receipt=execution_claim_receipt).allowed
    assert decide(claim_item=execution_claim, claim_receipt=execution_claim_receipt,
                  execution=execution_receipt()).allowed
    for changed in ({"document_revision": "v2"}, {"verified": False}, {"revoked": True},
                    {"execution_scope": execution_receipt().execution_scope.model_copy(
                        update={"semantics_hash": H})}):
        assert not decide(claim_item=execution_claim, claim_receipt=execution_claim_receipt,
                          execution=execution_receipt().model_copy(update=changed)).allowed


def test_no_synthetic_port_success_or_malformed_nested_copy():
    assert decide(lineage_review=lineage().model_copy(update={"status": "model_confirmed"})).reason == "INVALID_CONTRACT"
    with pytest.raises(ValidationError):
        lineage(status="model_confirmed")
    with pytest.raises(ValidationError):
        lineage(primary_document_hash="prefix-not-full")
