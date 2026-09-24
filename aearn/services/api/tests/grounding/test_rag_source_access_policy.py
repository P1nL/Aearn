from datetime import datetime, timedelta, timezone

from app.services.grounding.autonomous.access_policy import (
    AutonomousGates, check_access, check_candidate_access, issue_discovery_demand,
)
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate, SourceDiscoverySuggestion
from tests.grounding.rag_material_helpers import Authority, H, NOW, access, demand


def test_closed_gate_and_missing_resolver_zero_calls():
    resolver = Authority()
    assert check_access(access(), gates=AutonomousGates(), resolver=resolver, now=NOW).reason == "GATE_CLOSED"
    assert resolver.calls == 0
    assert check_access(access(), gates=AutonomousGates(discovery=True), resolver=None, now=NOW).reason == "AUTHORITY_MISSING"


def test_independent_action_gates():
    resolver = Authority()
    gates = AutonomousGates(discovery=True)
    assert check_access(access("discover"), gates=gates, resolver=resolver, now=NOW).allowed
    assert check_access(access("probe"), gates=gates, resolver=resolver, now=NOW).allowed
    for action in ("store", "activate", "consume"):
        assert check_access(access(action), gates=gates, resolver=resolver, now=NOW).reason == "GATE_CLOSED"
    assert check_access(access("store"), gates=AutonomousGates(intake=True), resolver=resolver, now=NOW).allowed
    assert check_access(access("activate"), gates=AutonomousGates(activation=True), resolver=resolver, now=NOW).allowed
    assert check_access(access("consume"), gates=AutonomousGates(evidence_consumer=True), resolver=resolver, now=NOW).allowed


def test_actor_policy_budget_and_scope_rechecked_against_server():
    resolver = Authority()
    gates = AutonomousGates(discovery=True)
    req = access()
    for update, reason in (({"actor_id": "actor.fake"}, "ACTOR_ACTION_DENIED"),
                           ({"policy_generation": 3}, "POLICY_SCOPE_STALE"),
                           ({"demand_hash": "b" * 64}, "POLICY_SCOPE_STALE"),
                           ({"budget": req.budget.model_copy(update={"root_id": "root.fake"})}, "BUDGET_UNAVAILABLE")):
        assert check_access(req.model_copy(update=update), gates=gates, resolver=resolver, now=NOW).reason == reason
    assert check_access(req, gates=gates, resolver=resolver,
                        now=req.budget.expires_at + timedelta(seconds=1)).reason == "BUDGET_UNAVAILABLE"
    assert check_access(req.model_copy(update={"action": "steal"}), gates=gates,
                        resolver=resolver, now=NOW).reason == "INVALID_CONTRACT"


class Projection:
    def project(self, demand, suggestion):
        return ("Python list",)


def test_suggestion_can_only_issue_with_trusted_context():
    suggestion = SourceDiscoverySuggestion(demand_hash=H, query_terms=("Python list",), reason="coverage_gap")
    resolver = Authority()
    result = issue_discovery_demand(demand(), suggestion, actor_id="actor.001", policy_id="policy.001",
                                    policy_generation=2, budget=access().budget,
                                    gates=AutonomousGates(discovery=True), resolver=resolver, projection=Projection(), now=NOW)
    assert result is not None and result.query_terms == ("Python list",)
    assert issue_discovery_demand(demand(), suggestion, actor_id="actor.fake", policy_id="policy.001",
                                  policy_generation=2, budget=access().budget,
                                  gates=AutonomousGates(discovery=True), resolver=resolver, projection=Projection(), now=NOW) is None
    assert issue_discovery_demand(demand(), suggestion, actor_id="actor.001", policy_id="policy.001",
                                  policy_generation=2, budget=access().budget,
                                  gates=AutonomousGates(), resolver=resolver, projection=Projection(), now=NOW) is None


