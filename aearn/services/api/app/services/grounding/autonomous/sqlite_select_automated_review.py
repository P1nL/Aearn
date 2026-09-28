"""Opt-in signed service review of finite SQLite SELECT source excerpts.

The full capture is identity, not a document-wide quality endorsement. No network,
provider or real database is used. Current provenance and storage grants are external.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Callable, Literal, cast
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, model_validator

from .contracts import FrozenContract, HANDLE, HASH, SubjectScope, revalidate
from .source_review_repository import CompleteCapture, QualityFinding
from .sqlite_select_quality import MAX_BODY_BYTES, SQLITE_SELECT_URL, CurrentCaptureProvenanceResolver

DOMAIN = b"AEARN-SQLITE-SELECT-AUTOMATED-REVIEW-V1\n"
PROFILE: Literal["sqlite-select-exact-excerpts-v1"] = "sqlite-select-exact-excerpts-v1"
USAGES: tuple[Literal["supplementary_explanation"], ...] = ("supplementary_explanation",)
# Exact normalized sentences, not keyword patterns. Only these assertions have oracles.
WHERE_TRUE_SENTENCE = "Only rows for which the WHERE clause expression evaluates to true are included from the dataset before continuing."
WHERE_PARAGRAPH = (
    "If a WHERE clause is specified, the WHERE expression is evaluated for each row in the input data as a boolean expression. "
    + WHERE_TRUE_SENTENCE
    + " Rows are excluded from the result if the WHERE clause evaluates to either false or NULL."
)
CLAIMS = {
    "where_true": WHERE_PARAGRAPH,
    "limit": "The LIMIT clause is used to place an upper bound on the number of rows returned by the entire SELECT statement.",
}
SENTENCES = {v: k for k, v in CLAIMS.items()}

VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())
SKIP = frozenset(("script", "style", "svg", "template"))
UNSAFE_CONTEXT = frozenset(("blockquote", "q", "del", "s", "strike", "aside", "nav", "footer"))
BLOCK_START = frozenset("div h1 h2 h3 h4 h5 h6 hr ol ul pre table section article header form".split()) | UNSAFE_CONTEXT


class AutomatedReviewDenied(ValueError):
    """Bounded code only; never include capture body or exception detail."""


@dataclass(frozen=True)
class AutomatedReviewEvaluation:
    code: Literal["SUPPORTED", "QUARANTINED"]
    claim_ids: tuple[str, ...]
    excerpt_count: int
    oracle_digest: str
    reason: str = "SUPPORTED"


class ApprovedSpan(FrozenContract):
    claim_id: Literal["where_true", "limit"]
    start_byte: int = Field(ge=0, le=MAX_BODY_BYTES)
    end_byte: int = Field(gt=0, le=MAX_BODY_BYTES)
    sha256: str = Field(pattern=HASH)

    @model_validator(mode="after")
    def bounded(self) -> ApprovedSpan:
        if not 0 < self.end_byte - self.start_byte <= 512:
            raise ValueError("invalid span")
        return self


class AutomatedReviewPayload(FrozenContract):
    format: Literal["aearn.sqlite-select.automated-service.v1"]
    reviewer_kind: Literal["automated_service"]
    quality_scope: Literal["approved_excerpts_only"]
    profile: Literal["sqlite-select-exact-excerpts-v1"]
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
    excerpts: tuple[ApprovedSpan, ...] = Field(min_length=1, max_length=12)
    oracle_digest: str = Field(pattern=HASH)
    usages: tuple[Literal["supplementary_explanation"], ...]
    reviewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded(self) -> AutomatedReviewPayload:
        if (self.scope.subject_id != "route.sql" or self.scope.facets != ("queries",)
            or self.request_chain != (SQLITE_SELECT_URL,) or self.usages != USAGES
            or self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() != timedelta(0)
            or self.expires_at.tzinfo is None or self.expires_at.utcoffset() != timedelta(0)
            or not timedelta(0) < self.expires_at - self.reviewed_at <= timedelta(hours=24)):
            raise ValueError("invalid review scope")
        return self


class SignedAutomatedReview(FrozenContract):
    service_key_id: str = Field(pattern=HANDLE)
    payload: AutomatedReviewPayload
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def canonical_automated_payload(payload: AutomatedReviewPayload) -> bytes:
    checked = revalidate(payload, AutomatedReviewPayload)
    return DOMAIN + json.dumps(checked.model_dump(mode="json"), sort_keys=True,
                               separators=(",", ":"), ensure_ascii=False).encode()


def canonical_signed_review(review: SignedAutomatedReview) -> bytes:
    checked = revalidate(review, SignedAutomatedReview)
    return json.dumps(checked.model_dump(mode="json"), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False).encode()


class _Parser(HTMLParser):
    """Only entire visible paragraph/list-item assertions qualify, never submatches."""
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0] + [m.end() for m in re.finditer("\n", source)]
        self.stack: list[str] = []
        self.unit: list[tuple[str, int, int]] | None = None
        self.spans: list[tuple[str, int, int]] = []
        self.invalid = False
        self.unit_unsafe = False
        self.html_count = 0
        self.body_count = 0
        self.closed_html = False

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _finish_unit(self) -> None:
        if not self.unit:
            self.unit = None
            self.unit_unsafe = False
            return
        whole = "".join(part[0] for part in self.unit)
        normalized = " ".join(html.unescape(whole).split())
        if normalized in SENTENCES:
            if self.unit_unsafe:
                self.invalid = True  # a selected assertion has broken local markup
            else:
                first, last = self.unit[0], self.unit[-1]
                self.spans.append((SENTENCES[normalized], first[1], last[2]))
        elif any(statement in normalized for statement in SENTENCES):
            # Never pull out a sub-sentence. An explicit assertion that the
            # approved statement is false conflicts with the whole profile.
            if normalized.startswith(("This is false:", "Warning: this is false:", "Incorrect:")):
                self.invalid = True
        # Other near-match units are unsupported, not a reason to bless/reject
        # the entire unrelated document. They never produce approved spans.
        self.unit = None
        self.unit_unsafe = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.closed_html:
            self.invalid = True
        if tag == "html":
            self.html_count += 1
        if tag == "body":
            self.body_count += 1
        if tag in ("p", "li"):
            if self.unit is not None:
                self._finish_unit()
                if tag in self.stack:
                    del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag):]
            self.unit = []
            self.unit_unsafe = any(t in self.stack for t in UNSAFE_CONTEXT)
        elif self.unit is not None and tag in BLOCK_START:
            # HTML permits omitted </p> before a block. The new block is not
            # part of that paragraph's assertion.
            self._finish_unit()
            if "p" in self.stack:
                del self.stack[len(self.stack) - 1 - self.stack[::-1].index("p"):]
        elif self.unit is not None and tag in UNSAFE_CONTEXT | SKIP:
            self.unit_unsafe = True
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP and self.unit is not None:
            self.unit_unsafe = True

    def handle_endtag(self, tag: str) -> None:
        if self.closed_html:
            self.invalid = True
        if tag == "html":
            self.closed_html = True
        if tag in VOID:
            return
        if tag not in self.stack:
            if self.unit is not None:
                self.unit_unsafe = True
            return
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        skipped = self.stack[index + 1:]
        if self.unit is not None and any(t not in ("p", "li") for t in skipped):
            self.unit_unsafe = True
        if self.unit is not None and (tag in ("p", "li") or any(t in ("p", "li") for t in skipped)):
            self._finish_unit()
        del self.stack[index:]

    def handle_data(self, data: str) -> None:
        if (not self.stack or self.closed_html) and data.strip():
            self.invalid = True
        if self.unit is None or "body" not in self.stack or any(t in self.stack for t in SKIP):
            return
        start = self._offset()
        if self.source[start:start + len(data)] != data:
            self.invalid = True
            return
        if data:
            self.unit.append((data, start, start + len(data)))

    def handle_entityref(self, name: str) -> None:
        if self.unit is not None:
            start = self._offset()
            token = "&" + name + ";"
            if self.source[start:start + len(token)] != token:
                self.invalid = True
            self.unit.append((html.unescape(token), start, start + len(token)))

    def handle_charref(self, name: str) -> None:
        self.handle_entityref("#" + name)

def _capture_ok(c: CompleteCapture) -> bool:
    return (type(c) is CompleteCapture and type(c.body) is bytes and 0 < len(c.body) <= MAX_BODY_BYTES
            and c.lane == "registered" and c.final_url == SQLITE_SELECT_URL
            and c.request_chain == (SQLITE_SELECT_URL,) and c.scope.subject_id == "route.sql"
            and c.scope.facets == ("queries",) and c.digest == hashlib.sha256(c.body).hexdigest()
            and c.revision == c.digest)


def _oracle(claims: tuple[str, ...]) -> str:
    """Hard-coded SQL only, across contrasting data/NULL/duplicate/bound cases."""
    observations: list[tuple[str, tuple[object, ...]]] = []
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE t(n INTEGER)")
        for values in ((1, 1, 2, None, None, 3), (0, -1, 0, 5, None, 5, 9),
                       (None, None), (4, 3, 2, 1, 0, -1, -2)):
            conn.execute("DELETE FROM t")
            conn.executemany("INSERT INTO t VALUES (?)", ((v,) for v in values))
            if "where_true" in claims:
                got = tuple(r[0] for r in conn.execute("SELECT n FROM t WHERE n > 1 ORDER BY rowid"))
                if (got != tuple(v for v in values if v is not None and v > 1)
                    or tuple(conn.execute("SELECT n FROM t WHERE 0"))
                    or tuple(conn.execute("SELECT n FROM t WHERE NULL"))
                    or tuple(r[0] for r in conn.execute("SELECT n FROM t WHERE 1 ORDER BY rowid")) != values):
                    raise AutomatedReviewDenied("ORACLE_FAILED")
                observations.append(("where_true", got))
            if "limit" in claims:
                for bound in (0, 1, 2, 5):
                    got = tuple(r[0] for r in conn.execute("SELECT n FROM t ORDER BY rowid LIMIT ?", (bound,)))
                    if got != values[:bound]:
                        raise AutomatedReviewDenied("ORACLE_FAILED")
                    observations.append((f"limit.{bound}", got))
            if "where_true" in claims and "limit" in claims:
                combined = tuple(r[0] for r in conn.execute(
                    "SELECT n FROM t WHERE n > 1 ORDER BY rowid LIMIT 2"))
                if combined != tuple(v for v in values if v is not None and v > 1)[:2]:
                    raise AutomatedReviewDenied("ORACLE_FAILED")
                observations.append(("where_limit", combined))
    return hashlib.sha256(json.dumps((PROFILE, sqlite3.sqlite_version, claims, observations),
                                   separators=(",", ":")).encode()).hexdigest()


def _analyze(c: CompleteCapture) -> tuple[tuple[ApprovedSpan, ...], str]:
    if not _capture_ok(c):
        raise AutomatedReviewDenied("CAPTURE_INVALID")
    try:
        source = c.body.decode("utf-8", errors="strict")
        parser = _Parser(source)
        parser.feed(source)
        parser.close()
        if parser.unit is not None:
            parser._finish_unit()  # optional paragraph end at EOF is valid HTML
        if parser.invalid or parser.rawdata or parser.html_count != 1 or parser.body_count != 1:
            raise AutomatedReviewDenied("HTML_INVALID")
        spans = []
        for claim, start, end in parser.spans:
            first, last = len(source[:start].encode()), len(source[:end].encode())
            raw = c.body[first:last]
            spans.append(ApprovedSpan(claim_id=cast(Literal["where_true", "limit"], claim), start_byte=first, end_byte=last,
                                      sha256=hashlib.sha256(raw).hexdigest()))
        spans.sort(key=lambda s: s.start_byte)
        if len(spans) != 2 or any(a.end_byte > b.start_byte for a, b in zip(spans, spans[1:])):
            raise AutomatedReviewDenied("PROFILE_UNSUPPORTED")
        claims = tuple(sorted({s.claim_id for s in spans}))
        if claims != ("limit", "where_true") or len({s.claim_id for s in spans}) != 2:
            raise AutomatedReviewDenied("PROFILE_UNSUPPORTED")
        return tuple(spans), _oracle(claims)
    except AutomatedReviewDenied:
        raise
    except (UnicodeError, ValueError, IndexError, sqlite3.Error):
        raise AutomatedReviewDenied("PROFILE_UNSUPPORTED") from None


def evaluate(capture: CompleteCapture) -> AutomatedReviewEvaluation:
    """Offline-only probe; SUPPORTED does not grant provenance or usage."""
    try:
        spans, digest = _analyze(capture)
        return AutomatedReviewEvaluation("SUPPORTED", tuple(sorted({s.claim_id for s in spans})), len(spans), digest)
    except AutomatedReviewDenied as exc:
        return AutomatedReviewEvaluation("QUARANTINED", (), 0, "0" * 64, str(exc))
    except (AttributeError, TypeError):
        return AutomatedReviewEvaluation("QUARANTINED", (), 0, "0" * 64, "CAPTURE_INVALID")


def sign_service_review(capture: CompleteCapture, *, provenance: CurrentCaptureProvenanceResolver,
                        private_key: Ed25519PrivateKey, service_key_id: str, now: datetime,
                        expires_at: datetime, enabled: bool = False) -> SignedAutomatedReview:
    """Root-isolated reviewer operation; key provisioning/persistence external."""
    if enabled is not True or not isinstance(private_key, Ed25519PrivateKey):
        raise AutomatedReviewDenied("SIGNER_DISABLED")
    try:
        spans, oracle_digest = _analyze(capture)
        digest = provenance.resolve(capture)
        if type(digest) is not str or re.fullmatch(HASH, digest) is None:
            raise AutomatedReviewDenied("PROVENANCE_UNVERIFIED")
        payload = AutomatedReviewPayload(
            format="aearn.sqlite-select.automated-service.v1", reviewer_kind="automated_service",
            quality_scope="approved_excerpts_only", profile=PROFILE,
            capture_id=capture.capture_id, lane="registered", source_handle=capture.source_handle,
            scope=capture.scope, revision=capture.revision, body_sha256=capture.digest,
            body_bytes=len(capture.body), final_url=SQLITE_SELECT_URL,
            request_chain=(SQLITE_SELECT_URL,), origin=capture.origin,
            reading_level=capture.reading_level, license_id=capture.license_id,
            provenance_digest=digest, excerpts=spans, oracle_digest=oracle_digest,
            usages=USAGES, reviewed_at=now, expires_at=expires_at)
        return SignedAutomatedReview(service_key_id=service_key_id, payload=payload,
                                     signature_hex=private_key.sign(canonical_automated_payload(payload)).hex())
    except AutomatedReviewDenied:
        raise
    except Exception:
        raise AutomatedReviewDenied("SIGNING_REFUSED") from None


class SQLiteSelectAutomatedReviewVerifier:
    """Pinned public-key verifier; all three methods recheck body/provenance/oracle."""
    def __init__(self, *, review: SignedAutomatedReview | None = None,
                 service_key_id: str | None = None, service_public_key: bytes | None = None,
                 provenance: CurrentCaptureProvenanceResolver | None = None,
                 enabled: bool = False, clock: Callable[[], datetime] | None = None) -> None:
        self._review = review
        self._key_id = service_key_id
        self._provenance = provenance
        self._enabled = enabled is True
        self._clock = clock or (lambda: datetime.now(UTC))
        self._key: Ed25519PublicKey | None = None
        if type(service_public_key) is bytes and len(service_public_key) == 32:
            try:
                self._key = Ed25519PublicKey.from_public_bytes(service_public_key)
            except ValueError:
                pass

    def _reviewed(self, capture: CompleteCapture) -> tuple[tuple[str, ...], str] | None:
        if not self._enabled or self._review is None or self._key is None or self._key_id is None or self._provenance is None:
            return None
        try:
            review = revalidate(self._review, SignedAutomatedReview)
            p = review.payload
            if review.service_key_id != self._key_id or not _capture_ok(capture):
                return None
            now = self._clock()
            if (type(now) is not datetime or now.tzinfo is None or now.utcoffset() != timedelta(0)
                or p.reviewed_at > now or p.expires_at <= now):
                return None
            self._key.verify(bytes.fromhex(review.signature_hex), canonical_automated_payload(p))
            if (p.capture_id != capture.capture_id or p.lane != capture.lane
                or p.source_handle != capture.source_handle
                or p.scope != revalidate(capture.scope, SubjectScope)
                or p.revision != capture.revision or p.body_sha256 != capture.digest
                or p.body_bytes != len(capture.body) or p.final_url != capture.final_url
                or p.request_chain != capture.request_chain or p.origin != capture.origin
                or p.reading_level != capture.reading_level or p.license_id != capture.license_id
                or self._provenance.resolve(capture) != p.provenance_digest):
                return None
            spans, oracle_digest = _analyze(capture)
            if p.excerpts != spans or p.oracle_digest != oracle_digest:
                return None
            excerpts = tuple(capture.body[s.start_byte:s.end_byte].decode("utf-8") for s in spans)
            return excerpts, hashlib.sha256(canonical_signed_review(review)).hexdigest()
        except Exception:  # signature, resolver and profile failures all deny without body leakage
            return None

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        checked = self._reviewed(capture)
        if checked is None:
            return QualityFinding("offline_protocol_only", "unknown", "unknown", "unknown", "unknown",
                                  "unknown", (), "unverified.sqlite-select", "0" * 64)
        return QualityFinding("production", "current", "suitable", "correct", "resolved",
                              "absent", ("queries",), "family.sqlite", checked[1])

    def reviewed_usages(self, capture: CompleteCapture) -> tuple[str, ...]:
        return USAGES if self._reviewed(capture) is not None else ()

    def approved_excerpts(self, capture: CompleteCapture) -> tuple[str, ...]:
        checked = self._reviewed(capture)
        return checked[0] if checked is not None else ()
