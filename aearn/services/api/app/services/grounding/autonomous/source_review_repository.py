"""C current review authority. Never infer quality from a URL, hash or model text.

A trusted verifier must inspect complete bytes and return independent findings. The
caller owns the transaction; no provider or network request is made here. Claim
receipts are deliberately outside this source-level repository.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

import psycopg

from .contracts import SourceAssessment, SubjectScope, Usage
from .source_assessment import (
    CurrentReview, DocumentCoordinate, DocumentReviewFacts, StorageUseGrant,
    assess_document,
)
from .source_policy import SourceAuthorization


class ReviewDenied(ValueError):
    """A bounded, non-secret refusal code."""


@dataclass(frozen=True)
class CompleteCapture:
    capture_id: UUID
    lane: Literal["registered", "candidate"]
    body: bytes
    digest: str
    revision: str
    scope: SubjectScope
    source_handle: str
    final_url: str
    request_chain: tuple[str, ...]
    origin: str
    reading_level: str
    license_id: str


@dataclass(frozen=True)
class QualityFinding:
    mode: Literal["production", "offline_protocol_only"]
    version_fit: Literal["current", "stale", "unknown"]
    reading_fit: Literal["suitable", "unsuitable", "unknown"]
    technical_status: Literal["correct", "incorrect", "unknown"]
    conflict_status: Literal["resolved", "unresolved", "unknown"]
    known_error: Literal["absent", "present", "unknown"]
    covered_facets: tuple[str, ...]
    lineage_family: str
    evidence_hash: str  # bounded verifier evidence, not content or prose


class QualityVerifier(Protocol):
    """Trusted adapter; optional reviewed_usages/approved_excerpts must be paired.

    Neither optional method means a legacy full-source reviewer. Offline fakes
    MUST report offline_protocol_only.
    """

    def verify(self, capture: CompleteCapture) -> QualityFinding: ...


@dataclass(frozen=True)
class CandidateUseGrant:
    """Independent current operator storage/use/history grant for a B capture."""

    capture_id: UUID
    policy_id: str
    generation: int
    root_id: str
    source_handle: str
    license_id: str
    origin: str
    reading_level: str
    facets: tuple[str, ...]
    allowed_usages: tuple[Usage, ...]
    immutable_history_allowed: bool
    retained_until: datetime
    storage_receipt_id: str
    active: bool


class CandidateGrantResolver(Protocol):
    def resolve(self, capture_id: UUID) -> CandidateUseGrant | None: ...


class RegisteredProviderCaptureResolver(Protocol):
    """Explicit opt-in resolver for registered provider-native captures."""

    def resolve_capture(
        self, capture_id: UUID, now: datetime,
    ) -> tuple[CompleteCapture, dict[str, Any]] | None: ...


# A bare QUALIFIED flag cannot be projected into DocumentReviewFacts. This
# schema preflight fails closed until the schema owner adds these columns.
_FINDING_COLUMNS = {
    "reading_fit", "version_fit", "technical_status", "conflict_status",
    "known_error", "covered_facets", "quality_evidence_hash", "storage_receipt_id",
}


def _digest(*parts: object) -> str:
    value = json.dumps(parts, separators=(",", ":"), default=str)
    return hashlib.sha256(value.encode()).hexdigest()


def _qualified(item: QualityFinding, scope: SubjectScope) -> bool:
    return (type(item) is QualityFinding and item.mode == "production"
            and item.version_fit == "current" and item.reading_fit == "suitable"
            and item.technical_status == "correct" and item.conflict_status == "resolved"
            and item.known_error == "absent" and bool(item.covered_facets)
            and len(set(item.covered_facets)) == len(item.covered_facets)
            and set(item.covered_facets) <= set(scope.facets)
            and len(item.evidence_hash) == 64
            and all(c in "0123456789abcdef" for c in item.evidence_hash))


class SourceReviewRepository:
    """Transaction-scoped writer and CurrentReviewResolver (no auto-commit)."""

    def __init__(self, conn: psycopg.Connection[dict[str, Any]], *,
                 verifier: QualityVerifier | None = None,
                 candidate_grants: CandidateGrantResolver | None = None,
                 registered_provider_captures: RegisteredProviderCaptureResolver | None = None,
                 ) -> None:
        self.conn = conn
        self.verifier = verifier
        self.candidate_grants = candidate_grants
        self.registered_provider_captures = registered_provider_captures

    def _verifier_scope(self, capture: CompleteCapture
                        ) -> tuple[tuple[Usage, ...] | None, tuple[str, ...] | None]:
        """Current excerpt reviewer limits, or None/None for legacy full review."""
        if self.verifier is None:
            raise ReviewDenied("VERIFIER_DENIED")
        try:
            missing = object()
            usage_method = getattr(self.verifier, "reviewed_usages", missing)
            excerpt_method = getattr(self.verifier, "approved_excerpts", missing)
            if usage_method is missing and excerpt_method is missing:
                return None, None
            if not callable(usage_method) or not callable(excerpt_method):
                raise ReviewDenied("VERIFIER_SCOPE_DENIED")
            usages = usage_method(capture)
            excerpts = excerpt_method(capture)
            if (type(usages) is not tuple or usages != ("supplementary_explanation",)
                    or capture.scope.subject_id != "route.sql"
                    or capture.scope.facets != ("queries",)
                    or type(excerpts) is not tuple or not excerpts or len(excerpts) > 512
                    or any(type(text) is not str or not text.strip() for text in excerpts)
                    or len(set(excerpts)) != len(excerpts)):
                raise ReviewDenied("VERIFIER_SCOPE_DENIED")
            source_text = capture.body.decode("utf-8")
            if any(text not in source_text for text in excerpts):
                raise ReviewDenied("VERIFIER_SCOPE_DENIED")
            return usages, excerpts
        except ReviewDenied:
            raise
        except Exception as exc:
            raise ReviewDenied("VERIFIER_SCOPE_DENIED") from exc

    def reviewed_excerpts(self, capture: CompleteCapture) -> tuple[str, ...] | None:
        """Exact reviewed UTF-8 substrings; None only for legacy full review.

        Caller must obtain a current capture via `_capture` and require the
        current reviewed admission; this helper does not itself grant usage.
        """
        _, excerpts = self._verifier_scope(capture)
        return excerpts

    def _schema_ready(self) -> bool:
        rows = self.conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name='rag_source_reviews'"
        ).fetchall()
        return _FINDING_COLUMNS <= {row["column_name"] for row in rows}

    def _capture(self, capture_id: UUID, lane: Literal["registered", "candidate"],
                 now: datetime) -> tuple[CompleteCapture, dict[str, Any]]:
        if lane == "registered":
            if self.registered_provider_captures is not None:
                try:
                    provider_capture = self.registered_provider_captures.resolve_capture(
                        capture_id, now,
                    )
                except Exception as exc:
                    raise ReviewDenied("CAPTURE_DENIED") from exc
                if provider_capture is not None:
                    return provider_capture
            row = self.conn.execute(
                "SELECT c.*,p.source_handle,p.subject_id,p.subject_version,p.facets,"
                "p.origin,p.reading_level,p.allowed_usages,p.immutable_history_allowed,"
                "p.enabled,p.revoked_at,p.expires_at,p.retention_until AS policy_retention,"
                "p.root_id,p.license_id AS policy_license,p.generation AS policy_generation,"
                "a.state AS attempt_state,a.response_sha256,a.response_bytes,a.root_id AS attempt_root "
                "FROM rag_registered_source_captures c "
                "JOIN rag_registered_source_policies p ON p.policy_id=c.policy_id "
                "JOIN rag_registered_fetch_attempts a ON a.id=c.fetch_attempt_id "
                "WHERE c.id=%s FOR SHARE OF c,p,a", (capture_id,),
            ).fetchone()
            if (row is None or row["generation"] != row["policy_generation"]
                    or not row["enabled"] or row["revoked_at"] is not None
                    or row["expires_at"] <= now or row["policy_retention"] <= now
                    or row["retention_until"] <= now or row["cleared_at"] is not None
                    or row["attempt_state"] != "settled" or row["attempt_root"] != row["root_id"]
                    or row["response_sha256"] != row["fetched_sha256"]
                    or row["response_bytes"] != row["captured_bytes"]
                    or row["license_id"] != row["policy_license"]
                    or row["evidence_level"] != "live_egress_attested"):
                raise ReviewDenied("CAPTURE_DENIED")
            scope = SubjectScope(subject_id=row["subject_id"],
                                 subject_version=row["subject_version"], facets=tuple(row["facets"]))
            license_id = row["policy_license"]
            row = dict(row, storage_receipt_id="store." + _digest(
                row["policy_id"], row["policy_generation"], row["root_id"],
                row["policy_license"], row["fetched_sha256"],
            )[:32])
        else:
            row = self.conn.execute(
                "SELECT c.*,d.subject_id,d.subject_version,d.canonical_url,d.job_id,"
                "j.root_id,j.state AS job_state,l.state AS intake_state,"
                "p.enabled,p.current_generation,p.expires_at,p.revoked_at AS policy_revoked "
                "FROM rag_candidate_captures c "
                "JOIN rag_discovery_candidates d ON d.id=c.candidate_id AND d.job_id=c.job_id "
                "JOIN rag_discovery_jobs j ON j.id=d.job_id "
                "JOIN rag_candidate_intake_leases l ON l.candidate_id=d.id "
                "JOIN rag_candidate_access_policies p ON p.policy_id=c.policy_id "
                "WHERE c.id=%s FOR SHARE OF c,d,j,l,p", (capture_id,),
            ).fetchone()
            if (row is None or row["capture_kind"] != "full"
                    or row["evidence_level"] != "live_egress_attested"
                    or row["cleared_at"] is not None or row["retention_until"] <= now
                    or row["job_state"] != "completed" or row["intake_state"] != "done"
                    or not row["enabled"] or row["policy_revoked"] is not None
                    or row["expires_at"] <= now or row["current_generation"] != row["policy_generation"]
                    or row["full_sha256"] != row["fetched_sha256"]
                    or self.candidate_grants is None):
                raise ReviewDenied("CAPTURE_DENIED")
            settled = self.conn.execute(
                "SELECT 1 FROM rag_discovery_candidates d "
                "JOIN rag_discovery_receipts receipt ON receipt.id=d.discovery_receipt_id "
                "AND receipt.job_id=d.job_id "
                "JOIN rag_budget_attempts attempt ON attempt.id=receipt.attempt_id "
                "AND attempt.job_id=d.job_id "
                "JOIN rag_budget_reservations reservation ON reservation.id=attempt.reservation_id "
                "AND reservation.job_id=d.job_id "
                "WHERE d.id=%s AND receipt.result_code='SEARCH_COMPLETED' "
                "AND attempt.state='settled' AND reservation.state='settled' "
                "AND reservation.root_id=%s FOR SHARE OF d,receipt,attempt,reservation",
                (row["candidate_id"], row["root_id"]),
            ).fetchone()
            if settled is None:
                raise ReviewDenied("CAPTURE_DENIED")
            try:
                grant = self.candidate_grants.resolve(capture_id)
            except Exception as exc:
                raise ReviewDenied("STORAGE_DENIED") from exc
            if (type(grant) is not CandidateUseGrant or not grant.active
                    or grant.capture_id != capture_id or grant.policy_id != row["policy_id"]
                    or grant.generation != row["policy_generation"] or grant.root_id != row["root_id"]
                    or grant.license_id != row["license_id"] or grant.retained_until <= now
                    or grant.retained_until > row["retention_until"]):
                raise ReviewDenied("STORAGE_DENIED")
            parsed = urlsplit(row["final_url"])
            path = parsed.path or "/"
            if (parsed.scheme != "https" or not parsed.hostname
                    or parsed.username or parsed.password or parsed.port
                    or parsed.query or parsed.fragment):
                raise ReviewDenied("CAPTURE_DENIED")
            rules = self.conn.execute(
                "SELECT * FROM rag_candidate_access_rules WHERE policy_id=%s AND generation=%s "
                "AND host=%s AND store_allowed AND allowed_capture='full' "
                "AND revoked_at IS NULL FOR SHARE",
                (row["policy_id"], row["policy_generation"], parsed.hostname),
            ).fetchall()
            if not any(
                (rule["path_prefix"] == "/" or path == rule["path_prefix"]
                 or path.startswith(rule["path_prefix"] + "/"))
                and rule["license_id"] == grant.license_id
                and rule["valid_until"] > now and rule["retention_until"] > now
                and rule["max_captured_bytes"] >= row["captured_bytes"]
                and grant.retained_until <= rule["retention_until"]
                for rule in rules
            ):
                raise ReviewDenied("STORAGE_DENIED")
            scope = SubjectScope(subject_id=row["subject_id"],
                                 subject_version=row["subject_version"], facets=grant.facets)
            license_id = grant.license_id
            row = dict(row, source_handle=grant.source_handle, origin=grant.origin,
                       reading_level=grant.reading_level, allowed_usages=grant.allowed_usages,
                       immutable_history_allowed=grant.immutable_history_allowed,
                       policy_generation=grant.generation, policy_retention=grant.retained_until,
                       storage_receipt_id=grant.storage_receipt_id)
        body = bytes(row["captured_body"] or b"")
        if (not body or len(body) != row["captured_bytes"] or len(body) > 8_388_608
                or hashlib.sha256(body).hexdigest() != row["fetched_sha256"]):
            raise ReviewDenied("CAPTURE_DENIED")
        root = self.conn.execute(
            "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",
            (row["root_id"],),
        ).fetchone()
        if (root is None or not root["enabled"] or root["delegation_expires_at"] <= now
                or not root["period_start"] <= now < root["period_end"]
                or (lane == "registered" and (root["policy_id"] != row["policy_id"]
                    or root["policy_generation"] != row["policy_generation"]))):
            raise ReviewDenied("ROOT_DENIED")
        chain = row["request_chain"]
        if (not isinstance(chain, list) or not chain or not all(isinstance(url, str) for url in chain)
                or row["final_url"] != chain[-1]):
            raise ReviewDenied("CAPTURE_DENIED")
        revision = (row["repo_commit"] if lane == "candidate" else None) or row["fetched_sha256"]
        capture = CompleteCapture(capture_id, lane, body, row["fetched_sha256"],
                                  revision, scope, row["source_handle"], row["final_url"],
                                  tuple(chain), row["origin"], row["reading_level"], license_id)
        return capture, row

    def review_and_admit(self, *, capture_id: UUID, lane: Literal["registered", "candidate"],
                         document_handle: str, requested_usages: tuple[Usage, ...],
                         now: datetime) -> UUID:
        """Never includes assessment_evidence: that requires an exact claim verifier."""
        if (self.conn.autocommit or type(capture_id) is not UUID or self.verifier is None
                or now.tzinfo is None or now.utcoffset() is None or not self._schema_ready()):
            raise ReviewDenied("REVIEW_AUTHORITY_MISSING")
        clock_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if clock_row is None:
            raise ReviewDenied("CLOCK_DENIED")
        clock = clock_row["now"]
        if abs((clock - now).total_seconds()) > 30:
            raise ReviewDenied("CLOCK_DENIED")
        capture, row = self._capture(capture_id, lane, clock)
        try:
            finding = self.verifier.verify(capture)
            reviewed_usages, _ = self._verifier_scope(capture)
        except Exception as exc:
            raise ReviewDenied("VERIFIER_DENIED") from exc
        if (not _qualified(finding, capture.scope) or not requested_usages
                or len(set(requested_usages)) != len(requested_usages)
                or "assessment_evidence" in requested_usages
                or (reviewed_usages is not None
                    and not set(requested_usages) <= set(reviewed_usages))
                or not set(requested_usages) <= set(row["allowed_usages"])
                or not row["immutable_history_allowed"]):
            raise ReviewDenied("REVIEW_DENIED")
        coordinate = DocumentCoordinate(
            scope=capture.scope, source_handle=row["source_handle"],
            document_handle=document_handle, document_revision=capture.revision,
            document_hash=capture.digest,
        )
        receipt = _digest(str(capture_id), capture.digest, finding.evidence_hash,
                          finding.covered_facets, row["policy_generation"], requested_usages)
        try:
            with self.conn.transaction():
                review_row = self.conn.execute(
                    "INSERT INTO rag_source_reviews "
                    "(registered_capture_id,candidate_capture_id,source_handle,document_handle,"
                    "subject_id,subject_version,facets,document_revision,document_hash,lineage_family,"
                    "origin,reading_level,status,quality_code,license_id,allowed_usages,"
                    "immutable_history_allowed,policy_id,policy_generation,root_id,review_receipt_hash,"
                    "reading_fit,version_fit,technical_status,conflict_status,known_error,"
                    "covered_facets,quality_evidence_hash,storage_receipt_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'reviewed','QUALIFIED',%s,%s,"
                    "true,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (capture_id if lane == "registered" else None,
                     capture_id if lane == "candidate" else None,
                     coordinate.source_handle, coordinate.document_handle,
                     coordinate.scope.subject_id, coordinate.scope.subject_version,
                     list(coordinate.scope.facets), coordinate.document_revision, coordinate.document_hash,
                     finding.lineage_family, capture.origin, capture.reading_level, capture.license_id,
                     list(requested_usages), row["policy_id"], row["policy_generation"], row["root_id"],
                     receipt, finding.reading_fit, finding.version_fit, finding.technical_status,
                     finding.conflict_status, finding.known_error, list(finding.covered_facets),
                     finding.evidence_hash, row["storage_receipt_id"]),
                ).fetchone()
                if review_row is None:
                    raise ReviewDenied("REVIEW_DENIED")
                review = review_row["id"]
                handle = "admission." + review.hex
                self.conn.execute(
                    "INSERT INTO rag_source_admissions "
                    "(review_id,receipt_handle,allowed_usages,policy_generation,receipt_hash) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (review, handle, list(requested_usages), row["policy_generation"],
                     _digest(str(review), handle, receipt, requested_usages)),
                )
                return review
        except psycopg.Error as exc:
            raise ReviewDenied("REVIEW_PERSISTENCE_DENIED") from exc

    def resolve(self, source_handle: str, document_handle: str) -> CurrentReview | None:
        """CurrentReviewResolver: no projection without current body/policy/root."""
        scoped = self._resolve_scoped(source_handle, document_handle)
        return scoped[0] if scoped is not None else None

    def _resolve_scoped(self, source_handle: str, document_handle: str
                        ) -> tuple[CurrentReview, tuple[str, ...] | None] | None:
        """Current authority and excerpt fence from the same captured bytes."""
        try:
            if not self._schema_ready() or self.verifier is None:
                return None
            row = self.conn.execute(
                "SELECT r.*,a.receipt_handle,a.allowed_usages AS admission_usages,"
                "a.policy_generation AS admission_generation,a.active AS admission_active,"
                "a.revoked_at AS admission_revoked FROM rag_source_reviews r "
                "JOIN rag_source_admissions a ON a.review_id=r.id "
                "WHERE r.source_handle=%s AND r.document_handle=%s "
                "FOR SHARE OF r,a",
                (source_handle, document_handle),
            ).fetchone()
            if row is None:
                return None
            now_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
            if now_row is None:
                return None
            now = now_row["now"]
            lane = cast(Literal["registered", "candidate"],
                        "registered" if row["registered_capture_id"] is not None else "candidate")
            capture, policy = self._capture(
                row["registered_capture_id"] or row["candidate_capture_id"], lane, now,
            )
            finding = self.verifier.verify(capture)
            reviewed_usages, excerpts = self._verifier_scope(capture)
            if not _qualified(finding, capture.scope):
                return None
            if (finding.version_fit != row["version_fit"]
                    or finding.reading_fit != row["reading_fit"]
                    or finding.technical_status != row["technical_status"]
                    or finding.conflict_status != row["conflict_status"]
                    or finding.known_error != row["known_error"]
                    or finding.covered_facets != tuple(row["covered_facets"])
                    or finding.lineage_family != row["lineage_family"]
                    or finding.evidence_hash != row["quality_evidence_hash"]):
                return None
            if (capture.digest != row["document_hash"] or capture.revision != row["document_revision"]
                    or row["source_handle"] != policy["source_handle"]
                    or capture.scope.subject_id != row["subject_id"]
                    or capture.scope.subject_version != row["subject_version"]
                    or tuple(row["facets"]) != capture.scope.facets
                    or row["policy_generation"] != policy["policy_generation"]
                    or row["policy_id"] != policy["policy_id"]
                    or row["root_id"] != policy["root_id"]
                    or row["license_id"] != capture.license_id
                    or row["origin"] != capture.origin or row["reading_level"] != capture.reading_level
                    or not row["immutable_history_allowed"] or not policy["immutable_history_allowed"]
                    or row["quality_code"] != "QUALIFIED" or row["reading_fit"] != "suitable"
                    or row["version_fit"] != "current" or row["technical_status"] != "correct"
                    or row["conflict_status"] != "resolved" or row["known_error"] != "absent"
                    or not row["quality_evidence_hash"] or not row["covered_facets"]
                    or not set(row["covered_facets"]) <= set(row["facets"])
                    or not row["admission_active"] or row["admission_revoked"] is not None
                    or row["admission_generation"] != row["policy_generation"]
                    or not set(row["admission_usages"]) <= set(policy["allowed_usages"])
                    or (reviewed_usages is not None and (
                        not set(row["allowed_usages"]) <= set(reviewed_usages)
                        or not set(row["admission_usages"]) <= set(reviewed_usages)))
                    or "assessment_evidence" in row["admission_usages"]):
                return None
            coord = DocumentCoordinate(
                scope=capture.scope, source_handle=source_handle, document_handle=document_handle,
                document_revision=row["document_revision"], document_hash=row["document_hash"],
            )
            facts = DocumentReviewFacts(
                coordinate=coord, review_id=row["id"],
                registered_capture_id=row["registered_capture_id"],
                candidate_capture_id=row["candidate_capture_id"],
                review_receipt_hash=row["review_receipt_hash"], quality_code=row["quality_code"],
                license_id=row["license_id"], policy_id=row["policy_id"],
                policy_generation=row["policy_generation"], root_id=row["root_id"],
                immutable_history_allowed=row["immutable_history_allowed"],
                allowed_usages=tuple(row["allowed_usages"]), lineage_family=row["lineage_family"],
                origin=row["origin"], reading_level=row["reading_level"],
                reading_fit=row["reading_fit"], version_fit=row["version_fit"],
                technical_status=row["technical_status"], conflict_status=row["conflict_status"],
                known_error=row["known_error"], covered_facets=tuple(row["covered_facets"]),
                status=row["status"],
            )
            grant = StorageUseGrant(
                coordinate=coord, review_id=row["id"], active=True, revoked=False,
                storage_receipt_id=row["storage_receipt_id"],
                admission_receipt_id=row["receipt_handle"],
                policy_generation=row["policy_generation"], license_status="granted",
                retained_until=min(policy["policy_retention"], policy["retention_until"]),
                allowed_usages=tuple(row["admission_usages"]),
            )
            return CurrentReview(facts=facts, grant=grant, revoked=False), excerpts
        except Exception:  # trusted port/DB failure must not expose stale source authority
            return None

    def resolve_authorization(self, source_handle: str,
                              document_handle: str) -> SourceAuthorization | None:
        current = self.resolve(source_handle, document_handle)
        if current is None:
            return None
        decision = assess_document(current.facts, resolver=self, now=datetime.now(UTC))
        return decision.authorization if decision.allowed else None

    def resolve_assessment(self, source_handle: str,
                           document_handle: str) -> SourceAssessment | None:
        current = self.resolve(source_handle, document_handle)
        if current is None:
            return None
        decision = assess_document(current.facts, resolver=self, now=datetime.now(UTC))
        return decision.assessment if decision.allowed else None


class PostgresSourceAuthorizationResolver:
    """Two-argument A SourceAuthorizationResolver adapter."""

    def __init__(self, repository: SourceReviewRepository) -> None:
        self.repository = repository

    def resolve(self, source_handle: str, document_handle: str) -> SourceAuthorization | None:
        return self.repository.resolve_authorization(source_handle, document_handle)
