"""Independent exact-excerpt review of Tavily Markdown, never origin HTML proof."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal, Protocol, cast
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, model_validator

from .contracts import FrozenContract, HANDLE, HASH, SubjectScope, revalidate
from .source_review_repository import CompleteCapture, QualityFinding
from .sqlite_select_automated_review import (
    ApprovedSpan, AutomatedReviewDenied, AutomatedReviewEvaluation, SENTENCES, USAGES,
    _capture_ok, _oracle,
)
from .sqlite_select_quality import MAX_BODY_BYTES, SQLITE_SELECT_URL

DOMAIN = b"AEARN-SQLITE-SELECT-TAVILY-REVIEW-V1\n"
PROFILE = "sqlite-select-tavily-markdown-excerpts-v1"
_LINK = re.compile(r"\[([^\]\n]+)\]\(([^\s)]+)\)")


class ProviderProvenance(Protocol):
    def provenance_digest(self, capture: CompleteCapture, *, expected_format: str | None = None) -> str | None: ...


class TavilySQLiteReviewPayload(FrozenContract):
    format: Literal["aearn.sqlite-select.tavily-service.v1"]
    reviewer_kind: Literal["automated_service"]
    quality_scope: Literal["approved_excerpts_only"]
    profile: Literal["sqlite-select-tavily-markdown-excerpts-v1"]
    representation: Literal["provider_extracted_markdown"]
    capture_id: UUID
    lane: Literal["registered"]
    source_handle: str = Field(pattern=HANDLE)
    scope: SubjectScope
    revision: str = Field(min_length=1, max_length=160)
    body_sha256: str = Field(pattern=HASH)
    body_bytes: int = Field(gt=0, le=MAX_BODY_BYTES)
    final_url: Literal["https://www.sqlite.org/lang_select.html"]
    request_chain: tuple[Literal["https://www.sqlite.org/lang_select.html"], ...]
    origin: str = Field(pattern=HANDLE)
    reading_level: str = Field(pattern=HANDLE)
    license_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$")
    provenance_digest: str = Field(pattern=HASH)
    excerpts: tuple[ApprovedSpan, ...] = Field(min_length=2, max_length=2)
    oracle_digest: str = Field(pattern=HASH)
    usages: tuple[Literal["supplementary_explanation"], ...]
    reviewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> TavilySQLiteReviewPayload:
        if (self.scope.subject_id != "route.sql" or self.scope.facets != ("queries",)
                or self.request_chain != (SQLITE_SELECT_URL,) or self.usages != USAGES
                or self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != timedelta(0)
                or self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(0)
                or not timedelta(0) < self.expires_at-self.reviewed_at <= timedelta(hours=24)):
            raise ValueError("invalid provider review scope")
        return self


class SignedTavilySQLiteReview(FrozenContract):
    service_key_id: str = Field(pattern=HANDLE)
    payload: TavilySQLiteReviewPayload
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def _canonical_payload(payload: TavilySQLiteReviewPayload) -> bytes:
    p = revalidate(payload, TavilySQLiteReviewPayload)
    return DOMAIN + json.dumps(p.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False).encode()


def canonical_tavily_sqlite_review(review: SignedTavilySQLiteReview) -> bytes:
    checked = revalidate(review, SignedTavilySQLiteReview)
    return json.dumps(checked.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()


def _visible_link(match: re.Match[str]) -> str:
    target = urlsplit(urljoin(SQLITE_SELECT_URL, match.group(2)))
    if (target.scheme != "https" or target.hostname not in {"www.sqlite.org", "sqlite.org"}
            or target.username or target.password or target.port):
        raise AutomatedReviewDenied("MARKDOWN_LINK_DENIED")
    return match.group(1)


def _analyze_markdown(capture: CompleteCapture) -> tuple[tuple[ApprovedSpan, ...], str]:
    if not _capture_ok(capture):
        raise AutomatedReviewDenied("CAPTURE_INVALID")
    try:
        text = capture.body.decode("utf-8", errors="strict")
        spans: list[ApprovedSpan] = []
        start: int | None = None
        parts: list[str] = []
        position = 0
        fenced = False

        def finish() -> None:
            nonlocal start
            if start is not None and parts:
                raw = "".join(parts).rstrip()
                normalized = " ".join(_LINK.sub(lambda match: match.group(1), raw).split())
                if normalized in SENTENCES:
                    _LINK.sub(_visible_link, raw)  # Validate links only in a selected complete assertion.
                    first = len(text[:start].encode())
                    payload = raw.encode()
                    spans.append(ApprovedSpan(
                        claim_id=cast(Literal["where_true", "limit"], SENTENCES[normalized]),
                        start_byte=first, end_byte=first+len(payload),
                        sha256=hashlib.sha256(payload).hexdigest(),
                    ))
                elif normalized.startswith(("This is false:", "Warning: this is false:", "Incorrect:")):
                    if any(value in normalized for value in SENTENCES):
                        raise AutomatedReviewDenied("CONFLICTING_ASSERTION")
            parts.clear()
            start = None

        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                finish()
                fenced = not fenced
            elif not stripped:
                finish()
            elif fenced or line.startswith(("    ", "\t")) or stripped.startswith((">", "#", "- ", "* ", "<")):
                finish()
            else:
                if start is None:
                    start = position
                parts.append(line)
            position += len(line)
        finish()
        if fenced or len(spans) != 2 or {s.claim_id for s in spans} != {"where_true", "limit"}:
            raise AutomatedReviewDenied("PROFILE_UNSUPPORTED")
        spans.sort(key=lambda span: span.start_byte)
        return tuple(spans), _oracle(("limit", "where_true"))
    except AutomatedReviewDenied:
        raise
    except (UnicodeError, ValueError, TypeError):
        raise AutomatedReviewDenied("PROFILE_UNSUPPORTED") from None


def evaluate_tavily_sqlite(capture: CompleteCapture) -> AutomatedReviewEvaluation:
    """An offline supported result is not a source-use grant or signed review."""
    try:
        spans, oracle = _analyze_markdown(capture)
        return AutomatedReviewEvaluation("SUPPORTED", ("limit", "where_true"), len(spans), oracle)
    except AutomatedReviewDenied as exc:
        return AutomatedReviewEvaluation("QUARANTINED", (), 0, "0"*64, str(exc))


def sign_tavily_sqlite_review(
    capture: CompleteCapture, *, provenance: ProviderProvenance,
    private_key: Ed25519PrivateKey, service_key_id: str, now: datetime,
    expires_at: datetime, enabled: bool = False,
) -> SignedTavilySQLiteReview:
    if not enabled or not isinstance(private_key, Ed25519PrivateKey):
        raise AutomatedReviewDenied("SIGNER_DISABLED")
    spans, oracle = _analyze_markdown(capture)
    proof = provenance.provenance_digest(capture, expected_format="markdown")
    if type(proof) is not str or re.fullmatch(HASH, proof) is None:
        raise AutomatedReviewDenied("PROVIDER_PROVENANCE_UNVERIFIED")
    payload = TavilySQLiteReviewPayload(
        format="aearn.sqlite-select.tavily-service.v1", reviewer_kind="automated_service",
        quality_scope="approved_excerpts_only", profile="sqlite-select-tavily-markdown-excerpts-v1",
        representation="provider_extracted_markdown", capture_id=capture.capture_id,
        lane="registered", source_handle=capture.source_handle, scope=capture.scope,
        revision=capture.revision, body_sha256=capture.digest, body_bytes=len(capture.body),
        final_url=SQLITE_SELECT_URL, request_chain=(SQLITE_SELECT_URL,), origin=capture.origin,
        reading_level=capture.reading_level, license_id=capture.license_id,
        provenance_digest=proof, excerpts=spans, oracle_digest=oracle, usages=USAGES,
        reviewed_at=now, expires_at=expires_at,
    )
    return SignedTavilySQLiteReview(service_key_id=service_key_id, payload=payload,
                                   signature_hex=private_key.sign(_canonical_payload(payload)).hex())


class TavilySQLiteReviewVerifier:
    def __init__(self, *, review: SignedTavilySQLiteReview, service_key_id: str,
                 service_public_key: bytes, provenance: ProviderProvenance,
                 enabled: bool = False, clock: Callable[[], datetime] | None = None) -> None:
        self.review, self.key_id, self.provenance = review, service_key_id, provenance
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(UTC))
        self.key = Ed25519PublicKey.from_public_bytes(service_public_key)

    def _reviewed(self, capture: CompleteCapture) -> tuple[tuple[str, ...], str] | None:
        if not self.enabled:
            return None
        try:
            review = revalidate(self.review, SignedTavilySQLiteReview)
            p = review.payload
            now = self.clock()
            self.key.verify(bytes.fromhex(review.signature_hex), _canonical_payload(p))
            if (review.service_key_id != self.key_id or not _capture_ok(capture)
                    or p.reviewed_at > now or p.expires_at <= now
                    or p.capture_id != capture.capture_id or p.source_handle != capture.source_handle
                    or p.scope != capture.scope or p.revision != capture.revision
                    or p.body_sha256 != capture.digest or p.body_bytes != len(capture.body)
                    or p.final_url != capture.final_url or p.request_chain != capture.request_chain
                    or p.origin != capture.origin or p.reading_level != capture.reading_level
                    or p.license_id != capture.license_id
                    or self.provenance.provenance_digest(capture, expected_format="markdown") != p.provenance_digest):
                return None
            spans, oracle = _analyze_markdown(capture)
            if p.excerpts != spans or p.oracle_digest != oracle:
                return None
            excerpts = tuple(capture.body[s.start_byte:s.end_byte].decode() for s in spans)
            return excerpts, hashlib.sha256(canonical_tavily_sqlite_review(review)).hexdigest()
        except Exception:
            return None

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        checked = self._reviewed(capture)
        if checked is None:
            return QualityFinding("offline_protocol_only", "unknown", "unknown", "unknown", "unknown",
                                  "unknown", (), "unverified.sqlite-select.tavily", "0"*64)
        return QualityFinding("production", "current", "suitable", "correct", "resolved",
                              "absent", ("queries",), "family.sqlite", checked[1])

    def reviewed_usages(self, capture: CompleteCapture) -> tuple[str, ...]:
        return USAGES if self._reviewed(capture) is not None else ()

    def approved_excerpts(self, capture: CompleteCapture) -> tuple[str, ...]:
        result = self._reviewed(capture)
        return result[0] if result else ()
