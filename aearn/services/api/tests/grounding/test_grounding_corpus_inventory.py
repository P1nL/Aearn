"""Shared corpus ownership guards for local user and Tutor flows."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

from app.services.grounding.corpus_contracts import (
    CorpusCandidate,
    CorpusChunk,
    CorpusDocument,
    CorpusSource,
)
from app.services.grounding.corpus_repository import CorpusRepository
from app.services.repositories import local_user_data_repository
from app.services.tutor import cutover


_EXPECTED_SHARED_CORPUS_TABLES = frozenset(
    {
        "grounding_corpus_versions",
        "grounding_active_corpora",
        "grounding_corpus_source_snapshots",
        "grounding_corpus_documents",
        "grounding_corpus_chunks",
        "grounding_corpus_events",
    }
)


def test_corpus_inventory_is_shared_infrastructure_not_tutor_target_state() -> None:
    assert cutover.CUTOVER_SHARED_GROUNDING_CORPUS_TABLES == _EXPECTED_SHARED_CORPUS_TABLES
    assert all(not table.startswith("tutor_") for table in _EXPECTED_SHARED_CORPUS_TABLES)
    assert _EXPECTED_SHARED_CORPUS_TABLES.isdisjoint(cutover.CUTOVER_SHARED_TUTOR_TABLES)
    assert _EXPECTED_SHARED_CORPUS_TABLES.isdisjoint(cutover.CUTOVER_TARGET_TUTOR_TABLES)
    assert _EXPECTED_SHARED_CORPUS_TABLES.isdisjoint(
        {name for name, _query in cutover._LEGACY_COUNT_SQL}
    )
    assert _EXPECTED_SHARED_CORPUS_TABLES.isdisjoint(
        {name for name, _query in cutover._TARGET_COUNT_SQL}
    )


def test_local_user_reset_delete_export_and_tutor_cutover_do_not_touch_shared_corpus() -> None:
    # Local export is an explicit learner-data projection; reset/delete share an
    # exact user-owned deletion path. A new direct corpus reference in either
    # module is a boundary change requiring explicit review, not an implicit
    # addition to the user-owned list.
    local_user_source = inspect.getsource(local_user_data_repository)
    cutover_service_source = inspect.getsource(cutover.HarnessCutoverService)
    count_queries = (*cutover._LEGACY_COUNT_SQL, *cutover._TARGET_COUNT_SQL)
    for table in _EXPECTED_SHARED_CORPUS_TABLES:
        assert table not in local_user_source
        assert table not in cutover_service_source
        assert all(table not in query for _name, query in count_queries)


@pytest.fixture
def isolated_corpus_db() -> Iterator[Connection[dict[str, object]]]:
    """Use only an explicit, pre-bootstrapped disposable database; never the default."""
    url = os.environ.get("AEARN_CORPUS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set AEARN_CORPUS_TEST_DATABASE_URL to a pre-bootstrapped isolated corpus test database")
    dbname = str(conninfo_to_dict(url).get("dbname") or "")
    if not dbname.startswith(("aearn_corpus_test_", "aearn_rag260_")):
        pytest.fail("Corpus inventory tests require aearn_corpus_test_* or aearn_rag260_* database, not the default DB")
    with psycopg.connect(url, connect_timeout=3, row_factory=dict_row) as conn:
        try:
            yield conn
        finally:
            # Published corpus rows/events are intentionally undeletable. Roll
            # back the entire test-owned user + corpus transaction, never purge.
            conn.rollback()


def _seed_published_shared_corpus(conn: Connection[dict[str, object]]) -> tuple[UUID, str]:
    """Create a complete published corpus using the normal repository lifecycle."""
    suffix = uuid4().hex
    subject = f"corpus.test.{suffix}"
    corpus_id = uuid4()
    marker = f"private-shared-corpus-content-{suffix}"
    digest = hashlib.sha256(marker.encode()).hexdigest()
    source_id = f"official.{suffix}"
    document_id = f"document.{suffix}"
    repository = CorpusRepository(conn)
    repository.create_candidate(
        CorpusCandidate(
            corpus_id=corpus_id,
            subject_id=subject,
            subject_version="v1",
            registry_digest=digest,
            retrieval_policy_version="test_v1",
            coverage_policy_version="test_v1",
        ),
        idempotency_key=f"candidate.{suffix}",
    )
    repository.add_source(
        CorpusSource(
            corpus_id=corpus_id,
            subject_id=subject,
            subject_version="v1",
            source_id=source_id,
            source_hash=digest,
            trust_tier="official",
            source_kind="documentation",
            source_version="v1",
            allowed_domains=("docs.example.org",),
            seed_urls=("https://docs.example.org/reference",),
            facets=("basics",),
        )
    )
    repository.add_document(
        CorpusDocument(
            corpus_id=corpus_id,
            document_id=document_id,
            source_id=source_id,
            subject_id=subject,
            subject_version="v1",
            source_hash=digest,
            trust_tier="official",
            canonical_url="https://docs.example.org/reference",
            final_url="https://docs.example.org/reference",
            content_type="text/html",
            document_version="v1",
            fetched_at=datetime.now(UTC),
            document_hash=digest,
            parse_status="parsed",
        )
    )
    repository.add_chunk(
        CorpusChunk(
            corpus_id=corpus_id,
            chunk_id=f"chunk.{suffix}",
            document_id=document_id,
            source_id=source_id,
            subject_id=subject,
            subject_version="v1",
            source_hash=digest,
            trust_tier="official",
            document_hash=digest,
            ordinal=0,
            title="Shared test reference",
            section_path="Basics",
            content=marker,
            facets=("basics",),
            topic_tags=(),
            chunk_hash=digest,
        )
    )
    validated = repository.finalize_validation(
        corpus_id,
        passed=True,
        expected_generation=0,
        validation_summary={"passed": True},
        coverage_summary={"covered": True},
        idempotency_key=f"validation.{suffix}",
    )
    assert validated.summary_hash is not None
    repository.activate(
        corpus_id,
        expected_generation=0,
        summary_hash=validated.summary_hash,
        idempotency_key=f"activation.{suffix}",
    )
    _assert_shared_corpus_retained(conn, corpus_id)
    return corpus_id, marker


def _assert_shared_corpus_retained(conn: Connection[dict[str, object]], corpus_id: UUID) -> None:
    for table in _EXPECTED_SHARED_CORPUS_TABLES:
        id_column = "id" if table == "grounding_corpus_versions" else "corpus_version_id"
        row = conn.execute(
            f"SELECT count(*)::int AS count FROM {table} WHERE {id_column} = %s",
            (corpus_id,),
        ).fetchone()
        expected_count = 3 if table == "grounding_corpus_events" else 1
        assert row is not None and row["count"] == expected_count, table


def _create_owned_user(conn: Connection[dict[str, object]], *, legacy: bool = False) -> str:
    user = conn.execute(
        "INSERT INTO users (display_name, learning_style) VALUES (%s, %s) RETURNING id",
        (f"Corpus inventory {uuid4().hex}", "practice_first" if legacy else None),
    ).fetchone()
    assert user is not None
    return str(user["id"])


def test_local_export_reset_and_delete_preserve_all_shared_corpus_rows(
    isolated_corpus_db: Connection[dict[str, object]],
) -> None:
    conn = isolated_corpus_db
    corpus_id, marker = _seed_published_shared_corpus(conn)
    user_id = _create_owned_user(conn)

    exported = local_user_data_repository.export_user_data(conn, user_id)
    exported_text = json.dumps(exported, ensure_ascii=False, default=str)
    assert marker not in exported_text
    assert all(table not in exported_text for table in _EXPECTED_SHARED_CORPUS_TABLES)
    assert all(table not in exported for table in _EXPECTED_SHARED_CORPUS_TABLES)
    _assert_shared_corpus_retained(conn, corpus_id)

    local_user_data_repository.reset_user_data(conn, user_id)
    _assert_shared_corpus_retained(conn, corpus_id)
    local_user_data_repository.delete_user_data(conn, user_id)
    _assert_shared_corpus_retained(conn, corpus_id)
    deleted = conn.execute("SELECT deleted_at FROM users WHERE id = %s", (user_id,)).fetchone()
    assert deleted is not None and deleted["deleted_at"] is not None


def test_confirmed_tutor_cutover_preserves_all_shared_corpus_rows(
    isolated_corpus_db: Connection[dict[str, object]],
) -> None:
    conn = isolated_corpus_db
    corpus_id, marker = _seed_published_shared_corpus(conn)
    user_id = _create_owned_user(conn, legacy=True)
    service = cutover.HarnessCutoverService(conn)
    preview = service.get_decision(user_id=user_id)
    assert preview["state"] == "summary_ready"
    assert not any(service._inventory(user_id).target_counts.values())
    assert marker not in json.dumps(preview, ensure_ascii=False, default=str)
    summary_version = preview["summary_version"]
    assert isinstance(summary_version, int)
    result = service.confirm(
        user_id=user_id,
        cutover_version=cutover.CUTOVER_VERSION,
        summary_version=summary_version,
        preview_nonce=str(preview["preview_nonce"]),
        summary_hash=str(preview["summary_hash"]),
        client_action_id=f"inventory.{uuid4().hex}",
        confirm=True,
    )
    assert result["state"] == "verified"
    assert marker not in json.dumps(result, ensure_ascii=False, default=str)
    _assert_shared_corpus_retained(conn, corpus_id)
    user = conn.execute("SELECT learning_style FROM users WHERE id = %s", (user_id,)).fetchone()
    assert user is not None and user["learning_style"] is None
