"""Two-connection D fence barriers on disposable synthetic C rows only.

No actual item publisher or public materialization is invoked by this test.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg.rows import dict_row

from app.db.bootstrap import apply_schema
from app.services.grounding.current_authorization import EvidenceDenied
from tests.grounding.test_rag_d_evidence import setup_ready


@pytest.fixture()
def pair():  # type: ignore[no-untyped-def]
    dsn = os.environ.get("AEARN_RAG_D_TEST_DATABASE_URL")
    if dsn is None:
        pytest.skip("explicit AEARN_RAG_D_TEST_DATABASE_URL required")
    name = urlsplit(dsn).path.lstrip("/")
    if not name.startswith("aearn_rag260_c_d_"):
        pytest.fail("refusing non-disposable D database")
    with psycopg.connect(dsn, row_factory=dict_row) as first,             psycopg.connect(dsn, row_factory=dict_row) as second:
        for conn in (first, second):
            found = conn.execute("SELECT current_database() AS name").fetchone()
            if found is None or found["name"] != name:
                pytest.fail("current_database mismatch")
        apply_schema(first)
        apply_schema(first)
        yield first, second
        first.rollback()
        second.rollback()


def _bound(first):  # type: ignore[no-untyped-def]
    adapter, draft, req, policy, candidate = setup_ready(first)
    selection = adapter.resolve_evidence(draft, (req,))
    assert selection.entries[0].status == "ready"
    binding, _receipt = adapter.freeze_binding(
        selection, node_id=req.node_id, goal_hash=req.goal_hash,
        purpose=req.demand.purpose, request=adapter.request_for(req),
    )
    return adapter, binding, adapter.request_for(req), policy, candidate


def _sink(first) -> None:  # type: ignore[no-untyped-def]
    first.execute("CREATE TEMP TABLE IF NOT EXISTS rag_d_synthetic_publication_sink "
                  "(id uuid PRIMARY KEY)")
    first.execute("CREATE TEMP TABLE IF NOT EXISTS rag_d_synthetic_materialization_sink "
                  "(id uuid PRIMARY KEY)")
    first.commit()


def test_revocation_before_fence_rolls_back_publication_and_materialization(pair) -> None:  # type: ignore[no-untyped-def]
    first, second = pair
    adapter, binding, request, policy, candidate = _bound(first)
    _sink(first)  # fixture rows become visible to the second connection.
    second.execute("UPDATE rag_registered_source_policies "
                   "SET enabled=false,revoked_at=clock_timestamp() WHERE policy_id=%s", (policy,))
    second.commit()
    marker = uuid4()
    first.execute("INSERT INTO rag_d_synthetic_publication_sink(id) VALUES (%s)", (marker,))
    first.execute("INSERT INTO rag_d_synthetic_materialization_sink(id) VALUES (%s)", (marker,))
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        adapter.assert_publication_fence(binding, exact_item_claims=(),
            expected_generation=binding.evidence[0].active_generation, request=request)
    first.rollback()
    row = first.execute("SELECT 1 FROM rag_d_synthetic_publication_sink WHERE id=%s", (marker,)).fetchone()
    assert row is None
    assert first.execute("SELECT 1 FROM rag_d_synthetic_materialization_sink "
                         "WHERE id=%s", (marker,)).fetchone() is None
    assert adapter.governance.repo.active("route.sql").corpus_id == candidate.corpus_id


def test_fence_before_revocation_serializes_on_source_policy(pair) -> None:  # type: ignore[no-untyped-def]
    first, second = pair
    adapter, binding, request, policy, candidate = _bound(first)
    _sink(first)
    marker = uuid4()
    first.execute("INSERT INTO rag_d_synthetic_publication_sink(id) VALUES (%s)", (marker,))
    receipt = adapter.assert_publication_fence(binding, exact_item_claims=(),
        expected_generation=binding.evidence[0].active_generation, request=request)
    assert receipt.binding_digest == binding.binding_digest
    second.execute("SET LOCAL lock_timeout = '150ms'")
    with pytest.raises(psycopg.errors.LockNotAvailable):
        second.execute("UPDATE rag_registered_source_policies "
                       "SET enabled=false,revoked_at=clock_timestamp() WHERE policy_id=%s", (policy,))
    second.rollback()
    first.commit()  # simulated publication and materialization commits before revoke.
    second.execute("UPDATE rag_registered_source_policies "
                   "SET enabled=false,revoked_at=clock_timestamp() WHERE policy_id=%s", (policy,))
    second.commit()
    first.execute("SELECT 1")
    with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
        adapter.check_current_authorization(binding, binding.purpose, request=request)
    first.rollback()
    assert adapter.governance.repo.active("route.sql").corpus_id == candidate.corpus_id


def test_root_lock_wait_then_db_clock_expiry_denies_same_transaction(pair) -> None:  # type: ignore[no-untyped-def]
    """An old pre-wait timestamp cannot authorize after the root deadline."""
    first, second = pair
    adapter, binding, request, policy, _candidate = _bound(first)
    _sink(first)
    root = second.execute("SELECT root_id FROM rag_registered_source_policies "
                          "WHERE policy_id=%s", (policy,)).fetchone()["root_id"]
    # The UPDATE keeps an exclusive root lock while a separate connection
    # reaches C's SELECT FOR SHARE. Its new expiry is already imminent.
    second.execute("UPDATE rag_budget_authority_roots SET "
                   "delegation_expires_at=clock_timestamp()+interval '800 milliseconds' "
                   "WHERE root_id=%s", (root,))
    deadline = second.execute("SELECT delegation_expires_at AS end_at "
                              "FROM rag_budget_authority_roots WHERE root_id=%s",
                              (root,)).fetchone()["end_at"]
    marker = uuid4()
    started = Event()

    def fence_after_insert() -> None:
        first.execute("INSERT INTO rag_d_synthetic_publication_sink(id) VALUES (%s)", (marker,))
        first.execute("INSERT INTO rag_d_synthetic_materialization_sink(id) VALUES (%s)", (marker,))
        started.set()
        try:
            adapter.assert_publication_fence(binding, exact_item_claims=(),
                expected_generation=binding.evidence[0].active_generation, request=request)
        finally:
            first.rollback()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fence_after_insert)
        assert started.wait(timeout=3)
        time.sleep(0.1)
        assert not future.done()  # blocked behind the other connection's root UPDATE
        time.sleep(0.9)
        assert second.execute("SELECT clock_timestamp() AS now").fetchone()["now"] > deadline
        second.commit()
        with pytest.raises(EvidenceDenied, match="SOURCE_AUTHORIZATION_STALE"):
            future.result(timeout=5)
    assert first.execute("SELECT 1 FROM rag_d_synthetic_publication_sink "
                         "WHERE id=%s", (marker,)).fetchone() is None
    assert first.execute("SELECT 1 FROM rag_d_synthetic_materialization_sink "
                         "WHERE id=%s", (marker,)).fetchone() is None
