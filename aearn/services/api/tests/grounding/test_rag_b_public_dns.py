import asyncio
import socket

import pytest

from app.services.grounding.autonomous.public_dns import PublicDnsResolver
from app.services.grounding.autonomous.safe_fetch import SafeFetchDenied


@pytest.mark.asyncio
async def test_bounded_public_dns_resolves_without_a_second_connection(monkeypatch):
    seen = []

    async def lookup(self, host, port, *, family, type, proto):
        seen.append((host, port, family, type, proto))
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    assert await PublicDnsResolver().resolve("docs.python.org") == ("8.8.8.8",)
    assert seen == [("docs.python.org", 443, socket.AF_UNSPEC, socket.SOCK_STREAM, socket.IPPROTO_TCP)]


@pytest.mark.asyncio
async def test_mixed_private_dns_fails_closed(monkeypatch):
    async def lookup(self, host, port, *, family, type, proto):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
                (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    with pytest.raises(SafeFetchDenied, match="DNS_DENIED|ADDRESS_DENIED"):
        await PublicDnsResolver().resolve("docs.python.org")
