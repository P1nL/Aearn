"""Offline C review contracts; fake ports are not production authority."""
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.services.grounding.autonomous.source_assessment import (
    CurrentReview, DocumentCoordinate, DocumentReviewFacts, StorageUseGrant, assess_document,
)
from app.services.grounding.autonomous.source_policy import check_source
from tests.grounding.rag_material_helpers import H, H2, NOW, SCOPE


REVIEW_ID = UUID("00000000-0000-0000-0000-000000000001")
CAPTURE_ID = UUID("00000000-0000-0000-0000-000000000002")


class Reviews:
    def __init__(self, review):
        self.review = review
        self.calls = 0

    def resolve(self, source_handle, document_handle):
        self.calls += 1
        return self.review


def coordinate():
    return DocumentCoordinate(scope=SCOPE, source_handle="source.blog", document_handle="document.001",
                              document_revision="v1", document_hash=H2)


def facts(**changes):
    values = dict(coordinate=coordinate(), review_id=REVIEW_ID, registered_capture_id=CAPTURE_ID,
                  review_receipt_hash=H, quality_code="QUALIFIED", license_id="CC0",
                  policy_id="policy.001", policy_generation=2, root_id="root.001",
                  immutable_history_allowed=True,
                  allowed_usages=("main_teaching", "assessment_evidence"),
                  lineage_family="family.blog", origin="blog", reading_level="beginner",
                  reading_fit="suitable", version_fit="current", technical_status="correct",
                  conflict_status="resolved", known_error="absent", covered_facets=("syntax",),
                  status="reviewed")
    return DocumentReviewFacts(**(values | changes))


def grant(**changes):
    values = dict(coordinate=coordinate(), review_id=REVIEW_ID, active=True, revoked=False,
                  storage_receipt_id="store.001",
                  admission_receipt_id="admission.001", policy_generation=2,
                  license_status="granted", retained_until=NOW + timedelta(days=1),
                  allowed_usages=("main_teaching", "assessment_evidence"))
    return StorageUseGrant(**(values | changes))


def decide(item=None, permission=None, *, revoked=False):
    item = item or facts()
    permission = grant() if permission is None else permission
    return assess_document(item, resolver=Reviews(CurrentReview(facts=item, grant=permission,
                                                                  revoked=revoked)), now=NOW)


def test_exact_review_projects_existing_a_contracts_without_claim_success():
    result = decide()
    assert result.allowed and result.assessment is not None and result.authorization is not None
    assert result.authorization.lineage_family == "family.blog"
    assert check_source(result.assessment, purpose="main_teaching",
                        resolver=type("Port", (), {"resolve": lambda self, *_: result.authorization})()).allowed
    assert result.assessment.allowed_usages == ("main_teaching", "assessment_evidence")
    # Admission at the source level is not itself a scoring/claim receipt.
    assert result.assessment.status == "reviewed"


@pytest.mark.parametrize("change", [
    {"version_fit": "stale"}, {"reading_fit": "unsuitable"},
    {"technical_status": "incorrect"}, {"technical_status": "unknown"},
    {"conflict_status": "unresolved"}, {"known_error": "present"},
    {"covered_facets": ()}, {"quality_code": "KNOWN_ERROR"},
])
def test_bad_or_unknown_quality_never_admits(change):
    result = decide(facts(**change))
    assert not result.allowed and result.reason == "QUALITY_UNVERIFIED"
    assert result.assessment is None and result.authorization is None


def test_official_label_or_hash_does_not_override_unverified_quality():
    assert decide(facts(origin="official", technical_status="unknown")).reason == "QUALITY_UNVERIFIED"
    assert decide(facts(origin="official", quality_code="UNREVIEWED")).reason == "QUALITY_UNVERIFIED"


def test_quarantine_revocation_and_stale_snapshot_fail_closed():
    assert decide(facts(status="quarantined", allowed_usages=(), immutable_history_allowed=False)).reason == "REVIEW_QUARANTINED"
    with pytest.raises(ValidationError):
        facts(status="revoked")
    assert decide(revoked=True).reason == "SOURCE_REVOKED"
    supplied = facts()
    current = CurrentReview(facts=facts(coordinate=coordinate().model_copy(update={"document_revision": "v2"})),
                            grant=grant(), revoked=False)
    assert assess_document(supplied, resolver=Reviews(current), now=NOW).reason == "SOURCE_STALE"
    assert assess_document(supplied, resolver=None, now=NOW).reason == "AUTHORITY_MISSING"


def test_storage_use_retention_and_exact_coordinate_are_separate():
    assert decide(permission=grant(retained_until=NOW)).reason == "RETENTION_EXPIRED"
    assert decide(permission=grant(active=False)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(revoked=True, active=False)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(policy_generation=3)).reason == "STORAGE_DENIED"
    assert decide(permission=grant(review_id=UUID("00000000-0000-0000-0000-000000000003"))).reason == "STORAGE_DENIED"
    assert decide(permission=grant(allowed_usages=())).reason == "USAGE_DENIED"
    assert decide(permission=grant(allowed_usages=("supplementary_explanation",))).reason == "USAGE_DENIED"
    assert decide(permission=grant(coordinate=coordinate().model_copy(update={"document_hash": "c" * 64}))).reason == "STORAGE_DENIED"
    assert decide(permission=grant(license_status="unclear", allowed_usages=())).reason == "STORAGE_DENIED"
    assert decide(facts(allowed_usages=("supplementary_explanation",)),
                  permission=grant(allowed_usages=("supplementary_explanation",))).assessment.allowed_usages == (
        "supplementary_explanation",)


def test_strict_immutable_bounded_review_and_no_model_reviewer():
    with pytest.raises(ValidationError):
        facts(reviewer="model")
    with pytest.raises(ValidationError):
        facts(covered_facets=("schema",))
    with pytest.raises(ValidationError):
        facts(covered_facets=("syntax", "syntax"))
    with pytest.raises(ValidationError):
        facts(origin="official", arbitrary_model_score=0.9)
    with pytest.raises(ValidationError):
        grant(allowed_usages=("main_teaching", "main_teaching"))
    with pytest.raises(ValidationError):
        grant(retained_until=datetime(2026, 9, 26))
    invalid = facts().model_copy(update={"candidate_capture_id": CAPTURE_ID})
    current = CurrentReview(facts=facts(), grant=grant(), revoked=False).model_copy(update={"facts": invalid})
    assert assess_document(invalid, resolver=Reviews(current), now=NOW).reason == "INVALID_CONTRACT"
    assert facts().model_config["frozen"]
