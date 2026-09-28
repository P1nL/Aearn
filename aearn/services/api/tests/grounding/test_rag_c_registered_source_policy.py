"""Registered source hop checks use fake ports only; no live DNS, DB or provider."""
from __future__ import annotations

import asyncio
import gzip
import time
from dataclasses import replace
from hashlib import sha256
from datetime import timedelta
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.registered_source_policy import (
    RegisteredSourceGrantResolver, RegisteredSourceHopGrant, RegisteredSourceHopPolicy,
    RegisteredSourceScope,
)
from app.services.grounding.autonomous.safe_fetch import FetchLimits, SafeFetchDenied, SafeFetcher
from tests.grounding.rag_material_helpers import NOW
from tests.grounding.test_rag_b_safe_fetch import Connector, Egress, Resolver, response

URL = "https://example.org/lesson"


class CurrentGrant:
    """Fake current authority; production repository must verify dispatch/root/grants."""

    def __init__(self) -> None:
        self.calls = []
        self.allowed = False
        self.generation = 1
        self.expiry = NOW + timedelta(minutes=1)
        self.max_bytes = 1024 * 1024
        self.failure = False
        self.scope_override = None

    def resolve(self, scope, *, now):
        self.calls.append((scope, now))
        if self.failure:
            raise RuntimeError("secret and raw URL")
        return RegisteredSourceHopGrant(
            scope=self.scope_override or replace(scope, generation=self.generation),
            allowed=self.allowed,
            max_bytes=self.max_bytes, expires_at=self.expiry,
        )


def rig(*responses, grant=None, limits=None, request_gzip=False):
    scope = RegisteredSourceScope(
        policy_id="sqlite-select", generation=1, source_handle="sqlite-select",
        subject_id="route.sql", subject_version="v1", facets=("queries",),
        url=URL, host="example.org", path="/lesson", root_id="sqlite-root",
        dispatch_id=uuid4(),
    )
    current = grant or CurrentGrant()
    hop = RegisteredSourceHopPolicy(scope=scope, resolver=current, now_factory=lambda: NOW)
    dns, connector, egress = Resolver(), Connector(*responses), Egress()
    fetcher = SafeFetcher(
        resolver=dns, connector=connector, egress=egress, hop_policy=hop,
        limits=limits or FetchLimits(redirects=0), offline_protocol_test=True,
        request_gzip=request_gzip,
    )
    return fetcher, dns, connector, egress, current


@pytest.mark.asyncio
async def test_default_off_then_exact_full_fetch_rechecks_before_dns_and_dial():
    fetcher, dns, connector, egress, current = rig(response(body=b"full document"))
    with pytest.raises(SafeFetchDenied, match="PROBE_POLICY_DENIED"):
        await fetcher.fetch(URL)
    assert len(current.calls) == 1 and not dns.calls and not connector.calls
    current.allowed = True
    result = await fetcher.fetch(URL)
    assert result.capture_kind == "full" and result.body == b"full document"
    assert result.evidence_level == "offline_protocol_only" and result.live_receipt is None
    assert result.hops == (URL,) and result.final_url == URL
    assert len(current.calls) == 3 and dns.calls == ["example.org"]
    assert len(connector.calls) == connector.closed == 1 and len(egress.calls) == 1


@pytest.mark.asyncio
async def test_revoked_after_dns_blocks_pinned_dial():
    fetcher, dns, connector, _, current = rig(response())
    current.allowed = True
    original = dns.resolve

    async def revoke(host):
        result = await original(host)
        current.allowed = False
        return result

    dns.resolve = revoke
    with pytest.raises(SafeFetchDenied, match="PROBE_POLICY_DENIED"):
        await fetcher.fetch(URL)
    assert len(current.calls) == 2 and len(dns.calls) == 1 and not connector.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["generation", "root", "dispatch", "facets",
                                    "expired", "byte_cap", "failure"])
async def test_stale_or_failing_resolver_never_reaches_dns(change):
    fetcher, dns, connector, _, current = rig(response())
    current.allowed = True
    if change == "generation":
        current.generation = 2
    elif change in ("root", "dispatch", "facets"):
        current.scope_override = replace(
            fetcher.hop_policy.scope,
            **{("dispatch_id" if change == "dispatch" else
                "root_id" if change == "root" else "facets"):
               uuid4() if change == "dispatch" else
               ("schema",) if change == "facets" else "other-root"},
        )
    elif change == "expired":
        current.expiry = NOW
    elif change == "byte_cap":
        current.max_bytes = 100
    else:
        current.failure = True
    with pytest.raises(SafeFetchDenied) as exc:
        await fetcher.fetch(URL)
    assert exc.value.code == "PROBE_POLICY_DENIED"
    assert "secret" not in str(exc.value) and not dns.calls and not connector.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://example.org/other", "https://other.org/lesson",
    "https://EXAMPLE.org/lesson", "https://example.org/lesson?x=1",
])
async def test_only_exact_url_allowed(url):
    fetcher, dns, connector, _, current = rig(response())
    current.allowed = True
    with pytest.raises(SafeFetchDenied):
        await fetcher.fetch(url)
    assert not dns.calls and not connector.calls


