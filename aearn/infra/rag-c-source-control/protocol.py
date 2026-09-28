"""Bounded, exact registered-source grant wire format; never a transport proxy."""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

MAX_FRAME = 4096
MAX_BYTES = 8 * 1024 * 1024
TTL_SECONDS = 4
_NONCE = re.compile(r"[0-9a-f]{48}\Z")
_HANDLE = re.compile(r"[a-z][a-z0-9._:-]{2,159}\Z")
_SUBJECT = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}\Z")
_FACET = re.compile(r"[a-z][a-z0-9._-]{0,79}\Z")
_HOST = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*\Z")
_FIELDS = frozenset(
    {
        "policy_id",
        "generation",
        "source_handle",
        "subject_id",
        "subject_version",
        "facets",
        "url",
        "host",
        "path",
        "root_id",
        "dispatch_id",
        "max_bytes",
    }
)


class BridgeDenied(ValueError):
    """Safe fixed error; no scope, URL or exception text is exposed."""


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BridgeDenied("INVALID_FRAME")
        result[key] = value
    return result


def decode(raw: bytes, *, max_bytes: int = MAX_FRAME) -> object:
    if len(raw) > max_bytes or not raw or b"\x00" in raw:
        raise BridgeDenied("INVALID_FRAME")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
        if canonical(value) != raw:
            raise BridgeDenied("INVALID_FRAME")
        return value
    except (ValueError, UnicodeDecodeError, TypeError, OverflowError) as exc:
        raise BridgeDenied("INVALID_FRAME") from exc


@dataclass(frozen=True)
class Scope:
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
    dispatch_id: str
    max_bytes: int

    @classmethod
    def from_wire(cls, value: object) -> Scope:
        try:
            if type(value) is not dict or value.keys() != _FIELDS:
                raise ValueError()
            for key in ("policy_id", "source_handle", "root_id"):
                if type(value[key]) is not str or not _HANDLE.fullmatch(value[key]):
                    raise ValueError()
            if (
                type(value["generation"]) is not int
                or value["generation"] < 1
                or type(value["max_bytes"]) is not int
                or not 0 < value["max_bytes"] <= MAX_BYTES
            ):
                raise ValueError()
            if (
                type(value["subject_id"]) is not str
                or not 3 <= len(value["subject_id"]) <= 100
                or not _SUBJECT.fullmatch(value["subject_id"])
                or type(value["subject_version"]) is not str
                or not _VERSION.fullmatch(value["subject_version"])
            ):
                raise ValueError()
            facets = value["facets"]
            if (
                type(facets) is not list
                or not 1 <= len(facets) <= 24
                or any(type(f) is not str or not _FACET.fullmatch(f) for f in facets)
                or len(facets) != len(set(facets))
            ):
                raise ValueError()
            dispatch = value["dispatch_id"]
            if type(dispatch) is not str or str(UUID(dispatch)) != dispatch:
                raise ValueError()
            url = value["url"]
            host = value["host"]
            path = value["path"]
            if (
                type(url) is not str
                or not 0 < len(url) <= 2048
                or type(host) is not str
                or not _HOST.fullmatch(host)
                or len(host) > 253
                or len(host.split(".")) < 2
                or any(
                    not part or part.startswith("-") or part.endswith("-")
                    for part in host.split(".")
                )
                or host.endswith((".local", ".internal", ".localhost"))
                or type(path) is not str
                or not path.startswith("/")
                or "//" in path
                or "%" in path
                or any(p in (".", "..") for p in path.split("/"))
            ):
                raise ValueError()
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.netloc != host
                or parsed.hostname != host
                or parsed.port not in (None, 443)
                or parsed.path != path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
                or url != f"https://{host}{path}"
            ):
                raise ValueError()
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError()
            return cls(**{**value, "facets": tuple(facets)})
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise BridgeDenied("INVALID_SCOPE") from exc

    def wire(self) -> dict[str, object]:
        return {**vars(self), "facets": list(self.facets)}


def request(scope: Scope, nonce: str, deployment_id: str) -> dict[str, object]:
    if (
        type(scope) is not Scope
        or type(nonce) is not str
        or not _NONCE.fullmatch(nonce)
        or type(deployment_id) is not str
        or not _HANDLE.fullmatch(deployment_id)
    ):
        raise BridgeDenied("INVALID_REQUEST")
    return {
        "v": 1,
        "deployment_id": deployment_id,
        "nonce": nonce,
        "scope": scope.wire(),
    }


def parse_request(value: object, deployment_id: str) -> tuple[Scope, str]:
    if (
        type(value) is not dict
        or set(value) != {"v", "deployment_id", "nonce", "scope"}
        or type(value["v"]) is not int
        or value["v"] != 1
        or value["deployment_id"] != deployment_id
    ):
        raise BridgeDenied("INVALID_REQUEST")
    scope = Scope.from_wire(value["scope"])
    request(scope, value["nonce"], deployment_id)
    return scope, value["nonce"]
