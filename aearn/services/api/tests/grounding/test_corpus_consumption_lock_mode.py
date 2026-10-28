"""Lock selection only; protocol doubles do not prove source quality or PG races."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from app.services.grounding.autonomous.corpus_governance import (
    CorpusGovernance, CorpusGovernanceDenied,
)
from app.services.grounding.corpus_repository import CorpusRepository, _hash


CORPUS = UUID("1f25a966-1ba1-53e9-acf6-e20dc168c435")
VALIDATION = {"qualified": True}
COVERAGE = {"queries": True}
ADMISSIONS, FACETS = "1" * 64, "2" * 64


class RecordingConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []
        summary = _hash([
            str(CORPUS), "a" * 64, _hash([]), _hash([[], []]),
            VALIDATION, COVERAGE, "retrieval.test", "coverage.test",
        ])
        self.version = dict(
            id=CORPUS, subject_id="route.sql", subject_version="1.0",
            registry_digest="a" * 64, state="published", generation=2,
            source_set_hash=_hash([]), content_hash=_hash([[], []]), summary_hash=summary,
            retrieval_policy_version="retrieval.test", coverage_policy_version="coverage.test",
            coverage_summary_json=COVERAGE, validation_summary_json=VALIDATION,
        )

    def execute(self, query: str, params: object = None) -> SimpleNamespace:
        self.queries.append(query)
        if query.startswith("SELECT * FROM grounding_corpus_versions"):
            return SimpleNamespace(fetchone=lambda: self.version)
        if "FROM rag_corpus_validation_receipts r" in query:
            receipt = dict(
                summary_hash=self.version["summary_hash"], admission_digest=ADMISSIONS,
                coverage_digest=FACETS, review_policy_generation=5, partial_coverage=False,
            )
            return SimpleNamespace(fetchone=lambda: receipt)
        return SimpleNamespace(fetchall=lambda: [])


@pytest.mark.parametrize(("options", "suffix"), [
    ({}, ""), ({"for_update": True}, " FOR UPDATE"), ({"for_share": True}, " FOR SHARE"),
])
def test_repository_selects_explicit_lock_without_changing_default(
    options: dict[str, bool], suffix: str,
) -> None:
    conn = RecordingConnection()
    version = CorpusRepository(cast(Any, conn)).version(CORPUS, **options)
    assert version.corpus_id == CORPUS
    assert conn.queries == ["SELECT * FROM grounding_corpus_versions WHERE id=%s" + suffix]


def test_repository_rejects_ambiguous_lock_before_query() -> None:
    conn = RecordingConnection()
    with pytest.raises(ValueError, match="mutually exclusive"):
        CorpusRepository(cast(Any, conn)).version(CORPUS, for_update=True, for_share=True)
    assert not conn.queries


def test_governance_consumption_rows_keep_share_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = RecordingConnection()
    governance = CorpusGovernance(cast(Any, conn))
    # This test exercises SQL lock choice, not transaction/source authority.
    monkeypatch.setattr(governance, "_transaction", lambda: None)
    governance._rows(CORPUS, consumption_read=True)
    assert conn.queries[0].endswith(" FOR SHARE")
    assert all("FOR UPDATE" not in query for query in conn.queries)
    conn.queries.clear()
    governance._rows(CORPUS)
    assert conn.queries[0].endswith(" FOR UPDATE")
    conn.queries.clear()
    with pytest.raises(CorpusGovernanceDenied, match="CONSUMPTION_LOCK_REQUIRED"):
        governance._rows(CORPUS, lock=False, consumption_read=True)
    assert not conn.queries


@pytest.mark.parametrize("consumption", [False, True])
def test_verified_propagates_mode_through_audit_without_upgrade(
    consumption: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = RecordingConnection()
    governance = CorpusGovernance(cast(Any, conn))
    audit_modes: list[bool] = []

    def audit(corpus_id: UUID, *, purpose: str, consumption_read: bool = False) -> tuple[Any, ...]:
        assert corpus_id == CORPUS and purpose == "main_teaching"
        audit_modes.append(consumption_read)
        return VALIDATION, COVERAGE, ADMISSIONS, FACETS, 5, False

    # Keep the real verified snapshot/digest checks; this double supplies only
    # audit DATA so the test makes no teaching/current-authority claim.
    monkeypatch.setattr(governance, "_audit", audit)
    governance._verified(
        CORPUS, summary_hash=str(conn.version["summary_hash"]), purpose="main_teaching",
        consumption_read=consumption,
    )
    assert audit_modes == [consumption]
    assert conn.queries[0].endswith(" FOR SHARE" if consumption else " FOR UPDATE")


@pytest.mark.parametrize("consumption", [False, True])
def test_real_verified_audit_rows_chain_retains_mode_before_quality_denial(
    consumption: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = RecordingConnection()
    governance = CorpusGovernance(cast(Any, conn))
    monkeypatch.setattr(governance, "_transaction", lambda: None)
    # Do not mock _audit or _rows: this closes the prior pair of isolated
    # propagation tests. Empty fixture snapshots must still fail the real audit;
    # reaching the lock boundary is not source-quality/current-use acceptance.
    with pytest.raises(CorpusGovernanceDenied, match="SNAPSHOT_INCOMPLETE"):
        governance._verified(CORPUS, summary_hash=str(conn.version["summary_hash"]),
            purpose="main_teaching", consumption_read=consumption)
    versions = [query for query in conn.queries if query.startswith("SELECT * FROM grounding_corpus_versions")]
    suffix = " FOR SHARE" if consumption else " FOR UPDATE"
    assert versions == ["SELECT * FROM grounding_corpus_versions WHERE id=%s" + suffix] * 2
    assert any("FOR SHARE OF link,doc,src,admission,review" in query for query in conn.queries)


def _assessment_bridge(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    from tests.grounding.test_actual_d_private_provenance import _provenance_protocol, setup

    # Reuse the existing signed/ephemeral OFFLINE protocol. Original proof,
    # source, claim, active-pointer and final-clock owners are not stubbed here.
    _provenance_protocol.__wrapped__(monkeypatch)
    return setup(monkeypatch)


@pytest.mark.parametrize("kind", ["claim", "execution", "consume_authority"])
def test_real_public_assessment_resolvers_keep_outer_share_lock(
    kind: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.grounding.autonomous.access_policy import AccessRequest
    from app.services.grounding.autonomous.assessment_receipt_repository import (
        PostgresAssessmentClaimResolver, PostgresAssessmentExecutionResolver,
        PostgresAssessmentConsumeAuthority,
    )

    conn, repository = _assessment_bridge(monkeypatch)
    public, q = conn.public, conn.public.prepared
    conn.trace.clear()
    CorpusRepository(conn).version(conn.cid, for_share=True)
    if kind == "claim":
        result = PostgresAssessmentClaimResolver(repository).resolve(public.claim_handle)
    elif kind == "execution":
        result = PostgresAssessmentExecutionResolver(repository).resolve(public.execution_handle)
    else:
        request = AccessRequest(demand_hash=q.demand.demand_hash, scope=q.demand.scope,
            purpose="assessment_evidence", actor_id=q.consume_actor, action="consume",
            policy_id=q.policy_id, policy_generation=q.policy_generation, budget=q.budget)
        result = PostgresAssessmentConsumeAuthority(repository).resolve(request)
    assert result is not None and result.scope == q.demand.scope
    versions = [sql for sql in conn.trace if sql.startswith("SELECT * FROM grounding_corpus_versions")]
    assert versions == ["SELECT * FROM grounding_corpus_versions WHERE id=%s FOR SHARE"] * 2
    assert any("FOR SHARE OF v,active,r,l,c" in sql for sql in conn.trace)
    assert "SELECT clock_timestamp() AS now" in conn.trace
    assert conn.bridge is None  # PUBLIC resolution does not materialize private provenance.


@pytest.mark.parametrize("state", ["first", "existing", "purged_after_hint"])
def test_actual_d_provenance_locks_first_write_but_only_reads_existing(
    state: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
    from tests.grounding.test_actual_d_private_provenance import preparation_owner

    conn, repository = _assessment_bridge(monkeypatch)
    owner = preparation_owner(conn, repository, monkeypatch)
    handle = conn.private.claim_handle
    if state != "first":
        repository.private_provenance(handle, preparation_owner=owner)
    conn.trace.clear()
    if state == "purged_after_hint":
        execute = conn.execute

        def purge_after_hint(sql: str, params: tuple[Any, ...] = ()) -> Any:
            result = execute(sql, params)
            if " ".join(sql.split()).startswith("SELECT private_evidence_id FROM rag_actual_d_private_provenance"):
                assert conn.bridge is not None
                conn.bridge = None
            return result

        monkeypatch.setattr(conn, "execute", purge_after_hint)
        with pytest.raises(SourceAssessmentDenied, match="SOURCE_PRIVATE_PROVENANCE_STALE"):
            repository.private_provenance(handle, preparation_owner=owner)
        assert conn.bridge is None
    else:
        result = repository.private_provenance(handle, preparation_owner=owner)
        assert result.private == conn.private and result.public == conn.public
        assert result.corpus_id == conn.cid and result.generation == conn.generation
        assert conn.trace[-1] == "SELECT clock_timestamp() AS now"
    versions = [sql for sql in conn.trace if sql.startswith("SELECT * FROM grounding_corpus_versions")]
    suffix = "UPDATE" if state == "first" else "SHARE"
    assert versions == ["SELECT * FROM grounding_corpus_versions WHERE id=%s FOR " + suffix]
    inserts = [sql for sql in conn.trace if sql.startswith("INSERT INTO rag_actual_d_private_provenance")]
    assert len(inserts) == (1 if state == "first" else 0)
    assert any(sql.startswith("SELECT * FROM rag_actual_d_private_provenance") and sql.endswith("FOR SHARE")
        for sql in conn.trace)


@pytest.mark.parametrize("fault", ["proof", "source", "chunk", "row", "final_clock"])
def test_existing_provenance_share_hint_cannot_skip_original_current_fences(
    fault: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
    from tests.grounding.test_actual_d_private_provenance import preparation_owner

    conn, repository = _assessment_bridge(monkeypatch)
    owner = preparation_owner(conn, repository, monkeypatch)
    handle = conn.private.claim_handle
    repository.private_provenance(handle, preparation_owner=owner)
    conn.trace.clear()
    if fault == "proof":
        conn.evidence[conn.private.evidence_id]["signed_proof"]["signature_hex"] = "0" * 128
    elif fault == "source":
        conn.policies[conn.private.prepared.capture_id]["allowed_usages"] = []
    elif fault == "chunk":
        conn.chunks[0]["chunk_hash"] = "0" * 64
    elif fault == "row":
        conn.bridge["private_proof_hash"] = "0" * 64
    else:
        execute = conn.execute

        def expire_after_locked_association(sql: str, params: tuple[Any, ...] = ()) -> Any:
            result = execute(sql, params)
            if " ".join(sql.split()).startswith("SELECT * FROM rag_actual_d_private_provenance"):
                conn.now = min(conn.private.expires_at, conn.public.expires_at)
            return result

        monkeypatch.setattr(conn, "execute", expire_after_locked_association)
    with pytest.raises((SourceAssessmentDenied, ValueError)):
        repository.private_provenance(handle, preparation_owner=owner)
    versions = [sql for sql in conn.trace if sql.startswith("SELECT * FROM grounding_corpus_versions")]
    assert versions == ["SELECT * FROM grounding_corpus_versions WHERE id=%s FOR SHARE"]
    assert not any(sql.startswith("INSERT INTO rag_actual_d_private_provenance") for sql in conn.trace)
    if fault == "final_clock":
        assert conn.trace[-1] == "SELECT clock_timestamp() AS now"
