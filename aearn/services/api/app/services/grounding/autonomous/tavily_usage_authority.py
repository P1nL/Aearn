"""Process-local Tavily observation; lost responses remain unknown in the budget."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from uuid import UUID

from .tavily_search import (
    HttpxTavilyTransport,
    TavilyResponse,
    _REQUEST_ID,
    _candidate_url,
    _classify,
)

_MAX_OBSERVATIONS = 4096


def _attempt(value: UUID | str) -> UUID:
    if isinstance(value, UUID):
        return value
    if (
        not isinstance(value, str)
        or not value.startswith("attempt.")
        or len(value) != 40
        or any(char not in "0123456789abcdef" for char in value[8:])
    ):
        raise ValueError("invalid attempt handle")
    return UUID(hex=value[8:])


@dataclass(frozen=True)
class _Observation:
    kind: str
    receipt_id: str
    provider_request_id: str | None = None
    credits: int | None = None


class TavilyUsageAuthority:
    """One observed transport result per attempt; one exact verification vote.

    After durable take_dispatch, the bridge passes for_attempt(ticket.attempt_id)
    as the TavilySearchAdapter transport. For successful adapter receipts it uses
    usage_receipt(attempt_id, provider_request_id, credits) instead of hashing
    caller-provided fields. For classified 432 it uses the attempt handle as the
    quota receipt. Pass this SAME instance to PostgresDiscoveryWork(usage=...).
    A crash, restart, lost lease or missing evidence keeps the durable hold
    unknown. This is not an in-process malicious-code security boundary.
    """

    def __init__(
        self, transport: HttpxTavilyTransport, *, allow_mock_transport: bool = False
    ) -> None:
        if type(transport) is not HttpxTavilyTransport:
            raise ValueError("credentialed Tavily transport required")
        if transport._http_transport is not None and not allow_mock_transport:
            raise ValueError("mock transport requires explicit test opt-in")
        self._transport = transport
        self._lock = threading.Lock()
        self._issued: set[UUID] = set()
        self._observed: dict[UUID, _Observation] = {}
        self._provider_ids: set[str] = set()

    def for_attempt(self, attempt_id: UUID | str) -> _AttemptTransport:
        identity = _attempt(attempt_id)
        with self._lock:
            # Never evict a claimed identity in this process; saturation closes.
            if identity in self._issued or len(self._issued) >= _MAX_OBSERVATIONS:
                raise ValueError("attempt already issued or authority full")
            self._issued.add(identity)
        return _AttemptTransport(self, identity)

    def _observe(self, identity: UUID, response: TavilyResponse) -> None:
        if type(response) is not TavilyResponse:
            return
        kind = _classify(response)
        if kind == "quota_exhausted":
            observation = _Observation("exhausted", f"attempt.{identity.hex}")
        elif kind == "ok":
            payload = response.payload
            if not isinstance(payload, dict):
                return
            request_id, usage, results = (
                payload.get("request_id"),
                payload.get("usage"),
                payload.get("results"),
            )
            credits = usage.get("credits") if isinstance(usage, dict) else None
            if (
                not isinstance(request_id, str)
                or not _REQUEST_ID.fullmatch(request_id)
                or type(credits) is not int
                or not 0 <= credits <= 100
                or not isinstance(results, list)
                or len(results) > 5
                or any(
                    not isinstance(item, dict) or not _candidate_url(item.get("url"))
                    for item in results
                )
            ):
                return
            observation = _Observation(
                "usage", "usage." + secrets.token_hex(24), request_id, credits
            )
        else:
            # 401, 429, generic 432/433, timeout and provider failures are not
            # account-exhaustion or exact credit evidence.
            return
        with self._lock:
            if identity not in self._issued or identity in self._observed:
                return
            if observation.provider_request_id is not None:
                if observation.provider_request_id in self._provider_ids:
                    return
                self._provider_ids.add(observation.provider_request_id)
            self._observed[identity] = observation

    def usage_receipt(
        self, attempt_id: UUID | str, provider_request_id: str, credits: int
    ) -> str | None:
        """Expose an opaque handle only for an exact observed response."""
        try:
            identity = _attempt(attempt_id)
        except ValueError:
            return None
        with self._lock:
            found = self._observed.get(identity)
            if (
                found is not None
                and found.kind == "usage"
                and found.provider_request_id == provider_request_id
                and type(credits) is int
                and found.credits == credits
            ):
                return found.receipt_id
        return None

    def quota_receipt(self, attempt_id: UUID | str) -> str | None:
        """Expose a quota handle only after the exact 432 was observed."""
        try:
            identity = _attempt(attempt_id)
        except ValueError:
            return None
        with self._lock:
            found = self._observed.get(identity)
            if found is not None and found.kind == "exhausted":
                return found.receipt_id
        return None

    def _verify(
        self, identity: UUID, receipt_id: str, kind: str, units: int | None
    ) -> bool:
        with self._lock:
            found = self._observed.get(identity)
            if (
                found is None
                or found.kind != kind
                or found.receipt_id != receipt_id
                or (
                    kind == "usage"
                    and (type(units) is not int or found.credits != units)
                )
            ):
                return False
            del self._observed[identity]
            return True

    def verify_usage(self, attempt_id: UUID, receipt_id: str, units: int) -> bool:
        return isinstance(attempt_id, UUID) and self._verify(
            attempt_id, receipt_id, "usage", units
        )

    def verify_account_exhausted(self, attempt_id: UUID, receipt_id: str) -> bool:
        return isinstance(attempt_id, UUID) and self._verify(
            attempt_id, receipt_id, "exhausted", None
        )


class _AttemptTransport:
    """One-shot wrapper: never retains body, key or provider payload."""

    def __init__(self, authority: TavilyUsageAuthority, identity: UUID) -> None:
        self._authority = authority
        self._identity = identity
        self._lock = threading.Lock()
        self._called = False

    def search(self, body: dict[str, object]) -> TavilyResponse:
        with self._lock:
            if self._called:
                raise RuntimeError("attempt already sent")
            self._called = True
        response = self._authority._transport.search(body)
        self._authority._observe(self._identity, response)
        return response
