"""Local fake TLS streams only: no DNS, provider, live HTTPS or egress proof."""
from __future__ import annotations

import asyncio
import ssl
import time
import traceback

import pytest

from app.services.grounding.autonomous.pinned_tls_connector import PinnedTlsConnector
from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied

IP = "93.184.215.14"
HOST = "example.org"
URL = "https://example.org/lesson"
HEADERS = {"accept": "text/html, text/plain, text/markdown"}


class FakeWriter:
    def __init__(self, *, peer: str = IP, tls: bool = True):
        self.peer = peer
        self.tls = tls
        self.written = bytearray()
        self.closed = False

    def get_extra_info(self, name):
        if name == "peername":
            return (self.peer, 443)
        if name == "ssl_object":
            return object() if self.tls else None
        return None

    def write(self, data):
        self.written.extend(data)

    async def drain(self):
        pass

    def close(self):
        self.closed = True

    async def wait_closed(self):
        pass


def rig(monkeypatch, wire: bytes, *, peer: str = IP, tls: bool = True,
        eof: bool = True, max_body_bytes: int = 1024 * 1024, on_progress=None):
    reader = asyncio.StreamReader()
    reader.feed_data(wire)
    if eof:
        reader.feed_eof()
    writer = FakeWriter(peer=peer, tls=tls)
    calls = []

    async def fake_connect(ip, port, *, ssl, server_hostname):
        calls.append((ip, port, ssl, server_hostname))
        return reader, writer

    monkeypatch.setattr(asyncio, "open_connection", fake_connect)
    return PinnedTlsConnector(max_body_bytes=max_body_bytes, on_progress=on_progress), reader, writer, calls


def head(*lines: bytes, status: bytes = b"HTTP/1.1 200 OK") -> bytes:
    return status + b"\r\n" + b"\r\n".join(lines) + b"\r\n\r\n"


async def open_response(connector, **changes):
    headers = changes.pop("headers", HEADERS)
    return await connector.open(host=HOST, ip=IP, url=URL,
                                deadline=time.monotonic() + 1, headers=headers, **changes)


@pytest.mark.asyncio
async def test_literal_ip_tls_hostname_peer_host_and_exact_request(monkeypatch):
    connector, _, writer, calls = rig(
        monkeypatch, head(b"Content-Type: text/plain", b"Content-Length: 5") + b"hello",
    )
    response = await open_response(connector)
    assert len(calls) == 1 and calls[0][:2] == (IP, 443)
    assert isinstance(calls[0][2], ssl.SSLContext)
    assert calls[0][2].check_hostname and calls[0][2].verify_mode == ssl.CERT_REQUIRED
    assert calls[0][3] == HOST
    assert bytes(writer.written) == (
        b"GET /lesson HTTP/1.1\r\nHost: example.org\r\n"
        b"Accept: text/html, text/plain, text/markdown\r\nConnection: close\r\n\r\n"
    )
    assert response.connected_ip == response.peer_ip == IP
    assert response.tls_hostname == HOST and response.tls_verified
    assert not response.used_proxy and response.sent_headers == HEADERS
    assert response.status == 200 and response.headers["content-type"] == "text/plain"
    assert b"".join([part async for part in response.body]) == b"hello"
    await connector.close(response)
    assert writer.closed


@pytest.mark.asyncio
async def test_full_get_gzip_header_is_exact_and_other_shapes_never_dial(monkeypatch):
    wire = head(b"Content-Type: text/plain", b"Content-Encoding: gzip",
                b"Content-Length: 3") + b"abc"
    connector, _, writer, calls = rig(monkeypatch, wire)
    headers = {**HEADERS, "accept-encoding": "gzip"}
    response = await open_response(connector, headers=headers)
    assert len(calls) == 1
    assert bytes(writer.written) == (
        b"GET /lesson HTTP/1.1\r\nHost: example.org\r\n"
        b"Accept: text/html, text/plain, text/markdown\r\n"
        b"Accept-Encoding: gzip\r\nConnection: close\r\n\r\n"
    )
    assert response.sent_headers == headers
    assert b"".join([part async for part in response.body]) == b"abc"
    await connector.close(response)
    assert writer.closed

    for method, bad_headers in (
        ("HEAD", headers),
        ("GET", {**headers, "range": "bytes=0-4"}),
        ("GET", {**headers, "cookie": "x"}),
        ("GET", {**HEADERS, "accept-encoding": "br"}),
        ("GET", {**HEADERS, "accept-encoding": "GZIP"}),
    ):
        connector, _, _, calls = rig(monkeypatch, b"")
        with pytest.raises(SafeFetchDenied, match="HEADER_DENIED"):
            await open_response(connector, headers=bad_headers, method=method)
        assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["tls", "headers", "body"])
