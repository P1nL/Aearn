"""Offline fake-port tests only; no PostgreSQL/provider/egress acceptance claim."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from psycopg.pq import TransactionStatus

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.autonomous.budget import BudgetDenied, ReservationDecision
from app.services.grounding.autonomous.contracts import ContentCapture, SourceCandidate, SourceDiscoveryDemand
from app.services.grounding.autonomous.discovery_broker import (
    AttemptTicket, SearchSettlement, WorkClaim, _query_operation_id,
)
from app.services.grounding.autonomous.discovery_work import (
    PostgresDiscoveryWork, WorkContext, _handle, _uuid,
)
from app.services.grounding.autonomous.jobs import JobLease
from tests.grounding.rag_material_helpers import Authority, BUDGET, H, NOW, SCOPE, demand


class FakeConnection:
    """Transaction boundary spy, not a PostgreSQL concurrency simulation."""

    autocommit = False

    def __init__(self):
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self.events = []
        self.rows = []

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == TransactionStatus.IDLE
        self.info.transaction_status = TransactionStatus.INTRANS
        self.events.append("begin")
        try:
            yield
        except Exception:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")
        finally:
            self.info.transaction_status = TransactionStatus.IDLE

    def execute(self, sql, args):
        self.events.append("sql")
        assert self.rows
        return SimpleNamespace(fetchone=lambda: self.rows.pop(0))


class FakeContext:
    def __init__(self, value):
        self.value = value
        self.issued = True

    def resolve_issued(self, d, p):
        return self.value if self.issued else None

    def resolve_job(self, job_id):
        return self.value


class FakePermission:
    def __init__(self):
        self.enabled = True

    def permitted(self):
        return self.enabled


class FakeUsage:
    def __init__(self):
        self.enabled = True

    def verify_usage(self, attempt_id, receipt_id, units):
        return self.enabled and receipt_id == "usage.001" and units == 1

    def verify_account_exhausted(self, attempt_id, receipt_id):
        return self.enabled and receipt_id == _handle("attempt", attempt_id)


def projection():
    return SourceDiscoveryDemand(demand_hash=H, scope=SCOPE, query_terms=("Python 3.12", "list"),
                                 actor_id="actor.001", policy_id="policy.001",
                                 policy_generation=2, budget=BUDGET)


def adapter(conn=None):
    db = conn or FakeConnection()
    context = FakeContext(WorkContext(demand(), projection()))
    permission = FakePermission()
    usage = FakeUsage()
    work = PostgresDiscoveryWork(conn=db, authority=Authority(), context=context,
                                 policy=object(), gates=lambda: AutonomousGates(discovery=True),
                                 permission=permission, usage=usage,
                                 owner_id="worker.001", clock=lambda: NOW)
    return work, db, context, permission, usage


def identities():
    job, reservation, attempt = uuid4(), uuid4(), uuid4()
    claim = WorkClaim(job_id=_handle("job", job), reservation_id=_handle("reservation", reservation),
                      lease_owner="worker.001", lease_generation=1)
    ticket = AttemptTicket(job_id=claim.job_id, attempt_id=_handle("attempt", attempt), lease_generation=1)
    lease = JobLease(job, claim.lease_owner, 1, NOW + timedelta(seconds=60))
    return claim, ticket, lease, reservation, attempt


def test_attempt_handle_is_exact_reversible_uuid_not_permission():
    value = uuid4()
    assert _uuid(_handle("attempt", value), "attempt") == value
    for invalid in (str(value), "attempt." + value.hex.upper(), "attempt." + value.hex[:-1],
                    "job." + value.hex, "attempt." + value.hex + "0"):
        with pytest.raises(BudgetDenied, match="INVALID_HANDLE"):
            _uuid(invalid, "attempt")


def test_missing_issuance_or_permission_fails_closed_without_ledger_write():
    work, db, context, permission, _ = adapter()
    key = _query_operation_id(demand(), projection())
    context.issued = False
    assert work.claim_or_reuse(demand(), projection(), key).status == "denied"
    context.issued = True
    permission.enabled = False
    assert work.claim_or_reuse(demand(), projection(), key).status == "denied"
    assert "sql" not in db.events


def test_fake_job_first_write_and_root_reserve_share_transaction():
    work, db, _, _, _ = adapter()
    job_id, reservation_id = uuid4(), uuid4()

    class Jobs:
        def enqueue(self, **kwargs):
            assert db.info.transaction_status == TransactionStatus.INTRANS
            db.events.append("job")
            assert kwargs["projection"] == projection()
            return job_id

        def claim(self, **kwargs):
            db.events.append("lease")
            return JobLease(job_id, "worker.001", 1, NOW + timedelta(seconds=60))

    class Budget:
        def reserve(self, **kwargs):
            assert db.info.transaction_status == TransactionStatus.INTRANS
            assert db.events[-1] == "job"
            db.events.append("reserve")
            assert kwargs["units"] == 1 and kwargs["job_id"] == job_id
            return ReservationDecision(True, "RESERVED", reservation_id)

    work.jobs, work.budget = Jobs(), Budget()
    result = work.claim_or_reuse(demand(), projection(), _query_operation_id(demand(), projection()))
    assert result.status == "claimed"
    assert result.claim.reservation_id == _handle("reservation", reservation_id)
    assert db.events == ["begin", "job", "reserve", "lease", "commit"]

    class DeniedBudget:
        def reserve(self, **kwargs):
            db.events.append("reserve")
            return ReservationDecision(False, "CAP_EXHAUSTED")

    db.events.clear()
    work.budget = DeniedBudget()
    assert work.claim_or_reuse(demand(), projection(), _query_operation_id(demand(), projection())).status == "denied"
    assert db.events == ["begin", "job", "reserve", "rollback"]


def test_dispatch_uses_persisted_cas_and_exact_projection(monkeypatch):
    work, db, _, permission, _ = adapter()
    claim, ticket, lease, reservation, attempt = identities()
    monkeypatch.setattr(work, "_ticket", lambda c, t: (WorkContext(demand(), projection()), lease, attempt, NOW))
    calls = []

    class Budget:
        def take_dispatch(self, **kwargs):
            calls.append(kwargs)
            return len(calls) == 1

    work.budget = Budget()
    assert work.take_dispatch(projection(), claim, ticket)
    assert not work.take_dispatch(projection(), claim, ticket)
    assert len(calls) == 2 and calls[0]["attempt_id"] == attempt
    assert calls[0]["reservation_id"] == reservation
    changed = projection().model_copy(update={"query_terms": ("different",)})
    assert not work.take_dispatch(changed, claim, ticket)
    assert len(calls) == 2
    permission.enabled = False
    assert not work.take_dispatch(projection(), claim, ticket)


def test_outcome_atomically_settles_candidates_and_terminalizes_even_empty(monkeypatch):
    work, db, _, _, usage = adapter()
    claim, ticket, lease, _, attempt = identities()
    monkeypatch.setattr(work, "_ticket", lambda c, t: (WorkContext(demand(), projection()), lease, attempt, NOW))
    candidate = SourceCandidate(kind="landing", demand_hash=H, scope=SCOPE,
                                url="https://example.org/lesson", discovery_receipt_id=ticket.attempt_id,
                                capture=ContentCapture(kind="none", captured_bytes=0))
    events = []

    class Budget:
        def settle(self, **kwargs):
            assert db.info.transaction_status == TransactionStatus.INTRANS
            events.append("settle")
            return SimpleNamespace(state="settled")

        def mark_unknown(self, **kwargs):
            events.append("unknown")

    class Candidates:
        def record_receipt(self, **kwargs):
            assert events == ["settle"]
            events.append("receipt")

        def record_candidate(self, **kwargs):
            assert events == ["settle", "receipt"]
            events.append("candidate")

    class Jobs:
        def complete(self, **kwargs):
            assert db.info.transaction_status == TransactionStatus.INTRANS
            events.append(("terminal", kwargs["success"]))

    work.budget, work.candidates, work.jobs = Budget(), Candidates(), Jobs()
    settlement = SearchSettlement(status="completed", usage_units=1, usage_receipt_id="usage.001")
    db.rows.append({"state": "started"})
    assert not work.record_outcome(claim, ticket, settlement, (candidate,))
    assert events == []
    usage.enabled = False
    db.rows.append({"state": "dispatched"})
    assert not work.record_outcome(claim, ticket, settlement, (candidate,))
    assert events == []
    usage.enabled = True
    db.rows.append({"state": "dispatched"})
    assert work.record_outcome(claim, ticket, settlement, (candidate,))
    assert events == ["settle", "receipt", "candidate", ("terminal", True)]
    assert db.events[-1] == "commit"
    events.clear()
    for leads in ((), (candidate.model_copy(update={"kind": "document"}),),
                  (candidate.model_copy(update={"url": "https://example.org/?private=1"}),)):
        db.rows.append({"state": "dispatched"})
        assert work.record_outcome(claim, ticket, settlement, leads)
        assert events == ["settle", ("terminal", False)]
        events.clear()
    db.rows.append({"state": "dispatched"})
    assert work.record_outcome(claim, ticket, SearchSettlement(status="uncertain"))
    assert events == ["unknown", ("terminal", False)]


def test_fake_attempt_replay_never_gets_dispatch_ticket(monkeypatch):
    work, _, _, _, _ = adapter()
    claim, ticket, lease, reservation, attempt = identities()
    monkeypatch.setattr(work, "_claim", lambda c: (WorkContext(demand(), projection()), lease, reservation, NOW))

    class Budget:
        def record_attempt(self, **kwargs):
            return SimpleNamespace(attempt_id=attempt, created=False, state="started")

    work.budget = Budget()
    assert work.prepare_attempt(claim) is None
    work.budget.record_attempt = lambda **kwargs: SimpleNamespace(attempt_id=attempt, created=True, state="started")
    assert work.prepare_attempt(claim) == ticket


def test_fake_account_exhaustion_holds_unknown_before_existing_only(monkeypatch):
    work, db, _, _, usage = adapter()
    claim, ticket, lease, _, attempt = identities()
    monkeypatch.setattr(work, "_ticket", lambda c, t: (WorkContext(demand(), projection()), lease, attempt, NOW))
    events = []

    class Budget:
        def mark_unknown(self, **kwargs):
            events.append(("hold", kwargs["error_code"]))

    class Jobs:
        def complete(self, **kwargs):
            events.append(("terminal", kwargs["success"]))

    work.budget, work.jobs = Budget(), Jobs()
    db.rows.append({"state": "dispatched"})
    assert work.record_outcome(claim, ticket, SearchSettlement(status="account_exhausted",
                                                                quota_receipt_id=ticket.attempt_id))
    assert events == [("hold", "ACCOUNT_EXHAUSTED"), ("terminal", False)]
    usage.enabled = False
    events.clear()
    db.rows.append({"state": "dispatched"})
    assert not work.record_outcome(claim, ticket, SearchSettlement(status="account_exhausted",
                                                                    quota_receipt_id=ticket.attempt_id))
    assert events == []


def test_fake_unknown_hold_requires_exact_persisted_attempt_not_live_lease():
    work, db, _, _, _ = adapter()
    claim, ticket, _, reservation, _ = identities()
    held = []

    class Budget:
        def mark_unknown(self, **kwargs):
            held.append(kwargs["error_code"])

    class Jobs:
        def fail_if_owned(self, **kwargs):
            held.append("terminal_if_owned")
            return True

    work.budget, work.jobs = Budget(), Jobs()
    db.rows.append({"attempt_key": _handle("attempt", reservation)})
    work.record_unknown(claim, ticket)
    assert held == ["OUTCOME_UNKNOWN", "terminal_if_owned"]
    db.rows.append({"attempt_key": "attempt.00000000000000000000000000000000"})
    work.record_unknown(claim, ticket)
    assert held == ["OUTCOME_UNKNOWN", "terminal_if_owned"]
    assert db.events.count("commit") == 2


def test_fake_dispatch_rejects_uncommitted_caller_transaction():
    work, db, _, _, _ = adapter()
    claim, ticket, _, _, _ = identities()
    db.info.transaction_status = TransactionStatus.INTRANS
    assert not work.take_dispatch(projection(), claim, ticket)
    assert db.events == []

def test_fake_replay_reuses_job_without_new_lease_or_attempt():
    work, db, _, _, _ = adapter()
    job_id, reservation_id = uuid4(), uuid4()
    calls = []

    class Jobs:
        def enqueue(self, **kwargs):
            calls.append("enqueue")
            return job_id

        def claim(self, **kwargs):
            calls.append("claim")
            raise AssertionError("already attempted job must not claim")

    class Budget:
        def reserve(self, **kwargs):
            calls.append("reserve")
            return ReservationDecision(True, "REPLAY", reservation_id)

    work.jobs, work.budget = Jobs(), Budget()
    db.rows.append({"state": "attempted"})
    result = work.claim_or_reuse(demand(), projection(), _query_operation_id(demand(), projection()))
    assert result.status == "existing" and result.job_id == _handle("job", job_id)
    assert calls == ["enqueue", "reserve"]
    assert db.events == ["begin", "sql", "commit"]