def test_no_server_query_projection_denies_even_authorized_actor():
    suggestion = SourceDiscoverySuggestion(demand_hash=H, query_terms=("Python list",), reason="coverage_gap")
    assert issue_discovery_demand(demand(), suggestion, actor_id="actor.001", policy_id="policy.001",
                                  policy_generation=2, budget=access().budget,
                                  gates=AutonomousGates(discovery=True), resolver=Authority(),
                                  projection=None, now=NOW) is None

def test_candidate_probe_and_storage_separate_with_bypass_recheck():
    candidate = SourceCandidate(kind="landing", demand_hash=H, scope=demand().scope, url="https://example.org/page",
                                discovery_receipt_id="search.001", capture=ContentCapture(kind="none", captured_bytes=0))
    authority = Authority()
    assert check_candidate_access(candidate, access("probe"), gates=AutonomousGates(discovery=True),
                                  resolver=authority, now=NOW).allowed
    assert not check_candidate_access(candidate, access("store"), gates=AutonomousGates(discovery=True),
                                      resolver=authority, now=NOW).allowed
    assert check_candidate_access(candidate, access("store"), gates=AutonomousGates(intake=True),
                                  resolver=authority, now=NOW).allowed
    assert not check_candidate_access(candidate, access("consume"), gates=AutonomousGates(evidence_consumer=True),
                                      resolver=authority, now=NOW).allowed
    assert not check_candidate_access(candidate.model_copy(update={"kind": "repo_file"}), access("probe"),
                                      gates=AutonomousGates(discovery=True), resolver=authority, now=NOW).allowed

def test_candidate_cannot_cross_demand_and_nested_copy_fails_closed():
    from tests.grounding.rag_material_helpers import SCOPE
    candidate = SourceCandidate(kind="document", demand_hash=H, scope=SCOPE,
                                url="https://example.org/lesson", discovery_receipt_id="search.001",
                                capture=ContentCapture(kind="none", captured_bytes=0))
    authority = Authority()
    for changed in (candidate.model_copy(update={"demand_hash": "b" * 64}),
                    candidate.model_copy(update={"scope": SCOPE.model_copy(update={"facets": ("queries",)})}),
                    candidate.model_copy(update={"capture": candidate.capture.model_copy(update={"kind": "full"})})):
        assert not check_candidate_access(changed, access("probe"),
                                          gates=AutonomousGates(discovery=True),
                                          resolver=authority, now=NOW).allowed
    assert authority.calls == 0


def test_discovery_rejects_substituted_full_demand_before_projection():
    class Projection:
        calls = 0

        def project(self, material, suggestion):
            self.calls += 1
            return ("Python list",)

    proposal = SourceDiscoverySuggestion(demand_hash=H, query_terms=("Python list",),
                                          reason="coverage_gap")
    projection = Projection()
    valid = demand()
    substituted = valid.model_copy(update={"node_ref": "node.other"})
    assert issue_discovery_demand(substituted, proposal, actor_id="actor.001",
                                  policy_id="policy.001", policy_generation=2, budget=access().budget,
                                  gates=AutonomousGates(discovery=True), resolver=Authority(),
                                  projection=projection, now=NOW) is None
    assert projection.calls == 0


def test_timezone_expiry_and_resolver_errors_fail_closed_without_secret_reason():
    class Broken:
        def resolve(self, request):
            raise RuntimeError("secret-token-should-not-leak")

    gates = AutonomousGates(discovery=True)
    assert check_access(access(), gates=gates, resolver=Broken(), now=NOW).reason == "INVALID_CONTRACT"
    expired_local = access().budget.expires_at.astimezone(timezone(timedelta(hours=8)))
    assert check_access(access(), gates=gates, resolver=Authority(), now=expired_local).reason == "BUDGET_UNAVAILABLE"
    assert check_access(access(), gates=gates, resolver=Authority(),
                        now=datetime(2026, 9, 24)).reason == "BUDGET_UNAVAILABLE"
    naive_budget = access().budget.model_copy(update={"expires_at": datetime(2026, 9, 25)})
    assert check_access(access().model_copy(update={"budget": naive_budget}), gates=gates,
                        resolver=Authority(), now=NOW).reason == "BUDGET_UNAVAILABLE"
