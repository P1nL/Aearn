"""Offline-only protocol tests: no dotenv, provider, database or network."""
from __future__ import annotations

import gzip
import json

import httpx
import pytest

from app.services.grounding.autonomous.contracts import SourceDiscoveryDemand
from app.services.grounding.autonomous.search_port import SearchPermit
from app.services.grounding.autonomous.tavily_search import (
    HttpxTavilyTransport, TavilyResponse, TavilySearchAdapter, TavilyTransportFailure,
)
from tests.grounding.rag_material_helpers import BUDGET, H, SCOPE


def demand() -> SourceDiscoveryDemand:
    return SourceDiscoveryDemand(
        demand_hash=H, scope=SCOPE, query_terms=("Python list", "Python 3.12"),
        actor_id="actor.001", policy_id="policy.001", policy_generation=2,
        budget=BUDGET,
    )


class Admission:
    def __init__(self, permit: SearchPermit | None = None) -> None:
        self.permit = permit or SearchPermit(demand(), "search.001")
        self.calls = 0

    def authorize_and_reserve(self, value: SourceDiscoveryDemand) -> SearchPermit | None:
        self.calls += 1
        return self.permit


class Transport:
    def __init__(self, response: TavilyResponse | Exception) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def search(self, body: dict[str, object]) -> TavilyResponse:
        self.calls.append(body)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def success(**updates: object) -> TavilyResponse:
    payload: dict[str, object] = {
        "request_id": "123e4567-e89b-12d3-a456-426614174111",
        "usage": {"credits": 1},
        "results": [{"url": "https://example.org/lesson", "title": "Untrusted title",
                     "content": "Untrusted snippet", "raw_content": "Forbidden body"}],
    }
    payload.update(updates)
    return TavilyResponse(200, payload)


def test_closed_without_broker_transport_or_explicit_enable() -> None:
    admission, transport = Admission(), Transport(success())
    assert TavilySearchAdapter(admission=admission, transport=transport).search(demand()).status == "disabled"
    assert TavilySearchAdapter(admission=admission, enabled=True).search(demand()).status == "disabled"
    assert TavilySearchAdapter(transport=transport, enabled=True).search(demand()).status == "disabled"
    assert admission.calls == 0
    assert transport.calls == []


def test_authorization_must_match_exact_demand_and_reservation_identity() -> None:
    transport = Transport(success())
    for permit in (SearchPermit(demand().model_copy(update={"actor_id": "actor.other"}), "search.001"),
                   SearchPermit(demand(), "INVALID")):
        result = TavilySearchAdapter(admission=Admission(permit), transport=transport,
                                     enabled=True).search(demand())
        assert result.status == "not_authorized"
        assert result.receipt is None
    assert transport.calls == []


def test_fixed_basic_parameters_and_discovery_only_receipt() -> None:
    transport = Transport(success())
    result = TavilySearchAdapter(admission=Admission(), transport=transport, enabled=True).search(demand())
    assert result.status == "ok" and not result.existing_only
    assert transport.calls == [{
        "query": "Python list Python 3.12", "search_depth": "basic", "max_results": 5,
        "auto_parameters": False, "include_answer": False, "include_raw_content": False,
        "include_images": False, "include_usage": True,
    }]
    assert result.receipt is not None and result.receipt.credits == 1
    assert result.receipt.provider_request_id == "123e4567-e89b-12d3-a456-426614174111"
    assert result.receipt.attempt_id == "search.001"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.kind == "landing" and candidate.capture.kind == "none"
    assert candidate.discovery_receipt_id == "search.001"
    assert "snippet" not in repr(result).lower() and "body" not in repr(result).lower()


