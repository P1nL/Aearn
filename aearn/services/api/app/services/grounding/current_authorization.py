"""D internal exact C-authority read and publication fence (never a release grant)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from psycopg import Connection
from psycopg.pq import TransactionStatus

from app.services.grounding.autonomous.access_policy import (
    AccessRequest, AuthorityResolver, AutonomousGates,
)
from app.services.grounding.autonomous.assessment_contracts import (
    ClaimReceiptResolver, ExecutionReceiptResolver, VerifiedClaim,
    authorize_assessment_claim,
)
from app.services.grounding.autonomous.contracts import SourceAssessment, SubjectScope, Usage, revalidate
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance
from app.services.grounding.autonomous.source_assessment import assess_document
from app.services.grounding.autonomous.source_policy import (
    SourceAuthorization, authorize_binding, check_source,
)
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.material_contracts_v2 import (
    EvidenceBindingV2, digest,
)


class EvidenceDenied(ValueError):
    """Closed reason only; never include SQL, capture text, or model payload."""


def project_covered_facets(demand_facets: Sequence[str],
                           chunk_facets: Sequence[Sequence[str]]) -> tuple[str, ...]:
    """Report only demanded facets actually covered by exact authorized chunks."""
    present = {facet for facets in chunk_facets for facet in facets}
    return tuple(facet for facet in demand_facets if facet in present)


@dataclass(frozen=True)
class _ScopedCurrentSource:
    """D-only narrowed view of a freshly verified full C grant, never a new grant."""

    assessment: SourceAssessment
    authorization: SourceAuthorization
    review_id: str
    review_receipt_hash: str
    original_authorization_digest: str

    def resolve(self, source_handle: str, document_handle: str) -> SourceAuthorization | None:
        if (source_handle, document_handle) == (
            self.authorization.source_handle, self.authorization.document_handle,
        ):
            return self.authorization
        return None


@dataclass(frozen=True)
class AuthorizationReceipt:
    """Short-lived same-transaction fact, not reusable as a public release token."""

    binding_digest: str
    purpose: Usage
    corpus_version_id: str
    active_generation: int
    source_policy_generations: tuple[tuple[str, int], ...]
    admission_receipt_ids: tuple[str, ...]
    original_source_digests: tuple[tuple[str, str, str, str], ...]
    exact_evidence_digest: str
    covered_facets: tuple[str, ...]
    checked_at: datetime


class CurrentAuthorization:
    """Bound service: one connection, one C governance, no hidden connection/commit."""

    def __init__(self, conn: Connection[dict[str, Any]], *, governance: CorpusGovernance,
                 gates: AutonomousGates | None = None,
                 authority_resolver: AuthorityResolver | None = None,
                 claim_resolver: ClaimReceiptResolver | None = None,
                 execution_resolver: ExecutionReceiptResolver | None = None,
                 enabled: bool = False) -> None:
        self.conn = conn
        self.governance = governance
        self.gates = gates
        self.authority_resolver = authority_resolver
        self.claim_resolver = claim_resolver
        self.execution_resolver = execution_resolver
        self.enabled = enabled

    def require_transaction(self) -> None:
        # Check the gate before any query, including current_database().
        if not self.enabled or self.gates is None or not self.gates.evidence_consumer:
            raise EvidenceDenied("GATE_CLOSED")
        if (self.conn.autocommit or self.conn.info.transaction_status != TransactionStatus.INTRANS
                or self.governance.conn is not self.conn):
            raise EvidenceDenied("TRANSACTION_REQUIRED")
        try:
            self.governance._transaction()  # C isolation and exact verifier, same conn.
            isolation = self.conn.execute("SHOW transaction_isolation").fetchone()
            if isolation is None or isolation["transaction_isolation"] != "read committed":
                raise EvidenceDenied("TRANSACTION_REQUIRED")
            read_only = self.conn.execute("SHOW transaction_read_only").fetchone()
            if read_only is None or read_only["transaction_read_only"] != "off":
                raise EvidenceDenied("TRANSACTION_REQUIRED")
        except EvidenceDenied:
            raise
        except Exception as exc:
            raise EvidenceDenied("AUTHORITY_MISSING") from exc

    def _source_view(self, source_handle: str, document_handle: str,
                     scope: SubjectScope, purpose: Usage) -> _ScopedCurrentSource | None:
        """Narrow an already current, complete C review; never widen its grant."""
        reviews = self.governance.source_reviews
        if reviews is None:
            return None
        current = reviews.resolve(source_handle, document_handle)
        if current is None:
            return None
        decision = assess_document(current.facts, resolver=reviews, now=self._clock())
        original = decision.assessment
        authorization = decision.authorization
        if not decision.allowed or original is None or authorization is None:
            return None
        approved = current.facts.covered_facets
        original_digest = digest(authorization.model_dump(mode="json"))
        original_view = _ScopedCurrentSource(
            original, authorization, str(current.facts.review_id),
            current.facts.review_receipt_hash, original_digest,
        )
        if (original.scope != authorization.scope
                or original.scope != current.facts.coordinate.scope
                or scope.subject_id != original.scope.subject_id
                or scope.subject_version != original.scope.subject_version
                or not set(scope.facets) <= set(original.scope.facets)
                or not set(scope.facets) <= set(approved)
                or not check_source(original, purpose=purpose,
                                    resolver=original_view).allowed):
            return None
        # Both A objects are projected from the exact original C decision. The
        # original C grant/receipt is never rewritten or persisted as a new one.
        scoped_assessment = SourceAssessment.model_validate({
            **original.model_dump(mode="python"), "scope": scope,
        })
        scoped_authorization = SourceAuthorization.model_validate({
            **authorization.model_dump(mode="python"), "scope": scope,
        })
        return _ScopedCurrentSource(
            scoped_assessment, scoped_authorization,
            str(current.facts.review_id), current.facts.review_receipt_hash, original_digest,
        )

    def _current(self, binding: EvidenceBindingV2, purpose: Usage, request: AccessRequest,
                 exact_item_claims: Sequence[VerifiedClaim]) -> AuthorizationReceipt:
        item = revalidate(binding, EvidenceBindingV2)
        if (item.purpose != purpose or request.action != "consume"
                or request.purpose != purpose or not item.evidence):
            raise EvidenceDenied("BINDING_MISMATCH")
        if purpose == "assessment_evidence" and (
            self.claim_resolver is None or any(c.execution_receipt_id for c in item.evidence)
            and self.execution_resolver is None
        ):
            raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
        coords = item.evidence
        corpus_ids = {c.corpus_version_id for c in coords}
        if len(corpus_ids) != 1:
            raise EvidenceDenied("BINDING_MISMATCH")
        corpus_id = UUID(next(iter(corpus_ids)))
        try:
            # C's version -> links/docs/review/admission -> policy/capture/grant/root lock order.
            version = self.governance.repo.version(corpus_id, for_update=True)
            if (version.summary_hash is None or version.state != "published"
                    or version.subject_id != request.scope.subject_id
                    or version.subject_version != request.scope.subject_version):
                raise EvidenceDenied("CORPUS_GENERATION_STALE")
            self.governance._verified(corpus_id, summary_hash=version.summary_hash,
                                      purpose=purpose)
            rows = self.conn.execute(
                """SELECT c.chunk_id,c.chunk_hash,c.content,c.facets_json,c.document_id,
                          d.document_hash,l.admission_id,r.id AS review_id,
                          r.policy_id,r.policy_generation,r.review_receipt_hash,a.receipt_handle
                   FROM grounding_corpus_chunks c
                   JOIN grounding_corpus_documents d ON d.corpus_version_id=c.corpus_version_id
                        AND d.document_id=c.document_id
                   JOIN rag_corpus_admission_links l ON l.corpus_id=c.corpus_version_id
                        AND l.document_id=c.document_id
                   JOIN rag_source_admissions a ON a.id=l.admission_id
                   JOIN rag_source_reviews r ON r.id=a.review_id
                   WHERE c.corpus_version_id=%s ORDER BY c.chunk_id
                   FOR SHARE OF c,d,l,a,r""", (corpus_id,),
            ).fetchall()
            by_chunk = {row["chunk_id"]: row for row in rows}
            reviews = self.governance.source_reviews
            if reviews is None:
                raise EvidenceDenied("AUTHORITY_MISSING")
            original_sources: set[tuple[str, str, str, str]] = set()
            expected_claims = {c.binding.claim_receipt_id for c in coords if c.binding.claim_receipt_id}
            if purpose == "assessment_evidence" and (
                len(exact_item_claims) != len(expected_claims)
                or {claim.claim_receipt_id for claim in exact_item_claims} != expected_claims
            ):
                raise EvidenceDenied("CLAIM_VERIFICATION_REQUIRED")
            for coord in coords:
                if (coord.binding.purpose != purpose or coord.binding.scope != request.scope
                        or coord.binding.demand_hash != request.demand_hash
                        or coord.corpus_version_id != str(corpus_id)
                        or coord.summary_hash != version.summary_hash
                        or coord.subject_id != version.subject_id
                        or coord.registry_digest != version.registry_digest
                        or coord.validation_hash != _hash(version.validation_summary)
                        or coord.retrieval_hash != digest(version.retrieval_policy_version)
                        or coord.coverage_hash != _hash(version.coverage_summary)
                        or coord.chunk_id not in by_chunk):
                    raise EvidenceDenied("BINDING_MISMATCH")
                row = by_chunk[coord.chunk_id]
                if (row["document_id"] != coord.binding.document_handle
                        or row["document_hash"] != coord.binding.document_hash
                        or row["chunk_hash"] != coord.chunk_hash
                        or str(row["review_id"]) != coord.source_review_id
                        or row["policy_id"] != coord.source_policy_id
                        or row["policy_generation"] != coord.source_policy_generation
                        or row["receipt_handle"] != coord.binding.admission_receipt_id
                        or hashlib.sha256(row["content"].encode()).hexdigest() != coord.approved_excerpt_hash
                        or not set(row["facets_json"]) & set(request.scope.facets)):
                    raise EvidenceDenied("BINDING_MISMATCH")
                source = self._source_view(
                    coord.binding.source_handle, coord.binding.document_handle,
                    request.scope, purpose,
                )
                if source is None or source.review_receipt_hash != by_chunk[coord.chunk_id]["review_receipt_hash"]:
                    raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
                original_sources.add((coord.binding.source_handle,
                    coord.binding.document_handle, source.review_receipt_hash,
                    source.original_authorization_digest))
                if purpose == "assessment_evidence":
                    claim = next(c for c in exact_item_claims
                                 if c.claim_receipt_id == coord.binding.claim_receipt_id)
                    if claim.binding != coord.binding:
                        raise EvidenceDenied("BINDING_MISMATCH")
                    allowed = authorize_assessment_claim(
                        claim, source.assessment, request=request, gates=self.gates,
                        authority_resolver=self.authority_resolver,
                        source_resolver=source, claim_resolver=self.claim_resolver,
                        execution_resolver=self.execution_resolver, now=self._clock(),
                    ).allowed
                else:
                    allowed = authorize_binding(
                        coord.binding, source.assessment, request=request, gates=self.gates,
                        authority_resolver=self.authority_resolver,
                        source_resolver=source, now=self._clock(),
                    ).allowed
                if not allowed:
                    raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
            # Last mutable authority: pointer. Do not lock it before the version.
            pointer = self.conn.execute(
                "SELECT corpus_version_id,generation,activation_event_id "
                "FROM grounding_active_corpora WHERE subject_id=%s FOR SHARE",
                (version.subject_id,),
            ).fetchone()
            if (pointer is None or pointer["corpus_version_id"] != corpus_id
                    or any(c.active_generation != pointer["generation"] for c in coords)):
                raise EvidenceDenied("CORPUS_GENERATION_STALE")
            # A fresh DB clock after all waits, not transaction_timestamp() or Python time.
            checked_at = self._clock()
            self.governance._verified(corpus_id, summary_hash=version.summary_hash,
                                      purpose=purpose)
            for coord in coords:
                source = self._source_view(
                    coord.binding.source_handle, coord.binding.document_handle,
                    request.scope, purpose,
                )
                if source is None or source.review_receipt_hash != by_chunk[coord.chunk_id]["review_receipt_hash"]:
                    raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
                original_sources.add((coord.binding.source_handle,
                    coord.binding.document_handle, source.review_receipt_hash,
                    source.original_authorization_digest))
                if purpose == "assessment_evidence":
                    claim = next(c for c in exact_item_claims
                                 if c.claim_receipt_id == coord.binding.claim_receipt_id)
                    allowed = authorize_assessment_claim(
                        claim, source.assessment, request=request, gates=self.gates,
                        authority_resolver=self.authority_resolver,
                        source_resolver=source, claim_resolver=self.claim_resolver,
                        execution_resolver=self.execution_resolver, now=checked_at,
                    ).allowed
                else:
                    allowed = authorize_binding(
                        coord.binding, source.assessment, request=request, gates=self.gates,
                        authority_resolver=self.authority_resolver,
                        source_resolver=source, now=checked_at,
                    ).allowed
                if not allowed:
                    raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE")
            return AuthorizationReceipt(
                binding_digest=item.binding_digest, purpose=purpose,
                corpus_version_id=str(corpus_id), active_generation=pointer["generation"],
                source_policy_generations=tuple(sorted({
                    (c.source_policy_id, c.source_policy_generation) for c in coords
                })),
                admission_receipt_ids=tuple(sorted({
                    c.binding.admission_receipt_id for c in coords
                })),
                original_source_digests=tuple(sorted(original_sources)),
                exact_evidence_digest=digest([c.model_dump(mode="json") for c in coords]),
                covered_facets=project_covered_facets(
                    request.scope.facets,
                    [by_chunk[coord.chunk_id]["facets_json"] for coord in coords],
                ),
                checked_at=checked_at,
            )
        except EvidenceDenied:
            raise
        except Exception as exc:
            raise EvidenceDenied("SOURCE_AUTHORIZATION_STALE") from exc

    def _clock(self) -> datetime:
        row = self.conn.execute("SELECT clock_timestamp() AS now").fetchone()
        if row is None:
            raise EvidenceDenied("AUTHORITY_MISSING")
        return row["now"]

    def check_current_authorization(self, binding: EvidenceBindingV2, purpose: Usage, *,
                                    request: AccessRequest,
                                    exact_item_claims: Sequence[VerifiedClaim] = ()) -> AuthorizationReceipt:
        self.require_transaction()
        return self._current(binding, purpose, request, exact_item_claims)

    def assert_publication_fence(self, binding: EvidenceBindingV2, *,
                                 exact_item_claims: Sequence[VerifiedClaim],
                                 expected_generation: int,
                                 request: AccessRequest) -> AuthorizationReceipt:
        self.require_transaction()
        receipt = self._current(binding, binding.purpose, request, exact_item_claims)
        if receipt.active_generation != expected_generation:
            raise EvidenceDenied("CORPUS_GENERATION_STALE")
        return receipt


def check_current_authorization(conn: Connection[dict[str, Any]], binding: EvidenceBindingV2,
                                purpose: Usage, *, governance: CorpusGovernance,
                                request: AccessRequest, gates: AutonomousGates | None = None,
                                authority_resolver: AuthorityResolver | None = None,
                                claim_resolver: ClaimReceiptResolver | None = None,
                                execution_resolver: ExecutionReceiptResolver | None = None,
                                enabled: bool = False) -> AuthorizationReceipt:
    return CurrentAuthorization(
        conn, governance=governance, gates=gates, authority_resolver=authority_resolver,
        claim_resolver=claim_resolver, execution_resolver=execution_resolver,
        enabled=enabled,
    ).check_current_authorization(binding, purpose, request=request)


def assert_publication_fence(conn: Connection[dict[str, Any]], binding: EvidenceBindingV2, *,
                             governance: CorpusGovernance, request: AccessRequest,
                             exact_item_claims: Sequence[VerifiedClaim], expected_generation: int,
                             gates: AutonomousGates | None = None,
                             authority_resolver: AuthorityResolver | None = None,
                             claim_resolver: ClaimReceiptResolver | None = None,
                             execution_resolver: ExecutionReceiptResolver | None = None,
                             enabled: bool = False) -> AuthorizationReceipt:
    return CurrentAuthorization(
        conn, governance=governance, gates=gates, authority_resolver=authority_resolver,
        claim_resolver=claim_resolver, execution_resolver=execution_resolver,
        enabled=enabled,
    ).assert_publication_fence(
        binding, exact_item_claims=exact_item_claims, expected_generation=expected_generation,
        request=request,
    )
