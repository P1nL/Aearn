"""Native public finite curriculum material from real exact active C authority."""
from __future__ import annotations

import hashlib
from typing import Any

from psycopg import Connection

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository, PostgresAssessmentClaimResolver
from app.services.grounding.autonomous.contracts import RagEvidenceBinding
from app.services.grounding.autonomous.finite_course_source_oracle import SOURCE_PROFILE_BY_TARGET
from app.services.grounding.autonomous.source_assessment_profiles import SourceAssessmentDenied
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.material_contracts_v2 import EvidenceCoordinate, digest
from app.services.grounding.public_course_contracts import PUBLIC_COURSE_ACTOR, PublicCourseEvidenceBindingV1, public_course_demand
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority


def create_public_course_material(conn: Connection[dict[str, Any]], *,
                               receipts: AssessmentReceiptRepository, authority: RagSourceAuthority,
                               claim_receipt_id: str, target_id: TargetId,
                               chunk_id: str, enabled: bool = False) -> PublicMaterialV2:
    """One exact active reviewed chunk, with no private user/track/draft identity.

    Native public source proofs only. This does not publish a learning item or
    bypass the identical concrete C/execution/current-authorization fences.
    """
    if (not enabled or type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn
            or type(authority) is not RagSourceAuthority or authority.connection is not conn
            or not isinstance(authority._claims, PostgresAssessmentClaimResolver)
            or authority._claims.repository is not receipts
            or authority._current.governance.source_reviews is None
            or authority._current.governance.source_reviews.assessment_receipts is not receipts):
        raise SourceAssessmentDenied("SOURCE_FACTORY_GATE_CLOSED")
    receipts.require_transaction()
    if target_id not in ("python-state-update-v1", "python-kc-binding-v1", "sqlite-predicate-order-v1"):
        raise SourceAssessmentDenied("SOURCE_PUBLIC_PROFILE_NOT_IMPLEMENTED")
    target = get_finite_course_target(target_id)
    demand = public_course_demand(target_id)
    # Same established lock order: version before review/evidence/current pointer.
    header = conn.execute(
        """SELECT v.id FROM grounding_corpus_versions v
           JOIN rag_corpus_admission_links l ON l.corpus_id=v.id
           JOIN rag_source_claim_receipts c ON c.admission_id=l.admission_id
           WHERE c.receipt_handle=%s ORDER BY v.created_at DESC LIMIT 2""", (claim_receipt_id,),
    ).fetchall()
    current_corpus = None
    for row in header:
        version = authority._current.governance.repo.version(row["id"],for_update=True)
        pointer = authority._current.governance.repo.active(version.subject_id)
        if pointer is not None and pointer.corpus_id == version.corpus_id:
            current_corpus = version
            break
    if current_corpus is None or current_corpus.state != "published" or not current_corpus.summary_hash:
        raise SourceAssessmentDenied("SOURCE_CORPUS_STALE")
    authority._current.governance._verified(current_corpus.corpus_id,
        summary_hash=current_corpus.summary_hash,purpose="assessment_evidence")
    p,capture,_ = receipts._find(claim_receipt_id)
    q = p.prepared
    if (q.demand != demand or q.consume_actor != PUBLIC_COURSE_ACTOR
            or q.profile_id != SOURCE_PROFILE_BY_TARGET[target_id]
            or current_corpus.subject_id != demand.scope.subject_id
            or current_corpus.subject_version != demand.scope.subject_version):
        raise SourceAssessmentDenied("SOURCE_DEMAND_STALE")
    claim = authority._claims.resolve(claim_receipt_id)
    if claim is None:
        raise SourceAssessmentDenied("SOURCE_CLAIM_STALE")
    rows = conn.execute(
        """SELECT c.*,active.generation AS active_generation,r.id AS source_review_id
           FROM grounding_corpus_chunks c
           JOIN grounding_active_corpora active ON active.corpus_version_id=c.corpus_version_id
           JOIN rag_corpus_admission_links l ON l.corpus_id=c.corpus_version_id AND l.document_id=c.document_id
           JOIN rag_source_admissions a ON a.id=l.admission_id
           JOIN rag_source_reviews r ON r.id=a.review_id
           WHERE c.corpus_version_id=%s AND l.admission_id=%s AND c.document_id=%s
           ORDER BY c.chunk_id FOR SHARE OF c,active,l,a,r""",
        (current_corpus.corpus_id,p.admission_id,q.document_handle),
    ).fetchall()
    matching = [r for r in rows if r["chunk_id"] == chunk_id
                and r["content"] in receipts.excerpts(p,capture)]
    if len(matching) != 1:
        raise SourceAssessmentDenied("SOURCE_CHUNK_STALE")
    chunk = matching[0]
    excerpt_hash = hashlib.sha256(chunk["content"].encode()).hexdigest()
    if chunk["chunk_hash"] != excerpt_hash or tuple(chunk["facets_json"]) != q.demand.scope.facets:
        raise SourceAssessmentDenied("SOURCE_CHUNK_STALE")
    binding = RagEvidenceBinding(scope=q.demand.scope,demand_hash=q.demand.demand_hash,
        purpose="assessment_evidence",source_handle=q.source_handle,document_handle=q.document_handle,
        document_revision=q.document_hash,document_hash=q.document_hash,
        admission_receipt_id=p.admission_handle,claim_receipt_id=p.claim_handle)
    exact_claim = VerifiedClaim(claim_hash=q.claim_hash,scope=q.demand.scope,binding=binding,
        claim_receipt_id=p.claim_handle,applicability=claim.applicability,execution_scope=q.execution_scope)
    coordinate = EvidenceCoordinate(binding=binding,subject_id=q.demand.scope.subject_id,
        corpus_version_id=str(current_corpus.corpus_id),active_generation=chunk["active_generation"],
        summary_hash=current_corpus.summary_hash,validation_hash=_hash(current_corpus.validation_summary),
        registry_digest=current_corpus.registry_digest,source_review_id=str(chunk["source_review_id"]),
        source_policy_id=q.policy_id,source_policy_generation=q.policy_generation,
        chunk_id=chunk["chunk_id"],chunk_hash=excerpt_hash,approved_excerpt_hash=excerpt_hash,
        retrieval_hash=digest(current_corpus.retrieval_policy_version),
        coverage_hash=_hash(current_corpus.coverage_summary),claim_id=p.claim_handle,
        claim_receipt_hash=canonical_hash(claim.model_dump(mode="json")),execution_receipt_id=p.execution_handle)
    values: dict[str, Any] = dict(target_id=target_id,target_definition_hash=target.definition_hash,
        course_goal_hash=digest({"goal":target.goal_text,"clauses":[c.definition_hash for c in target.clauses]}),
        demand=demand,purpose="assessment_evidence",evidence=(coordinate,))
    unsealed = PublicCourseEvidenceBindingV1.model_construct(**values,binding_digest="0"*64)
    whole = PublicCourseEvidenceBindingV1(**values,binding_digest=digest(unsealed.payload()))
    access = AccessRequest(demand_hash=q.demand.demand_hash,scope=q.demand.scope,
        purpose="assessment_evidence",actor_id=PUBLIC_COURSE_ACTOR,action="consume",policy_id=q.policy_id,
        policy_generation=q.policy_generation,budget=q.budget)
    material = PublicMaterialV2(binding=whole,access_request=access,exact_claims=(exact_claim,),excerpt=chunk["content"])
    authority.authorize(material)
    return material
