"""Offline simulations, not real DNS pinning, TLS, or egress acceptance."""
from __future__ import annotations

import asyncio
import gzip
from dataclasses import replace
from hashlib import sha256

import pytest

from app.services.grounding.autonomous.safe_fetch import (
    FetchLimits, PinnedResponse, SafeFetchDenied, SafeFetcher,
)

IP = "93.184.215.14"
URL = "https://example.org/lesson"


async def chunks(*items: bytes):
    for item in items:
        yield item


class Resolver:
    def __init__(self, answers=(IP,)):
        self.answers = answers
        self.calls = []

    async def resolve(self, hostname):
        self.calls.append(hostname)
        return self.answers


class Egress:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = []

    async def attest(self, *, host, ip):
        self.calls.append((host, ip))
        return self.allowed


class Connector:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.closed = 0

    async def open(self, *, host, ip, url, deadline, headers, method="GET"):
        self.calls.append((host, ip, url, dict(headers), method))
        return self.responses.pop(0)

    async def close(self, response):
        self.closed += 1


def response(*, status=200, headers=None, body=b"lesson", **changes):
    base = PinnedResponse(status, headers or {"content-type": "text/html"}, chunks(body),
                          IP, IP, "example.org", True,
                          sent_headers={"accept": "text/html, text/plain, text/markdown"})
    return replace(base, **changes)


def rig(*responses, answers=(IP,), allowed=True, limits=None):
    resolver, connector, egress = Resolver(answers), Connector(*responses), Egress(allowed)
    fetch = SafeFetcher(resolver=resolver, connector=connector, egress=egress,
                        limits=limits, offline_protocol_test=True)
    return fetch, resolver, connector, egress


async def denied(fetch, url=URL):
    with pytest.raises(SafeFetchDenied) as error:
        await fetch.fetch(url)
    return error.value.code


@pytest.mark.asyncio
async def test_live_is_always_closed_even_with_mock_ports():
    fetch, resolver, connector, egress = rig(response())
    fetch.offline_protocol_test = False
    assert await denied(fetch) == "LIVE_EGRESS_UNVERIFIED"
    assert not resolver.calls and not connector.calls and not egress.calls
    assert await denied(SafeFetcher()) == "LIVE_EGRESS_UNVERIFIED"
    fetch.offline_protocol_test = True
    fetch.egress = None
    assert await denied(fetch) == "PORT_MISSING"


@pytest.mark.asyncio
async def test_public_pin_tls_peer_and_bounded_hash():
    fetch, resolver, connector, egress = rig(response(body=b"hello"))
    result = await fetch.fetch(URL)
    assert result.body == b"hello" and result.sha256 == sha256(b"hello").hexdigest()
    assert result.hops == (URL,) and result.final_url == URL
    assert result.evidence_level == "offline_protocol_only"
    assert resolver.calls == ["example.org"] and egress.calls == [("example.org", IP)]
    assert connector.calls == [("example.org", IP, URL,
                                {"accept": "text/html, text/plain, text/markdown"}, "GET")]
    assert connector.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://example.org/", "https://example.org:444/", "https://user:token@example.org/",
    "https://127.0.0.1/", "https://[::1]/", "https://foo.local/",
    "https://example.org\\@127.0.0.1/", "https://example.org/#fragment",
    "https://example.org/\r\nHost:bad", "https://example.org./",
    "https://example.org/?token=secret",
])
async def test_url_denied_before_dns(url):
    fetch, resolver, connector, _ = rig(response())
    assert await denied(fetch, url) == "URL_DENIED"
    assert not resolver.calls and not connector.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.0.1",
    "169.254.169.254", "100.100.100.200", "0.0.0.0", "224.0.0.1",
    "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "not-an-ip",
])
async def test_dns_private_metadata_special_denied_before_connect(ip):
    fetch, _, connector, egress = rig(response(), answers=(IP, ip))
    assert await denied(fetch) == "ADDRESS_DENIED"
    assert not connector.calls and not egress.calls


