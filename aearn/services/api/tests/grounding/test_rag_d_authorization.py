"""D authorization defaults and exact-bound receipt protocol; offline, no DB."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from psycopg.pq import TransactionStatus

from app.services.grounding.autonomous.access_policy import AutonomousGates
from app.services.grounding.current_authorization import (
    AuthorizationReceipt, CurrentAuthorization, EvidenceDenied, project_covered_facets,
)
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from tests.grounding.test_rag_d_contracts import _fixture


class NoIO:
    autocommit = False
    info = SimpleNamespace(transaction_status=TransactionStatus.INTRANS)

    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("gate closed should not touch DB")


def test_default_off_is_zero_io() -> None:
    db = NoIO()
    governance = SimpleNamespace(conn=db)
    for service in (
        CurrentAuthorization(db, governance=governance),
        EvidenceSelection(db, governance=governance, request_for=lambda _: None),
        CurrentAuthorization(db, governance=governance,
                             gates=AutonomousGates(evidence_consumer=True)),
    ):
        with pytest.raises(EvidenceDenied, match="GATE_CLOSED"):
            service.require_transaction()


def test_binding_callback_closed_gate_never_reads_persisted_selection() -> None:
    db = NoIO()
    service = EvidenceSelection(
        db, governance=SimpleNamespace(conn=db), request_for=lambda _: None,
        selections=SimpleNamespace(conn=db),
    )
    with pytest.raises(EvidenceDenied, match="GATE_CLOSED"):
        service.authorize_binding(db, None)  # type: ignore[arg-type]


def test_ready_receipt_must_prove_facets_from_exact_chunks(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    selection, _ = _fixture()
    db = NoIO()

    def request_for(requirement):  # type: ignore[no-untyped-def]
        demand = requirement.demand
        return SimpleNamespace(demand_hash=demand.demand_hash, scope=demand.scope,
                               purpose=demand.purpose, action="consume")

    service = EvidenceSelection(db, governance=SimpleNamespace(conn=db),
                                request_for=request_for,
                                gates=AutonomousGates(evidence_consumer=True), enabled=True)
    monkeypatch.setattr(service, "require_transaction", lambda: None)
    monkeypatch.setattr(service, "_clock", lambda: datetime.now(UTC))
    monkeypatch.setattr("app.services.grounding.evidence_binding_v2.check_access",
                        lambda *_args, **_kwargs: SimpleNamespace(allowed=True))
    # The reviewed chunk can legitimately cover more than this narrow demand.
    covered = project_covered_facets(("queries",), (("queries", "schema"),))
    assert covered == ("queries",)
    monkeypatch.setattr(service, "check_current_authorization",
        lambda binding, purpose, **_kwargs: AuthorizationReceipt(
            binding_digest=binding.binding_digest, purpose=purpose,
            corpus_version_id=binding.evidence[0].corpus_version_id,
            active_generation=1, source_policy_generations=(), admission_receipt_ids=(),
            original_source_digests=(), exact_evidence_digest="0" * 64, covered_facets=covered, checked_at=datetime.now(UTC),
        ))
    assert service.authorize_selection(db, selection).kind == "selection"
    entry = selection.entries[0]
    assert service.freeze_binding(selection, node_id=entry.node_id, goal_hash=entry.goal_hash,
                                  purpose=entry.purpose, request=None)[1].covered_facets == covered  # type: ignore[arg-type]
    covered = ()  # A missing demanded facet must not be laundered into ready.
    with pytest.raises(EvidenceDenied, match="EVIDENCE_INSUFFICIENT"):
        service.authorize_selection(db, selection)
    with pytest.raises(EvidenceDenied, match="EVIDENCE_INSUFFICIENT"):
        service.freeze_binding(selection, node_id=entry.node_id, goal_hash=entry.goal_hash,
                               purpose=entry.purpose, request=None)  # type: ignore[arg-type]


def test_read_only_transaction_cannot_issue_fence_receipt() -> None:
    class ReadOnly(NoIO):
        def execute(self, sql: str) -> SimpleNamespace:
            if sql == "SHOW transaction_isolation":
                return SimpleNamespace(fetchone=lambda: {"transaction_isolation": "read committed"})
            if sql == "SHOW transaction_read_only":
                return SimpleNamespace(fetchone=lambda: {"transaction_read_only": "on"})
            raise AssertionError("read-only denial should not access corpus")

    db = ReadOnly()
    governance = SimpleNamespace(conn=db, _transaction=lambda: None)
    service = CurrentAuthorization(
        db, governance=governance, gates=AutonomousGates(evidence_consumer=True), enabled=True,
    )
    with pytest.raises(EvidenceDenied, match="TRANSACTION_REQUIRED"):
        service.require_transaction()


def test_wrong_connection_and_autocommit_are_denied_before_c_port() -> None:
    db = NoIO()
    other = NoIO()
    service = CurrentAuthorization(db, governance=SimpleNamespace(conn=other),
                                   gates=AutonomousGates(evidence_consumer=True), enabled=True)
    with pytest.raises(EvidenceDenied, match="TRANSACTION_REQUIRED"):
        service.require_transaction()
    db.autocommit = True
    service = CurrentAuthorization(db, governance=SimpleNamespace(conn=db),
                                   gates=AutonomousGates(evidence_consumer=True), enabled=True)
    with pytest.raises(EvidenceDenied, match="TRANSACTION_REQUIRED"):
        service.require_transaction()
