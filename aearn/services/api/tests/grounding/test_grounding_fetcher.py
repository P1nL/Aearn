from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from app.services.grounding.grounding_fetcher import GroundingDocsFetcher, GroundingHttpResponse
from app.services.grounding.grounding_sources import seed_urls_for_language


class FakeHttpClient:
    def __init__(self, responder: Callable[[str], GroundingHttpResponse]) -> None:
        self._responder = responder
        self.calls: list[str] = []

    def get(self, url: str, timeout_seconds: float) -> GroundingHttpResponse:
        assert timeout_seconds > 0
        self.calls.append(url)
        return self._responder(url)


def _ok_response(url: str) -> GroundingHttpResponse:
    return GroundingHttpResponse(
        status_code=200,
        final_url=url,
        content_type="text/html; charset=utf-8",
        text="<html><h1>Python Tutorial</h1><p>Control flow basics.</p></html>",
    )


def _fixed_now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def test_fetch_registered_seed_document_with_fake_client() -> None:
    client = FakeHttpClient(_ok_response)
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)

    result = fetcher.fetch("python-tutorial", "https://docs.python.org/3/tutorial/index.html")

    assert result.status == "ok"
    assert result.error_code is None
    assert result.document is not None
    assert result.document.source_id == "python-tutorial"
    assert result.document.language_id == "python"
    assert result.document.canonical_url == "https://docs.python.org/3/tutorial/index.html"
    assert result.document.final_url == "https://docs.python.org/3/tutorial/index.html"
    assert result.document.content_type == "text/html; charset=utf-8"
    assert result.document.fetched_at == _fixed_now()
    assert len(result.document.content_hash) == 64
    assert client.calls == ["https://docs.python.org/3/tutorial/index.html"]


def test_fetch_postgresql_query_seed_with_offline_fake_client() -> None:
    # This fake transport verifies registry/fetcher wiring only; it is not real source evidence.
    url = "https://www.postgresql.org/docs/current/tutorial-select.html"
    client = FakeHttpClient(
        lambda requested_url: GroundingHttpResponse(
            status_code=200,
            final_url=requested_url,
            content_type="text/html; charset=utf-8",
            text="<html><h1>Querying a Table</h1><p>SELECT rows with WHERE and ORDER BY.</p></html>",
        ),
    )
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)

    result = fetcher.fetch("postgresql-sql-docs", url)

    assert result.status == "ok"
    assert result.document is not None
    assert result.document.source_id == "postgresql-sql-docs"
    assert result.document.language_id == "sql"
    assert result.document.canonical_url == url
    assert result.document.final_url == url
    assert result.document.provenance.kind == "unknown"
    assert client.calls == [url]


def test_fetch_blocks_urls_outside_source_allowlist_without_http_call() -> None:
    client = FakeHttpClient(_ok_response)
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)

    result = fetcher.fetch("python-tutorial", "https://example.com/python")

    assert result.status == "blocked"
    assert result.error_code == "URL_NOT_ALLOWLISTED"
    assert result.document is None
    assert client.calls == []


def test_fetch_maps_http_status_failures_without_raising() -> None:
    client = FakeHttpClient(
        lambda url: GroundingHttpResponse(
            status_code=503,
            final_url=url,
            content_type="text/html",
            text="temporarily unavailable",
        ),
    )
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)

    result = fetcher.fetch("mdn-javascript-guide", "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide")

    assert result.status == "failed"
    assert result.error_code == "HTTP_STATUS"
    assert result.error_message == "HTTP status 503"
    assert result.document is None


def test_fetch_uses_in_memory_cache_for_repeated_source_url() -> None:
    client = FakeHttpClient(_ok_response)
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)
    url = "https://docs.python.org/3/tutorial/index.html"

    first = fetcher.fetch("python-tutorial", url)
    second = fetcher.fetch("python-tutorial", url)

    assert first.status == "ok"
    assert second.status == "ok"
    assert second.cache_hit is True
    assert client.calls == [url]


def test_fetch_language_seed_documents_returns_one_result_per_seed_url() -> None:
    client = FakeHttpClient(_ok_response)
    fetcher = GroundingDocsFetcher(http_client=client, now=_fixed_now)

    results = fetcher.fetch_language_seed_documents("python")

    assert len(results) == len(seed_urls_for_language("python"))
    assert all(result.status == "ok" for result in results)
    assert client.calls == list(seed_urls_for_language("python"))

