"""Offline provenance regressions; no real DB or HTTP transport is used."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.grounding.grounding_fetcher import GroundingDocsFetcher, GroundingHttpResponse, HttpxGroundingHttpClient
from app.services.grounding.grounding_fixtures import fixture_documents_for_language
from app.services.grounding.grounding_index_repository import _chunk_from_row, replace_grounding_chunks, search_persisted_grounding_chunks
from app.services.grounding.grounding_processing import clean_and_chunk_document, is_admissible_lesson_source
from app.services.grounding.grounding_provenance import GroundingProvenance, provenance_from_metadata
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery, GroundingRetrievalResult
from app.services.grounding.grounding_sources import get_grounding_source
from app.services.learning import lesson_authoring

NOW = datetime(2026, 9, 8, tzinfo=UTC)
URL = "https://docs.python.org/3/tutorial/introduction.html"
HTML = "<h1>Numbers</h1><p>Python variables store values. Use print to display a value.</p>"


def response(url=URL, content_type="text/html", status=200):
    return GroundingHttpResponse(status, url, content_type, HTML)


@pytest.fixture
def real_chunk(monkeypatch):
    # Exercise the production fetcher path, but replace its I/O method explicitly.
    monkeypatch.setattr(HttpxGroundingHttpClient, "get", lambda *_: response())
    fetched = GroundingDocsFetcher(now=lambda: NOW).fetch("python-tutorial", URL)
    assert fetched.document is not None
    return clean_and_chunk_document(fetched.document)[0]


def row_for(chunk, metadata):
    return {
        "chunk_id": chunk.chunk_id, "source_id": chunk.source_id, "language_id": chunk.language_id,
        "title": chunk.title, "section_path_json": list(chunk.section_path),
        "canonical_url": chunk.canonical_url, "source_type": chunk.source_type,
        "source_trust_tier": chunk.source_trust_tier, "fetched_at": chunk.fetched_at,
        "content_hash": chunk.content_hash, "content": chunk.text,
        "topic_tags_json": list(chunk.topic_tags), "source_version_label": chunk.source_version_label,
        "source_version_kind": chunk.source_version_kind, "document_content_hash": chunk.document_content_hash,
        "metadata_json": metadata,
    }


def test_real_fetch_provenance_survives_processing_cache_and_persistence(real_chunk):
    import json

    assert is_admissible_lesson_source(real_chunk)
    conn = Mock()
    replace_grounding_chunks(conn, (real_chunk,))
    metadata = json.loads(conn.execute.call_args.args[1][-1])
    restored = _chunk_from_row(row_for(real_chunk, metadata))
    assert restored == real_chunk
    assert is_admissible_lesson_source(restored)


@pytest.mark.parametrize("metadata", [None, {}, [], {"provenance": "http_fetch"},
    {"provenance": {"kind": "http_fetch"}},
    {"provenance": dict(GroundingProvenance().payload(), schema_version="future")},
    {"provenance": dict(GroundingProvenance().payload(), kind="official")},
    {"provenance": dict(GroundingProvenance().payload(), final_url=17)}])
def test_historical_or_malformed_metadata_is_readable_but_never_admitted(real_chunk, metadata):
    original = row_for(real_chunk, metadata)
    restored = _chunk_from_row(original)
    assert restored.provenance.kind == "unknown"
    assert restored.text == real_chunk.text
    assert restored.title == real_chunk.title
    assert restored.content_hash == real_chunk.content_hash
    assert original["metadata_json"] == metadata
    assert not is_admissible_lesson_source(restored)
    assert not is_admissible_lesson_source(restored, allow_fixtures_for_tests=True)


def test_fixture_identity_is_stable_and_only_explicit_offline_seam_accepts_it():
    document = fixture_documents_for_language("python")[0]
    chunk = clean_and_chunk_document(document)[0]
    assert chunk.chunk_id == "b583c08721c345b11595376e"
    assert len(chunk.text) == 120
    assert chunk.provenance.kind == "fixture"
    assert not is_admissible_lesson_source(chunk)
    assert is_admissible_lesson_source(chunk, allow_fixtures_for_tests=True)
    assert not is_admissible_lesson_source(replace(chunk, title="Official Python tutorial"))
    assert provenance_from_metadata({"provenance": chunk.provenance.payload()}) == chunk.provenance


@pytest.mark.parametrize("change", [
    {"text": "tampered"}, {"document_content_hash": "0" * 64},
    {"language_id": "javascript"}, {"source_id": "unknown"},
    {"canonical_url": "https://example.com"}, {"source_trust_tier": "community"},
    {"fetched_at": NOW.replace(tzinfo=None)},
])
def test_mismatched_evidence_fails_closed(real_chunk, change):
    assert not is_admissible_lesson_source(replace(real_chunk, **change))


def test_unallowlisted_final_url_fails_closed(real_chunk):
    chunk = replace(real_chunk, provenance=replace(real_chunk.provenance, final_url="https://example.com"))
    assert not is_admissible_lesson_source(chunk)


def test_injected_transport_does_not_claim_real_ingestion():
    client = Mock()
    client.get.return_value = response()
    fetcher = GroundingDocsFetcher(http_client=client)
    first = fetcher.fetch("python-tutorial", URL)
    cached = fetcher.fetch("python-tutorial", URL)
    assert cached.cache_hit
    assert cached.document == first.document
    assert first.document.provenance.kind == "unknown"
    assert not is_admissible_lesson_source(clean_and_chunk_document(first.document)[0])


@pytest.mark.parametrize("reply, code", [
    (response(url="https://example.com"), "FINAL_URL_NOT_ALLOWLISTED"),
    (response(url="https://user:password@docs.python.org/3/"), "FINAL_URL_NOT_ALLOWLISTED"),
    (response(content_type="application/json"), "CONTENT_TYPE_UNSUPPORTED"),
    (response(status=503), "HTTP_STATUS"),
])
def test_fetch_does_not_mint_evidence_for_invalid_response(monkeypatch, reply, code):
    monkeypatch.setattr(HttpxGroundingHttpClient, "get", lambda *_: reply)
    result = GroundingDocsFetcher().fetch("python-tutorial", URL)
    assert result.document is None
    assert result.error_code == code


def test_changed_document_cannot_carry_old_receipt(monkeypatch):
    monkeypatch.setattr(HttpxGroundingHttpClient, "get", lambda *_: response())
    document = GroundingDocsFetcher().fetch("python-tutorial", URL).document
    assert document is not None
    chunks = clean_and_chunk_document(replace(document, raw_content="<p>Changed source body.</p>"))
    assert chunks and chunks[0].provenance.kind == "unknown"


def test_lesson_filter_runs_before_top_k_and_general_historical_search_is_unchanged(real_chunk):
    unknown = replace(real_chunk, chunk_id="000", provenance=GroundingProvenance())
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = [
        row_for(unknown, {}), row_for(real_chunk, {"provenance": real_chunk.provenance.payload()}),
    ]
    query = GroundingRetrievalQuery("python", query_text="Python variables", top_k=1)
    assert search_persisted_grounding_chunks(conn, query)[0].chunk.chunk_id == "000"
    admitted = search_persisted_grounding_chunks(conn, query, admission_filter=is_admissible_lesson_source)
    assert len(admitted) == 1 and admitted[0].chunk == real_chunk


def test_snapshot_loader_rechecks_origin_and_keeps_fixture_override_explicit(monkeypatch, real_chunk):
    fixture = clean_and_chunk_document(fixture_documents_for_language("python")[0])[0]
    unknown = replace(real_chunk, provenance=GroundingProvenance())
    def results(*args, **kwargs):
        return tuple(GroundingRetrievalResult(chunk, 1.0, ("query",)) for chunk in (unknown, fixture, real_chunk))
    monkeypatch.setattr(lesson_authoring, "search_persisted_grounding_chunks", results)
    snapshots = lesson_authoring._load_evidence_snapshots(Mock(), "python", "python.variables", "Variables", NOW)
    assert [snapshot.grounding_chunk_id for snapshot in snapshots] == [real_chunk.chunk_id]
    offline = lesson_authoring._load_evidence_snapshots(
        Mock(), "python", "python.variables", "Variables", NOW, allow_fixtures_for_tests=True,
    )
    assert len(offline) == 2


def test_dispatch_rejects_fixture_before_author_factory_or_source_hash_write(monkeypatch):
    fixture = clean_and_chunk_document(fixture_documents_for_language("python")[0])[0]
    monkeypatch.setattr(lesson_authoring, "search_persisted_grounding_chunks", lambda *a, **kw: (
        GroundingRetrievalResult(fixture, 1.0, ("fallback",)),
    ))
    conn = Mock()
    conn.transaction.side_effect = lambda: nullcontext()
    monkeypatch.setattr(lesson_authoring, "connect", lambda: nullcontext(conn))
    repo = Mock()
    run = SimpleNamespace(run_id="run", lease_generation=1, user_id="user", track_id="track", knowledge_key="python.variables")
    repo.claim_authoring_run.return_value = run
    repo.mark_authoring_running.return_value = run
    repo.read_scope.return_value = SimpleNamespace(language_id="python", knowledge_key="python.variables", node_title="Variables")
    monkeypatch.setattr(lesson_authoring, "PostgresLessonDocumentRepository", lambda _: repo)
    fail = Mock()
    factory = Mock(side_effect=AssertionError("must not construct provider"))
    monkeypatch.setattr(lesson_authoring, "_safe_fail", fail)
    monkeypatch.setattr(lesson_authoring, "LESSON_AUTHOR_FACTORY", factory)
    lesson_authoring.dispatch_lesson_authoring_run("run", now=lambda: NOW)
    assert fail.call_args.args[2] == "LESSON_SOURCE_EVIDENCE_INSUFFICIENT"
    factory.assert_not_called()
    repo.set_authoring_source_set.assert_not_called()
    repo.publish_authoring_result.assert_not_called()


def test_python_seeds_include_bounded_substantive_pages_without_changing_version():
    source = get_grounding_source("python-tutorial")
    assert source.seed_urls == (
        "https://docs.python.org/3/tutorial/index.html", URL,
        "https://docs.python.org/3/tutorial/controlflow.html",
    )
    assert source.source_version_label == "python-3"
    assert source.source_version_kind == "rolling"


@pytest.mark.parametrize("external", [False, True])
def test_real_transport_checks_redirect_before_following(monkeypatch, external):
    import httpx

    original_client = httpx.Client
    calls = []
    final_url = "https://example.com/private" if external else "https://docs.python.org/3/tutorial/controlflow.html"
    def handler(request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": final_url})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=HTML)
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    result = GroundingDocsFetcher().fetch("python-tutorial", URL)
    if external:
        assert calls == [URL]
        assert result.status == "blocked" and result.document is None
        assert result.error_code == "FINAL_URL_NOT_ALLOWLISTED"
    else:
        assert calls == [URL, final_url]
        assert result.document.provenance.kind == "http_fetch"
        assert result.document.provenance.final_url == final_url
        assert is_admissible_lesson_source(clean_and_chunk_document(result.document)[0])


def test_real_transport_redirect_loop_is_bounded_without_provenance(monkeypatch):
    import httpx

    original_client = httpx.Client
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": URL})
    monkeypatch.setattr(httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw))
    result = GroundingDocsFetcher().fetch("python-tutorial", URL)
    assert len(calls) == 6
    assert result.document is None and result.error_code == "HTTP_STATUS"