@pytest.mark.asyncio
async def test_egress_absence_denied_before_connect():
    fetch, resolver, connector, egress = rig(response(), allowed=False)
    assert await denied(fetch) == "EGRESS_UNVERIFIED"
    assert resolver.calls and egress.calls and not connector.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"connected_ip": "8.8.8.8"}, {"peer_ip": "169.254.169.254"},
    {"tls_hostname": "other.org"}, {"tls_verified": False}, {"used_proxy": True},
    {"sent_headers": {"cookie": "secret"}}, {"sent_headers": {"authorization": "secret"}},
])
async def test_peer_tls_proxy_or_request_headers_rejected(changes):
    fetch, _, connector, _ = rig(response(**changes))
    assert await denied(fetch) in ("CONNECTION_DENIED", "ADDRESS_DENIED")
    assert connector.closed == 1


@pytest.mark.asyncio
async def test_redirect_revalidation_loop_and_limit():
    fetch, resolver, connector, _ = rig(response(status=302, headers={"location":
                                                       "https://169.254.169.254/latest"}))
    assert await denied(fetch) == "URL_DENIED"
    assert resolver.calls == ["example.org"] and connector.closed == 1
    fetch, resolver, connector, egress = rig(response(status=301, headers={"location": "/next"}),
                                             response(body=b"next"))
    result = await fetch.fetch(URL)
    assert result.hops == (URL, "https://example.org/next")
    assert len(resolver.calls) == len(connector.calls) == len(egress.calls) == 2
    assert connector.closed == 2
    fetch, _, connector, _ = rig(response(status=302, headers={"location": URL}))
    assert await denied(fetch) == "REDIRECT_LOOP" and connector.closed == 1
    fetch, _, connector, _ = rig(response(status=302, headers={"location": "/next"}),
                                  limits=FetchLimits(redirects=0))
    assert await denied(fetch) == "REDIRECT_LIMIT" and connector.closed == 1


@pytest.mark.asyncio
async def test_type_encoding_status_and_byte_limits():
    for bad, code in [
        (response(headers={"content-type": "application/pdf"}), "TYPE_DENIED"),
        (response(headers={"content-type": "text/html", "content-encoding": "br"}), "ENCODING_DENIED"),
        (response(status=401), "STATUS_DENIED"),
        (response(body=b"x" * 11), "COMPRESSED_LIMIT"),
        (response(headers={"content-type": "text/plain", "content-length": "11"}), "COMPRESSED_LIMIT"),
    ]:
        fetch, _, connector, _ = rig(bad, limits=FetchLimits(compressed_bytes=10))
        assert await denied(fetch) == code and connector.closed == 1
    bomb = gzip.compress(b"x" * 1000)
    fetch, _, connector, _ = rig(response(headers={"content-type": "text/plain",
                                                 "content-encoding": "gzip"}, body=bomb),
                                  limits=FetchLimits(expanded_bytes=100))
    assert await denied(fetch) == "EXPANDED_LIMIT" and connector.closed == 1
    fetch, _, _, _ = rig(response(headers={"content-type": "text/plain",
                                          "content-encoding": "gzip"}, body=gzip.compress(b"hello")))
    assert (await fetch.fetch(URL)).body == b"hello"
    fetch, _, _, _ = rig(response(headers={"content-type": "text/plain",
                                          "content-encoding": "gzip"}, body=b"broken"))
    assert await denied(fetch) == "BODY_DENIED"


@pytest.mark.asyncio
async def test_cancel_and_deadline_interrupt_waiting_resolver():
    class WaitingResolver:
        async def resolve(self, hostname):
            await asyncio.Event().wait()

    connector = Connector(response())
    fetch = SafeFetcher(resolver=WaitingResolver(), connector=connector, egress=Egress(),
                        offline_protocol_test=True, limits=FetchLimits(deadline_seconds=0.02))
    assert await denied(fetch) == "DEADLINE_EXCEEDED"
    event = asyncio.Event()
    event.set()
    with pytest.raises(SafeFetchDenied, match="CANCELLED"):
        await fetch.fetch(URL, cancelled=event)
    event.clear()
    task = asyncio.create_task(fetch.fetch(URL, cancelled=event))
    await asyncio.sleep(0)
    event.set()
    with pytest.raises(SafeFetchDenied, match="CANCELLED"):
        await task
    assert not connector.calls

