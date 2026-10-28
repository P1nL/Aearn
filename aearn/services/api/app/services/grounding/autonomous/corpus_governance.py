"""Default-off C corpus orchestration; never promotes B staging or fixture summaries.

The caller owns the transaction and all grants. This module has no network, worker,
route, or consumer entrypoint. A DB transaction must span the current-authority read,
validation receipt and CorpusRepository CAS; failures must roll it back.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID
from urllib.parse import urlsplit

from psycopg import Connection, Error
from psycopg.pq import TransactionStatus

from app.services.grounding.corpus_contracts import (
    CorpusCandidate, CorpusChunk, CorpusDocument, CorpusEvent, CorpusSource,
)
from app.services.grounding.corpus_repository import CorpusConflict, CorpusRepository, _hash
from app.services.grounding.subject_registry import get_grounding_subject

from .contracts import LearningMaterialDemand, SourceAssessment, SubjectScope, revalidate
from .qualified_corpus import QualificationSnapshot, QualifiedDocument
from .source_policy import SourceAuthorization
from .source_review_repository import ReviewDenied, SourceReviewRepository
from .candidate_use_grants import PostgresCandidateGrantResolver, require_candidate_history_grant
from .registered_source_retention import require_indefinite_history_grant
from .corpus_usage_partition import LEGACY_AUDIT_POLICY, PURPOSE_PARTITION_POLICY, document_usages, purpose_facets


class CorpusGovernanceDenied(ValueError):
    """Safe reason code, never a URL, body, provider error or credential."""


class CurrentCorpusAuthority(Protocol):
    """Trusted current operator lease/policy/root gate (not model-supplied facts)."""

    def require_current(self, conn: Connection[dict[str, Any]], *, policy_id: str,
                        generation: int, root_id: str, subject_id: str,
                        subject_version: str, now: datetime) -> None: ...


class PostgresCorpusAuthority:
    """Registered-source authority; root period/delegation is its lease.

    This port does not authorize B captures: a separate vetted B current-root
    implementation is required before they can be admitted by this orchestration.
    """

    def require_current(self, conn: Connection[dict[str, Any]], *, policy_id: str,
                        generation: int, root_id: str, subject_id: str,
                        subject_version: str, now: datetime) -> None:
        policy = conn.execute(
            "SELECT * FROM rag_registered_source_policies WHERE policy_id=%s FOR SHARE", (policy_id,)
        ).fetchone()
        root = conn.execute(
            "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE", (root_id,)
        ).fetchone()
        clock = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if clock is None or policy is None or root is None:
            raise CorpusGovernanceDenied("AUTHORITY_MISSING")
        db_now = clock["now"]
        if (policy["generation"] != generation or policy["root_id"] != root_id
                or policy["subject_id"] != subject_id
                or policy["subject_version"] != subject_version
                or policy["enabled"] is not True or policy["revoked_at"] is not None
                or policy["expires_at"] <= db_now or policy["retention_until"] <= db_now
                or policy["immutable_history_allowed"] is not True
                or root["enabled"] is not True or root["root_id"] != root_id
                or root["policy_id"] != policy_id or root["policy_generation"] != generation
                or root["delegation_expires_at"] <= db_now
                or root["period_start"] > db_now or root["period_end"] <= db_now
                ):
            raise CorpusGovernanceDenied("AUTHORITY_STALE")


class PostgresCandidateCorpusAuthority:
    """B root and candidate policy gate; never infer formal use from B storage."""

    def require_current(self, conn: Connection[dict[str, Any]], *, policy_id: str,
                        generation: int, root_id: str, subject_id: str,
                        subject_version: str, now: datetime) -> None:
        policy = conn.execute(
            "SELECT * FROM rag_candidate_access_policies WHERE policy_id=%s FOR SHARE",
            (policy_id,),
        ).fetchone()
        root = conn.execute(
            "SELECT * FROM rag_budget_authority_roots WHERE root_id=%s FOR SHARE",
            (root_id,),
        ).fetchone()
        clock = conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if policy is None or root is None or clock is None:
            raise CorpusGovernanceDenied("AUTHORITY_MISSING")
        db_now = clock["now"]
        if (policy["current_generation"] != generation
                or policy["enabled"] is not True or policy["revoked_at"] is not None
                or policy["expires_at"] <= db_now
                or root["enabled"] is not True or root["delegation_expires_at"] <= db_now
                or not root["period_start"] <= db_now < root["period_end"]):
            raise CorpusGovernanceDenied("AUTHORITY_STALE")


class OfflineCorpusAuthority:
    """Explicitly test-only fake; must never be composed into live operation."""

    def require_current(self, conn: Connection[dict[str, Any]], *, policy_id: str,
                        generation: int, root_id: str, subject_id: str,
                        subject_version: str, now: datetime) -> None:
        raise CorpusGovernanceDenied("OFFLINE_ONLY")


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


class CorpusGovernance:
    """C candidate/validation/CAS gate on top of the sole 260 writer.

    Disabled unless constructed with a trusted current authority and explicitly
    enabled in an isolated operator context. No implicit environment flag or fixture
    mode can enable it. All methods require a caller-owned, non-autocommit transaction.
    """

    def __init__(self, conn: Connection[dict[str, Any]], *,
                 authority: CurrentCorpusAuthority | None = None,
                 source_reviews: SourceReviewRepository | None = None,
                 isolated_operator_enabled: bool = False) -> None:
        self.conn = conn
        self.repo = CorpusRepository(conn)
        self.authority = authority
        self.source_reviews = source_reviews
        self.enabled = isolated_operator_enabled

    def _transaction(self) -> None:
        if self.conn.autocommit or self.conn.info.transaction_status == TransactionStatus.IDLE:
            raise CorpusGovernanceDenied("TRANSACTION_REQUIRED")
        if (not self.enabled or self.authority is None or isinstance(self.authority, OfflineCorpusAuthority)
                or self.source_reviews is None or self.source_reviews.conn is not self.conn
                or self.source_reviews.verifier is None):
            raise CorpusGovernanceDenied("AUTHORITY_MISSING")
        current = self.conn.execute("SELECT current_database() AS name").fetchone()
        assessment = self.source_reviews.assessment_receipts
        owned_assessment = (assessment is not None and assessment.conn is self.conn
                            and self.source_reviews.verifier is assessment
                            and current is not None
                            and current["name"] == "aearn_b1d_sandbox_20261001")
        if assessment is not None:
            assessment.require_transaction()
        if current is None or not (current["name"].startswith("aearn_rag260_c_") or owned_assessment):
            raise CorpusGovernanceDenied("ISOLATED_DATABASE_REQUIRED")

    def _rows(self, corpus_id: UUID, *, lock: bool = True,
              consumption_read: bool = False) -> tuple[Any, list[dict[str, Any]]]:
        self._transaction()
        if consumption_read:
            if not lock:
                raise CorpusGovernanceDenied("CONSUMPTION_LOCK_REQUIRED")
            version = self.repo.version(corpus_id, for_share=True)
        else:
            version = self.repo.version(corpus_id, for_update=lock)
        if get_grounding_subject(version.subject_id) is None:
            raise CorpusGovernanceDenied("SUBJECT_UNSUPPORTED")
        rows = self.conn.execute(
            """SELECT link.*, link.document_hash AS linked_hash,
                      link.source_id AS linked_source_id, doc.*,
                      src.facets_json AS source_facets,
                      src.trust_tier AS source_trust, src.source_hash AS snapshot_source_hash,
                      src.source_version, src.allowed_domains_json, src.seed_urls_json,
                      admission.active, admission.revoked_at, admission.receipt_handle,
                      admission.allowed_usages AS admitted_usages,
                      admission.policy_generation AS admission_generation,
                      review.id AS review_id, review.source_handle, review.document_handle,
                      review.document_revision, review.document_hash AS reviewed_hash,
                      review.facets AS review_facets, review.allowed_usages AS review_usages,
                      review.status AS review_status, review.quality_code, review.origin,
                      review.reading_level, review.lineage_family, review.immutable_history_allowed,
                      review.storage_receipt_id,
                      review.policy_id, review.policy_generation AS review_generation, review.root_id,
                      review.registered_capture_id, review.candidate_capture_id,
                      policy.enabled AS policy_enabled, policy.revoked_at AS policy_revoked,
                      policy.retention_until, policy.expires_at AS policy_expires,
                      policy.generation AS current_generation,
                      policy.source_handle AS current_source_handle,
                      policy.facets AS policy_facets, policy.allowed_usages AS policy_usages,
                      policy.immutable_history_allowed AS policy_history,
                      capture.cleared_at, capture.captured_body, capture.fetched_sha256,
                      capture.retention_until AS capture_retention,
                      policy.canonical_url AS policy_url, capture.final_url AS capture_url
               FROM rag_corpus_admission_links link
               JOIN grounding_corpus_documents doc ON doc.corpus_version_id=link.corpus_id
                    AND doc.document_id=link.document_id
               JOIN grounding_corpus_source_snapshots src ON src.corpus_version_id=link.corpus_id
                    AND src.source_id=doc.source_id
               JOIN rag_source_admissions admission ON admission.id=link.admission_id
               JOIN rag_source_reviews review ON review.id=admission.review_id
               LEFT JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id
               LEFT JOIN rag_registered_source_captures capture ON capture.id=review.registered_capture_id
               WHERE link.corpus_id=%s ORDER BY doc.document_id
               FOR SHARE OF link,doc,src,admission,review""", (corpus_id,)
        ).fetchall()
        return version, rows

    def _audit(self, corpus_id: UUID, *, purpose: str, full_required: bool = False,
               consumption_read: bool = False
               ) -> tuple[dict[str, str | int | bool], dict[str, str | int | bool], str, str, int | None, bool]:
        version, rows = self._rows(corpus_id, consumption_read=True) if consumption_read else self._rows(corpus_id)
        partitioned = version.coverage_policy_version == PURPOSE_PARTITION_POLICY
        subject = get_grounding_subject(version.subject_id)
        assert subject is not None
        assessment_enabled = (purpose == "assessment_evidence" and self.source_reviews is not None
                              and self.source_reviews.assessment_receipts is not None
                              and self.source_reviews.verifier is self.source_reviews.assessment_receipts)
        if purpose not in ("main_teaching", "supplementary_explanation") and not assessment_enabled:
            raise CorpusGovernanceDenied("PURPOSE_DENIED")
        all_docs = self.conn.execute(
            "SELECT document_id FROM grounding_corpus_documents WHERE corpus_version_id=%s", (corpus_id,)
        ).fetchall()
        sources = self.conn.execute(
            "SELECT source_id FROM grounding_corpus_source_snapshots WHERE corpus_version_id=%s", (corpus_id,)
        ).fetchall()
        chunks = self.conn.execute(
            "SELECT * FROM grounding_corpus_chunks WHERE corpus_version_id=%s ORDER BY chunk_id", (corpus_id,)
        ).fetchall()
        if (not rows or len(rows) > 96 or len(rows) != len(all_docs)
                or not sources or len(sources) > 96 or not chunks or len(chunks) > 512
                or len(sources) != len({row["source_id"] for row in rows})
                or {row["document_id"] for row in rows} != {chunk["document_id"] for chunk in chunks}):
            raise CorpusGovernanceDenied("SNAPSHOT_INCOMPLETE")
        db_now_row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        assert db_now_row is not None
        db_now = db_now_row["now"]
        covered: set[str] = set()
        families: dict[str, str] = {}
        doc_rows: dict[str, dict[str, Any]] = {}
        generations: set[int] = set()
        admission_facts: list[tuple[object, ...]] = []
        per_doc_usages: dict[str, tuple[str, ...]] = {}
        per_doc_facets: dict[str, set[str]] = {}
        per_policy: set[tuple[str, int]] = set()
        for row in rows:
            try:
                needed_usages = document_usages(row["admitted_usages"], row["review_usages"],
                                                purpose=purpose, partitioned=partitioned)
            except ValueError:
                raise CorpusGovernanceDenied("USAGE_PARTITION_DENIED") from None
            if (row["source_id"] != row["linked_source_id"]
                    or row["linked_hash"] != row["reviewed_hash"]
                    or row["source_id"] != row["source_handle"]
                    or row["document_id"] != row["document_handle"]
                    or row["document_hash"] != row["reviewed_hash"]
                    or row["document_version"] != row["document_revision"]
                    or row["subject_id"] != version.subject_id
                    or row["subject_version"] != version.subject_version
                    or row["parse_status"] != "parsed"
                    or row["source_hash"] != row["snapshot_source_hash"]
                    or row["source_trust"] != ("official" if row["origin"] == "official" else "trusted_de_facto")
                    or row["review_status"] != "reviewed" or row["quality_code"] != "QUALIFIED"
                    or row["active"] is not True or row["revoked_at"] is not None
                    or row["immutable_history_allowed"] is not True
                    or row["admission_generation"] != row["review_generation"]):
                raise CorpusGovernanceDenied("ADMISSION_STALE")
            # A persisted QUALIFIED string is not an authenticated quality review.
            # The repository reopens complete bytes and independently reruns its
            # trusted verifier under the same caller-owned transaction.
            assert self.source_reviews is not None
            scoped_review = self.source_reviews._resolve_scoped(
                row["source_handle"], row["document_handle"],
            )
            if scoped_review is None:
                raise CorpusGovernanceDenied("REVIEW_UNVERIFIED")
            current_review, approved_excerpts = scoped_review
            if (current_review.revoked or current_review.grant is None
                    or not current_review.grant.active or current_review.grant.revoked
                    or current_review.facts.review_id != row["review_id"]
                    or current_review.facts.coordinate.document_hash != row["reviewed_hash"]
                    or current_review.facts.coordinate.scope.subject_id != version.subject_id
                    or current_review.facts.coordinate.scope.subject_version != version.subject_version
                    or not set(needed_usages) <= set(current_review.grant.allowed_usages)
                    or current_review.grant.admission_receipt_id != row["receipt_handle"]
                    or not set(row["scope_facets"]) <= set(current_review.facts.covered_facets)):
                raise CorpusGovernanceDenied("REVIEW_UNVERIFIED")
            if row["candidate_capture_id"] is not None:
                if (row["registered_capture_id"] is not None
                        or not isinstance(self.authority, PostgresCandidateCorpusAuthority)
                        or not isinstance(self.source_reviews.candidate_grants, PostgresCandidateGrantResolver)
                        or self.source_reviews.candidate_grants.conn is not self.conn):
                    raise CorpusGovernanceDenied("AUTHORITY_MISSING")
                try:
                    capture, _ = self.source_reviews._capture(
                        row["candidate_capture_id"], "candidate", db_now,
                    )
                except (ReviewDenied, ValueError, TypeError, KeyError):
                    raise CorpusGovernanceDenied("SOURCE_STALE") from None
                host = urlsplit(capture.final_url).hostname
                if (capture.digest != row["reviewed_hash"]
                        or capture.revision != row["document_revision"]
                        or capture.source_handle != row["source_handle"]
                        or capture.origin != row["origin"]
                        or capture.reading_level != row["reading_level"]
                        or capture.final_url != row["final_url"]
                        or capture.final_url != row["canonical_url"]
                        or capture.final_url not in row["seed_urls_json"]
                        or host not in row["allowed_domains_json"]
                        or row["source_version"] != capture.revision
                        or not set(row["scope_facets"]) <= set(capture.scope.facets)
                        or not set(row["source_facets"]) <= set(row["review_facets"])):
                    raise CorpusGovernanceDenied("SOURCE_STALE")
                body = capture.body
            else:
                if (row["registered_capture_id"] is None
                        or not isinstance(self.authority, PostgresCorpusAuthority)):
                    raise CorpusGovernanceDenied("AUTHORITY_MISSING")
                # Lock and re-read mutable capture/policy after any lock wait. Joining a
                # previously read row is not a current grant under READ COMMITTED.
                current_policy = self.conn.execute(
                    "SELECT * FROM rag_registered_source_policies WHERE policy_id=%s FOR SHARE",
                    (row["policy_id"],),
                ).fetchone()
                current_capture = self.conn.execute(
                    "SELECT * FROM rag_registered_source_captures WHERE id=%s FOR SHARE",
                    (row["registered_capture_id"],),
                ).fetchone() if row["registered_capture_id"] is not None else None
                if (current_policy is None or current_capture is None
                        or current_capture["cleared_at"] is not None
                        or current_capture["captured_body"] is None
                        or current_capture["retention_until"] <= db_now
                        or hashlib.sha256(bytes(current_capture["captured_body"])).hexdigest()
                            != row["reviewed_hash"]
                        or current_capture["final_url"] != row["final_url"]
                        or current_policy["canonical_url"] != row["canonical_url"]
                        or current_policy["generation"] != row["review_generation"]
                        or current_policy["source_handle"] != row["source_handle"]
                        or current_policy["canonical_url"] != row["final_url"]
                        or current_policy["host"] not in row["allowed_domains_json"]
                        or row["seed_urls_json"] != [current_policy["canonical_url"]]
                        or row["source_version"] != row["document_revision"]
                        or current_policy["enabled"] is not True
                        or current_policy["revoked_at"] is not None
                        or current_policy["retention_until"] <= db_now
                        or current_policy["expires_at"] <= db_now
                        or current_policy["immutable_history_allowed"] is not True
                        or not set(needed_usages) <= set(current_policy["allowed_usages"])
                        or not set(row["scope_facets"]) <= set(current_policy["facets"])):
                    raise CorpusGovernanceDenied("SOURCE_STALE")
                # Registered captures only. A B capture needs a separate current B root
                # authority and complete body/retention resolver, not a fake registration.
                if (row["registered_capture_id"] is None or row["candidate_capture_id"] is not None
                        or row["policy_enabled"] is not True or row["policy_revoked"] is not None
                        or row["current_generation"] != row["review_generation"]
                        or row["current_source_handle"] != row["source_handle"]
                        or row["policy_history"] is not True
                        or row["policy_expires"] <= db_now or row["retention_until"] <= db_now
                        or row["capture_retention"] <= db_now or row["cleared_at"] is not None
                        or row["captured_body"] is None
                        or hashlib.sha256(bytes(row["captured_body"])).hexdigest() != row["fetched_sha256"]
                        or row["fetched_sha256"] != row["reviewed_hash"]
                        or not set(needed_usages) <= set(row["policy_usages"])
                        or not set(row["scope_facets"]) <= set(row["review_facets"])
                        or not set(row["scope_facets"]) <= set(row["policy_facets"])
                        or not set(row["source_facets"]) <= set(row["review_facets"])):
                    raise CorpusGovernanceDenied("SOURCE_STALE")
                body = bytes(current_capture["captured_body"])
            assert self.authority is not None
            self.authority.require_current(
                self.conn, policy_id=row["policy_id"], generation=row["review_generation"],
                root_id=row["root_id"], subject_id=version.subject_id,
                subject_version=version.subject_version, now=db_now,
            )
            family = row["lineage_family"]
            if family in families and families[family] != row["source_id"]:
                raise CorpusGovernanceDenied("LINEAGE_CONFLICT")
            families[family] = row["source_id"]
            generations.add(row["review_generation"])
            per_policy.add((row["policy_id"], row["review_generation"]))
            per_doc_usages[row["document_id"]] = needed_usages
            per_doc_facets[row["document_id"]] = set()
            doc_rows[row["document_id"]] = dict(
                row, captured_body=body, approved_excerpts=approved_excerpts,
            )
            admission_facts.append((str(row["admission_id"]), str(row["review_id"]), row["reviewed_hash"], row["review_generation"]))
            if partitioned:
                admission_facts[-1] += (row["document_id"], row["policy_id"], needed_usages)
        for chunk in chunks:
            doc_row = doc_rows.get(chunk["document_id"])
            if (doc_row is None or chunk["source_id"] != doc_row["source_id"]
                    or chunk["document_hash"] != doc_row["reviewed_hash"]
                    or chunk["subject_id"] != version.subject_id
                    or chunk["subject_version"] != version.subject_version
                    or not set(chunk["facets_json"]) <= set(doc_row["scope_facets"])
                    or not chunk["content"].strip()
                    or hashlib.sha256(chunk["content"].encode()).hexdigest() != chunk["chunk_hash"]
                    or chunk["content"].encode() not in bytes(doc_row["captured_body"])
                    or (doc_row["approved_excerpts"] is not None
                        and chunk["content"] not in doc_row["approved_excerpts"])):
                raise CorpusGovernanceDenied("CHUNK_INVALID")
            covered.update(chunk["facets_json"])
            per_doc_facets[chunk["document_id"]].update(chunk["facets_json"])
        index = self.conn.execute(
            """SELECT 1 FROM pg_index WHERE indexrelid=to_regclass('idx_grounding_corpus_chunks_search')
               AND indisvalid AND indisready"""
        ).fetchone()
        bad_fts = self.conn.execute(
            """SELECT 1 FROM grounding_corpus_chunks WHERE corpus_version_id=%s
               AND search_vector IS DISTINCT FROM to_tsvector('simple'::regconfig,title || ' ' || section_path || ' ' || content)
               LIMIT 1""", (corpus_id,)
        ).fetchone()
        if index is None or bad_fts is not None:
            raise CorpusGovernanceDenied("FTS_UNAVAILABLE")
        required = set(subject.required_facets)
        missing = required - covered
        partitions = purpose_facets(per_doc_usages, per_doc_facets)
        if partitioned and not partitions[purpose]:
            raise CorpusGovernanceDenied("PURPOSE_COVERAGE_GAP")
        if full_required and (required - set(partitions[purpose]) if partitioned else missing):
            raise CorpusGovernanceDenied("COVERAGE_GAP")
        if not covered or not covered <= set(subject.required_facets + subject.optional_facets):
            raise CorpusGovernanceDenied("COVERAGE_INVALID")
        if not partitioned and len(generations) != 1:
            raise CorpusGovernanceDenied("POLICY_CONFLICT")
        partial = bool(missing)
        validation: dict[str, str | int | bool] = {
            "dynamic_c": True, "sources": len(sources), "documents": len(rows),
            "chunks": len(chunks), "policy_generation": next(iter(generations)),
        }
        coverage: dict[str, str | int | bool] = {
            "required": len(required), "covered": len(covered & required),
            "gap": len(missing), "partial": partial,
        }
        if partitioned:
            # No fabricated common generation: independent current policies are
            # hashed per identity. Summary stays identical for every authorized
            # purpose, while qualification exposes only its own document subset.
            validation.pop("policy_generation")
            validation.update(purpose_partitioned=True, policy_generations_digest=_digest(sorted(per_policy)))
            coverage["usage_facets_digest"] = _digest(partitions)
        return (validation, coverage, _digest(admission_facts),
                _digest(partitions) if partitioned else _digest(sorted(covered)),
                None if partitioned else next(iter(generations)), partial)

    def create_candidate(self, candidate: CorpusCandidate, *, sources: Sequence[CorpusSource],
                         documents: Sequence[CorpusDocument], chunks: Sequence[CorpusChunk],
                         admissions: Mapping[str, UUID], purpose: str, idempotency_key: str) -> CorpusEvent:
        self._transaction()
        if (not 1 <= len(sources) <= 96 or not 1 <= len(documents) <= 96
                or not 1 <= len(chunks) <= 512 or len(admissions) != len(documents)
                or get_grounding_subject(candidate.subject_id) is None):
            raise CorpusGovernanceDenied("SNAPSHOT_INCOMPLETE")
        with self.conn.transaction():
            event = self.repo.create_candidate(candidate, idempotency_key=idempotency_key)
            for source in sources:
                self.repo.add_source(source)
            for doc in documents:
                self.repo.add_document(doc)
                admission = admissions.get(doc.document_id)
                if admission is None:
                    raise CorpusGovernanceDenied("ADMISSION_MISSING")
                lane_row = self.conn.execute(
                    "SELECT review.candidate_capture_id FROM rag_source_reviews review "
                    "JOIN rag_source_admissions granted ON granted.review_id=review.id "
                    "WHERE granted.id=%s FOR SHARE OF review,granted", (admission,),
                ).fetchone()
                if lane_row is None:
                    raise CorpusGovernanceDenied("ADMISSION_MISSING")
                if lane_row["candidate_capture_id"] is not None:
                    require_candidate_history_grant(self.conn, admission)
                else:
                    require_indefinite_history_grant(self.conn, admission_id=admission)
                self.conn.execute(
                    """INSERT INTO rag_corpus_admission_links
                       (corpus_id,source_id,document_id,admission_id,document_hash,scope_facets)
                       SELECT %s,%s,%s,%s,%s,review.facets FROM rag_source_reviews review
                       JOIN rag_source_admissions granted ON granted.review_id=review.id
                       WHERE granted.id=%s AND granted.active AND review.status='reviewed'
                         AND review.document_hash=%s AND review.document_handle=%s
                         AND review.source_handle=%s AND review.subject_id=%s
                         AND review.subject_version=%s""",
                    (candidate.corpus_id, doc.source_id, doc.document_id, admission,
                     doc.document_hash, admission, doc.document_hash, doc.document_id,
                     doc.source_id, candidate.subject_id, candidate.subject_version),
                )
            for chunk in chunks:
                self.repo.add_chunk(chunk)
            # Re-read persisted facts, not supplied quality/admission booleans.
            self._audit(candidate.corpus_id, purpose=purpose)
            return event

    def validate(self, corpus_id: UUID, *, expected_generation: int,
                 purpose: str, idempotency_key: str) -> CorpusEvent:
        self._transaction()
        with self.conn.transaction():
            version = self.repo.version(corpus_id, for_update=True)
            if version.state != "candidate" or version.generation != expected_generation:
                raise CorpusConflict("candidate generation mismatch")
            validation, coverage, admissions, facets, generation, partial = self._audit(corpus_id, purpose=purpose)
            event = self.repo.finalize_validation(
                corpus_id, passed=True, expected_generation=expected_generation,
                validation_summary=validation, coverage_summary=coverage, idempotency_key=idempotency_key,
            )
            sealed = self.repo.version(corpus_id)
            if sealed.summary_hash is None:
                raise CorpusGovernanceDenied("VALIDATION_UNSEALED")
            self.conn.execute(
                """INSERT INTO rag_corpus_validation_receipts
                   (corpus_id,validation_event_id,admission_digest,coverage_digest,
                    review_policy_generation,summary_hash,partial_coverage,audit_policy_version)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (corpus_id, event.event_id, admissions, facets, generation, sealed.summary_hash, partial,
                 PURPOSE_PARTITION_POLICY if version.coverage_policy_version == PURPOSE_PARTITION_POLICY else LEGACY_AUDIT_POLICY),
            )
            return event

    def _verified(self, corpus_id: UUID, *, summary_hash: str, purpose: str,
                  consumption_read: bool = False) -> Any:
        version = (self.repo.version(corpus_id, for_share=True) if consumption_read
                   else self.repo.version(corpus_id, for_update=True))
        if version.summary_hash != summary_hash or version.state not in ("validated", "published"):
            raise CorpusGovernanceDenied("SUMMARY_STALE")
        validation, coverage, admissions, facets, generation, partial = (
            self._audit(corpus_id, purpose=purpose, consumption_read=True) if consumption_read
            else self._audit(corpus_id, purpose=purpose))
        source_rows = self.conn.execute(
            "SELECT source_id,source_hash FROM grounding_corpus_source_snapshots "
            "WHERE corpus_version_id=%s ORDER BY source_id", (corpus_id,),
        ).fetchall()
        document_rows = self.conn.execute(
            "SELECT document_id,source_id,document_hash FROM grounding_corpus_documents "
            "WHERE corpus_version_id=%s ORDER BY document_id", (corpus_id,),
        ).fetchall()
        chunk_rows = self.conn.execute(
            "SELECT chunk_id,document_id,chunk_hash FROM grounding_corpus_chunks "
            "WHERE corpus_version_id=%s ORDER BY chunk_id", (corpus_id,),
        ).fetchall()
        source_hash = _hash(source_rows)
        content_hash = _hash([document_rows, chunk_rows])
        expected_summary = _hash([
            str(corpus_id), version.registry_digest, source_hash, content_hash,
            validation, coverage, version.retrieval_policy_version,
            version.coverage_policy_version,
        ])
        if (version.source_set_hash != source_hash or version.content_hash != content_hash
                or version.summary_hash != expected_summary):
            raise CorpusGovernanceDenied("SNAPSHOT_STALE")
        receipt = self.conn.execute(
            """SELECT r.* FROM rag_corpus_validation_receipts r
               JOIN grounding_corpus_events e ON e.id=r.validation_event_id
               WHERE r.corpus_id=%s AND e.corpus_version_id=%s
                 AND e.event_kind='validation_passed' AND e.summary_hash=%s
               FOR SHARE OF r,e""",
            (corpus_id, corpus_id, summary_hash),
        ).fetchone()
        if (receipt is None or version.validation_summary != validation
                or version.coverage_summary != coverage or receipt["summary_hash"] != summary_hash
                or receipt["admission_digest"] != admissions or receipt["coverage_digest"] != facets
                or receipt["review_policy_generation"] != generation
                or receipt.get("audit_policy_version", LEGACY_AUDIT_POLICY) != (
                    PURPOSE_PARTITION_POLICY if version.coverage_policy_version == PURPOSE_PARTITION_POLICY else LEGACY_AUDIT_POLICY)
                or receipt["partial_coverage"] != partial):
            raise CorpusGovernanceDenied("VALIDATION_STALE")
        return version

    def activate(self, corpus_id: UUID, *, expected_generation: int,
                 summary_hash: str, purpose: str, idempotency_key: str) -> CorpusEvent:
        self._transaction()
        with self.conn.transaction():
            self._verified(corpus_id, summary_hash=summary_hash, purpose=purpose)
            return self.repo.activate(corpus_id, expected_generation=expected_generation,
                                      summary_hash=summary_hash, idempotency_key=idempotency_key)

    def rollback(self, subject_id: str, target_corpus_id: UUID, *,
                 expected_generation: int, summary_hash: str, purpose: str,
                 idempotency_key: str) -> CorpusEvent:
        self._transaction()
        with self.conn.transaction():
            version = self._verified(target_corpus_id, summary_hash=summary_hash, purpose=purpose)
            if version.subject_id != subject_id:
                raise CorpusGovernanceDenied("SUBJECT_STALE")
            return self.repo.rollback(subject_id, target_corpus_id,
                                      expected_generation=expected_generation,
                                      idempotency_key=idempotency_key)

