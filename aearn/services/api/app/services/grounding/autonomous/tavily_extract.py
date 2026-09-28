"""Default-closed, bounded Tavily Extract transport.

This adapter performs one provider extraction request for one exact public HTTPS
URL. Provider text is untrusted acquisition material; this module does not grant
source admission, origin-TLS attestation, or consumer authority.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

_TAVILY_EXTRACT_ENDPOINT = "https://api.tavily.com/extract"
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_CONTENT_BYTES = 8 * 1024 * 1024
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_API_KEY = re.compile(r"[A-Za-z0-9_-]{8,256}\Z")
_HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_QUOTA_TEXT = "this request exceeds your plan's set usage limit"


class TavilyExtractError(RuntimeError):
    """Stable safe failure whose message is only a local error code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TavilyExtractResult:
    url: str
    content: str = field(repr=False)
    content_format: str
    extract_depth: str
    request_id: str | None
    usage_credits: int | float | None
    content_sha256: str
    response_sha256: str
    received_at: datetime


class HttpxTavilyExtractTransport:
    """Opt-in single POST with no redirects, retries, cookies, or env proxies."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        enabled: bool = False,
        api_timeout_seconds: int = 60,
        http_timeout_seconds: float = 75.0,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
        max_content_bytes: int = _MAX_CONTENT_BYTES,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if api_key is not None and not _API_KEY.fullmatch(api_key):
            raise ValueError("invalid Tavily Extract transport configuration")
        if enabled and api_key is None:
            raise ValueError("invalid Tavily Extract transport configuration")
        if type(api_timeout_seconds) is not int or not 1 <= api_timeout_seconds <= 60:
            raise ValueError("invalid Tavily Extract transport configuration")
        if (
            not math.isfinite(http_timeout_seconds)
            or not 0 < http_timeout_seconds <= 75
            or http_timeout_seconds < api_timeout_seconds
        ):
            raise ValueError("invalid Tavily Extract transport configuration")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ValueError("invalid Tavily Extract transport configuration")
        if type(max_content_bytes) is not int or not 1 <= max_content_bytes <= _MAX_CONTENT_BYTES:
            raise ValueError("invalid Tavily Extract transport configuration")
        if http_transport is not None and type(http_transport) is not httpx.MockTransport:
            raise ValueError("invalid Tavily Extract transport configuration")

        self._api_key = api_key
        self._enabled = enabled
        self._api_timeout_seconds = api_timeout_seconds
        self._http_timeout_seconds = http_timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._max_content_bytes = max_content_bytes
        self._http_transport = http_transport

    def extract(
        self,
        url: str,
        *,
        extract_depth: str = "advanced",
        content_format: str = "markdown",
    ) -> TavilyExtractResult:
        if not self._enabled or self._api_key is None:
            raise TavilyExtractError("transport_disabled")
        if not _public_https_url(url) or extract_depth not in {"advanced", "basic"}:
            raise TavilyExtractError("invalid_extract_parameters")
        if content_format not in {"markdown", "text"}:
            raise TavilyExtractError("invalid_extract_parameters")

        body: dict[str, object] = {
            "urls": [url],
            "extract_depth": extract_depth,
            "format": content_format,
            "include_images": False,
            "include_favicon": False,
            "include_usage": True,
            "timeout": self._api_timeout_seconds,
        }
        raw, status_code = self._post(body)
        response_sha256 = hashlib.sha256(raw).hexdigest()
        try:
            payload: object = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None

        if status_code != 200:
            raise TavilyExtractError(_http_error(status_code, payload))
        if not isinstance(payload, dict):
            raise TavilyExtractError("invalid_response")

        results = payload.get("results")
        failed_results = payload.get("failed_results")
        if not isinstance(results, list) or not isinstance(failed_results, list):
            raise TavilyExtractError("invalid_response")
        exact_results = [item for item in results if isinstance(item, dict) and item.get("url") == url]
        if failed_results:
            if exact_results:
                raise TavilyExtractError("partial_extraction")
            raise TavilyExtractError("extraction_failed")
        if len(results) != 1 or len(exact_results) != 1:
            raise TavilyExtractError("invalid_response")

        content = exact_results[0].get("raw_content")
        if not isinstance(content, str) or not content:
            raise TavilyExtractError("extraction_failed")
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > self._max_content_bytes:
            raise TavilyExtractError("content_too_large")

        request_id = payload.get("request_id")
        safe_request_id = (
            request_id
            if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id)
            else None
        )
        usage = payload.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        safe_credits: int | float | None = None
        if isinstance(credits, (int, float)) and not isinstance(credits, bool) and math.isfinite(credits) and credits >= 0:
            safe_credits = credits

        return TavilyExtractResult(
            url=url,
            content=content,
            content_format=content_format,
            extract_depth=extract_depth,
            request_id=safe_request_id,
            usage_credits=safe_credits,
            content_sha256=hashlib.sha256(content_bytes).hexdigest(),
            response_sha256=response_sha256,
            received_at=datetime.now(UTC),
        )

    def _post(self, body: dict[str, object]) -> tuple[bytes, int]:
        try:
            with httpx.Client(
                timeout=httpx.Timeout(
                    self._http_timeout_seconds,
                    connect=min(5.0, self._http_timeout_seconds),
                ),
                trust_env=False,
                follow_redirects=False,
                transport=self._http_transport,
            ) as client:
                with client.stream(
                    "POST",
                    _TAVILY_EXTRACT_ENDPOINT,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    follow_redirects=False,
                ) as response:
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise TavilyExtractError("invalid_response_encoding")
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if content_type.strip().lower() != "application/json":
                        raise TavilyExtractError("invalid_response_type")
                    length = response.headers.get("content-length")
                    if length is not None and (
                        not length.isdecimal() or int(length) > self._max_response_bytes
                    ):
                        raise TavilyExtractError("response_too_large")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_raw(chunk_size=8192):
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise TavilyExtractError("response_too_large")
                        chunks.append(chunk)
                    return b"".join(chunks), response.status_code
        except httpx.TimeoutException:
            raise TavilyExtractError("tavily_extract_timeout") from None
        except TavilyExtractError:
            raise
        except Exception:
            raise TavilyExtractError("transport_unavailable") from None


def _http_error(status_code: int, payload: object) -> str:
    if status_code == 401:
        return "authentication_failed"
    if status_code == 429:
        return "rate_limited"
    if status_code == 433:
        return "quota_exhausted"
    if status_code == 432 and isinstance(payload, dict):
        detail = payload.get("detail")
        message = detail.get("error") if isinstance(detail, dict) else None
        if isinstance(message, str) and message.strip().casefold().startswith(_QUOTA_TEXT):
            return "quota_exhausted"
    return "provider_error"


def _public_https_url(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return False
    if any(ord(char) < 33 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.port not in (None, 443)
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.fragment)
        ):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            ascii_host = host.encode("idna").decode("ascii")
            labels = ascii_host.rstrip(".").split(".")
            return (
                len(labels) >= 2
                and ascii_host.casefold() != "localhost"
                and not ascii_host.casefold().endswith(".localhost")
                and all(_HOST_LABEL.fullmatch(label) for label in labels)
            )
    except (UnicodeError, ValueError):
        return False