@pytest.mark.asyncio
async def test_redirect_dns_rebinding_private_answer_blocks_second_connect():
    class RebindingResolver:
        def __init__(self):
            self.calls = 0

        async def resolve(self, hostname):
            self.calls += 1
            return (IP,) if self.calls == 1 else ("169.254.169.254",)

    connector = Connector(response(status=302, headers={"location": "/next"}), response())
    resolver = RebindingResolver()
    fetch = SafeFetcher(resolver=resolver, connector=connector, egress=Egress(),
                        offline_protocol_test=True)
    assert await denied(fetch) == "ADDRESS_DENIED"
    assert resolver.calls == 2 and len(connector.calls) == connector.closed == 1


@pytest.mark.asyncio
async def test_incomplete_body_and_gzip_trailer_rejected():
    fetch, _, connector, _ = rig(response(headers={"content-type": "text/plain",
                                                  "content-length": "8"}, body=b"short"))
    assert await denied(fetch) == "BODY_DENIED" and connector.closed == 1
    compressed = gzip.compress(b"text")
    fetch, _, _, _ = rig(response(headers={"content-type": "text/plain",
                                          "content-encoding": "gzip"}, body=compressed[:-2]))
    assert await denied(fetch) == "BODY_DENIED"
    fetch, _, _, _ = rig(response(headers={"content-type": "text/plain",
                                          "content-encoding": "gzip"}, body=compressed + compressed))
    assert await denied(fetch) == "BODY_DENIED"


@pytest.mark.asyncio
async def test_pending_body_deadline_and_external_cancellation_close_stream():
    async def waiting_body():
        await asyncio.Event().wait()
        yield b"unreachable"

    fetch, _, connector, _ = rig(replace(response(), body=waiting_body()),
                                  limits=FetchLimits(deadline_seconds=0.02))
    assert await denied(fetch) == "DEADLINE_EXCEEDED"
    assert connector.closed == 1
    fetch, _, connector, _ = rig(replace(response(), body=waiting_body()))
    task = asyncio.create_task(fetch.fetch(URL))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert connector.closed == 1


@pytest.mark.asyncio
async def test_transport_exception_is_redacted():
    class BrokenResolver:
        async def resolve(self, hostname):
            raise RuntimeError("SECRET-token-and-private-url")

    fetch = SafeFetcher(resolver=BrokenResolver(), connector=Connector(), egress=Egress(),
                        offline_protocol_test=True)
    assert await denied(fetch) == "TRANSPORT_DENIED"

@pytest.mark.asyncio
async def test_head_none_never_reads_entity_and_hashes_only_empty_response():
    async def forbidden_body():
        raise AssertionError("HEAD response entity read")
        yield b"forbidden"

    head_response = replace(response(headers={"content-type": "text/plain",
                                              "content-length": "999999999"}),
                            body=forbidden_body(), method="HEAD")
    fetch, _, connector, _ = rig(head_response)
    result = await fetch.fetch(URL, capture_kind="none")
    assert result.body == b"" and result.sha256 == sha256(b"").hexdigest()
    assert result.capture_kind == "none" and result.expanded_bytes == 0
    assert connector.calls[0][4] == "HEAD" and connector.closed == 1


