"""Untrusted B2 fetch provenance preparation; never source admission."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from .candidate_parser import CandidateFragment, parse_candidate_document
from .candidate_repository import _public_url
from .contracts import SourceCandidate, revalidate
from .safe_fetch import FetchResult


@dataclass(frozen=True)
class Attribution:
    """Unverified page claims, not verified license or independent corroboration."""

    license_id: str | None = None
    author_name: str | None = None
    claimed_origin_url: str | None = None


@dataclass(frozen=True)
class PreparedCapture:
    final_url: str
    request_chain: tuple[str, ...]
    chain_sha256: str
    media_type: str
    fetched_sha256: str  # capture_kind scopes this: HEAD=empty, prefix=range, full=document
    capture_kind: Literal["none", "prefix", "full"]
    captured_body: bytes | None
    prefix_sha256: str | None
    full_sha256: str | None
    fragments: tuple[CandidateFragment, ...]
    license_id: str | None
    author_name: str | None
    origin_sha256: str | None
    evidence_level: str = "offline_protocol_only"
    live_receipt: object | None = field(default=None, repr=False, compare=False)


def prepare_capture(candidate: SourceCandidate, fetched: FetchResult, *,
                    capture_kind: Literal["none", "prefix", "full"], prefix_bytes: int = 0,
                    attribution: Attribution | None = None) -> PreparedCapture:
    """Verify local bytes and chain without upgrading offline transport evidence."""
    valid = revalidate(candidate, SourceCandidate)
    if (type(fetched) is not FetchResult or fetched.evidence_level not in
            ("offline_protocol_only", "live_egress_attested")
            or (fetched.evidence_level == "offline_protocol_only" and fetched.live_receipt is not None)
            or (fetched.evidence_level == "live_egress_attested" and fetched.live_receipt is None)):
        raise ValueError("FETCH_EVIDENCE_UNVERIFIED")
    if (fetched.capture_kind != capture_kind
            or type(fetched.body) is not bytes or len(fetched.body) > 1_000_000
            or (capture_kind == "none" and (fetched.body or fetched.range_end is not None))
            or (capture_kind == "prefix" and (
                not fetched.body or fetched.range_end != prefix_bytes - 1
                or len(fetched.body) != prefix_bytes
            ))
            or (capture_kind == "full" and (not fetched.body or fetched.range_end is not None))):
        raise ValueError("FETCH_BODY_INVALID")
    if (hashlib.sha256(fetched.body).hexdigest() != fetched.sha256
            or fetched.expanded_bytes != len(fetched.body)
            or fetched.compressed_bytes < 0):
        raise ValueError("FETCH_HASH_MISMATCH")
    if (not isinstance(fetched.hops, tuple) or not 1 <= len(fetched.hops) <= 6
            or fetched.hops[0] != valid.url or fetched.hops[-1] != fetched.final_url
            or len(set(fetched.hops)) != len(fetched.hops)):
        raise ValueError("FETCH_CHAIN_INVALID")
    try:
        chain = tuple(_public_url(url) for url in fetched.hops)
        if chain != fetched.hops:
            raise ValueError("FETCH_CHAIN_INVALID")
    except ValueError:
        raise ValueError("FETCH_CHAIN_INVALID") from None
    # Search labels are leads, not content authority. A landing URL may yield a
    # parsed document only from the bounded fetch bytes below; the original B1
    # discovery candidate stays landing (one candidate per job/URL).
    if (valid.kind == "repo_page" and capture_kind != "none"
            or valid.kind == "landing" and capture_kind == "prefix"):
        raise ValueError("CAPTURE_SCOPE_INVALID")
    if valid.kind == "repo_file":
        assert valid.repo_commit is not None and valid.repo_path is not None
        path = urlsplit(fetched.final_url).path
        if valid.repo_commit not in path.split("/") or not path.endswith("/" + valid.repo_path):
            raise ValueError("REPO_REVISION_UNVERIFIED")
    if fetched.content_type not in {"text/html", "text/plain", "text/markdown"}:
        raise ValueError("FETCH_TYPE_INVALID")
    if capture_kind == "none":
        if prefix_bytes != 0:
            raise ValueError("CAPTURE_SCOPE_INVALID")
        body = None
    elif capture_kind == "prefix":
        if type(prefix_bytes) is not int or not 0 < prefix_bytes == len(fetched.body):
            raise ValueError("CAPTURE_SCOPE_INVALID")
        body = fetched.body
    elif capture_kind == "full":
        if prefix_bytes != 0:
            raise ValueError("CAPTURE_SCOPE_INVALID")
        body = fetched.body
    else:
        raise ValueError("CAPTURE_SCOPE_INVALID")
    parts: tuple[CandidateFragment, ...] = ()
    if capture_kind == "full":
        assert body is not None
        parts = parse_candidate_document(body, content_type=fetched.content_type,
                                         capture_kind="full", complete=True).fragments
    info = attribution or Attribution()
    if (type(info) is not Attribution or
            info.license_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,79}", info.license_id) or
            info.author_name is not None and (not 1 <= len(info.author_name) <= 160
                                              or any(ord(ch) < 32 for ch in info.author_name))):
        raise ValueError("ATTRIBUTION_INVALID")
    origin_hash = None
    if info.claimed_origin_url is not None:
        origin = _public_url(info.claimed_origin_url)
        if origin != info.claimed_origin_url:
            raise ValueError("ATTRIBUTION_INVALID")
        # A mirror claim is lineage only; it must never count as corroboration.
        origin_hash = hashlib.sha256(origin.encode()).hexdigest()
    chain_hash = hashlib.sha256(json.dumps(chain, separators=(",", ":")).encode()).hexdigest()
    digest = hashlib.sha256(body).hexdigest() if body is not None else None
    return PreparedCapture(fetched.final_url, chain, chain_hash, fetched.content_type,
                           fetched.sha256, capture_kind, body,
                           digest if capture_kind == "prefix" else None,
                           digest if capture_kind == "full" else None, parts,
                           info.license_id, info.author_name, origin_hash, fetched.evidence_level,
                           fetched.live_receipt)


def validate_prepared_capture(prepared: PreparedCapture, *, candidate: SourceCandidate | None = None) -> None:
    """Detect forged hashes/fragments before any durable content write."""
    if (type(prepared) is not PreparedCapture or prepared.evidence_level not in
            ("offline_protocol_only", "live_egress_attested")
            or (prepared.evidence_level == "offline_protocol_only" and prepared.live_receipt is not None)
            or (prepared.evidence_level == "live_egress_attested" and prepared.live_receipt is None)
            or not 1 <= len(prepared.request_chain) <= 6
            or prepared.request_chain[-1] != prepared.final_url
            or prepared.chain_sha256 != hashlib.sha256(
                json.dumps(prepared.request_chain, separators=(",", ":")).encode()
            ).hexdigest()):
        raise ValueError("CAPTURE_INVALID")
    try:
        if any(_public_url(url) != url for url in prepared.request_chain):
            raise ValueError("CAPTURE_INVALID")
    except ValueError:
        raise ValueError("CAPTURE_INVALID") from None
    if (prepared.media_type not in {"text/html", "text/plain", "text/markdown"}
            or not re.fullmatch(r"[0-9a-f]{64}", prepared.fetched_sha256)
            or prepared.license_id is not None and not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9.-]{0,79}", prepared.license_id
            ) or prepared.author_name is not None and (
                not 1 <= len(prepared.author_name) <= 160
                or any(ord(ch) < 32 for ch in prepared.author_name)
            ) or prepared.origin_sha256 is not None and not re.fullmatch(
                r"[0-9a-f]{64}", prepared.origin_sha256
            )):
        raise ValueError("CAPTURE_INVALID")
    if candidate is not None:
        item = revalidate(candidate, SourceCandidate)
        if (prepared.request_chain[0] != item.url
                or item.kind == "repo_page" and prepared.capture_kind != "none"
                or item.kind == "landing" and prepared.capture_kind == "prefix"):
            raise ValueError("CAPTURE_SCOPE_INVALID")
        if item.kind == "repo_file":
            assert item.repo_commit is not None and item.repo_path is not None
            path = urlsplit(prepared.final_url).path
            if item.repo_commit not in path.split("/") or not path.endswith("/" + item.repo_path):
                raise ValueError("REPO_REVISION_UNVERIFIED")
    body = prepared.captured_body
    if prepared.capture_kind == "none":
        if (body is not None or prepared.prefix_sha256 is not None or prepared.full_sha256 is not None
                or prepared.fragments or prepared.fetched_sha256 != hashlib.sha256(b"").hexdigest()):
            raise ValueError("CAPTURE_INVALID")
    elif prepared.capture_kind == "prefix":
        if (not body or len(body) > 1_000_000 or prepared.prefix_sha256 != hashlib.sha256(body).hexdigest()
                or prepared.full_sha256 is not None or prepared.fragments
                or prepared.fetched_sha256 != prepared.prefix_sha256):
            raise ValueError("CAPTURE_INVALID")
    elif prepared.capture_kind == "full":
        if (not body or len(body) > 1_000_000 or prepared.full_sha256 != hashlib.sha256(body).hexdigest()
                or prepared.full_sha256 != prepared.fetched_sha256 or prepared.prefix_sha256 is not None
                or prepared.fragments != parse_candidate_document(
                    body, content_type=prepared.media_type, capture_kind="full", complete=True,
                ).fragments):
            raise ValueError("CAPTURE_INVALID")
    else:
        raise ValueError("CAPTURE_INVALID")
