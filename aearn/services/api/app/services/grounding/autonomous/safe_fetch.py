"""B2 bounded HTTPS protocol; live requires a separate signed egress attestor."""
from __future__ import annotations

import asyncio
import ipaddress
import re
import time
import zlib
from dataclasses import dataclass, field
from hashlib import sha256
from typing import AsyncIterator, Callable, Mapping, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_REDIRECTS = frozenset({301, 302, 303, 307, 308})
_MIME = frozenset({"text/html", "text/plain", "text/markdown"})
_REQUEST_HEADERS = {"accept": "text/html, text/plain, text/markdown"}


class SafeFetchDenied(Exception):
    """Only a stable code; never include URL, response or underlying exception."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FetchLimits:
    compressed_bytes: int = 256 * 1024
    expanded_bytes: int = 1024 * 1024
    redirects: int = 3
    deadline_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (not 0 < self.compressed_bytes <= 1024 * 1024
                or not 0 < self.expanded_bytes <= 4 * 1024 * 1024
                or not 0 <= self.redirects <= 5
                or not 0 < self.deadline_seconds <= 30):
            raise ValueError("INVALID_FETCH_LIMITS")


@dataclass(frozen=True)
class PinnedResponse:
    """Connector evidence; live accepts only the concrete pinned TLS adapter."""
    status: int
    headers: Mapping[str, str]
    body: AsyncIterator[bytes]
    connected_ip: str
    peer_ip: str
    tls_hostname: str
    tls_verified: bool
    used_proxy: bool = False
    sent_headers: Mapping[str, str] | None = None
    method: str = "GET"


class Resolver(Protocol):
    async def resolve(self, hostname: str) -> tuple[str, ...]: ...


class PinnedConnector(Protocol):
    """Dial vetted literal IP with original host/SNI and checked TLS peer."""
    async def open(self, *, host: str, ip: str, url: str, deadline: float,
                   headers: Mapping[str, str], method: str = "GET") -> PinnedResponse: ...

    async def close(self, response: PinnedResponse) -> None: ...


class EgressAttestor(Protocol):
    """Offline seam; live requires a concrete independently signed attestor."""
    async def attest(self, *, host: str, ip: str) -> bool: ...


class HopPolicy(Protocol):
    """Trusted, current probe permission for one exact canonical URL."""
    def allows(self, url: str, *, initial: bool) -> bool: ...


@dataclass(frozen=True)
class FetchResult:
    """SHA-256 covers only response entity bytes actually read.

    For HEAD/none that is SHA-256(empty), not a remote representation hash;
    for GET/prefix it is the exact verified 206 byte range, never the full
    resource digest. Only GET/full has a complete-document digest.
    """
    final_url: str
    hops: tuple[str, ...]
    content_type: str
    body: bytes
    sha256: str
    compressed_bytes: int
    expanded_bytes: int
    evidence_level: str = "offline_protocol_only"
    live_receipt: object | None = field(default=None, repr=False, compare=False)
    capture_kind: str = "full"
    range_end: int | None = None


def _validated_url(url: str) -> tuple[str, str]:
    if (not isinstance(url, str) or not url or len(url) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url):
        raise SafeFetchDenied("URL_DENIED")
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        # Conservatively deny query-bearing candidates: no token-bearing URLs.
        if (parsed.scheme != "https" or not hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or parsed.fragment or parsed.query or parsed.netloc.endswith(".")):
            raise SafeFetchDenied("URL_DENIED")
        host = hostname.encode("idna").decode("ascii").lower()
        if (len(host) > 253 or len(host.split(".")) < 2
                or any(not _HOST_LABEL.fullmatch(part) for part in host.split("."))
                or "[" in parsed.netloc or "]" in parsed.netloc
                or host.replace(".", "").isdigit()
                or host.endswith((".local", ".internal", ".localhost"))):
            raise SafeFetchDenied("URL_DENIED")
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, "")), host
    except (ValueError, UnicodeError) as exc:
        raise SafeFetchDenied("URL_DENIED") from exc


def _public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
        if (not address.is_global or address.is_multicast or address.is_reserved
                or address.is_unspecified or (isinstance(address, ipaddress.IPv6Address)
                                             and address.ipv4_mapped is not None)):
            raise SafeFetchDenied("ADDRESS_DENIED")
        return address.compressed
    except ValueError as exc:
        raise SafeFetchDenied("ADDRESS_DENIED") from exc


def _resolved_public(answers: tuple[str, ...]) -> str:
    if not isinstance(answers, tuple) or not 0 < len(answers) <= 8:
        raise SafeFetchDenied("DNS_DENIED")
    # Reject the entire RRset if even one answer is private/ambiguous.
    checked = tuple(_public_ip(answer) for answer in answers)
    if len(set(checked)) != len(checked):
        raise SafeFetchDenied("DNS_DENIED")
    return checked[0]  # no DNS retry/fallback after a failed pinned connection


def _headers(headers: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in headers.items():
        name = key.lower()
        if name in normalized or not isinstance(value, str) or "\r" in value or chr(10) in value:
            raise SafeFetchDenied("HEADER_DENIED")
        normalized[name] = value
    return normalized


async def _read_body(response: PinnedResponse, *, encoding: str,
                     compressed_limit: int, expanded_limit: int,
                     deadline: float) -> tuple[bytes, int, int]:
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
    output = bytearray()
    compressed = 0
    iterator = response.body.__aiter__()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SafeFetchDenied("DEADLINE_EXCEEDED")
        try:
            chunk = await asyncio.wait_for(iterator.__anext__(), remaining)
        except StopAsyncIteration:
            break
        if not isinstance(chunk, bytes) or not chunk:
            raise SafeFetchDenied("BODY_DENIED")
        compressed += len(chunk)
        if compressed > compressed_limit:
            raise SafeFetchDenied("COMPRESSED_LIMIT")
        try:
            piece = decoder.decompress(chunk, expanded_limit - len(output) + 1) if decoder else chunk
        except zlib.error as exc:
            raise SafeFetchDenied("BODY_DENIED") from exc
        if len(output) + len(piece) > expanded_limit or (decoder and decoder.unconsumed_tail):
            raise SafeFetchDenied("EXPANDED_LIMIT")
        if decoder and decoder.unused_data:
            raise SafeFetchDenied("BODY_DENIED")
        output.extend(piece)
    if decoder:
        if not decoder.eof:
            raise SafeFetchDenied("BODY_DENIED")
        try:
            trailer = decoder.flush(expanded_limit - len(output) + 1)
        except zlib.error as exc:
            raise SafeFetchDenied("BODY_DENIED") from exc
        if len(output) + len(trailer) > expanded_limit:
            raise SafeFetchDenied("EXPANDED_LIMIT")
        output.extend(trailer)
    return bytes(output), compressed, len(output)


class SafeFetcher:
    def __init__(self, *, resolver: Resolver | None = None,
                 connector: PinnedConnector | None = None,
                 egress: EgressAttestor | None = None,
                 hop_policy: HopPolicy | None = None,
                 limits: FetchLimits | None = None,
                 offline_protocol_test: bool = False) -> None:
        self.resolver = resolver
        self.connector = connector
        self.egress = egress
        self.hop_policy = hop_policy
        self.limits = limits or FetchLimits()
        self.offline_protocol_test = offline_protocol_test
        self._live_receipts: dict[object, tuple[str, str, float]] = {}

    @property
    def live_ready(self) -> bool:
        """Structural precondition only; each hop still needs fresh signed proof."""
        from .hop_policy import CandidateHopPolicy
        from .live_egress import LiveEgressAttestor
        from .pinned_tls_connector import PinnedTlsConnector
        from .public_dns import PublicDnsResolver

        return (not self.offline_protocol_test
                and type(self.resolver) is PublicDnsResolver
                and type(self.connector) is PinnedTlsConnector
                and type(self.egress) is LiveEgressAttestor
                and type(self.hop_policy) is CandidateHopPolicy)

    def consume_live_receipt(self, receipt: object | None, *, url: str, digest: str) -> bool:
        """One-use in-process proof of a completed pinned and attested fetch."""
        if receipt is None or self.offline_protocol_test:
            return False
        expected = self._live_receipts.pop(receipt, None)
        return (expected is not None and expected[:2] == (url, digest)
                and time.monotonic() < expected[2])

    async def fetch(self, url: str, *, capture_kind: str = "full",
                    prefix_bytes: int = 0,
                    cancelled: asyncio.Event | None = None,
                    hop_grant: Callable[[str], bool] | None = None) -> FetchResult:
        """Offline fake ports cannot be substituted for live transport/attestation."""
        if (capture_kind not in ("none", "prefix", "full")
                or type(prefix_bytes) is not int
                or (capture_kind != "prefix" and prefix_bytes != 0)
                or (capture_kind == "prefix" and not 0 < prefix_bytes < min(1_000_000, self.limits.expanded_bytes))):
            raise SafeFetchDenied("CAPTURE_SCOPE_INVALID")
        if not self.offline_protocol_test:
            if not self.live_ready:
                raise SafeFetchDenied("LIVE_EGRESS_UNVERIFIED")
            self._live_receipts = {
                token: receipt for token, receipt in self._live_receipts.items()
                if time.monotonic() < receipt[2]
            }
            if len(self._live_receipts) >= 32:
                raise SafeFetchDenied("LIVE_RECEIPT_LIMIT")
        if self.resolver is None or self.connector is None or self.egress is None:
            raise SafeFetchDenied("PORT_MISSING")
        if cancelled is not None and cancelled.is_set():
            raise SafeFetchDenied("CANCELLED")
        work = asyncio.create_task(self._fetch_hops(url, capture_kind, prefix_bytes, hop_grant))
        watcher = asyncio.create_task(cancelled.wait()) if cancelled is not None else None
        try:
            tasks = {work, watcher} if watcher is not None else {work}
            done, _ = await asyncio.wait(tasks, timeout=self.limits.deadline_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
            if not done:
                raise SafeFetchDenied("DEADLINE_EXCEEDED")
            if watcher is not None and watcher in done:
                raise SafeFetchDenied("CANCELLED")
            try:
                return await work
            except SafeFetchDenied:
                raise
            except TimeoutError as exc:
                raise SafeFetchDenied("DEADLINE_EXCEEDED") from exc
            except Exception as exc:
                raise SafeFetchDenied("TRANSPORT_DENIED") from exc
        finally:
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if not work.done():
                work.cancel()
            await asyncio.gather(work, return_exceptions=True)

    async def _fetch_hops(self, url: str, capture_kind: str, prefix_bytes: int,
                          hop_grant: Callable[[str], bool] | None) -> FetchResult:
        assert self.resolver is not None and self.connector is not None and self.egress is not None
        deadline = time.monotonic() + self.limits.deadline_seconds
        hops: list[str] = []
        visited: set[str] = set()
        compressed_total = 0
        method = "HEAD" if capture_kind == "none" else "GET"
        request_headers = (_REQUEST_HEADERS if capture_kind != "prefix" else
                           {**_REQUEST_HEADERS, "range": f"bytes=0-{prefix_bytes - 1}",
                            "accept-encoding": "identity"})
        for _ in range(self.limits.redirects + 1):
            current, host = _validated_url(url)
            if current in visited:
                raise SafeFetchDenied("REDIRECT_LOOP")
            visited.add(current)
            hops.append(current)
            try:
                self._check_hop_policy(current, initial=len(hops) == 1)
                self._check_grant(hop_grant, current)
                ip = _resolved_public(await self.resolver.resolve(host))
                if not await self.egress.attest(host=host, ip=ip):
                    raise SafeFetchDenied("EGRESS_UNVERIFIED")
                self._check_hop_policy(current, initial=len(hops) == 1)
                self._check_grant(hop_grant, current)
                response = await self.connector.open(
                    host=host, ip=ip, url=current, deadline=deadline,
                    headers=request_headers, method=method,
                )
            except SafeFetchDenied:
                raise
            except Exception as exc:
                raise SafeFetchDenied("TRANSPORT_DENIED") from exc
            try:
                if (response.connected_ip != ip or _public_ip(response.peer_ip) != ip
                        or response.tls_hostname.lower() != host or not response.tls_verified
                        or response.used_proxy or response.sent_headers is None
                        or response.method != method
                        or _headers(response.sent_headers) != request_headers):
                    raise SafeFetchDenied("CONNECTION_DENIED")
                headers = _headers(response.headers)
                if response.status in _REDIRECTS:
                    location = headers.get("location")
                    if not location:
                        raise SafeFetchDenied("REDIRECT_DENIED")
                    url = urljoin(current, location)
                    _validated_url(url)
                    continue
                expected_status = 206 if capture_kind == "prefix" else 200
                if response.status != expected_status:
                    # In particular, a server ignoring Range never licenses reading a full GET.
                    raise SafeFetchDenied("RANGE_IGNORED" if capture_kind == "prefix" and response.status == 200
                                          else "STATUS_DENIED")
                mime = headers.get("content-type", "").split(";", 1)[0].lower().strip()
                if mime not in _MIME:
                    raise SafeFetchDenied("TYPE_DENIED")
                encoding = headers.get("content-encoding", "identity").lower().strip()
                if encoding not in ("identity", "gzip"):
                    raise SafeFetchDenied("ENCODING_DENIED")
                length = headers.get("content-length")
                if capture_kind == "none":
                    # HEAD has no response entity. This is SHA-256(empty response),
                    # NOT a claim to hash the remote representation.
                    if headers.get("transfer-encoding"):
                        raise SafeFetchDenied("HEAD_DENIED")
                    digest = sha256(b"").hexdigest()
                    receipt = self._receipt(hops[0], digest)
                    return FetchResult(current, tuple(hops), mime, b"", digest, 0, 0,
                                       "offline_protocol_only" if receipt is None else "live_egress_attested",
                                       receipt, "none")
                if capture_kind == "prefix":
                    # Exact single range and known total are required. Multipart,
                    # compression, weaker/shorter range and unknown totals close.
                    total = headers.get("content-range", "")
                    match = re.fullmatch(r"bytes 0-([0-9]+)/([0-9]+)", total)
                    if (encoding != "identity" or match is None
                            or int(match[1]) != prefix_bytes - 1
                            or int(match[2]) <= prefix_bytes
                            or length != str(prefix_bytes)
                            or headers.get("transfer-encoding")):
                        raise SafeFetchDenied("RANGE_DENIED")
                if length is not None and (len(length) > 9 or not length.isascii()
                                           or not length.isdecimal()
                                           or int(length) > self.limits.compressed_bytes - compressed_total):
                    raise SafeFetchDenied("COMPRESSED_LIMIT")
                body, compressed, expanded = await _read_body(
                    response, encoding=encoding,
                    compressed_limit=(prefix_bytes if capture_kind == "prefix"
                                      else self.limits.compressed_bytes - compressed_total),
                    expanded_limit=(prefix_bytes if capture_kind == "prefix"
                                    else self.limits.expanded_bytes), deadline=deadline,
                )
                if length is not None and compressed != int(length):
                    raise SafeFetchDenied("BODY_DENIED")
                compressed_total += compressed
                digest = sha256(body).hexdigest()
                receipt = self._receipt(hops[0], digest)
                return FetchResult(current, tuple(hops), mime, body, digest,
                                   compressed_total, expanded,
                                   "offline_protocol_only" if receipt is None else "live_egress_attested",
                                   receipt, capture_kind,
                                   prefix_bytes - 1 if capture_kind == "prefix" else None)
            finally:
                await self.connector.close(response)
        raise SafeFetchDenied("REDIRECT_LIMIT")

    def _check_grant(self, guard: Callable[[str], bool] | None, url: str) -> None:
        if guard is None:
            if self.offline_protocol_test:
                return
            raise SafeFetchDenied("HOP_GRANT_DENIED")
        try:
            allowed = guard(url)
        except Exception as exc:
            raise SafeFetchDenied("HOP_GRANT_DENIED") from exc
        if allowed is not True:
            raise SafeFetchDenied("HOP_GRANT_DENIED")

    def _receipt(self, initial_url: str, digest: str) -> object | None:
        if self.offline_protocol_test:
            return None
        receipt = object()
        self._live_receipts[receipt] = (initial_url, digest, time.monotonic() + 30)
        return receipt

    def _check_hop_policy(self, url: str, *, initial: bool) -> None:
        policy = self.hop_policy
        if policy is None:
            # Strictly an offline compatibility seam; live entry always closes.
            if self.offline_protocol_test:
                return
            raise SafeFetchDenied("PROBE_POLICY_DENIED")
        try:
            allowed = policy.allows(url, initial=initial)
        except Exception as exc:
            raise SafeFetchDenied("PROBE_POLICY_DENIED") from exc
        if allowed is not True:
            raise SafeFetchDenied("PROBE_POLICY_DENIED")
