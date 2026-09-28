from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC

os.environ["DATABASE_URL"] = "postgresql://disabled:disabled@127.0.0.1:1/unreachable"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["LLM_TYPE"] = "disabled"

import httpx
import pytest

from app.services.grounding.autonomous.tavily_extract import (
    HttpxTavilyExtractTransport,
    TavilyExtractError,
)

_KEY = "tvly-test-secret"
_URL = "https://www.sqlite.org/lang_select.html"


def _response(payload: object, *, status_code: int = 200) -> httpx.Response:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return httpx.Response(
        status_code,
        stream=httpx.ByteStream(raw),
        headers={"content-type": "application/json"},
    )


def test_extract_success_uses_fixed_bounded_request_and_preserves_hashes(monkeypatch) -> None:
    seen: list[httpx.Request] = []
    payload = {
        "request_id": "123e4567-e89b-12d3-a456-426614174111",
        "results": [{"url": _URL, "raw_content": "# SELECT\nExact source text."}],
        "failed_results": [],
        "usage": {"credits": 2.5},
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(raw),
            headers={"content-type": "application/json"},
        )

    client_kwargs: list[dict[str, object]] = []
    real_client = httpx.Client

    def client_spy(*args, **kwargs):
        client_kwargs.append(kwargs)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client_spy)
    result = HttpxTavilyExtractTransport(
        api_key=_KEY,
        enabled=True,
        api_timeout_seconds=45,
        http_timeout_seconds=60,
        http_transport=httpx.MockTransport(reply),
    ).extract(_URL, extract_depth="advanced", content_format="markdown")

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.tavily.com/extract"
    assert request.headers["authorization"] == f"Bearer {_KEY}"
    assert request.headers["accept-encoding"] == "identity"
    body = json.loads(request.content)
    assert body == {
        "urls": [_URL],
        "extract_depth": "advanced",
        "format": "markdown",
        "include_images": False,
        "include_favicon": False,
        "include_usage": True,
        "timeout": 45,
    }
    assert "query" not in body and "chunks_per_source" not in body
    assert client_kwargs[0]["trust_env"] is False
    assert client_kwargs[0]["follow_redirects"] is False
    assert result.url == _URL
    assert result.content == "# SELECT\nExact source text."
    assert result.content_format == "markdown" and result.extract_depth == "advanced"
    assert result.request_id == payload["request_id"] and result.usage_credits == 2.5
    assert result.content_sha256 == hashlib.sha256(result.content.encode()).hexdigest()
    assert result.response_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.received_at.tzinfo is UTC
    assert result.content not in repr(result)


@pytest.mark.parametrize(
    ("results", "failed_results", "code"),
    [
        ([], [{"url": _URL, "error": "provider private detail"}], "extraction_failed"),
        (
            [{"url": _URL, "raw_content": "partial private content"}],
            [{"url": _URL, "error": "provider private detail"}],
            "partial_extraction",
        ),
    ],
)
def test_failed_results_are_safe_and_distinguish_failed_from_partial(
    results: list[dict[str, str]],
    failed_results: list[dict[str, str]],
    code: str,
) -> None:
    transport = HttpxTavilyExtractTransport(
        api_key=_KEY,
        enabled=True,
        http_transport=httpx.MockTransport(
            lambda request: _response(
                {"request_id": "request_12345678", "results": results, "failed_results": failed_results}
            )
        ),
    )
    with pytest.raises(TavilyExtractError, match=f"^{code}$") as exc_info:
        transport.extract(_URL)
    assert exc_info.value.code == code
    assert "private" not in repr(exc_info.value)


def test_disabled_transport_makes_no_http_call() -> None:
    requests: list[httpx.Request] = []
    mock = httpx.MockTransport(
        lambda request: requests.append(request) or _response({"results": [], "failed_results": []})
    )
    with pytest.raises(TavilyExtractError, match="^transport_disabled$"):
        HttpxTavilyExtractTransport(http_transport=mock).extract(_URL)
    assert requests == []


@pytest.mark.parametrize(
    ("reply", "kwargs", "expected"),
    [
        (lambda request: _response({"detail": "secret"}, status_code=401), {}, "authentication_failed"),
        (lambda request: _response({"detail": "secret"}, status_code=429), {}, "rate_limited"),
        (
            lambda request: _response(
                {"detail": {"error": "This request exceeds your plan's set usage limit"}},
                status_code=432,
            ),
            {},
            "quota_exhausted",
        ),
        (
            lambda request: (_ for _ in ()).throw(httpx.ConnectError("secret transport detail")),
            {},
            "transport_unavailable",
        ),
        (
            lambda request: _response(
                {"results": [{"url": _URL, "raw_content": "12345"}], "failed_results": []}
            ),
            {"max_content_bytes": 4},
            "content_too_large",
        ),
        (
            lambda request: _response(
                {"results": [{"url": _URL, "raw_content": "content"}], "failed_results": []}
            ),
            {"max_response_bytes": 32},
            "response_too_large",
        ),
    ],
)
def test_bounded_safe_error_classification(
    reply,
    kwargs: dict[str, int],
    expected: str,
) -> None:
    transport = HttpxTavilyExtractTransport(
        api_key=_KEY,
        enabled=True,
        http_transport=httpx.MockTransport(reply),
        **kwargs,
    )
    with pytest.raises(TavilyExtractError, match=f"^{expected}$") as exc_info:
        transport.extract(_URL)
    assert exc_info.value.code == expected
    assert "secret" not in repr(exc_info.value)

    unknown_usage = HttpxTavilyExtractTransport(
        api_key=_KEY,
        enabled=True,
        http_transport=httpx.MockTransport(
            lambda request: _response(
                {
                    "results": [{"url": _URL, "raw_content": "content"}],
                    "failed_results": [],
                    "usage": {"credits": True},
                }
            )
        ),
    ).extract(_URL, extract_depth="basic", content_format="text")
    assert unknown_usage.usage_credits is None