async def test_progress_distinguishes_deadline_stage_without_response_text(monkeypatch, stage):
    progress = []
    wire = (head(b"Content-Type: text/plain", b"Content-Length: 16385",
                 b"Content-Encoding: secret-unsupported-value") + b"x" * 16384
            if stage == "body" else b"")
    connector, _, writer, _ = rig(monkeypatch, wire, eof=False,
                                   on_progress=lambda *args: progress.append(args))
    if stage == "tls":
        async def stalled_connect(*args, **kwargs):
            await asyncio.Event().wait()
        monkeypatch.setattr(asyncio, "open_connection", stalled_connect)
    with pytest.raises(SafeFetchDenied, match="DEADLINE_EXCEEDED"):
        response = await connector.open(host=HOST, ip=IP, url=URL,
                                        deadline=time.monotonic() + .1, headers=HEADERS)
        try:
            _ = [part async for part in response.body]
        finally:
            await connector.close(response)
    assert progress[-1] == (stage, 16384 if stage == "body" else 0,
                            16385 if stage == "body" else None, "unknown")
    assert "secret" not in repr(progress) and URL not in repr(progress) and IP not in repr(progress)
    if stage != "tls":
        assert writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("wire,expected", [
    (head(b"Transfer-Encoding: chunked") + b"3\r\nabc\r\n2\r\nde\r\n0\r\n\r\n", b"abcde"),
    (head(b"Content-Length: 0"), b""),
    (head(b"Location: /next", b"Content-Length: 0", status=b"HTTP/1.1 302 Found"), b""),
])
async def test_valid_framed_streams(monkeypatch, wire, expected):
    connector, _, writer, _ = rig(monkeypatch, wire)
    response = await open_response(connector)
    assert b"".join([part async for part in response.body]) == expected
    await connector.close(response)
    assert writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [
    head(b"Content-Type: text/plain"),  # no framing, not an EOF body
    head(b"Content-Length: 2", b"content-length: 2") + b"ab",
    head(b"Content-Length: 2", b"Transfer-Encoding: chunked") + b"ab",
    head(b"Transfer-Encoding: gzip") + b"ab",
    head(b"Content-Length: 02") + b"ab",
    head(b"Content-Length: -1") + b"ab",
    head(b"Content-Length: 999999999"),
    head(b"Content-Length: 0", b"Folded: yes\r\n continuation"),
    head(b"Content-Length: 0", status=b"HTTP/1.0 200 OK"),
    head(b"Content-Length: 0", status=b"HTTP/1.1 100 Continue"),
    head(b"Content-Length: 0", status=b"HTTP/1.1 204 No Content"),
    b"HTTP/1.1 200 OK\nContent-Length: 0\n\n",
    head(b"X: " + b"x" * (16 * 1024)),
    head(*[b"X" + str(i).encode() + b": a" for i in range(65)]),
    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n",  # incomplete header
])
async def test_malformed_or_ambiguous_head_closes_socket(monkeypatch, wire):
    connector, _, writer, _ = rig(monkeypatch, wire)
    with pytest.raises(SafeFetchDenied):
        await open_response(connector)
    assert writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [
    head(b"Content-Length: 5") + b"abc",
    head(b"Transfer-Encoding: chunked") + b"4\r\nab",
    head(b"Transfer-Encoding: chunked") + b"1;ext=x\r\na\r\n0\r\n\r\n",
    head(b"Transfer-Encoding: chunked") + b"1\r\naX0\r\n\r\n",
    head(b"Transfer-Encoding: chunked") + b"1\r\na\r\n0\r\nX: value\r\n\r\n",
    head(b"Transfer-Encoding: chunked") + b"g\r\n",
    head(b"Transfer-Encoding: chunked") + b"100001\r\n",
])
async def test_incomplete_chunked_and_oversize_body_fail_closed(monkeypatch, wire):
    connector, _, writer, _ = rig(monkeypatch, wire)
    response = await open_response(connector)
    with pytest.raises(SafeFetchDenied):
        _ = b"".join([part async for part in response.body])
    await connector.close(response)
    assert writer.closed


