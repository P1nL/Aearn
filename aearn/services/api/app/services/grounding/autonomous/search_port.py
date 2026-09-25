"""Internal B1 search seam; broker owns authorization and durable accounting."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .contracts import SourceCandidate, SourceDiscoveryDemand

SearchStatus = Literal[
    "ok", "disabled", "not_authorized", "quota_exhausted", "rate_limited",
    "authentication_failed", "timeout", "provider_error", "invalid_response",
]


@dataclass(frozen=True)
class SearchPermit:
    """Broker-issued after current access check and durable attempt reservation.

    This value alone is neither a transferable authorization nor a balance.
    Broker must fence the lease and settle even when consumption is uncertain.
    """

    demand: SourceDiscoveryDemand
    attempt_id: str


class SearchAdmission(Protocol):
    def authorize_and_reserve(self, demand: SourceDiscoveryDemand) -> SearchPermit | None: ...


@dataclass(frozen=True)
class SearchReceipt:
    attempt_id: str
    provider_request_id: str | None
    credits: int | None  # None means unknown; do not release the reservation.
    result_count: int


@dataclass(frozen=True)
class SearchOutcome:
    status: SearchStatus
    receipt: SearchReceipt | None = None
    candidates: tuple[SourceCandidate, ...] = ()

    @property
    def existing_only(self) -> bool:
        """Routing hint only; not source/teaching authority or settlement."""
        return self.status == "quota_exhausted"


class SearchPort(Protocol):
    def search(self, demand: SourceDiscoveryDemand) -> SearchOutcome: ...