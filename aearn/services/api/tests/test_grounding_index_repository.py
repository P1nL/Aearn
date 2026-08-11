from __future__ import annotations

from datetime import UTC, datetime

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.services.grounding.grounding_index_repository import (
    build_official_docs_grounding_context,
    replace_grounding_chunks,
    run_and_persist_fixture_grounding_reindex,
    search_persisted_grounding_chunks,
)
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


@pytest.fixture()
def conn():
    from psycopg.rows import dict_row

    bootstrap_database()
    with psycopg.connect(get_settings().database_url, row_factory=dict_row) as connection:
        connection.execute("DELETE FROM grounding_chunks")
        connection.execute("DELETE FROM grounding_reindex_runs")
        connection.commit()
        yield connection
        connection.rollback()


def test_fixture_reindex_persists_chunks_and_report_without_network(conn) -> None:
    result = run_and_persist_fixture_grounding_reindex(conn)
    conn.commit()

    assert result.run_id
    assert result.report.status == "completed"
    assert result.chunks_persisted == result.report.total_chunks

    chunk_count = conn.execute("SELECT count(*)::int AS count FROM grounding_chunks").fetchone()
    run_count = conn.execute("SELECT count(*)::int AS count FROM grounding_reindex_runs").fetchone()
    assert chunk_count is not None
    assert run_count is not None
    assert chunk_count["count"] == result.report.total_chunks
    assert run_count["count"] == 1


def test_search_persisted_grounding_chunks_returns_citation_ready_results(conn) -> None:
    run_and_persist_fixture_grounding_reindex(conn)
    conn.commit()

    results = search_persisted_grounding_chunks(
        conn,
        GroundingRetrievalQuery("python", query_text="python basics functions", top_k=2),
    )

    assert results
    assert all(result.chunk.language_id == "python" for result in results)
    assert results[0].chunk.canonical_url.startswith("https://docs.python.org/")
    assert results[0].chunk.source_version_label == "python-3"
    assert len(results[0].chunk.document_content_hash) == 64


def test_build_official_docs_grounding_context_is_safe_and_bounded(conn) -> None:
    run_and_persist_fixture_grounding_reindex(conn)
    conn.commit()

    context = build_official_docs_grounding_context(
        conn,
        language_id_or_alias="python",
        query_text="python functions",
        topic_tags=("functions",),
        knowledge_point_id="kp_1",
        knowledge_point_title="Python Functions",
    )

    assert context["status"] == "used"
    assert context["source_mode"] == "persisted_index"
    assert context["citation_count"] == 1
    assert context["fallback_reason"] is None
    assert context["citations"]
    citation = context["citations"][0]
    assert citation["canonical_url"].startswith("https://docs.python.org/")
    assert citation["source_trust_tier"] == "official"
    assert citation["source_version_label"] == "python-3"
    assert len(citation["document_content_hash"]) == 64
    assert "content" not in citation


def test_build_official_docs_grounding_context_reports_empty_without_index(conn) -> None:
    context = build_official_docs_grounding_context(
        conn,
        language_id_or_alias="python",
        query_text="python functions",
    )

    assert context["status"] == "empty"
    assert context["fallback_reason"] == "no_persisted_grounding"
    assert context["citations"] == []


def test_replace_grounding_chunks_removes_stale_chunks_for_source(conn) -> None:
    old_chunk = _chunk("old", "Old Functions", "old marker")
    new_chunk = _chunk("new", "New Functions", "new marker")

    replace_grounding_chunks(conn, (old_chunk,), source_ids=("python-tutorial",))
    conn.commit()
    replace_grounding_chunks(conn, (new_chunk,), source_ids=("python-tutorial",))
    conn.commit()

    rows = conn.execute(
        """
        SELECT chunk_id, content
        FROM grounding_chunks
        WHERE source_id = 'python-tutorial'
        ORDER BY chunk_id
        """
    ).fetchall()
    assert [row["chunk_id"] for row in rows] == ["new"]
    assert rows[0]["content"] == "new marker"


def test_html_css_public_course_language_searches_html_and_css_indexes(conn) -> None:
    run_and_persist_fixture_grounding_reindex(conn)
    conn.commit()

    context = build_official_docs_grounding_context(
        conn,
        language_id_or_alias="html_css",
        query_text="css layout",
    )

    assert context["status"] == "used"
    assert set(context["language_ids"]) == {"html", "css"}
    assert context["citations"]


def _chunk(chunk_id: str, title: str, text: str) -> GroundingChunk:
    return GroundingChunk(
        chunk_id=chunk_id,
        source_id="python-tutorial",
        language_id="python",
        title=title,
        section_path=("Python Tutorial", title),
        canonical_url="https://docs.python.org/3/tutorial/index.html",
        source_type="tutorial",
        source_trust_tier="official",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=f"hash-{chunk_id}",
        text=text,
        topic_tags=("functions",),
        source_version_label="python-3",
        source_version_kind="rolling",
        document_content_hash="d" * 64,
    )