@pytest.mark.parametrize(("response", "status", "existing_only"), [
    (TavilyResponse(432, {"detail": {"error": "This request exceeds your plan's set usage limit. Please upgrade your plan"}}), "quota_exhausted", True),
    (TavilyResponse(432, {"detail": {"error": "Unspecified forbidden"}}), "provider_error", False),
    (TavilyResponse(432, {"detail": {"error": "Echo: this request exceeds your plan's set usage limit"}}), "provider_error", False),
    (TavilyResponse(429, {"detail": {"error": "Quota exhausted"}}), "rate_limited", False),
    (TavilyResponse(401, {"detail": {"error": "secret-key"}}), "authentication_failed", False),
    (TavilyResponse(433, {"detail": {"error": "This request exceeds the pay-as-you-go limit"}}), "provider_error", False),
    (TavilyResponse(500, {"detail": {"error": "secret-key"}}), "provider_error", False),
])
def test_status_matrix(response: TavilyResponse, status: str, existing_only: bool) -> None:
    result = TavilySearchAdapter(admission=Admission(), transport=Transport(response), enabled=True).search(demand())
    assert result.status == status and result.existing_only is existing_only
    assert result.candidates == () and result.receipt is not None
    assert result.receipt.credits is None and "secret-key" not in repr(result)


@pytest.mark.parametrize(("failure", "status"), [
    (TimeoutError("secret-token"), "timeout"),
    (RuntimeError("secret-token"), "provider_error"),
])
def test_transport_failure_does_not_retry_or_refund(failure: Exception, status: str) -> None:
    transport = Transport(failure)
    result = TavilySearchAdapter(admission=Admission(), transport=transport, enabled=True).search(demand())
    assert result.status == status and not result.existing_only
    assert result.receipt is not None and result.receipt.credits is None
    assert len(transport.calls) == 1 and "secret-token" not in repr(result)


@pytest.mark.parametrize("url", [
    "http://example.org/path", "https://user:pass@example.org/path",
    "https://example.org:8443/path", "https://example.org/path#fragment",
    "https://example.org/path\nsecret", "https://[::1",
])
def test_bad_candidate_fails_closed_without_snippet_or_body(url: str) -> None:
    result = TavilySearchAdapter(admission=Admission(), transport=Transport(success(
        results=[{"url": url, "content": "private conversation"}]
    )), enabled=True).search(demand())
    assert result.status == "invalid_response" and result.candidates == ()
    assert result.receipt is not None and result.receipt.credits == 1
    assert "private conversation" not in repr(result)


def test_malformed_or_missing_usage_never_implies_free_search() -> None:
    for response in (success(usage={"credits": True}), success(usage={}),
                     success(results=[{"url": "https://example.org"}] * 6),
                     TavilyResponse(200, "private response")):
        result = TavilySearchAdapter(admission=Admission(), transport=Transport(response),
                                     enabled=True).search(demand())
        assert result.receipt is not None
        assert result.receipt.credits is None or result.status == "invalid_response"
        if result.status == "invalid_response":
            assert result.candidates == ()

def test_http_transport_is_default_closed_and_requires_explicit_key() -> None:
    requests: list[httpx.Request] = []
    mock = httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(
        200, json={"results": []}, headers={"content-type": "application/json"}
    ))
    with pytest.raises(TavilyTransportFailure, match="transport_disabled"):
        HttpxTavilyTransport(http_transport=mock).search({})
    assert requests == []
    with pytest.raises(ValueError, match="invalid Tavily transport configuration"):
        HttpxTavilyTransport(api_key="secret\r\nHeader: injected", enabled=True)
    with pytest.raises(ValueError, match="invalid Tavily transport configuration"):
        HttpxTavilyTransport(api_key="tvly-test-secret", enabled=True,
                             http_transport=httpx.HTTPTransport(retries=2))
    assert requests == []


