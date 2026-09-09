from __future__ import annotations

from collections.abc import Callable

from app.services.grounding.grounding_fetcher import GroundingDocsFetcher, GroundingHttpResponse
from app.services.grounding.grounding_reindex import run_fixture_grounding_reindex, run_grounding_reindex
from app.services.runners.language_capabilities import all_language_capabilities


class FakeHttpClient:
    def __init__(self, responder: Callable[[str], GroundingHttpResponse]) -> None:
        self._responder = responder
        self.calls: list[str] = []

    def get(self, url: str, timeout_seconds: float) -> GroundingHttpResponse:
        self.calls.append(url)
        return self._responder(url)


def _ok_response(url: str) -> GroundingHttpResponse:
    return GroundingHttpResponse(
        status_code=200,
        final_url=url,
        content_type="text/html",
        text="<html><body><h1>Python Tutorial</h1><p>python functions and control flow.</p></body></html>",
    )


def test_run_grounding_reindex_reports_successful_source_counts() -> None:
    fetcher = GroundingDocsFetcher(http_client=FakeHttpClient(_ok_response))

    report = run_grounding_reindex(fetcher, source_ids=("python-tutorial",))

    assert report.status == "completed"
    assert report.total_sources == 1
    assert report.total_documents == 3
    assert report.total_chunks == 3
    assert report.total_failures == 0
    assert report.source_reports[0].source_id == "python-tutorial"
    assert report.source_reports[0].status == "completed"
    assert report.chunks[0].language_id == "python"


def test_run_grounding_reindex_isolates_mixed_source_failures() -> None:
    def responder(url: str) -> GroundingHttpResponse:
        if "developer.mozilla.org" in url:
            return GroundingHttpResponse(status_code=503, final_url=url, content_type="text/html", text="down")
        return _ok_response(url)

    fetcher = GroundingDocsFetcher(http_client=FakeHttpClient(responder))

    report = run_grounding_reindex(fetcher, source_ids=("python-tutorial", "mdn-javascript-guide"))

    assert report.status == "completed_with_failures"
    assert report.total_documents == 3
    assert report.total_chunks == 3
    assert report.total_failures == 1
    assert [source.status for source in report.source_reports] == ["completed", "failed"]
    assert report.source_reports[1].error_codes == ("HTTP_STATUS",)


def test_run_grounding_reindex_reports_unknown_source_without_exception() -> None:
    fetcher = GroundingDocsFetcher(http_client=FakeHttpClient(_ok_response))

    report = run_grounding_reindex(fetcher, source_ids=("unknown-source",))

    assert report.status == "failed"
    assert report.total_sources == 1
    assert report.total_documents == 0
    assert report.total_chunks == 0
    assert report.total_failures == 1
    assert report.source_reports[0].source_id == "unknown-source"
    assert report.source_reports[0].error_codes == ("SOURCE_NOT_REGISTERED",)


def test_run_fixture_grounding_reindex_smokes_every_mainstream_language_without_network() -> None:
    report = run_fixture_grounding_reindex()
    language_ids = {chunk.language_id for chunk in report.chunks}
    expected_language_ids = {capability.language_id for capability in all_language_capabilities()}

    assert report.status == "completed"
    assert report.total_failures == 0
    assert language_ids == expected_language_ids
    assert report.total_documents == len(expected_language_ids)
    assert report.total_chunks == len(expected_language_ids)