@pytest.mark.asyncio
async def test_configured_limit_and_small_stream_chunks(monkeypatch):
    payload = b"x" * 20000
    connector, _, writer, _ = rig(monkeypatch, head(b"Content-Length: 20000") + payload,
                                  max_body_bytes=20000)
    response = await open_response(connector)
    pieces = [part async for part in response.body]
    assert pieces == [payload[:16384], payload[16384:]]
    await connector.close(response)
    assert writer.closed
    connector, _, writer, _ = rig(monkeypatch, head(b"Content-Length: 20000") + payload,
                                  max_body_bytes=100)
    with pytest.raises(SafeFetchDenied, match="BODY_DENIED"):
        await open_response(connector)
    assert writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("peer,tls", [("127.0.0.1", True), ("93.184.215.15", True), (IP, False)])
async def test_peer_or_tls_mismatch_closes_before_request(monkeypatch, peer, tls):
    connector, _, writer, calls = rig(monkeypatch, b"", peer=peer, tls=tls)
    with pytest.raises(SafeFetchDenied, match="CONNECTION_DENIED|ADDRESS_DENIED"):
        await open_response(connector)
    assert len(calls) == 1 and not writer.written and writer.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("host,ip,url,headers", [
    (HOST, "127.0.0.1", URL, HEADERS),
    ("other.org", IP, URL, HEADERS),
    (HOST, IP, "https://example.org/lesson?secret=1", HEADERS),
    (HOST, IP, URL, {"accept": "x", "cookie": "secret"}),
    (HOST, IP, URL, {"authorization": "token"}),
])
async def test_invalid_request_never_dials(monkeypatch, host, ip, url, headers):
    connector, _, _, calls = rig(monkeypatch, b"")
    with pytest.raises(SafeFetchDenied):
        await connector.open(host=host, ip=ip, url=url,
                             deadline=time.monotonic() + 1, headers=headers)
    assert not calls


@pytest.mark.asyncio
async def test_deadline_and_cancellation_close_pending_stream(monkeypatch):
    connector, reader, writer, _ = rig(monkeypatch, head(b"Content-Length: 5"), eof=False)
    response = await connector.open(host=HOST, ip=IP, url=URL,
                                    deadline=time.monotonic() + .2, headers=HEADERS)
    with pytest.raises(SafeFetchDenied, match="DEADLINE_EXCEEDED"):
        _ = [part async for part in response.body]
    await connector.close(response)
    assert writer.closed
    assert not reader.at_eof()

    connector, _, writer, _ = rig(monkeypatch, head(b"Content-Length: 5"), eof=False)
    response = await open_response(connector)
    async def consume():
        return [part async for part in response.body]

    task = asyncio.create_task(consume())
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await connector.close(response)
    assert writer.closed

@pytest.mark.asyncio
async def test_redirect_can_close_without_consuming_body(monkeypatch):
    connector, _, writer, calls = rig(
        monkeypatch, head(b"Location: /next", b"Content-Length: 100", status=b"HTTP/1.1 302 Found") + b"ignored",
    )
    response = await open_response(connector)
    assert response.status == 302
    await connector.close(response)
    assert writer.closed and len(calls) == 1


@pytest.mark.asyncio
async def test_incomplete_head_deadline_closes_socket(monkeypatch):
    connector, _, writer, calls = rig(monkeypatch, b"HTTP/1.1 200 OK\r\n", eof=False)
    with pytest.raises(SafeFetchDenied, match="DEADLINE_EXCEEDED"):
        await connector.open(host=HOST, ip=IP, url=URL,
                             deadline=time.monotonic() + .2, headers=HEADERS)
    assert writer.closed and len(calls) == 1

