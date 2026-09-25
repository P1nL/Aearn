"""Bounded resolver for B2's pinned HTTPS transport.

DNS results are untrusted until SafeFetcher rejects non-global addresses; the
connector must dial the selected literal address, never resolve again.
"""
from __future__ import annotations

import asyncio
import socket

from .safe_fetch import SafeFetchDenied, _public_ip


class PublicDnsResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        if not isinstance(hostname, str) or not hostname or len(hostname) > 253:
            raise SafeFetchDenied("DNS_DENIED")
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(
                hostname, 443, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
            addresses = tuple(dict.fromkeys(str(row[4][0]) for row in answers))
            if not 0 < len(addresses) <= 8:
                raise SafeFetchDenied("DNS_DENIED")
            return tuple(_public_ip(address) for address in addresses)
        except SafeFetchDenied:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise SafeFetchDenied("DNS_DENIED") from exc