class PostgresQualificationAuthority:
    """C-only read projection for B's QualifiedCorpusAdapter; never consults staging.

    A failed current audit returns unknown (None), not a forged ready snapshot.
    Full Subject gaps remain gaps even when a query-only corpus is published.
    The supplied connection remains caller-owned; this port never commits.
    """

    def __init__(self, governance: CorpusGovernance) -> None:
        self.governance = governance

    def resolve(self, demand: LearningMaterialDemand) -> QualificationSnapshot | None:
        try:
            full = revalidate(demand, LearningMaterialDemand)
            service = self.governance
            service._transaction()
            if full.purpose == "assessment_evidence":
                return None  # No independently verified exact claim adapter in this port.
            active = service.repo.active(full.scope.subject_id)
            if active is None:
                return None
            version = service.repo.version(active.corpus_id)
            if version.state != "published" or version.summary_hash is None:
                return None
            service._verified(active.corpus_id, summary_hash=version.summary_hash, purpose=full.purpose,
                              consumption_read=True)
            locked_pointer = service.conn.execute(
                "SELECT corpus_version_id,generation,activation_event_id FROM grounding_active_corpora "
                "WHERE subject_id=%s FOR SHARE", (full.scope.subject_id,),
            ).fetchone()
            if (locked_pointer is None or locked_pointer["corpus_version_id"] != active.corpus_id
                    or locked_pointer["generation"] != active.generation
                    or locked_pointer["activation_event_id"] != active.activation_event_id):
                return None
            _, rows = service._rows(active.corpus_id, consumption_read=True)
            chunks = service.conn.execute(
                "SELECT document_id,facets_json FROM grounding_corpus_chunks WHERE corpus_version_id=%s",
                (active.corpus_id,),
            ).fetchall()
            per_doc: dict[str, set[str]] = {}
            for chunk in chunks:
                per_doc.setdefault(chunk["document_id"], set()).update(chunk["facets_json"])
            documents: list[QualifiedDocument] = []
            for row in rows:
                if full.purpose not in row["admitted_usages"]:
                    continue
                scope = SubjectScope(subject_id=version.subject_id,
                                     subject_version=version.subject_version,
                                     facets=tuple(row["review_facets"]))
                common = dict(
                    scope=scope, source_handle=row["source_handle"],
                    document_handle=row["document_handle"],
                    document_revision=row["document_revision"], document_hash=row["reviewed_hash"],
                    origin=row["origin"], reading_level=row["reading_level"],
                    allowed_usages=tuple(row["admitted_usages"]),
                    storage_receipt_id=row["storage_receipt_id"],
                    admission_receipt_id=row["receipt_handle"],
                    policy_generation=row["review_generation"],
                )
                assessment = SourceAssessment(**common, status="reviewed")
                authorization = SourceAuthorization(
                    **common, lineage_family=row["lineage_family"],
                    reviewed=True, revoked=False, readable=True,
                )
                documents.append(QualifiedDocument(
                    assessment=assessment, authorization=authorization,
                    covered_facets=tuple(sorted(per_doc.get(row["document_id"], set()))),
                ))
            return QualificationSnapshot(
                demand=full, receipt_id=f"qualification.{active.activation_event_id.hex}",
                corpus_id=active.corpus_id, subject_id=version.subject_id,
                subject_version=version.subject_version, active=True, state="published",
                synthetic_fixture=False, documents=tuple(documents),
            )
        except (CorpusGovernanceDenied, CorpusConflict, ValueError, TypeError, KeyError, Error):
            return None
