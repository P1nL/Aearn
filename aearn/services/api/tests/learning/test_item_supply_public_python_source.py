"""Native source pure contracts; fixtures never establish live source authority."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace

import pytest

from app.services.grounding.autonomous.finite_course_source_oracle import public_course_execution_scope
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository
from app.services.grounding.autonomous.source_assessment_profiles import (
    PYTHON_AUGMENTED, PYTHON_BINDING, PYTHON_RHS, PYTHON_STATEMENTS_URL,
    PreparedSourceAssessment, SourceAssessmentDenied, analyze_source,
)
from app.services.grounding.public_course_contracts import public_course_demand
from app.services.grounding.public_course_material_factory import create_public_course_material
from tests.learning.test_item_supply_assessment_source import NOW, _capture, _prepared, _signed


def _public(profile):
    target = "python-state-update-v1" if profile == "python-state-source-v1" else "python-kc-binding-v1"
    demand = public_course_demand(target)
    paragraphs = (PYTHON_BINDING, PYTHON_RHS, PYTHON_AUGMENTED) if profile == "python-state-source-v1" else (PYTHON_BINDING, PYTHON_RHS)
    body = ("<html><body>" + "".join("<p>"+p+"</p>" for p in paragraphs) + "</body></html>").encode()
    digest = hashlib.sha256(body).hexdigest()
    capture = replace(_capture("python-sum-print-source-v1"), body=body, digest=digest, revision=digest,
                      scope=demand.scope, final_url=PYTHON_STATEMENTS_URL, request_chain=(PYTHON_STATEMENTS_URL,))
    values = _prepared("python-sum-print-source-v1").model_dump()
    values.update(profile_id=profile, capture_id=capture.capture_id, document_hash=digest, demand=demand,
                  spans=analyze_source(capture, profile))
    return target, capture, PreparedSourceAssessment(**values)


@pytest.mark.parametrize("profile", ("python-state-source-v1", "python-binding-source-v1"))
def test_native_source_has_exact_public_demand_actor_and_execution_semantics(profile):
    target, capture, prepared = _public(profile)
    assert prepared.execution_scope == public_course_execution_scope(target)
    assert prepared.consume_actor == "service.rag-public-course"
    assert "consume_actor" not in prepared.model_dump()
    assert "draft." not in prepared.model_dump_json()
    assert all(hashlib.sha256(capture.body[s.start_byte:s.end_byte]).hexdigest()==s.sha256 for s in prepared.spans)
    with pytest.raises(ValueError, match="public course demand"):
        PreparedSourceAssessment(**{**prepared.model_dump(), "demand": prepared.demand.model_copy(update={"plan_ref": "draft.fake"})})
    changed = replace(capture, final_url="https://docs.python.org/3/builtins/functions.html")
    with pytest.raises(SourceAssessmentDenied):
        analyze_source(changed, profile)


def test_legacy_serialized_proof_no_actor_field_and_public_factory_not_duck_typed():
    signed, pins = _signed()
    from app.services.grounding.autonomous.source_assessment_profiles import verify_source_assessment

    assert verify_source_assessment(signed,service_keys=pins,now=NOW+timedelta(seconds=2)).prepared.consume_actor == "service.rag-assessment"
    assert "consume_actor" not in signed.model_dump_json()
    with pytest.raises(SourceAssessmentDenied,match="SOURCE_FACTORY_GATE_CLOSED"):
        create_public_course_material(None,receipts=None,authority=None,claim_receipt_id="source-claim.fake",
                                      target_id="python-state-update-v1",chunk_id="chunk.one",enabled=True)


def test_db_clock_timezone_changes_representation_not_the_authoritative_instant():
    observed = datetime(2026,10,3,17,0,tzinfo=timezone(timedelta(hours=8)))
    repo = object.__new__(AssessmentReceiptRepository)
    repo.conn = SimpleNamespace(execute=lambda _: SimpleNamespace(fetchone=lambda: {"now": observed}))
    assert repo._clock() == observed
    assert repo._clock().utcoffset() == timedelta(0)
