from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.source_policy import (
    authorize_binding, check_binding, check_source,
)
from tests.grounding.rag_material_helpers import (
    Authority, H, NOW, Sources, access, assessment, binding,
)


def test_storage_and_teaching_purposes_independent():
    item = assessment()
    assert check_source(item, purpose=None, resolver=Sources()).allowed
    assert check_source(item, purpose="main_teaching", resolver=Sources()).allowed
    assert not check_source(item, purpose="supplementary_explanation", resolver=Sources()).allowed
    assert not check_source(item, purpose="assessment_evidence", resolver=Sources()).allowed
    assert not check_source(item, purpose="main_teaching", resolver=None).allowed
    assert not check_source(item.model_copy(update={"status": "revoked", "allowed_usages": ()}),
                            purpose="main_teaching", resolver=Sources()).allowed
    assert not check_source(item.model_copy(update={"document_revision": "v2"}),
                            purpose="main_teaching", resolver=Sources()).allowed


def test_binding_needs_exact_scope_and_actor_gate():
    item = assessment()
    assert check_binding(binding(), item, resolver=Sources()).allowed
    assert check_binding(binding().model_copy(update={"document_hash": H}), item,
                         resolver=Sources()).reason == "BINDING_MISMATCH"
    assert not authorize_binding(binding(), item, request=access("consume"),
                                 gates=AutonomousGates(), authority_resolver=Authority(),
                                 source_resolver=Sources(), now=NOW).allowed
    assert authorize_binding(binding(), item, request=access("consume"),
                             gates=AutonomousGates(evidence_consumer=True), authority_resolver=Authority(),
                             source_resolver=Sources(), now=NOW).allowed


def test_assessment_source_grant_alone_cannot_authorize_binding():
    usages = ("main_teaching", "assessment_evidence")
    item = assessment(usages)
    assert check_binding(binding("assessment_evidence", "claim.001"), item,
                         resolver=Sources(usages)).reason == "CLAIM_VERIFICATION_REQUIRED"
    assert authorize_binding(binding("assessment_evidence", "claim.001"), item,
                             request=access("consume", "assessment_evidence"), gates=AutonomousGates(evidence_consumer=True),
                             authority_resolver=Authority("assessment_evidence"), source_resolver=Sources(usages),
                             now=NOW).reason == "CLAIM_VERIFICATION_REQUIRED"


def test_caller_cannot_relabel_current_source_origin_or_reading_level():
    item = assessment()
    for changed in (item.model_copy(update={"origin": "official"}),
                    item.model_copy(update={"reading_level": "advanced"})):
        assert check_source(changed, purpose="main_teaching", resolver=Sources()).reason == "SOURCE_STALE"