def test_http_transport_fixed_endpoint_auth_header_json_and_client_controls(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({
            "request_id": "123e4567-e89b-12d3-a456-426614174111",
            "usage": {"credits": 1}, "results": [{"url": "https://example.org/page"}],
        }).encode()), headers={"content-type": "application/json"})

    client_kwargs: list[dict[str, object]] = []
    real_client = httpx.Client

    def client_spy(*args, **kwargs):
        client_kwargs.append(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_spy)
    transport = HttpxTavilyTransport(
        api_key="tvly-test-secret", enabled=True,
        http_transport=httpx.MockTransport(reply), timeout_seconds=4,
    )
    result = TavilySearchAdapter(admission=Admission(), transport=transport,
                                 enabled=True).search(demand())
    assert result.status == "ok" and len(seen) == 1
    request = seen[0]
    assert request.method == "POST" and str(request.url) == "https://api.tavily.com/search"
    assert request.headers["Authorization"] == "Bearer tvly-test-secret"
    assert request.headers["accept-encoding"] == "identity"
    assert request.headers["content-type"].startswith("application/json")
    assert b"tvly-test-secret" not in request.content
    assert b"Python list Python 3.12" in request.content
    assert client_kwargs[0]["trust_env"] is False
    assert client_kwargs[0]["follow_redirects"] is False
    assert isinstance(client_kwargs[0]["timeout"], httpx.Timeout)


@pytest.mark.parametrize(("response", "status"), [
    (httpx.Response(307, json={"detail": "redirect secret"},
                    headers={"location": "https://other.example/search"}), "provider_error"),
    (httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"}), "invalid_response"),
    (httpx.Response(200, content=b"x" * 128, headers={"content-type": "application/json"}), "provider_error"),
    (httpx.Response(200, content=b"{}", headers={"content-type": "text/html"}), "provider_error"),
    (httpx.Response(200, content=gzip.compress(b"{}"), headers={"content-type": "application/json",
                                               "content-encoding": "gzip"}), "provider_error"),
])
def test_http_transport_redirect_malformed_oversize_and_type_fail_closed(
    response: httpx.Response, status: str,
) -> None:
    seen = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(response.status_code, stream=httpx.ByteStream(response.content),
                              headers=response.headers)

    transport = HttpxTavilyTransport(api_key="tvly-test-secret", enabled=True,
                                     max_response_bytes=64, http_transport=httpx.MockTransport(reply))
    outcome = TavilySearchAdapter(admission=Admission(), transport=transport,
                                  enabled=True).search(demand())
    assert outcome.status == status and not outcome.existing_only
    assert outcome.candidates == () and seen == 1
    assert "secret" not in repr(outcome)


def test_http_transport_stream_limit_without_content_length() -> None:
    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"{" + b" " * 40
            yield b" " * 40 + b"}"

    seen = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(200, stream=Stream(), headers={"content-type": "application/json"})

    transport = HttpxTavilyTransport(api_key="tvly-test-secret", enabled=True,
                                     max_response_bytes=64, http_transport=httpx.MockTransport(reply))
    with pytest.raises(TavilyTransportFailure, match="response_too_large"):
        transport.search({"query": "Python list Python 3.12", "search_depth": "basic",
                          "max_results": 5, "auto_parameters": False, "include_answer": False,
                          "include_raw_content": False, "include_images": False,
                          "include_usage": True})
    assert seen == 1


def test_http_timeout_and_network_exception_are_sanitized_without_retry() -> None:
    for failure, status in ((httpx.ReadTimeout("secret-key"), "timeout"),
                            (httpx.ConnectError("secret-key"), "provider_error")):
        seen = 0

        def reply(request: httpx.Request) -> httpx.Response:
            nonlocal seen
            seen += 1
            raise failure

        transport = HttpxTavilyTransport(api_key="tvly-test-secret", enabled=True,
                                         http_transport=httpx.MockTransport(reply))
        outcome = TavilySearchAdapter(admission=Admission(), transport=transport,
                                      enabled=True).search(demand())
        assert outcome.status == status and seen == 1
        assert outcome.receipt is not None and outcome.receipt.credits is None
        assert "secret-key" not in repr(outcome)


def test_http_transport_rejects_arbitrary_payload_and_never_sends_key_in_body() -> None:
    seen = 0

    def reply(request: httpx.Request) -> httpx.Response:
        nonlocal seen
        seen += 1
        return httpx.Response(200, json={"results": []})

    transport = HttpxTavilyTransport(api_key="tvly-test-secret", enabled=True,
                                     http_transport=httpx.MockTransport(reply))
    with pytest.raises(TavilyTransportFailure, match="invalid_search_parameters"):
        transport.search({"query": "private learner text", "api_key": "tvly-test-secret"})
    assert seen == 0