@pytest.mark.asyncio
async def test_redirect_is_rejected_after_one_request_without_following():
    fetcher, dns, connector, _, current = rig(
        response(status=302, headers={"location": "/next"}), response(),
    )
    current.allowed = True
    with pytest.raises(SafeFetchDenied, match="REDIRECT_DENIED"):
        await fetcher.fetch(URL)
    assert dns.calls == ["example.org"] and len(connector.calls) == connector.closed == 1
    assert len(current.calls) == 2


@pytest.mark.asyncio
async def test_full_only_zero_redirects_and_limits_checked_before_ports():
    fetcher, dns, connector, _, current = rig(response())
    current.allowed = True
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL, capture_kind="prefix", prefix_bytes=20)
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL, capture_kind="none")
    fetcher.limits = FetchLimits(redirects=1)
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    fetcher.limits = FetchLimits(redirects=0, expanded_bytes=1024 * 1024 + 1)
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    assert not dns.calls and not connector.calls and not current.calls


@pytest.mark.parametrize("change", [
    {"host": "other.org"}, {"path": "/other"},
    {"url": "https://EXAMPLE.org/lesson"}, {"path": "/%2e%2e/lesson"},
    {"max_bytes": 8 * 1024 * 1024 + 1}, {"generation": 0},
    {"root_id": ""}, {"source_handle": ""}, {"facets": ("queries", "queries")},
])
def test_scope_rejects_unbound_or_ambiguous_identity(change):
    scope = rig()[0].hop_policy.scope
    with pytest.raises(ValueError, match="INVALID_REGISTERED_SOURCE_SCOPE"):
        replace(scope, **change)


def test_live_structural_gate_accepts_only_two_concrete_policy_types(monkeypatch):
    from app.services.grounding.autonomous import live_egress, pinned_tls_connector, public_dns

    # Replace adapter types themselves: this only exercises the structural gate.
    # No real DNS, socket, signed attestor or live fetch is constructed or called.
    monkeypatch.setattr(public_dns, "PublicDnsResolver", Resolver)
    monkeypatch.setattr(pinned_tls_connector, "PinnedTlsConnector", Connector)
    monkeypatch.setattr(live_egress, "LiveEgressAttestor", Egress)
    scope = rig()[0].hop_policy.scope
    hop = RegisteredSourceHopPolicy(scope=scope, resolver=CurrentGrant())
    fetcher = SafeFetcher(resolver=Resolver(), connector=Connector(), egress=Egress(),
                          hop_policy=hop, limits=FetchLimits(redirects=0))
    assert fetcher.live_ready

    class DuckPolicy:
        def allows(self, url, *, initial):
            return True

    fetcher.hop_policy = DuckPolicy()
    assert not fetcher.live_ready
    fetcher.hop_policy = hop
    fetcher.resolver = object()
    assert not fetcher.live_ready


def test_port_is_declared_and_missing_resolver_closes():
    assert RegisteredSourceGrantResolver.__name__ == "RegisteredSourceGrantResolver"
    scope = rig()[0].hop_policy.scope
    assert not RegisteredSourceHopPolicy(scope=scope).allows(URL, initial=True)
    assert not RegisteredSourceHopPolicy(scope=scope, resolver=CurrentGrant()).allows(
        URL, initial=False,
    )


@pytest.mark.asyncio
async def test_formal_eight_mib_full_body_and_lower_policy_denial():
    cap = 8 * 1024 * 1024
    payload = b"x" * cap
    fetcher, dns, connector, _, grant = rig(
        response(headers={"content-type": "text/html", "content-length": str(cap)}, body=payload),
        limits=FetchLimits(compressed_bytes=cap, expanded_bytes=cap, redirects=0),
    )
    scope = replace(fetcher.hop_policy.scope, max_bytes=cap)
    fetcher.hop_policy = replace(fetcher.hop_policy, scope=scope)
    grant.allowed = True
    grant.max_bytes = cap - 1
    with pytest.raises(SafeFetchDenied, match="PROBE_POLICY_DENIED"):
        await fetcher.fetch(URL)
    assert not dns.calls and not connector.calls
    grant.max_bytes = cap
    result = await fetcher.fetch(URL)
    assert result.compressed_bytes == result.expanded_bytes == cap
    assert result.body == payload

    # A lower caller cap denies on Content-Length before asking for the entity.
    fetcher, _, connector, _, grant = rig(
        response(headers={"content-type": "text/html", "content-length": str(cap + 1)}, body=b""),
        limits=FetchLimits(compressed_bytes=cap, expanded_bytes=cap, redirects=0),
    )
    fetcher.hop_policy = replace(fetcher.hop_policy,
                                 scope=replace(fetcher.hop_policy.scope, max_bytes=cap))
    grant.allowed = True
    grant.max_bytes = cap
    with pytest.raises(SafeFetchDenied, match="COMPRESSED_LIMIT"):
        await fetcher.fetch(URL)
    assert connector.closed == 1
    with pytest.raises(ValueError, match="INVALID_FETCH_LIMITS"):
        FetchLimits(compressed_bytes=cap + 1, expanded_bytes=cap)