@pytest.mark.asyncio
async def test_exact_range_prefix_never_claims_full_hash():
    headers = {"content-type": "text/plain", "content-range": "bytes 0-4/1000000",
               "content-length": "5"}
    fetch, _, connector, _ = rig(replace(response(status=206, headers=headers, body=b"hello"),
                                         sent_headers={"accept": "text/html, text/plain, text/markdown",
                                                       "range": "bytes=0-4", "accept-encoding": "identity"}))
    result = await fetch.fetch(URL, capture_kind="prefix", prefix_bytes=5)
    assert result.body == b"hello" and result.sha256 == sha256(b"hello").hexdigest()
    assert result.range_end == 4 and result.capture_kind == "prefix"
    assert connector.calls[0][3]["range"] == "bytes=0-4"
    assert connector.calls[0][3]["accept-encoding"] == "identity"
    assert connector.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers,code", [
    (200, {"content-type": "text/plain", "content-length": "1000000"}, "RANGE_IGNORED"),
    (206, {"content-type": "text/plain", "content-range": "bytes 0-3/100",
           "content-length": "4"}, "RANGE_DENIED"),
    (206, {"content-type": "text/plain", "content-range": "bytes 0-4/*",
           "content-length": "5"}, "RANGE_DENIED"),
    (206, {"content-type": "text/plain", "content-range": "bytes 0-4/5",
           "content-length": "5"}, "RANGE_DENIED"),
    (206, {"content-type": "text/plain", "content-range": "bytes 0-4/100",
           "content-length": "5", "content-encoding": "gzip"}, "RANGE_DENIED"),
])
async def test_range_ignored_or_ambiguous_denied_without_reading_body(status, headers, code):
    async def forbidden_body():
        raise AssertionError("unbounded body read")
        yield b"forbidden"

    fetch, _, connector, _ = rig(replace(response(status=status, headers=headers),
                                         body=forbidden_body(),
                                         sent_headers={"accept": "text/html, text/plain, text/markdown",
                                                       "range": "bytes=0-4", "accept-encoding": "identity"}))
    with pytest.raises(SafeFetchDenied, match=code):
        await fetch.fetch(URL, capture_kind="prefix", prefix_bytes=5)
    assert connector.closed == 1


@pytest.mark.asyncio
async def test_hop_grant_revocation_before_redirect_dns_and_before_dial():
    first = replace(response(status=302, headers={"location": "/next"}), method="HEAD")
    second = replace(response(headers={"content-type": "text/plain"}), method="HEAD")
    fetch, dns, connector, _ = rig(first, second)
    checks = []

    def grant(url):
        checks.append(url)
        return url == URL

    with pytest.raises(SafeFetchDenied, match="HOP_GRANT_DENIED"):
        await fetch.fetch(URL, capture_kind="none", hop_grant=grant)
    assert dns.calls == ["example.org"] and len(connector.calls) == 1
    assert checks == [URL, URL, "https://example.org/next"]

    fetch, dns, connector, _ = rig(second)
    checks = []

    def expire_before_dial(url):
        checks.append(url)
        return len(checks) == 1

    with pytest.raises(SafeFetchDenied, match="HOP_GRANT_DENIED"):
        await fetch.fetch(URL, capture_kind="none", hop_grant=expire_before_dial)
    assert dns.calls == ["example.org"] and not connector.calls

@pytest.mark.asyncio
async def test_range_redirect_rechecks_each_hop_and_keeps_exact_request():
    request_headers = {"accept": "text/html, text/plain, text/markdown",
                       "range": "bytes=0-4", "accept-encoding": "identity"}
    redirect = replace(response(status=302, headers={"location": "/next"}),
                       sent_headers=request_headers)
    last = replace(response(status=206, headers={"content-type": "text/plain",
                                                  "content-range": "bytes 0-4/100",
                                                  "content-length": "5"}, body=b"hello"),
                   sent_headers=request_headers)
    fetch, dns, connector, egress = rig(redirect, last)
    checks = []
    result = await fetch.fetch(URL, capture_kind="prefix", prefix_bytes=5,
                               hop_grant=lambda url: checks.append(url) or True)
    assert result.hops == (URL, "https://example.org/next")
    assert len(dns.calls) == len(egress.calls) == connector.closed == 2
    assert [call[3] for call in connector.calls] == [request_headers, request_headers]
    assert checks == [URL, URL, "https://example.org/next", "https://example.org/next"]

@pytest.mark.asyncio
async def test_prefix_oversize_fake_stream_is_rejected_even_with_valid_range_headers():
    reply = replace(response(status=206, headers={"content-type": "text/plain",
                                                 "content-range": "bytes 0-4/100",
                                                 "content-length": "5"}, body=b"123456"),
                    sent_headers={"accept": "text/html, text/plain, text/markdown",
                                  "range": "bytes=0-4", "accept-encoding": "identity"})
    fetch, _, connector, _ = rig(reply)
    with pytest.raises(SafeFetchDenied, match="COMPRESSED_LIMIT"):
        await fetch.fetch(URL, capture_kind="prefix", prefix_bytes=5)
    assert connector.closed == 1
