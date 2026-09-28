"""SQLite SELECT quality ports: offline preflight and opt-in operator review.

`SQLiteSelectQualityVerifier` always reports offline_protocol_only. The
separate trusted-operator verifier requires a pinned external Ed25519 reviewer
key, an exact signed human judgment and current authenticated full-capture
transport provenance. A signature authenticates operator judgment, NOT
technical truth: the reviewer must inspect the actual body and independent
reference evidence. The caller still checks current storage/use/retention grants.
No HTML/keyword/hostname inference or network/database/provider/model I/O occurs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal, Protocol
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_validator

from .contracts import FrozenContract, HASH, HANDLE, SubjectScope, revalidate
from .source_review_repository import CompleteCapture, QualityFinding

SQLITE_SELECT_URL: Literal["https://www.sqlite.org/lang_select.html"] = (
    "https://www.sqlite.org/lang_select.html"
)
MAX_BODY_BYTES = 8_388_608


class FactCrosscheckReference(FrozenContract):
    """Untrusted pointer to a check, NOT a proof that the claim is correct."""

    claim_id: str = Field(pattern=HANDLE)
    page_span_sha256: str = Field(pattern=HASH)
    independent_source_revision_sha256: str = Field(pattern=HASH)
    reference_family: str = Field(pattern=HANDLE)
    check_receipt_sha256: str = Field(pattern=HASH)


class SQLiteSelectQualityEvidence(FrozenContract):
    """Exact audit-input manifest; none of its fields is self-authenticating.

    Receipt hashes refer to separately retained, independently auditable
    records, not model-authored claims or page text. The signature has no
    configured trust anchor here; it cannot authorize a production finding.
    """

    capture_id: UUID
    source_handle: str = Field(pattern=HANDLE)
    scope: SubjectScope
    final_url: Literal["https://www.sqlite.org/lang_select.html"]
    body_sha256: str = Field(pattern=HASH)
    body_bytes: int = Field(gt=0, le=MAX_BODY_BYTES)
    revision: str = Field(min_length=1, max_length=160)
    egress_provenance_receipt_sha256: str = Field(pattern=HASH)
    currentness_review_receipt_sha256: str = Field(pattern=HASH)
    fact_crosschecks: tuple[FactCrosscheckReference, ...] = Field(
        min_length=1, max_length=16
    )
    known_error_review_receipt_sha256: str = Field(pattern=HASH)
    reading_fit_review_receipt_sha256: str = Field(pattern=HASH)
    lineage_review_receipt_sha256: str = Field(pattern=HASH)
    license_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,79}$")
    storage_use_grant_receipt_sha256: str = Field(pattern=HASH)
    retained_until: datetime
    reviewed_at: datetime
    reviewer_key_id: str = Field(pattern=HANDLE)
    reviewer_signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")

    @model_validator(mode="after")
    def exact_review_scope(self) -> SQLiteSelectQualityEvidence:
        if (
            self.scope.subject_id != "route.sql"
            or self.scope.facets != ("queries",)
            or self.reviewed_at.tzinfo is None
            or self.reviewed_at.utcoffset() is None
            or self.retained_until.tzinfo is None
            or self.retained_until.utcoffset() is None
            or self.retained_until <= self.reviewed_at
        ):
            raise ValueError("invalid SQLite SELECT review scope")
        return self


AuditCode = Literal[
    "CAPTURE_INVALID",
    "EVIDENCE_MISSING",
    "EVIDENCE_MISMATCH",
    "INDEPENDENT_AUTHORITY_MISSING",
    "OPERATOR_REVIEWED",
]


@dataclass(frozen=True)
class SQLiteSelectAudit:
    code: AuditCode
    evidence_hash: str
    missing_authorities: tuple[str, ...]


class SQLiteSelectQualityVerifier:
    """Offline-only implementation of ``QualityVerifier`` for one exact URL.

    The supplied evidence may be a forged dataclass or model copy. It is
    revalidated, bound to the complete bytes, and still cannot promote a
    finding: an independent trust anchor, reference oracle and live policy/
    license authority are intentionally not part of this adapter.
    """

    def __init__(self, evidence: SQLiteSelectQualityEvidence | None = None) -> None:
        self._evidence = evidence

    def audit(self, capture: CompleteCapture) -> SQLiteSelectAudit:
        # A digest is a local consistency check, not proof of a full live fetch.
        try:
            if (
                type(capture) is not CompleteCapture
                or type(capture.body) is not bytes
                or not 0 < len(capture.body) <= MAX_BODY_BYTES
                or capture.lane != "registered"
                or capture.final_url != SQLITE_SELECT_URL
                or capture.request_chain != (SQLITE_SELECT_URL,)
                or capture.scope.subject_id != "route.sql"
                or capture.scope.facets != ("queries",)
                or capture.digest != hashlib.sha256(capture.body).hexdigest()
                or capture.revision != capture.digest
            ):
                return self._closed("CAPTURE_INVALID")
            scope = revalidate(capture.scope, SubjectScope)
            if self._evidence is None:
                return self._closed("EVIDENCE_MISSING", capture.digest)
            evidence = revalidate(self._evidence, SQLiteSelectQualityEvidence)
            if (
                evidence.capture_id != capture.capture_id
                or evidence.source_handle != capture.source_handle
                or evidence.scope != scope
                or evidence.final_url != capture.final_url
                or evidence.body_sha256 != capture.digest
                or evidence.body_bytes != len(capture.body)
                or evidence.revision != capture.revision
                or evidence.license_id != capture.license_id
            ):
                return self._closed("EVIDENCE_MISMATCH", capture.digest)
            # This hash binds a *claimed* bundle for diagnostics only. Never
            # reinterpret it as an authenticated reviewer or transport receipt.
            manifest_hash = hashlib.sha256(
                json.dumps(
                    evidence.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            return self._closed(
                "INDEPENDENT_AUTHORITY_MISSING", capture.digest, manifest_hash
            )
        except (AttributeError, TypeError, ValueError):
            return self._closed("CAPTURE_INVALID")

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        audit = self.audit(capture)
        return QualityFinding(
            mode="offline_protocol_only",
            version_fit="unknown",
            reading_fit="unknown",
            technical_status="unknown",
            conflict_status="unknown",
            known_error="unknown",
            covered_facets=(),
            lineage_family="unverified.sqlite-select",
            evidence_hash=audit.evidence_hash,
        )

    @staticmethod
    def _closed(code: AuditCode, *binding: str) -> SQLiteSelectAudit:
        digest = hashlib.sha256(
            json.dumps(
                ("sqlite-select-quality-v1", code, binding), separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest()
        missing = (
            "signed_full_body_provenance",
            "independent_currentness_and_fact_oracle",
            "independent_known_error_and_reading_fit_review",
            "verified_operator_signature",
            "current_license_storage_use_retention_grant",
        )
        return SQLiteSelectAudit(
            code=code, evidence_hash=digest, missing_authorities=missing
        )


class OperatorQualityJudgment(FrozenContract):
    """Explicit human judgments; no host, HTML or keyword quality oracle."""

    version_fit: Literal["current", "stale", "unknown"]
    reading_fit: Literal["suitable", "unsuitable", "unknown"]
    technical_status: Literal["correct", "incorrect", "unknown"]
    conflict_status: Literal["resolved", "unresolved", "unknown"]
    known_error: Literal["absent", "present", "unknown"]
    covered_facets: tuple[Literal["queries"], ...] = Field(max_length=1)
    lineage_family: str = Field(pattern=HANDLE)


class SQLiteSelectOperatorReviewPayload(FrozenContract):
    """Domain-separated signed operator judgment, NOT proof of technical truth.

    A real reviewer must inspect the *actual complete body* and independent
    evidence for correctness, version, reading fit, conflicts and known errors.
    The signature authenticates that reviewer's judgment, not its truth.
    """

    format: Literal["aearn.sqlite-select.operator-review.v1"]
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
    judgment: OperatorQualityJudgment
    reviewed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded_review(self) -> SQLiteSelectOperatorReviewPayload:
        if (
            self.scope.subject_id != "route.sql"
            or self.scope.facets != ("queries",)
            or self.request_chain != (SQLITE_SELECT_URL,)
            or self.reviewed_at.tzinfo is None
            or self.reviewed_at.utcoffset() != timedelta(0)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() != timedelta(0)
            or self.expires_at <= self.reviewed_at
            or self.expires_at - self.reviewed_at > timedelta(days=30)
        ):
            raise ValueError("invalid SQLite SELECT operator review")
        return self


class SignedSQLiteSelectOperatorReview(FrozenContract):
    reviewer_key_id: str = Field(pattern=HANDLE)
    payload: SQLiteSelectOperatorReviewPayload
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def canonical_operator_review_payload(
    payload: SQLiteSelectOperatorReviewPayload,
) -> bytes:
    """Exact versioned signing bytes; no signer or key creation in this module."""
    checked = revalidate(payload, SQLiteSelectOperatorReviewPayload)
    return b"AEARN-SQLITE-SELECT-OPERATOR-REVIEW-V1\n" + json.dumps(
        checked.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


class CurrentCaptureProvenanceResolver(Protocol):
    """Trusted current capture proof, never a digest copied from a review.

    Resolve the exact persisted transport_proof_sha256 only after checking the
    non-null canonical signed transport proof, attestor/worker image pins and
    current capture/source/scope/revision/full-body binding. Nullable legacy or
    synthetic captures MUST return None. Caller also owns storage/use grants.
    """

    def resolve(self, capture: CompleteCapture) -> str | None: ...


class TrustedOperatorSQLiteSelectQualityVerifier:
    """Opt-in operator review, separate from the always-offline adapter.

    Key ID/public bytes must be provisioned and pinned externally; no key or
    production review is generated here. The caller must inject a trustworthy
    provenance resolver and independently check current license/use/retention.
    """

    def __init__(
        self,
        *,
        review: SignedSQLiteSelectOperatorReview | None = None,
        reviewer_key_id: str | None = None,
        reviewer_public_key: bytes | None = None,
        provenance: CurrentCaptureProvenanceResolver | None = None,
        enabled: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._review = review
        self._key_id = reviewer_key_id
        self._provenance = provenance
        self._enabled = enabled is True
        self._clock = clock or (lambda: datetime.now(UTC))
        self._key: Ed25519PublicKey | None = None
        if type(reviewer_public_key) is bytes and len(reviewer_public_key) == 32:
            try:
                self._key = Ed25519PublicKey.from_public_bytes(reviewer_public_key)
            except ValueError:
                pass

    def _reviewed(
        self,
        capture: CompleteCapture,
    ) -> tuple[SQLiteSelectAudit, OperatorQualityJudgment | None]:
        closed = SQLiteSelectQualityVerifier._closed
        if not self._enabled:
            return closed("INDEPENDENT_AUTHORITY_MISSING"), None
        try:
            # Reuse the offline adapter's full-byte/exact-scope preflight. Its
            # evidence-less outcome is expected; it never approves a finding.
            if SQLiteSelectQualityVerifier().audit(capture).code != "EVIDENCE_MISSING":
                return closed("CAPTURE_INVALID"), None
            if (
                self._key is None
                or self._key_id is None
                or self._provenance is None
                or self._review is None
            ):
                return closed("INDEPENDENT_AUTHORITY_MISSING"), None
            review = revalidate(self._review, SignedSQLiteSelectOperatorReview)
            payload = review.payload
            if (
                review.reviewer_key_id != self._key_id
                or payload.capture_id != capture.capture_id
                or payload.lane != capture.lane
                or payload.source_handle != capture.source_handle
                or payload.scope != revalidate(capture.scope, SubjectScope)
                or payload.revision != capture.revision
                or payload.body_sha256 != capture.digest
                or payload.body_bytes != len(capture.body)
                or payload.final_url != capture.final_url
                or payload.request_chain != capture.request_chain
                or payload.origin != capture.origin
                or payload.reading_level != capture.reading_level
                or payload.license_id != capture.license_id
            ):
                return closed("EVIDENCE_MISMATCH"), None
            now = self._clock()
            if (
                type(now) is not datetime
                or now.tzinfo is None
                or now.utcoffset() is None
                or payload.reviewed_at > now
                or payload.expires_at <= now
            ):
                return closed("INDEPENDENT_AUTHORITY_MISSING"), None
            signed = canonical_operator_review_payload(payload)
            try:
                self._key.verify(bytes.fromhex(review.signature_hex), signed)
            except (InvalidSignature, ValueError):
                return closed("INDEPENDENT_AUTHORITY_MISSING"), None
            # Must be resolved from a current authenticated full transport proof,
            # not a nullable legacy capture row or the review's own assertion.
            current_digest = self._provenance.resolve(capture)
            if (
                type(current_digest) is not str
                or len(current_digest) != 64
                or any(c not in "0123456789abcdef" for c in current_digest)
                or current_digest != payload.provenance_digest
            ):
                return closed("INDEPENDENT_AUTHORITY_MISSING"), None
            finding = payload.judgment
            if (
                finding.version_fit != "current"
                or finding.reading_fit != "suitable"
                or finding.technical_status != "correct"
                or finding.conflict_status != "resolved"
                or finding.known_error != "absent"
                or finding.covered_facets != ("queries",)
            ):
                return closed("INDEPENDENT_AUTHORITY_MISSING"), None
            evidence_hash = hashlib.sha256(
                signed + bytes.fromhex(review.signature_hex) + self._key_id.encode()
            ).hexdigest()
            return SQLiteSelectAudit("OPERATOR_REVIEWED", evidence_hash, ()), finding
        except Exception:
            # Includes provenance resolver errors; never leak body or proof text.
            return closed("INDEPENDENT_AUTHORITY_MISSING"), None

    def audit(self, capture: CompleteCapture) -> SQLiteSelectAudit:
        return self._reviewed(capture)[0]

    def verify(self, capture: CompleteCapture) -> QualityFinding:
        audit, finding = self._reviewed(capture)
        if audit.code != "OPERATOR_REVIEWED" or finding is None:
            return SQLiteSelectQualityVerifier().verify(capture)
        return QualityFinding(
            mode="production",
            version_fit=finding.version_fit,
            reading_fit=finding.reading_fit,
            technical_status=finding.technical_status,
            conflict_status=finding.conflict_status,
            known_error=finding.known_error,
            covered_facets=finding.covered_facets,
            lineage_family=finding.lineage_family,
            evidence_hash=audit.evidence_hash,
        )