@pytest.mark.asyncio
async def test_c_opt_in_full_gzip_is_complete_decoded_capture_with_independent_counts():
    cap = 8 * 1024 * 1024
    body = b"SQL SELECT WHERE schema\n" * 100_000
    wire = gzip.compress(body)
    headers = {"content-type": "text/html", "content-encoding": "gzip",
               "content-length": str(len(wire))}
    sent = {"accept": "text/html, text/plain, text/markdown", "accept-encoding": "gzip"}
    fetcher, _, connector, _, grant = rig(
        response(headers=headers, body=wire, sent_headers=sent),
        limits=FetchLimits(compressed_bytes=cap, expanded_bytes=cap, redirects=0),
        request_gzip=True,
    )
    fetcher.hop_policy = replace(fetcher.hop_policy,
                                 scope=replace(fetcher.hop_policy.scope, max_bytes=cap))
    grant.allowed = True
    grant.max_bytes = cap
    result = await fetcher.fetch(URL)
    assert connector.calls[0][3] == sent and connector.calls[0][4] == "GET"
    assert result.capture_kind == "full" and result.body == body
    assert result.sha256 == sha256(body).hexdigest()
    assert result.compressed_bytes == len(wire) and result.expanded_bytes == len(body)
    assert connector.closed == 1


@pytest.mark.asyncio
async def test_c_gzip_wire_and_expanded_caps_are_independent():
    body = b"x" * 2000
    wire = gzip.compress(body)
    sent = {"accept": "text/html, text/plain, text/markdown", "accept-encoding": "gzip"}
    headers = {"content-type": "text/html", "content-encoding": "gzip",
               "content-length": str(len(wire))}
    fetcher, _, connector, _, grant = rig(
        response(headers=headers, body=wire, sent_headers=sent),
        limits=FetchLimits(compressed_bytes=len(wire) - 1, expanded_bytes=3000, redirects=0),
        request_gzip=True,
    )
    grant.allowed = True
    with pytest.raises(SafeFetchDenied, match="COMPRESSED_LIMIT"):
        await fetcher.fetch(URL)
    assert connector.closed == 1

    fetcher, _, connector, _, grant = rig(
        response(headers=headers, body=wire, sent_headers=sent),
        limits=FetchLimits(compressed_bytes=len(wire), expanded_bytes=1000, redirects=0),
        request_gzip=True,
    )
    grant.allowed = True
    with pytest.raises(SafeFetchDenied, match="EXPANDED_LIMIT"):
        await fetcher.fetch(URL)
    assert connector.closed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("wire", [gzip.compress(b"complete")[:-2],
                                   gzip.compress(b"complete") * 2])
async def test_c_gzip_truncation_or_second_member_never_returns_partial_full(wire):
    sent = {"accept": "text/html, text/plain, text/markdown", "accept-encoding": "gzip"}
    fetcher, _, connector, _, grant = rig(
        response(headers={"content-type": "text/html", "content-encoding": "gzip",
                          "content-length": str(len(wire))}, body=wire, sent_headers=sent),
        request_gzip=True,
    )
    grant.allowed = True
    with pytest.raises(SafeFetchDenied, match="BODY_DENIED"):
        await fetcher.fetch(URL)
    assert connector.closed == 1


@pytest.mark.asyncio
async def test_c_gzip_opt_in_still_denies_head_prefix_and_redirect_before_body():
    sent = {"accept": "text/html, text/plain, text/markdown", "accept-encoding": "gzip"}
    fetcher, dns, connector, _, grant = rig(
        response(status=302, headers={"location": "/next"}, sent_headers=sent),
        request_gzip=True,
    )
    grant.allowed = True
    for kind, prefix in (("none", 0), ("prefix", 5)):
        with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
            await fetcher.fetch(URL, capture_kind=kind, prefix_bytes=prefix)
    assert not dns.calls and not connector.calls
    with pytest.raises(SafeFetchDenied, match="REDIRECT_DENIED"):
        await fetcher.fetch(URL)
    assert len(dns.calls) == len(connector.calls) == connector.closed == 1


