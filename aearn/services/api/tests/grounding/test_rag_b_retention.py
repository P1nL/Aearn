import hashlib
from datetime import timedelta

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate
from app.services.grounding.autonomous.retention import StorageGrant, check_storage
from tests.grounding.rag_material_helpers import Authority, H, NOW, SCOPE, access


CANDIDATE = SourceCandidate(kind="document", demand_hash=H, scope=SCOPE,
                            url="https://example.org/lesson", discovery_receipt_id="search.001",
                            capture=ContentCapture(kind="none", captured_bytes=0))
GATES = AutonomousGates(intake=True)


class Grants:
    def __init__(self, **changes):
        self.changes = changes
        self.calls = 0

    def resolve(self, candidate, request):
        self.calls += 1
        data = dict(demand_hash=H, scope=SCOPE, discovery_receipt_id="search.001",
                    candidate_url_sha256=hashlib.sha256(CANDIDATE.url.encode()).hexdigest(),
                    policy_id="policy.001", policy_generation=2, allowed_capture="prefix",
                    max_captured_bytes=1024, retention_until=NOW + timedelta(days=1), revoked=False)
        data.update(self.changes)
        return StorageGrant(**data)


def decide(grants=None, *, candidate=CANDIDATE, request=None, gates=GATES,
           intended_capture="prefix", planned_bytes=256, now=NOW):
    return check_storage(candidate, request or access("store"),
                         intended_capture=intended_capture, planned_bytes=planned_bytes,
                         gates=gates, authority_resolver=Authority(),
                         storage_resolver=grants, now=now)


def test_missing_and_closed_policy_fails_before_storage_resolver():
    resolver = Grants()
    assert decide(resolver, gates=AutonomousGates()).reason == "GATE_CLOSED"
    assert resolver.calls == 0
    assert decide(None).reason == "STORAGE_POLICY_MISSING"
    assert decide(resolver).allowed


def test_exact_candidate_and_generation_cannot_borrow_grant():
    grants = Grants()
    altered = CANDIDATE.model_copy(update={"url": "https://example.org/other"})
    assert decide(grants, candidate=altered).reason == "STORAGE_POLICY_STALE"
    assert decide(Grants(policy_generation=3)).reason == "STORAGE_POLICY_STALE"
    assert decide(Grants(discovery_receipt_id="search.other")).reason == "STORAGE_POLICY_STALE"
    assert decide(Grants(revoked=True)).reason == "STORAGE_POLICY_STALE"
    assert decide(Grants(retention_until=NOW)).reason == "STORAGE_POLICY_STALE"


def test_capture_and_byte_limits_are_exact_and_fail_closed():
    grants = Grants()
    assert decide(grants, intended_capture="full").reason == "STORAGE_SCOPE_DENIED"
    assert decide(grants, planned_bytes=1025).reason == "STORAGE_SCOPE_DENIED"
    assert decide(grants, intended_capture="none", planned_bytes=0).allowed
    assert decide(grants, intended_capture="none", planned_bytes=100).reason == "STORAGE_POLICY_MISSING"
    assert decide(grants, intended_capture="prefix", planned_bytes=0).reason == "STORAGE_POLICY_MISSING"
    assert decide(Grants(allowed_capture="none", max_captured_bytes=0)).reason == "STORAGE_SCOPE_DENIED"


def test_invalid_nested_contract_and_resolver_failure_never_authorize():
    class Broken:
        def resolve(self, candidate, request):
            raise RuntimeError("sensitive exception")

    assert decide(Broken()).reason == "INVALID_STORAGE_POLICY"
    invalid = CANDIDATE.model_copy(update={"capture": CANDIDATE.capture.model_copy(update={"kind": "full"})})
    assert decide(Grants(), candidate=invalid).reason == "INVALID_CONTRACT"
