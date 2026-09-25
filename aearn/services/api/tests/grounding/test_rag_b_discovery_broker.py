"""Pure B1 broker checks: synthetic ports, no provider, DB, env or network."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AuthoritySnapshot, AutonomousGates,
)
from app.services.grounding.autonomous.contracts import (
    ContentCapture, LearningMaterialDemand, SourceCandidate, SourceDiscoverySuggestion,
)
from app.services.grounding.autonomous.discovery_broker import (
    AttemptTicket, BrokerResult, CorpusAssessment, DiscoveryBroker,
    DiscoveryRequest, SearchResult, WorkClaim, WorkDecision,
)
from tests.grounding.rag_material_helpers import BUDGET, H, H2, NOW, SCOPE, demand


class Authority:
    def __init__(self) -> None:
        self.calls = 0
        self.enabled = True
        self.trusted = demand()

    def resolve(self, request: AccessRequest) -> AuthoritySnapshot:
        self.calls += 1
        return AuthoritySnapshot(
            demand=self.trusted, demand_hash=self.trusted.demand_hash,
            scope=self.trusted.scope, purpose=self.trusted.purpose,
            actor_id="actor.001", allowed_actions=("discover",) if self.enabled else (),
            policy_id="policy.001", policy_generation=2, budget=BUDGET,
            budget_active=self.enabled, authorized=self.enabled,
        )


class Projection:
    def __init__(self) -> None:
        self.calls = 0
        self.terms: tuple[str, ...] | None = ("Python 3.12", "list")

    def project(self, full: LearningMaterialDemand,
                suggestion: SourceDiscoverySuggestion) -> tuple[str, ...] | None:
        self.calls += 1
        assert full == demand()
        return self.terms


class Corpus:
    def __init__(self) -> None:
        self.calls = 0
        self.status = "gap"
        self.reason = "coverage_gap"
        self.full = demand()

    def assess(self, full: LearningMaterialDemand) -> CorpusAssessment:
        self.calls += 1
        return CorpusAssessment(demand=self.full, status=self.status,
                                receipt_id="coverage.001",
                                gap_reason=self.reason if self.status == "gap" else None)


class Gates:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = 0

    def current(self) -> AutonomousGates:
        self.calls += 1
        return AutonomousGates(discovery=self.enabled)


class Approval:
    def __init__(self) -> None:
        self.enabled = True
        self.calls = 0

    def permitted(self) -> bool:
        self.calls += 1
        return self.enabled


class Work:
    def __init__(self) -> None:
        self.calls = 0
        self.keys: list[str] = []
        self.state = "claimed"
        self.claim = WorkClaim(job_id="job.001", reservation_id="reserve.001",
                               lease_owner="owner.001", lease_generation=2)
        self.ticket: AttemptTicket | None = AttemptTicket(
            job_id="job.001", attempt_id="attempt.001", lease_generation=2,
        )
        self.outcomes = []
        self.unknown = []
        self.dispatched = set()
        self.committed = []
        self.accept_outcome = True
        self.accept_commit = True
        self.on_claim = None
        self.on_prepare = None

    def claim_or_reuse(self, full, projection, operation_id):
        self.calls += 1
        self.keys.append(operation_id)
        assert projection.demand_hash == full.demand_hash
        assert projection.budget == BUDGET
        if self.on_claim:
            self.on_claim()
        if self.state == "claimed":
            return WorkDecision(status="claimed", claim=self.claim)
        if self.state == "existing":
            return WorkDecision(status="existing", job_id=self.claim.job_id)
        return WorkDecision(status="denied")

    def prepare_attempt(self, claim):
        assert claim == self.claim
        if self.on_prepare:
            self.on_prepare()
        return self.ticket

    def take_dispatch(self, projected, claim, ticket):
        if claim != self.claim or projected != projected_demand() or ticket != self.ticket:
            return False
        if ticket.attempt_id in self.dispatched:
            return False
        self.dispatched.add(ticket.attempt_id)
        return True

    def record_outcome(self, claim, ticket, settlement, candidates=()):
        self.outcomes.append(settlement)
        if self.accept_outcome:
            if settlement.usage_units is None:
                self.unknown.append(ticket)  # fake durable hold, never a zero-cost settle
            elif candidates:
                self.committed.append(candidates)
        return self.accept_outcome

    def record_unknown(self, claim, ticket):
        self.unknown.append(ticket)


class Search:
    def __init__(self) -> None:
        self.calls = []
        self.result = SearchResult(status="completed", candidates=(candidate(),),
                                   usage_units=1, usage_receipt_id="usage.001")
        self.on_search = None

    def search(self, projected, claim, ticket):
        assert claim.job_id == ticket.job_id
        self.calls.append((projected.query_terms, ticket.attempt_id))
        if self.on_search:
            self.on_search()
        return self.result


def candidate(**changes):
    values = dict(kind="landing", demand_hash=H, scope=SCOPE,
                  url="https://docs.python.org/3/", discovery_receipt_id="attempt.001",
                  capture=ContentCapture(kind="none", captured_bytes=0))
    values.update(changes)
    return SourceCandidate(**values)


def request(**changes):
    values = dict(demand=demand(),
                  suggestion=SourceDiscoverySuggestion(demand_hash=H,
                      query_terms=("raw learner private dialogue",), reason="coverage_gap"),
                  actor_id="actor.001", policy_id="policy.001", policy_generation=2,
                  budget=BUDGET)
    values.update(changes)
    return DiscoveryRequest(**values)


def harness():
    authority, projection, corpus = Authority(), Projection(), Corpus()
    gates, approval, work, search = Gates(), Approval(), Work(), Search()
    now = [NOW]
    broker = DiscoveryBroker(
        authority=authority, projection=projection, corpus=corpus,
        gates=gates, approval=approval, work=work, search=search,
        clock=lambda: now[0],
    )
    return broker, authority, projection, corpus, gates, approval, work, search, now


def test_qualified_corpus_reuse_precedes_projection_ledger_and_provider():
    broker, authority, projection, corpus, _, approval, work, search, _ = harness()
    corpus.status = "sufficient"
    approval.enabled = False
    assert broker.discover(request()) == BrokerResult(status="reused_corpus", receipt_id="coverage.001")
    assert authority.calls == 1
    assert projection.calls == approval.calls == work.calls == len(search.calls) == 0


def test_closed_gate_missing_corpus_or_live_approval_does_not_reserve():
    broker, authority, projection, corpus, gates, approval, work, search, _ = harness()
    gates.enabled = False
    assert broker.discover(request()).status == "closed"
    assert authority.calls == corpus.calls == work.calls == len(search.calls) == 0
    gates.enabled = True
    corpus.reason = "version_stale"
    assert broker.discover(request()).status == "closed"
    corpus.reason = "coverage_gap"
    approval.enabled = False
    assert broker.discover(request()).status == "closed"
    assert projection.calls == work.calls == len(search.calls) == 0


def test_full_demand_policy_and_budget_are_checked_before_ledger():
    broker, authority, projection, corpus, _, _, work, search, _ = harness()
    tampered = demand().model_copy(update={"reading_level": "advanced"})
    assert broker.discover(request(demand=tampered)).status == "closed"
    assert broker.discover(request(policy_generation=3)).status == "closed"
    expired = BUDGET.model_copy(update={"expires_at": NOW - timedelta(seconds=1)})
    assert broker.discover(request(budget=expired)).status == "closed"
    assert corpus.calls == projection.calls == work.calls == len(search.calls) == 0
    authority.trusted = tampered
    # A resolver's full demand still must match the corpus assessment.
    assert broker.discover(request(demand=tampered)).status == "closed"
    assert corpus.calls == 1 and work.calls == 0


def test_projection_is_only_search_input_and_operation_key_has_no_private_text():
    broker, _, projection, _, _, _, work, search, _ = harness()
    assert broker.discover(request()).status == "discovered"
    assert search.calls == [(("Python 3.12", "list"), "attempt.001")]
    assert projection.calls == 1
    assert work.keys[0].startswith("discovery.")
    assert "private" not in work.keys[0] and "actor" not in work.keys[0]
    assert work.outcomes[0].usage_units == 1
    assert work.committed == [(candidate(),)]
    assert work.unknown == []


def test_shared_job_replay_across_requests_does_not_search_again():
    broker, _, _, _, _, _, work, search, _ = harness()
    first = broker.discover(request())
    work.state = "existing"
    replay = broker.discover(request())
    assert first.status == "discovered" and replay.status == "existing_job"
    assert work.keys[0] == work.keys[1]
    assert len(search.calls) == 1 and len(work.outcomes) == 1


def test_revocation_before_attempt_holds_reservation_without_external_call():
    broker, authority, _, _, _, _, work, search, _ = harness()
    work.on_claim = lambda: setattr(authority, "enabled", False)
    assert broker.discover(request()).status == "closed"
    assert work.unknown == [None]
    assert not search.calls and not work.outcomes


def test_gate_closes_after_attempt_holds_unknown_even_without_call():
    broker, _, _, _, gates, _, work, search, _ = harness()
    work.on_prepare = lambda: setattr(gates, "enabled", False)
    assert broker.discover(request()).status == "closed"
    assert work.unknown == [work.ticket]
    assert not search.calls


def test_revocation_during_search_still_settles_but_never_commits():
    broker, authority, _, _, _, _, work, search, _ = harness()
    search.on_search = lambda: setattr(authority, "enabled", False)
    assert broker.discover(request()).status == "closed"
    assert len(work.outcomes) == 1 and not work.committed and not work.unknown


@pytest.mark.parametrize("status", ["failed", "uncertain"])
def test_ordinary_failures_do_not_signal_existing_only(status):
    broker, _, _, _, _, _, work, search, _ = harness()
    search.result = SearchResult(status=status)
    assert broker.discover(request()).status == "closed"
    assert len(work.outcomes) == 1 and work.outcomes[0].usage_units is None
    assert not work.committed


def test_only_persisted_confirmed_account_exhaustion_emits_existing_only():
    broker, _, _, _, _, _, work, search, _ = harness()
    search.result = SearchResult(status="account_exhausted", quota_receipt_id="quota.001")
    assert broker.discover(request()).status == "existing_only"
    assert work.outcomes[0].quota_receipt_id == "quota.001"
    assert not work.committed
    work.accept_outcome = False
    assert broker.discover(request()).status == "closed"
    assert len(work.unknown) == 2


def test_search_exception_or_lost_receipt_preserves_unknown_usage():
    broker, _, _, _, _, _, work, search, _ = harness()
    def fail():
        raise TimeoutError("secret provider response")
    search.on_search = fail
    assert broker.discover(request()).status == "closed"
    assert work.unknown == [work.ticket] and not work.committed
    search.on_search = None
    search.result = SearchResult(status="completed", candidates=(candidate(),))
    assert broker.discover(request()).status == "closed"
    assert work.outcomes[-1].usage_receipt_id is None
    assert not work.committed


def test_stale_lease_and_untrusted_candidate_never_commit():
    broker, _, _, _, _, _, work, search, _ = harness()
    work.ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=3)
    assert broker.discover(request()).status == "closed"
    assert not search.calls and work.unknown == [work.ticket]
    work.ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    search.result = SearchResult(status="completed", candidates=(candidate(demand_hash=H2),),
                                 usage_units=1, usage_receipt_id="usage.001")
    assert broker.discover(request()).status == "closed"
    assert len(work.outcomes) == 1 and not work.committed


def test_expiration_after_search_prevents_candidate_commit():
    broker, _, _, _, _, _, work, search, now = harness()
    search.on_search = lambda: now.__setitem__(0, datetime(2026, 9, 26, tzinfo=timezone.utc))
    assert broker.discover(request()).status == "closed"
    assert len(work.outcomes) == 1 and not work.committed
class FakeTransport:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload
        self.calls = []

    def search(self, body):
        from app.services.grounding.autonomous.tavily_search import TavilyResponse

        self.calls.append(body)
        return TavilyResponse(self.status_code, self.payload)


def projected_demand():
    from app.services.grounding.autonomous.contracts import SourceDiscoveryDemand

    return SourceDiscoveryDemand(
        demand_hash=H, scope=SCOPE, query_terms=("Python 3.12", "list"),
        actor_id="actor.001", policy_id="policy.001", policy_generation=2,
        budget=BUDGET,
    )


def test_tavily_bridge_requires_gate_on_each_instance_without_second_reserve():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={
        "request_id": "request_12345678", "usage": {"credits": 1},
        "results": [{"url": "https://docs.python.org/3/"}],
    })
    work = Work()  # shared fake state checks bridge protocol, not DB durability
    bridge = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True)
    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    result = bridge.search(projected_demand(), work.claim, ticket)
    assert result.status == "completed"
    assert result.usage_units is None and result.usage_receipt_id is None
    assert result.candidates == (candidate(),)
    assert transport.calls[0]["query"] == "Python 3.12 list"
    assert transport.calls[0]["include_raw_content"] is False
    restarted = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True)
    assert restarted.search(projected_demand(), work.claim, ticket).status == "uncertain"
    assert len(transport.calls) == 1


@pytest.mark.parametrize("code,payload,expected", [
    (432, {"detail": {"error": "This request exceeds your plan's set usage limit"}}, "uncertain"),
    (432, {"detail": {"error": "unrelated"}}, "failed"),
    (429, {"detail": {"error": "rate limited"}}, "failed"),
    (401, {"detail": {"error": "unauthorized"}}, "failed"),
])
def test_offline_fake_quota_classifier_cannot_certify_account_exhaustion(code, payload, expected):
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(status_code=code, payload=payload)
    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    work = Work()
    result = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True).search(
        projected_demand(), work.claim, ticket,
    )
    assert result.status == expected
    assert result.usage_units is None and result.usage_receipt_id is None
    assert result.quota_receipt_id is None


def test_bridge_missing_provider_usage_receipt_cannot_settle():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={
        "usage": {"credits": 1}, "results": [{"url": "https://docs.python.org/3/"}],
    })
    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    work = Work()
    result = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True).search(
        projected_demand(), work.claim, ticket,
    )
    assert result.status == "completed"
    assert result.usage_units is None and result.usage_receipt_id is None


def test_bridge_invalid_response_or_transport_failure_cannot_settle():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={"request_id": "request_12345678", "usage": {"credits": 1}, "results": "bad"})
    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    work = Work()
    result = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True).search(
        projected_demand(), work.claim, ticket,
    )
    assert result.status == "uncertain" and result.usage_units is None

def test_malformed_search_result_is_unknown_not_settled():
    broker, _, _, _, _, _, work, search, _ = harness()
    search.result = SearchResult.model_construct(
        status="completed", candidates=(candidate(),), usage_units=1,
        usage_receipt_id=None,
    )
    assert broker.discover(request()).status == "closed"
    assert work.unknown == [work.ticket]
    assert not work.outcomes and not work.committed


def test_tavily_bridge_transport_timeout_is_unknown():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    class TimeoutTransport:
        def search(self, body):
            raise TimeoutError("secret")

    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    work = Work()
    result = PreparedTavilySearchBridge(transport=TimeoutTransport(), dispatch=work, enabled=True, offline_protocol_test=True).search(
        projected_demand(), work.claim, ticket,
    )
    assert result.status == "failed" and result.usage_units is None

def test_query_job_key_changes_with_reviewed_query_but_root_stays_shared():
    broker, _, projection, _, _, _, work, _, _ = harness()
    work.state = "existing"
    assert broker.discover(request()).status == "existing_job"
    projection.terms = ("Python 3.12", "dict")
    assert broker.discover(request()).status == "existing_job"
    assert work.keys[0] != work.keys[1]
    # Both operations used the same delegation/root in claim_or_reuse;
    # cumulative root-period spend is the ledger adapter's obligation.
    assert len(work.keys) == 2


def test_search_cannot_promote_landing_to_document_without_probe_receipt():
    broker, _, _, _, _, _, work, search, _ = harness()
    search.result = SearchResult(
        status="completed", candidates=(candidate(kind="document"),),
        usage_units=1, usage_receipt_id="usage.001",
    )
    assert broker.discover(request()).status == "closed"
    assert len(work.outcomes) == 1 and not work.committed


def test_bridge_without_durable_dispatch_gate_fails_closed():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={"request_id": "request_12345678", "usage": {"credits": 1},
                                       "results": [{"url": "https://docs.python.org/3/"}]})
    ticket = AttemptTicket(job_id="job.001", attempt_id="attempt.001", lease_generation=2)
    result = PreparedTavilySearchBridge(transport=transport, dispatch=None, enabled=True, offline_protocol_test=True).search(
        projected_demand(), Work().claim, ticket,
    )
    assert result.status == "uncertain" and transport.calls == []


def test_failed_prepare_after_reservation_never_refunds_from_local_state():
    broker, _, _, _, _, _, work, search, _ = harness()
    def fail():
        raise RuntimeError("persisted attempt might be ambiguous")
    work.on_prepare = fail
    assert broker.discover(request()).status == "closed"
    assert work.unknown == [None]
    assert not search.calls

def test_bridge_rejects_forged_projection_before_transport_or_gate_consumption():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={"request_id": "request_12345678", "usage": {"credits": 1},
                                       "results": []})
    work = Work()
    bridge = PreparedTavilySearchBridge(transport=transport, dispatch=work, enabled=True, offline_protocol_test=True)
    forged = projected_demand().model_copy(update={"query_terms": ("private dialogue",)})
    assert bridge.search(forged, work.claim, work.ticket).status == "uncertain"
    assert not transport.calls and not work.dispatched
    assert bridge.search(projected_demand(), work.claim, work.ticket).status == "completed"
    assert len(transport.calls) == 1

def test_settled_empty_or_invalid_leads_are_terminal_not_discovered():
    broker, _, _, _, _, _, work, search, _ = harness()
    for leads in ((), (candidate(kind="document"),),
                  (candidate(url="https://example.org/?private=1"),)):
        search.result = SearchResult(status="completed", candidates=leads,
                                     usage_units=1, usage_receipt_id="usage.001")
        assert broker.discover(request()).status == "closed"
        assert not work.committed
        assert work.outcomes[-1].usage_units == 1

def _observed_http_bridge(status_code, payload):
    """Fake HTTP only: no provider, credential, network or DB evidence."""
    from uuid import uuid4

    import httpx
    import json

    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge
    from app.services.grounding.autonomous.tavily_search import HttpxTavilyTransport
    from app.services.grounding.autonomous.tavily_usage_authority import TavilyUsageAuthority

    sent = []

    def reply(request):
        sent.append(request)
        return httpx.Response(status_code, stream=httpx.ByteStream(json.dumps(payload).encode()),
                              headers={"content-type": "application/json"})

    transport = HttpxTavilyTransport(
        api_key="fake_test_key_12345678", enabled=True,
        http_transport=httpx.MockTransport(reply),
    )
    authority = TavilyUsageAuthority(transport, allow_mock_transport=True)
    work = Work()
    identity = uuid4()
    ticket = AttemptTicket(job_id=work.claim.job_id,
                           attempt_id=f"attempt.{identity.hex}", lease_generation=2)
    work.ticket = ticket
    bridge = PreparedTavilySearchBridge(
        dispatch=work, usage_authority=authority, enabled=True,
    )
    return bridge, authority, work, ticket, identity, sent


def test_bridge_default_without_authority_never_dispatches_or_calls_fake_transport():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge

    transport = FakeTransport(payload={"request_id": "request_12345678",
                                       "usage": {"credits": 1}, "results": []})
    work = Work()
    result = PreparedTavilySearchBridge(
        transport=transport, dispatch=work, enabled=True,
    ).search(projected_demand(), work.claim, work.ticket)
    assert result.status == "uncertain"
    assert not work.dispatched and transport.calls == []


def test_bridge_uses_exact_observed_usage_not_self_report_or_hash():
    bridge, authority, work, ticket, identity, sent = _observed_http_bridge(
        200, {"request_id": "request_12345678", "usage": {"credits": 1},
              "results": [{"url": "https://docs.python.org/3/", "content": "untrusted"}]},
    )
    result = bridge.search(projected_demand(), work.claim, ticket)
    assert result.status == "completed" and result.usage_units == 1
    assert result.usage_receipt_id == authority.usage_receipt(identity, "request_12345678", 1)
    assert result.usage_receipt_id is not None and result.usage_receipt_id.startswith("usage.")
    assert authority.usage_receipt(identity, "request_12345678", 2) is None
    assert not authority.verify_usage(identity, "usage." + "0" * 48, 1)
    assert authority.verify_usage(identity, result.usage_receipt_id, 1)
    assert not authority.verify_usage(identity, result.usage_receipt_id, 1)
    assert len(sent) == 1 and sent[0].headers["Authorization"].startswith("Bearer ")
    assert bridge.search(projected_demand(), work.claim, ticket).status == "uncertain"
    assert len(sent) == 1


@pytest.mark.parametrize("status,payload,expected", [
    (432, {"detail": {"error": "This request exceeds your plan's set usage limit"}}, "account_exhausted"),
    (429, {"detail": {"error": "rate limited"}}, "failed"),
    (401, {"detail": {"error": "unauthorized"}}, "failed"),
    (432, {"detail": {"error": "unrelated"}}, "failed"),
])
def test_bridge_quota_requires_same_observed_authority(status, payload, expected):
    bridge, authority, work, ticket, identity, sent = _observed_http_bridge(status, payload)
    result = bridge.search(projected_demand(), work.claim, ticket)
    assert result.status == expected and len(sent) == 1
    if expected == "account_exhausted":
        assert result.quota_receipt_id == authority.quota_receipt(identity)
        assert authority.verify_account_exhausted(identity, result.quota_receipt_id)
        assert not authority.verify_account_exhausted(identity, result.quota_receipt_id)
    else:
        assert result.quota_receipt_id is None
        assert not authority.verify_account_exhausted(identity, ticket.attempt_id)


def test_bridge_failed_attempt_binding_after_dispatch_stays_unknown():
    from app.services.grounding.autonomous.discovery_broker import PreparedTavilySearchBridge
    from app.services.grounding.autonomous.tavily_search import HttpxTavilyTransport
    from app.services.grounding.autonomous.tavily_usage_authority import TavilyUsageAuthority

    work = Work()  # Its test handle cannot be bound as an authoritative UUID.
    authority = TavilyUsageAuthority(HttpxTavilyTransport())
    bridge = PreparedTavilySearchBridge(dispatch=work, usage_authority=authority, enabled=True)
    assert bridge.search(projected_demand(), work.claim, work.ticket).status == "uncertain"
    assert work.dispatched == {work.ticket.attempt_id}