@pytest.mark.asyncio
async def test_wider_formal_limits_do_not_expand_b_fetch():
    from tests.grounding.test_rag_b_safe_fetch import Connector, Egress, Resolver

    fetcher = SafeFetcher(
        resolver=Resolver(), connector=Connector(response()), egress=Egress(),
        limits=FetchLimits(compressed_bytes=8 * 1024 * 1024,
                           expanded_bytes=8 * 1024 * 1024),
        offline_protocol_test=True,
    )
    with pytest.raises(SafeFetchDenied, match="CAPTURE_SCOPE_INVALID"):
        await fetcher.fetch(URL)
    assert not fetcher.resolver.calls and not fetcher.connector.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [True, False, 0, -1, 301, float("nan"), float("inf"), "300"])
async def test_extended_deadline_invalid_values_deny_before_io(override):
    fetcher, dns, connector, _, grant = rig(request_gzip=True)
    grant.allowed = True
    fetcher.registered_full_deadline_seconds = override
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    assert not dns.calls and not connector.calls and not grant.calls


@pytest.mark.asyncio
async def test_extended_deadline_requires_exact_full_gzip_zero_redirect_c_scope():
    fetcher, dns, connector, _, grant = rig(request_gzip=True)
    fetcher.registered_full_deadline_seconds = 300
    grant.allowed = True
    for kind, prefix in (("none", 0), ("prefix", 5)):
        with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
            await fetcher.fetch(URL, capture_kind=kind, prefix_bytes=prefix)
    fetcher.request_gzip = False
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    fetcher.request_gzip = True
    fetcher.limits = FetchLimits(redirects=1)
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    fetcher.limits = FetchLimits(redirects=0)
    fetcher.hop_policy = None
    with pytest.raises(SafeFetchDenied, match="REGISTERED_SCOPE_DENIED"):
        await fetcher.fetch(URL)
    assert not dns.calls and not connector.calls and not grant.calls
    assert FetchLimits().deadline_seconds == 10
    assert FetchLimits(deadline_seconds=30).deadline_seconds == 30
    with pytest.raises(ValueError, match="INVALID_FETCH_LIMITS"):
        FetchLimits(deadline_seconds=30.001)


@pytest.mark.asyncio
async def test_extended_c_deadline_is_shared_by_outer_wait_connector_and_body(monkeypatch):
    from app.services.grounding.autonomous import safe_fetch

    async def slow_body():
        await asyncio.sleep(.03)  # exceeds the base limit, not the explicit C limit
        yield b"whole"

    sent = {"accept": "text/html, text/plain, text/markdown", "accept-encoding": "gzip"}
    fetcher, _, connector, _, grant = rig(
        response(sent_headers=sent, body=b"unused"), request_gzip=True,
        limits=FetchLimits(redirects=0, deadline_seconds=.01),
    )
    connector.responses[0] = replace(connector.responses[0], body=slow_body())
    grant.allowed = True
    fetcher.registered_full_deadline_seconds = 300
    observed, progress = {}, []
    original_wait, original_open, original_read = asyncio.wait, connector.open, safe_fetch._read_body

    async def wait(tasks, *, timeout, return_when):
        observed["outer"] = timeout
        return await original_wait(tasks, timeout=timeout, return_when=return_when)

    async def open_response(**kwargs):
        observed["connector"] = kwargs["deadline"]
        return await original_open(**kwargs)

    async def read_body(response, **kwargs):
        observed["body"] = kwargs["deadline"]
        return await original_read(response, **kwargs)

    monkeypatch.setattr(asyncio, "wait", wait)
    monkeypatch.setattr(connector, "open", open_response)
    monkeypatch.setattr(safe_fetch, "_read_body", read_body)
    fetcher.on_progress = lambda *args: progress.append(args)
    started = time.monotonic()
    result = await fetcher.fetch(URL)
    assert result.body == b"whole" and result.capture_kind == "full"
    assert observed["outer"] == 300
    assert observed["body"] == observed["connector"]
    assert started + 299 < observed["body"] <= time.monotonic() + 300
    assert [item[0] for item in progress] == ["dns", "signature", "tls"]


@pytest.mark.asyncio
async def test_extended_c_outer_wall_still_cancels_pending_dns():
    fetcher, dns, connector, _, grant = rig(request_gzip=True)
    grant.allowed = True
    fetcher.registered_full_deadline_seconds = .02
    progress = []
    fetcher.on_progress = lambda *args: progress.append(args)

    async def stalled(_host):
        await asyncio.Event().wait()

    dns.resolve = stalled
    started = time.monotonic()
    with pytest.raises(SafeFetchDenied, match="DEADLINE_EXCEEDED"):
        await fetcher.fetch(URL)
    assert time.monotonic() - started < 1
    assert progress == [("dns", 0, None, "unknown")]
    assert not connector.calls
