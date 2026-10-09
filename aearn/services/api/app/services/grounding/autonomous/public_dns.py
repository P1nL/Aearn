"""Bounded resolver for B2's pinned HTTPS transport.

DNS results are untrusted until SafeFetcher rejects non-global addresses; the
connector must dial the selected literal address, never resolve again.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket

from .safe_fetch import SafeFetchDenied, _public_ip


class PublicDnsResolver:
    def __init__(self, *, operator_allowed_ips: tuple[str, ...] | None = None) -> None:
        if operator_allowed_ips is not None:
            if (type(operator_allowed_ips) is not tuple or not 1 <= len(operator_allowed_ips) <= 16
                    or any(type(ip) is not str for ip in operator_allowed_ips)
                    or len(set(operator_allowed_ips)) != len(operator_allowed_ips)):
                raise SafeFetchDenied("DNS_DENIED")
            try:
                if any(str(ipaddress.IPv4Address(ip)) != ip or _public_ip(ip) != ip for ip in operator_allowed_ips):
                    raise SafeFetchDenied("DNS_DENIED")
            except (ValueError, TypeError) as exc:
                raise SafeFetchDenied("DNS_DENIED") from exc
        self._operator_allowed_ips = operator_allowed_ips

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
            # Validate the entire A/AAAA answer set before selecting any pin.
            public = tuple(_public_ip(address) for address in addresses)
            if self._operator_allowed_ips is None:
                return public
            selected = tuple(ip for ip in self._operator_allowed_ips if ip in public)
            if not selected:
                raise SafeFetchDenied("ADDRESS_DENIED")
            return selected
        except SafeFetchDenied:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise SafeFetchDenied("DNS_DENIED") from exc
