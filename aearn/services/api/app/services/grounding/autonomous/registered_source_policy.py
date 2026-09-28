"""Exact operator-registered source hop authority, separate from B discovery.

The resolver is a trusted, current repository-backed port. It must check the
policy/root, storage and network permission, retention, and the persisted
one-shot dispatch for *each* invocation; an in-memory grant is not authority.
This module does not create a DB connection, dispatch, candidate or receipt.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from .safe_fetch import SafeFetchDenied, _validated_url

_SUBJECT = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
_HANDLE = re.compile(r"[a-z][a-z0-9._:-]{2,159}\Z")
_FACET = re.compile(r"[a-z][a-z0-9._-]{0,79}\Z")
_MAX_BYTES = 8 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RegisteredSourceScope:
    """Trusted expected identity, not a grant or proof of a dispatched GET."""

    policy_id: str
    generation: int
    source_handle: str
    subject_id: str
    subject_version: str
    facets: tuple[str, ...]
    url: str
    host: str
    path: str
    root_id: str
    dispatch_id: UUID
    max_bytes: int = 1024 * 1024

    def __post_init__(self) -> None:
        try:
            canonical, host = _validated_url(self.url)
        except SafeFetchDenied as exc:
            raise ValueError("INVALID_REGISTERED_SOURCE_SCOPE") from exc
        path = urlsplit(canonical).path
        if (not isinstance(self.policy_id, str) or _HANDLE.fullmatch(self.policy_id) is None
                or not isinstance(self.source_handle, str)
                or _HANDLE.fullmatch(self.source_handle) is None
                or not isinstance(self.root_id, str) or _HANDLE.fullmatch(self.root_id) is None
                or type(self.dispatch_id) is not UUID
                or type(self.generation) is not int or self.generation < 1
                or not isinstance(self.subject_id, str) or not 3 <= len(self.subject_id) <= 100
                or _SUBJECT.fullmatch(self.subject_id) is None
                or not isinstance(self.subject_version, str)
                or _VERSION.fullmatch(self.subject_version) is None
                or type(self.facets) is not tuple or not 1 <= len(self.facets) <= 24
                or any(not isinstance(facet, str) or _FACET.fullmatch(facet) is None
                       for facet in self.facets)
                or len(set(self.facets)) != len(self.facets)
                or self.url != canonical or self.host != host or self.path != path
                or not path.startswith("/") or "//" in path
                or any(segment in (".", "..") for segment in path.split("/"))
                or "%" in path
                or type(self.max_bytes) is not int or not 0 < self.max_bytes <= _MAX_BYTES):
            raise ValueError("INVALID_REGISTERED_SOURCE_SCOPE")


@dataclass(frozen=True)
class RegisteredSourceHopGrant:
    """Current resolver result, bound to the entire requested identity."""

    scope: RegisteredSourceScope
    allowed: bool
    max_bytes: int
    expires_at: datetime


class RegisteredSourceGrantResolver(Protocol):
    """Read the *current* trusted policy and one-use dispatch outside network I/O.

    A production implementation must fail closed for missing/revoked policy,
    generation, exact host/path/subject mismatch, invalid root or dispatch,
    expired license/storage/retention, and unknown byte/call permission.
    """

    def resolve(self, scope: RegisteredSourceScope, *, now: datetime
                ) -> RegisteredSourceHopGrant | None: ...


@dataclass(frozen=True)
class RegisteredSourceHopPolicy:
    """Only the registered exact URL may be requested; no redirect inherits it."""

    scope: RegisteredSourceScope
    resolver: RegisteredSourceGrantResolver | None = None
    now_factory: Callable[[], datetime] = _utc_now

    def allows(self, url: str, *, initial: bool) -> bool:
        if not initial or self.resolver is None or type(self.scope) is not RegisteredSourceScope:
            return False
        try:
            canonical, _ = _validated_url(url)
            if canonical != url or canonical != self.scope.url:
                return False
            now = self.now_factory()
            if now.tzinfo is None or now.utcoffset() is None:
                return False
            grant = self.resolver.resolve(self.scope, now=now)
            return (type(grant) is RegisteredSourceHopGrant
                    and type(grant.scope) is RegisteredSourceScope
                    and grant.scope == self.scope
                    and grant.allowed is True
                    and type(grant.max_bytes) is int
                    and self.scope.max_bytes <= grant.max_bytes <= _MAX_BYTES
                    and isinstance(grant.expires_at, datetime)
                    and grant.expires_at.tzinfo is not None
                    and grant.expires_at.utcoffset() is not None
                    and now < grant.expires_at)
        except Exception:
            # Never leak a URL, policy row, permission or resolver failure.
            return False