@pytest.mark.asyncio
async def test_head_has_no_entity_read_and_range_request_is_exact(monkeypatch):
    connector, _, writer, _ = rig(
        monkeypatch, head(b"Content-Type: text/plain", b"Content-Length: 999999999") + b"ignored",
    )
    response = await open_response(connector, method="HEAD")
    assert bytes(writer.written).startswith(b"HEAD /lesson HTTP/1.1\r\n")
    assert [part async for part in response.body] == []
    await connector.close(response)
    assert writer.closed

    reply = head(b"Content-Type: text/plain", b"Content-Range: bytes 0-4/1000",
                 b"Content-Length: 5", status=b"HTTP/1.1 206 Partial Content") + b"hello"
    connector, _, writer, _ = rig(monkeypatch, reply)
    headers = {**HEADERS, "range": "bytes=0-4", "accept-encoding": "identity"}
    response = await open_response(connector, method="GET", headers=headers)
    assert bytes(writer.written) == (
        b"GET /lesson HTTP/1.1\r\nHost: example.org\r\n"
        b"Accept: text/html, text/plain, text/markdown\r\n"
        b"Range: bytes=0-4\r\nAccept-Encoding: identity\r\nConnection: close\r\n\r\n"
    )
    assert response.sent_headers == headers
    assert b"".join([part async for part in response.body]) == b"hello"
    await connector.close(response)


@pytest.mark.asyncio
async def test_invalid_range_never_dials(monkeypatch):
    connector, _, _, calls = rig(monkeypatch, b"")
    for headers in (
        {**HEADERS, "range": "bytes=0-9999999", "accept-encoding": "identity"},
        {**HEADERS, "range": "bytes=1-4", "accept-encoding": "identity"},
        {**HEADERS, "range": "bytes=0-4"},
    ):
        with pytest.raises(SafeFetchDenied, match="HEADER_DENIED"):
            await open_response(connector, headers=headers)
    assert not calls

@pytest.mark.asyncio
@pytest.mark.parametrize("failure,code", [
    (ssl.SSLCertVerificationError(1, "private certificate details"), "TLS_CERTIFICATE_DENIED"),
    (ssl.SSLError(1, "private TLS details"), "TLS_HANDSHAKE_DENIED"),
    (ConnectionResetError("private connection details"), "CONNECTION_DENIED"),
])
async def test_connect_failure_has_safe_code_without_retry(monkeypatch, failure, code):
    calls = 0

    async def fail_connect(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise failure

    monkeypatch.setattr(asyncio, "open_connection", fail_connect)
    with pytest.raises(SafeFetchDenied) as caught:
        await open_response(PinnedTlsConnector())
    assert str(caught.value) == code
    assert "private" not in "".join(traceback.format_exception(caught.value))
    assert calls == 1


@pytest.mark.asyncio
async def test_formal_eight_mib_header_and_body_boundary(monkeypatch):
    cap = 8 * 1024 * 1024
    payload = b"x" * cap
    connector, _, writer, _ = rig(
        monkeypatch, head(f"Content-Length: {cap}".encode()) + payload,
        max_body_bytes=cap,
    )
    response = await connector.open(
        host=HOST, ip=IP, url=URL,
        deadline=time.monotonic() + 10, headers=HEADERS,
    )
    assert sum(len(part) for part in [piece async for piece in response.body]) == cap
    await connector.close(response)
    assert writer.closed

    connector, _, writer, _ = rig(
        monkeypatch, head(f"Content-Length: {cap + 1}".encode()),
        max_body_bytes=cap,
    )
    with pytest.raises(SafeFetchDenied, match="BODY_DENIED"):
        await open_response(connector)
    assert writer.closed  # reject from header, without reading entity

    connector, _, writer, _ = rig(
        monkeypatch, head(b"Content-Length: 1048577"),
        max_body_bytes=1024 * 1024,
    )
    with pytest.raises(SafeFetchDenied, match="BODY_DENIED"):
        await open_response(connector)
    assert writer.closed  # an explicit lower transport limit remains binding

    with pytest.raises(ValueError, match="INVALID_BODY_LIMIT"):
        PinnedTlsConnector(max_body_bytes=cap + 1)
