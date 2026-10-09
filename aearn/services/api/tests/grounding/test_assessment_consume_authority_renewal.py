"""One OFFLINE resolver regression; rows/transport doubles are not live proof."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentConsumeAuthority,
)
from app.services.grounding.autonomous.contracts import RagBudgetDelegation
from app.services.grounding.public_course_contracts import public_course_demand


def test_public_demand_renewal_selects_exact_current_authority_not_latest(monkeypatch):
    now = datetime(2026, 10, 6, 8, 30, tzinfo=UTC)
    demand = public_course_demand("python-state-update-v1")
    budget = RagBudgetDelegation(root_id="root.current", delegation_id="delegation.current",
        generation=2, expires_at=now+timedelta(days=7))
    prepared = SimpleNamespace(demand=demand, consume_actor="service.rag-public-course",
        policy_id="policy.current", policy_generation=2, budget=budget)
    request = AccessRequest(demand_hash=demand.demand_hash, scope=demand.scope,
        purpose="assessment_evidence", actor_id=prepared.consume_actor, action="consume",
        policy_id=prepared.policy_id, policy_generation=prepared.policy_generation, budget=budget)
    current = dict(id=uuid4(), claim_handle="claim.current", demand_hash=demand.demand_hash,
        policy_id=request.policy_id, policy_generation=request.policy_generation, root_id=budget.root_id,
        revoked_at=None, issued_at=now-timedelta(minutes=1), expires_at=budget.expires_at)
    old = dict(current, id=uuid4(), claim_handle="claim.expired-old", policy_id="policy.old",
        policy_generation=1, root_id="root.old", expires_at=now-timedelta(seconds=1))
    rows = [old]
    # Each header dimension is necessary; unrelated unexpired history must not
    # make a unique matching renewal ambiguous, and elapsed/revoked rows deny.
    for changes in (
        {"policy_id":"policy.other"}, {"policy_generation":1}, {"root_id":"root.other"},
        {"expires_at":now}, {"revoked_at":now}, {"issued_at":now+timedelta(seconds=1)},
    ):
        rows.append(dict(current, id=uuid4(), **changes))
    rows.append(current)
    original_rows = deepcopy(rows)
    events = []

    class Connection:
        def execute(self, sql, params):
            assert "WHERE demand_hash=%s AND policy_id=%s AND policy_generation=%s AND root_id=%s" in sql
            assert "revoked_at IS NULL" in sql and "issued_at<=clock_timestamp()" in sql
            assert "expires_at>clock_timestamp()" in sql
            assert "FOR SHARE" not in sql and "FOR UPDATE" not in sql  # Discovery only.
            assert "ORDER BY id LIMIT 3" in sql and "DESC" not in sql
            selected = [r for r in rows if (r["demand_hash"], r["policy_id"], r["policy_generation"], r["root_id"]) == params
                and r["revoked_at"] is None and r["issued_at"] <= now < r["expires_at"]]
            selected.sort(key=lambda r: str(r["id"]))
            return SimpleNamespace(fetchall=lambda: selected[:3])

    repo = object.__new__(AssessmentReceiptRepository)
    repo.conn = Connection()
    monkeypatch.setattr(repo, "require_transaction", lambda: None)

    def lock_corpus(handle):
        assert handle == current["claim_handle"]
        events.append("corpus")

    def load_proof(evidence_id):
        assert events == ["corpus"] and evidence_id == current["id"]
        events.append("proof")
        return SimpleNamespace(prepared=prepared), "offline-capture", {}

    def current_corpus(payload, capture):
        assert events == ["corpus", "proof"] and capture == "offline-capture"
        events.append("active")

    monkeypatch.setattr(repo, "_lock_active_corpus", lock_corpus)
    monkeypatch.setattr(repo, "_load", load_proof)
    monkeypatch.setattr(repo, "_active", current_corpus)
    authority = PostgresAssessmentConsumeAuthority(repo)
    result = authority.resolve(request)
    assert result is not None and result.authorized and result.demand == demand and result.budget == budget
    assert events == ["corpus", "proof", "active"] and rows == original_rows

    events.clear()
    assert authority.resolve(request.model_copy(update={"policy_id":"policy.absent"})) is None
    assert events == []  # No matching delegation, no proof/source locking.
    assert authority.resolve(request.model_copy(update={"actor_id":"service.wrong"})) is None
    assert events == ["corpus", "proof", "active"]  # Header match is NOT full request authority.

    events.clear()
    rows.append(dict(current, id=uuid4(), claim_handle="claim.another-current", issued_at=now))
    assert authority.resolve(request) is None and events == []  # Two exact current proofs: no latest wins.
    assert rows[:-1] == original_rows
