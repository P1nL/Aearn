"""Conservative prompt hygiene. This module never fetches or resolves URLs."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import unquote, urlsplit


class PrivacyDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("privacy_denied")


_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|"
    r"\b(?:sk-[a-zA-Z0-9_-]{16,}|gh[pousr]_[a-zA-Z0-9]{20,})\b|"
    r"\b(?:api[_-]?key|access[_-]?token|authorization|password|secret)\s*[:=]\s*\S+)",
    re.IGNORECASE,
)


def safe_public_url(value: str) -> str:
    """Reject credential carriers outright rather than persist a redacted raw URL."""
    try:
        decoded = unquote(value)
        parts = urlsplit(value)
        host = parts.hostname
        if (parts.scheme != "https" or not host or parts.username is not None
                or parts.password is not None or parts.query or parts.fragment
                or any(ord(c) < 33 for c in decoded) or "\\" in decoded
                or any(c in unquote(parts.path) for c in ("?", "#", "@"))
                or parts.port not in (None, 443)):
            raise PrivacyDenied()
        if (host == "localhost" or "." not in host or host.endswith(
                (".localhost", ".local", ".internal", ".test", ".invalid"))):
            raise PrivacyDenied()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise PrivacyDenied()
        return value
    except (ValueError, TypeError):
        raise PrivacyDenied() from None


def require_public_text(text: str) -> None:
    if _SECRET.search(text):
        raise PrivacyDenied()
    for match in _URL.finditer(text):
        safe_public_url(match.group())
