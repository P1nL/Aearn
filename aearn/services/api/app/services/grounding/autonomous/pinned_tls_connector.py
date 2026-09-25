"""Pinned HTTPS/HTTP/1.1 transport for the internal safe-fetch protocol.

This is an application-layer connector, not an egress attestation. It is not
wired to a live fetch entrypoint. DNS resolution and exit policy remain the
caller's responsibility; no environment proxy or credentials are consulted.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import ssl
import time
from collections.abc import AsyncIterator, Awaitable, Mapping
from typing import TypeVar
from urllib.parse import urlsplit

from .safe_fetch import PinnedResponse, SafeFetchDenied, _public_ip, _validated_url

_T = TypeVar("_T")
_HEADER_MAX = 16 * 1024
_HEADER_COUNT_MAX = 64
_BODY_MAX = 1024 * 1024
_IO_CHUNK = 16 * 1024
_STATUS = re.compile(rb"HTTP/1\.1 ([1-5][0-9]{2})(?: [\x20-\x7e]*)?\Z")
_FIELD = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_VALUE = re.compile(rb"[\x09\x20-\x7e]*\Z")
_LENGTH = re.compile(r"(?:0|[1-9][0-9]{0,8})\Z")
_CHUNK_SIZE = re.compile(rb"[0-9A-Fa-f]{1,8}\Z")
_ACCEPT = "text/html, text/plain, text/markdown"


async def _within(awaitable: Awaitable[_T], deadline: float) -> _T:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        # The caller has already created a coroutine. Close it before denying
        # the deadline so a never-awaited socket/read coroutine cannot linger.
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise SafeFetchDenied("DEADLINE_EXCEEDED")
    try:
        return await asyncio.wait_for(awaitable, remaining)
    except TimeoutError as exc:
        raise SafeFetchDenied("DEADLINE_EXCEEDED") from exc


async def _until(reader: asyncio.StreamReader, marker: bytes, maximum: int,
                 deadline: float) -> bytes:
    # Read no bytes beyond the delimiter, so the body has no speculative buffer.
    data = bytearray()
    while len(data) < maximum:
        part = await _within(reader.read(1), deadline)
        if not part:
            raise SafeFetchDenied("RESPONSE_DENIED")
        data.extend(part)
        if data.endswith(marker):
            return bytes(data)
    raise SafeFetchDenied("RESPONSE_DENIED")


async def _exact(reader: asyncio.StreamReader, count: int, deadline: float) -> bytes:
    try:
        return await _within(reader.readexactly(count), deadline)
    except asyncio.IncompleteReadError as exc:
        raise SafeFetchDenied("BODY_DENIED") from exc


class PinnedTlsConnector:
    """One socket per request; never follows redirects, retries or reads env proxies.

    The caller must supply a vetted public DNS answer and independent egress
    permission. A default SSL context validates the certificate against the
    original hostname even though TCP dials the selected literal IP.
    """

    def __init__(self, *, max_body_bytes: int = _BODY_MAX) -> None:
        if not 0 < max_body_bytes <= _BODY_MAX:
            raise ValueError("INVALID_BODY_LIMIT")
        self.max_body_bytes = max_body_bytes
        self._open: dict[int, tuple[PinnedResponse, asyncio.StreamWriter]] = {}

    async def open(self, *, host: str, ip: str, url: str, deadline: float,
                   headers: Mapping[str, str], method: str = "GET") -> PinnedResponse:
        canonical, url_host = _validated_url(url)
        if canonical != url or host != url_host or _public_ip(ip) != ip:
            raise SafeFetchDenied("CONNECTION_DENIED")
        if method not in ("GET", "HEAD") or not isinstance(headers, Mapping):
            raise SafeFetchDenied("HEADER_DENIED")
        allowed = {"accept": _ACCEPT}
        if method == "GET" and "range" in headers:
            value = headers["range"]
            if not isinstance(value, str) or re.fullmatch(r"bytes=0-[0-9]{1,7}", value) is None:
                raise SafeFetchDenied("HEADER_DENIED")
            end = int(value[8:])
            if end >= min(self.max_body_bytes, 1_000_000):
                raise SafeFetchDenied("HEADER_DENIED")
            allowed.update({"range": value, "accept-encoding": "identity"})
        if dict(headers) != allowed:
            raise SafeFetchDenied("HEADER_DENIED")
        target = urlsplit(url).path or "/"
        try:
            target_bytes = target.encode("ascii")
        except UnicodeEncodeError as exc:
            raise SafeFetchDenied("URL_DENIED") from exc
        if not target_bytes.startswith(b"/") or any(b < 0x20 or b >= 0x7f for b in target_bytes):
            raise SafeFetchDenied("URL_DENIED")

        writer: asyncio.StreamWriter | None = None
        try:
            context = ssl.create_default_context()
            # Passing the literal IP as TCP destination avoids a second DNS
            # lookup; server_hostname drives SNI and certificate hostname check.
            reader, writer = await _within(
                asyncio.open_connection(ip, 443, ssl=context, server_hostname=host), deadline,
            )
            assert writer is not None
            peer = writer.get_extra_info("peername")
            if (not isinstance(peer, tuple) or not peer or not isinstance(peer[0], str)
                    or _public_ip(peer[0]) != ip or writer.get_extra_info("ssl_object") is None):
                raise SafeFetchDenied("CONNECTION_DENIED")
            request = (method.encode("ascii") + b" " + target_bytes + b" HTTP/1.1\r\nHost: "
                       + host.encode("ascii") + b"\r\nAccept: " + _ACCEPT.encode("ascii")
                       + (b"\r\nRange: " + allowed["range"].encode("ascii")
                          + b"\r\nAccept-Encoding: identity" if "range" in allowed else b"")
                       + b"\r\nConnection: close\r\n\r\n")
            writer.write(request)
            await _within(writer.drain(), deadline)
            raw = await _until(reader, b"\r\n\r\n", _HEADER_MAX, deadline)
            status, response_headers, framing, length = self._parse_head(raw, method=method)
            body = (self._empty_body() if method == "HEAD" else
                    self._body(reader, writer, framing, length, deadline))
            response = PinnedResponse(
                status=status, headers=response_headers, body=body, connected_ip=ip,
                peer_ip=ip, tls_hostname=host, tls_verified=True,
                used_proxy=False, sent_headers=allowed, method=method,
            )
            self._open[id(response)] = (response, writer)
            return response
        except BaseException:
            if writer is not None:
                writer.close()
            raise

    @staticmethod
    def _parse_head(raw: bytes, *, method: str = "GET") -> tuple[int, dict[str, str], str, int]:
        if not raw.endswith(b"\r\n\r\n") or b"\n" in raw.replace(b"\r\n", b""):
            raise SafeFetchDenied("RESPONSE_DENIED")
        lines = raw[:-4].split(b"\r\n")
        matched = _STATUS.fullmatch(lines[0])
        if matched is None or len(lines) - 1 > _HEADER_COUNT_MAX:
            raise SafeFetchDenied("RESPONSE_DENIED")
        status = int(matched.group(1))
        if status < 200 or status == 204 or status == 304:
            raise SafeFetchDenied("RESPONSE_DENIED")
        fields: dict[str, str] = {}
        for line in lines[1:]:
            name, sep, value = line.partition(b":")
            if not sep or not _FIELD.fullmatch(name) or not _VALUE.fullmatch(value):
                raise SafeFetchDenied("RESPONSE_DENIED")
            key = name.decode("ascii").lower()
            if key in fields:
                raise SafeFetchDenied("RESPONSE_DENIED")
            fields[key] = value.strip(b" \t").decode("ascii")
        if method == "HEAD":
            if "transfer-encoding" in fields or (
                "content-length" in fields and not _LENGTH.fullmatch(fields["content-length"])
            ):
                raise SafeFetchDenied("RESPONSE_DENIED")
            # Content-Length on HEAD describes the representation, not bytes read.
            return status, fields, "head", 0
        if "transfer-encoding" in fields:
            if "content-length" in fields or fields["transfer-encoding"].lower() != "chunked":
                raise SafeFetchDenied("RESPONSE_DENIED")
            return status, fields, "chunked", 0
        length_value = fields.get("content-length")
        if length_value is None or not _LENGTH.fullmatch(length_value):
            raise SafeFetchDenied("RESPONSE_DENIED")
        length = int(length_value)
        if length > _BODY_MAX:
            raise SafeFetchDenied("BODY_DENIED")
        return status, fields, "length", length

    @staticmethod
    async def _empty_body() -> AsyncIterator[bytes]:
        if False:  # pragma: no cover; maintain async-iterator protocol
            yield b""

    async def _body(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                    framing: str, length: int, deadline: float) -> AsyncIterator[bytes]:
        total = 0
        try:
            if framing == "length":
                if length > self.max_body_bytes:
                    raise SafeFetchDenied("BODY_DENIED")
                while total < length:
                    piece = await _exact(reader, min(_IO_CHUNK, length - total), deadline)
                    total += len(piece)
                    yield piece
            else:
                while True:
                    line = await _until(reader, b"\r\n", 128, deadline)
                    size_text = line[:-2]
                    if not _CHUNK_SIZE.fullmatch(size_text):
                        raise SafeFetchDenied("BODY_DENIED")
                    size = int(size_text, 16)
                    if size == 0:
                        if await _exact(reader, 2, deadline) != b"\r\n":
                            raise SafeFetchDenied("BODY_DENIED")
                        break  # no trailers accepted
                    if total + size > self.max_body_bytes:
                        raise SafeFetchDenied("BODY_DENIED")
                    remaining = size
                    while remaining:
                        piece = await _exact(reader, min(_IO_CHUNK, remaining), deadline)
                        total += len(piece)
                        remaining -= len(piece)
                        yield piece
                    if await _exact(reader, 2, deadline) != b"\r\n":
                        raise SafeFetchDenied("BODY_DENIED")
        finally:
            writer.close()

    async def close(self, response: PinnedResponse) -> None:
        entry = self._open.pop(id(response), None)
        if entry is None or entry[0] is not response:
            return
        writer = entry[1]
        writer.close()
        try:
            await asyncio.wait_for(writer.wait_closed(), 1.0)
        except (TimeoutError, OSError):
            pass
