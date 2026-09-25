"""Offline fake-HTTP tests; these do not validate live Tavily billing or egress."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest

from app.services.grounding.autonomous.tavily_search import HttpxTavilyTransport
from app.services.grounding.autonomous.tavily_usage_authority import (
    TavilyUsageAuthority,
)

_KEY = "fake_test_key_12345678"
_ID = "123e4567-e89b-12d3-a456-426614174111"
_BODY: dict[str, object] = {
    "query": "Python list",
    "search_depth": "basic",
    "max_results": 5,
    "auto_parameters": False,
    "include_answer": False,
    "include_raw_content": False,
    "include_images": False,
    "include_usage": True,
}


def _handle(identity: UUID) -> str:
    return f"attempt.{identity.hex}"


def _response(status: int = 200, *, payload: object = None) -> httpx.Response:
    if payload is None:
        payload = {
            "request_id": _ID,
            "usage": {"credits": 1},
            "results": [
                {"url": "https://example.org/guide", "content": "untrusted snippet"}
            ],
        }
    return httpx.Response(
        status, json=payload, headers={"content-type": "application/json"}
    )


def _authority(response: httpx.Response) -> TavilyUsageAuthority:
    mock = httpx.MockTransport(
        lambda _request: httpx.Response(
            response.status_code,
            stream=httpx.ByteStream(response.content),
            headers=response.headers,
        )
    )
    transport = HttpxTavilyTransport(api_key=_KEY, enabled=True, http_transport=mock)
    with pytest.raises(ValueError, match="mock transport"):
        TavilyUsageAuthority(transport)
    return TavilyUsageAuthority(transport, allow_mock_transport=True)


def test_exact_observation_one_vote_no_self_report_or_replay() -> None:
    authority = _authority(_response())
    attempt = uuid4()
    assert authority.usage_receipt(attempt, _ID, 1) is None
    assert not authority.verify_usage(attempt, "usage." + "0" * 48, 1)
    bound = authority.for_attempt(_handle(attempt))
    assert bound.search(_BODY).status_code == 200
    with pytest.raises(RuntimeError, match="already sent"):
        bound.search(_BODY)
    with pytest.raises(ValueError, match="already issued"):
        authority.for_attempt(attempt)
    assert authority.usage_receipt(attempt, _ID, 2) is None
    assert authority.usage_receipt(attempt, "another-id", 1) is None
    receipt = authority.usage_receipt(attempt, _ID, 1)
    assert receipt is not None and receipt.startswith("usage.")
    assert (
        _ID not in receipt
        and _KEY not in receipt
        and "Python" not in repr(authority._observed)
    )
    assert not authority.verify_usage(uuid4(), receipt, 1)
    assert not authority.verify_usage(attempt, receipt, 2)
    assert not authority.verify_usage(attempt, receipt, True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        votes = list(
            pool.map(lambda _i: authority.verify_usage(attempt, receipt, 1), range(8))
        )
    assert votes.count(True) == 1 and votes.count(False) == 7
    assert authority.usage_receipt(attempt, _ID, 1) is None
    # A new worker process has no evidence even if handed the same receipt.
    assert not _authority(_response()).verify_usage(attempt, receipt, 1)


@pytest.mark.parametrize(
    "status,payload,exhausted",
    [
        (
            432,
            {
                "detail": {
                    "error": "This request exceeds your plan's set usage limit. Upgrade"
                }
            },
            True,
        ),
        (
            432,
            {
                "detail": {
                    "error": "Echo: this request exceeds your plan's set usage limit"
                }
            },
            False,
        ),
        (429, {"detail": {"error": "Quota exhausted"}}, False),
        (401, {"detail": {"error": "bad credential"}}, False),
        (433, {"detail": {"error": "pay as you go cap"}}, False),
        (500, {"detail": {"error": "internal"}}, False),
    ],
)
def test_only_specific_observed_account_exhaustion(
    status: int,
    payload: object,
    exhausted: bool,
) -> None:
    authority = _authority(_response(status, payload=payload))
    attempt = uuid4()
    assert authority.for_attempt(attempt).search(_BODY).status_code == status
    assert authority.quota_receipt(attempt) == (_handle(attempt) if exhausted else None)
    assert authority.verify_account_exhausted(attempt, _handle(attempt)) is exhausted
    assert not authority.verify_account_exhausted(attempt, _handle(attempt))
    assert authority.quota_receipt(attempt) is None
    assert authority.usage_receipt(attempt, _ID, 1) is None


@pytest.mark.parametrize(
    "payload",
    [
        {
            "request_id": _ID,
            "usage": {"credits": 1},
            "results": [{"url": "http://example.org"}],
        },
        {"request_id": _ID, "usage": {"credits": True}, "results": []},
        {"request_id": "bad", "usage": {"credits": 1}, "results": []},
        {"request_id": _ID, "usage": {"credits": 1}, "results": "bad"},
    ],
)
def test_malformed_success_is_unknown(payload: object) -> None:
    authority = _authority(_response(payload=payload))
    attempt = uuid4()
    authority.for_attempt(attempt).search(_BODY)
    assert authority.usage_receipt(attempt, _ID, 1) is None
    assert not authority.verify_account_exhausted(attempt, _handle(attempt))


def test_duplicate_provider_request_identity_never_counts_twice() -> None:
    authority = _authority(_response())
    first, second = uuid4(), uuid4()
    authority.for_attempt(first).search(_BODY)
    authority.for_attempt(second).search(_BODY)
    assert authority.usage_receipt(first, _ID, 1) is not None
    assert authority.usage_receipt(second, _ID, 1) is None


def test_untrusted_transport_cannot_be_wired_as_authority() -> None:
    with pytest.raises(ValueError, match="credentialed"):
        TavilyUsageAuthority(object())  # type: ignore[arg-type]
    authority = _authority(_response())
    with pytest.raises(ValueError, match="invalid attempt"):
        authority.for_attempt("attempt.learner-chosen")
    assert authority._observed == {}


def test_transport_timeout_has_no_observation_or_retry() -> None:
    calls = 0

    def timeout(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("fake secret must not escape")

    transport = HttpxTavilyTransport(
        api_key=_KEY, enabled=True, http_transport=httpx.MockTransport(timeout)
    )
    authority = TavilyUsageAuthority(transport, allow_mock_transport=True)
    attempt = uuid4()
    bound = authority.for_attempt(attempt)
    with pytest.raises(TimeoutError, match="tavily_timeout"):
        bound.search(_BODY)
    with pytest.raises(RuntimeError, match="already sent"):
        bound.search(_BODY)
    assert calls == 1
    assert authority.usage_receipt(attempt, _ID, 1) is None
    assert not authority.verify_account_exhausted(attempt, _handle(attempt))
