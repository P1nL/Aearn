"""Default-closed Tavily search adapter with bounded HTTP transport.

Only an injected broker with current authority and durable reservation may issue
an attempt. HTTP transport is opt-in; deployment egress and cost approval remain external.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .contracts import ContentCapture, SourceCandidate, SourceDiscoveryDemand, revalidate
from .search_port import SearchAdmission, SearchOutcome, SearchPermit, SearchReceipt, SearchStatus

_ATTEMPT = re.compile(r"[a-z][a-z0-9._:-]{2,159}\Z")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_QUOTA_TEXT = "this request exceeds your plan's set usage limit"
_MAX_RESULTS = 5


@dataclass(frozen=True)
class TavilyResponse:
    status_code: int
    payload: object


class TavilyTransport(Protocol):
    """Injected transport; implementer must supply approved, bounded egress."""

    def search(self, body: dict[str, object]) -> TavilyResponse: ...


_TAVILY_ENDPOINT = "https://api.tavily.com/search"
_MAX_RESPONSE_BYTES = 1_048_576
_FIXED_OPTIONS: dict[str, object] = {
    "search_depth": "basic", "max_results": _MAX_RESULTS,
    "auto_parameters": False, "include_answer": False,
    "include_raw_content": False, "include_images": False,
    "include_usage": True,
}


class TavilyTransportFailure(RuntimeError):
    """Stable local transport failure; never contains provider text or credentials."""


class HttpxTavilyTransport:
    """Opt-in single POST; no redirects, env proxies, cookies or automatic retries.

    `http_transport` is only for isolated tests (httpx.MockTransport); production
    uses HTTPX defaults with no retry transport. Network-level egress approval is
    a separate deployment requirement, not established by this client.
    """

    def __init__(
        self, *, api_key: str | None = None, enabled: bool = False,
        timeout_seconds: float = 10.0, max_response_bytes: int = 262_144,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if (api_key is not None and not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", api_key)):
            raise ValueError("invalid Tavily transport configuration")
        if enabled and api_key is None:
            raise ValueError("invalid Tavily transport configuration")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 20:
            raise ValueError("invalid Tavily transport configuration")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= _MAX_RESPONSE_BYTES:
            raise ValueError("invalid Tavily transport configuration")
        if http_transport is not None and type(http_transport) is not httpx.MockTransport:
            raise ValueError("invalid Tavily transport configuration")
        self._api_key = api_key
        self._enabled = enabled
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._http_transport = http_transport

    def search(self, body: dict[str, object]) -> TavilyResponse:
        if not self._enabled or self._api_key is None:
            raise TavilyTransportFailure("transport_disabled")
        query = body.get("query")
        if (not isinstance(query, str) or not 0 < len(query) <= 480
                or any(ord(c) < 32 for c in query)
                or body != {"query": query, **_FIXED_OPTIONS}):
            raise TavilyTransportFailure("invalid_search_parameters")
        try:
            with httpx.Client(
                timeout=httpx.Timeout(self._timeout_seconds, connect=min(3.0, self._timeout_seconds)),
                trust_env=False, follow_redirects=False, transport=self._http_transport,
            ) as client:
                with client.stream(
                    "POST", _TAVILY_ENDPOINT, json=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json", "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                    follow_redirects=False,
                ) as response:
                    # Reject compression instead of buffering/decompressing an unbounded body.
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise TavilyTransportFailure("invalid_response_encoding")
                    if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                        raise TavilyTransportFailure("invalid_response_type")
                    length = response.headers.get("content-length")
                    if length is not None and (not length.isdecimal() or int(length) > self._max_response_bytes):
                        raise TavilyTransportFailure("response_too_large")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_raw(chunk_size=8192):
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise TavilyTransportFailure("response_too_large")
                        chunks.append(chunk)
                    try:
                        payload: object = json.loads(b"".join(chunks).decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        payload = None
                    return TavilyResponse(response.status_code, payload)
        except httpx.TimeoutException:
            raise TimeoutError("tavily_timeout") from None
        except TavilyTransportFailure:
            raise
        except Exception:
            raise TavilyTransportFailure("transport_unavailable") from None

class TavilySearchAdapter:
    def __init__(
        self, *, admission: SearchAdmission | None = None,
        transport: TavilyTransport | None = None, enabled: bool = False,
    ) -> None:
        self._admission = admission
        self._transport = transport
        self._enabled = enabled

    def search(self, demand: SourceDiscoveryDemand) -> SearchOutcome:
        # An additional kill switch, not a substitute for A's gate or the
        # broker's current actor/policy/budget/lease checks.
        if not self._enabled or self._admission is None or self._transport is None:
            return SearchOutcome("disabled")
        try:
            checked = revalidate(demand, SourceDiscoveryDemand)
            permit = self._admission.authorize_and_reserve(checked)
            if (type(permit) is not SearchPermit or permit.demand != checked
                    or not _ATTEMPT.fullmatch(permit.attempt_id)):
                return SearchOutcome("not_authorized")
        except Exception:
            # Never return input, query, resolver exception or credentials.
            return SearchOutcome("not_authorized")

        body: dict[str, object] = {
            "query": " ".join(checked.query_terms),
            "search_depth": "basic", "max_results": _MAX_RESULTS,
            "auto_parameters": False, "include_answer": False,
            "include_raw_content": False, "include_images": False,
            "include_usage": True,
        }
        try:
            response = self._transport.search(body)
        except TimeoutError:
            return SearchOutcome("timeout", _unknown(permit.attempt_id))
        except Exception:
            return SearchOutcome("provider_error", _unknown(permit.attempt_id))

        if type(response) is not TavilyResponse:
            return SearchOutcome("invalid_response", _unknown(permit.attempt_id))
        status = _classify(response)
        if status != "ok":
            return SearchOutcome(status, _unknown(permit.attempt_id))
        payload = response.payload
        if not isinstance(payload, dict):
            return SearchOutcome("invalid_response", _unknown(permit.attempt_id))
        request_id = payload.get("request_id")
        usage = payload.get("usage")
        credits = usage.get("credits") if isinstance(usage, dict) else None
        safe_id = request_id if isinstance(request_id, str) and _REQUEST_ID.fullmatch(request_id) else None
        safe_credits = credits if type(credits) is int and 0 <= credits <= 100 else None
        receipt = SearchReceipt(permit.attempt_id, safe_id, safe_credits, 0)
        results = payload.get("results")
        if not isinstance(results, list) or len(results) > _MAX_RESULTS:
            return SearchOutcome("invalid_response", receipt)
        candidates: list[SourceCandidate] = []
        for result in results:
            if not isinstance(result, dict) or not _candidate_url(result.get("url")):
                return SearchOutcome("invalid_response", receipt)
            try:
                candidates.append(SourceCandidate(
                    kind="landing", demand_hash=checked.demand_hash, scope=checked.scope,
                    url=result["url"], discovery_receipt_id=permit.attempt_id,
                    capture=ContentCapture(kind="none", captured_bytes=0),
                ))
            except ValueError:
                return SearchOutcome("invalid_response", receipt)
        return SearchOutcome("ok", SearchReceipt(permit.attempt_id, safe_id, safe_credits, len(candidates)),
                             tuple(candidates))


def _unknown(attempt_id: str) -> SearchReceipt:
    return SearchReceipt(attempt_id, None, None, 0)


def _classify(response: TavilyResponse) -> SearchStatus:
    if response.status_code == 200:
        return "ok"
    if response.status_code == 401:
        return "authentication_failed"
    if response.status_code == 429:
        return "rate_limited"
    # Official Search docs show 432 for plan usage, 429 for request rate,
    # 433 for pay-as-you-go cap. Bare status is insufficient evidence.
    payload = response.payload
    if response.status_code == 432 and isinstance(payload, dict):
        detail = payload.get("detail")
        message = detail.get("error") if isinstance(detail, dict) else None
        if isinstance(message, str) and message.strip().casefold().startswith(_QUOTA_TEXT):
            return "quota_exhausted"
    return "provider_error"


def _candidate_url(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None and not parsed.fragment)
    except ValueError:
        return False