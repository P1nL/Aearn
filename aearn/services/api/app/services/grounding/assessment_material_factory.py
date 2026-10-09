"""Internal finite assessment material factory; not D selection/search or release."""
from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from psycopg import Connection

from app.services.grounding.autonomous.access_policy import AccessRequest, AutonomousGates
from app.services.grounding.autonomous.assessment_contracts import VerifiedClaim
from app.services.grounding.autonomous.assessment_receipt_repository import (
    AssessmentReceiptRepository, PostgresAssessmentClaimResolver,
    PostgresAssessmentConsumeAuthority, PostgresAssessmentExecutionResolver,
)
from app.services.grounding.autonomous.contracts import RagEvidenceBinding, revalidate
from app.services.grounding.autonomous.corpus_governance import CorpusGovernance, PostgresCorpusAuthority
from app.services.grounding.autonomous.source_assessment_profiles import (
    PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment, SourceAssessmentDenied,
)
from app.services.grounding.autonomous.source_review_repository import SourceReviewRepository
from app.services.grounding.corpus_repository import _hash
from app.services.grounding.current_authorization import CurrentAuthorization
from app.services.grounding.material_contracts_v2 import (
    DraftScope, EvidenceBindingV2, EvidenceCoordinate, digest,
)
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority
from app.services.learning.item_bank.contracts import canonical_hash

if TYPE_CHECKING:
    from app.services.grounding.autonomous.public_python_teaching_review import PublicPythonTeachingVerifier


def compose_assessment_authority(conn: Connection[dict[str, Any]], *,
                                 receipts: AssessmentReceiptRepository,
                                 teaching_verifier: PublicPythonTeachingVerifier | None = None,
                                 enabled: bool = False) -> tuple[CorpusGovernance, RagSourceAuthority]:
    """Formal confirmed consumption; original PUBLIC/default path unchanged."""
    return _compose(conn,receipts=receipts,teaching_verifier=teaching_verifier,enabled=enabled,preparation_owner=None)


def compose_assessment_preparation_authority(conn: Connection[dict[str, Any]], *, receipts: AssessmentReceiptRepository,
                                             owner: object, teaching_verifier: PublicPythonTeachingVerifier | None = None,
                                             enabled: bool = False) -> tuple[CorpusGovernance, RagSourceAuthority]:
    if not enabled:
        raise SourceAssessmentDenied("SOURCE_FACTORY_GATE_CLOSED")
    _preparation_owner(conn,receipts,owner)
    return _compose(conn,receipts=receipts,teaching_verifier=teaching_verifier,enabled=enabled,preparation_owner=owner)


def _preparation_owner(conn: Connection[dict[str, Any]], receipts: AssessmentReceiptRepository, owner: object) -> None:
    from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer

    if type(owner) is not AssessmentCourseSelectionProducer or owner.conn is not conn or owner.receipts is not receipts or not owner.enabled:
        raise SourceAssessmentDenied("SOURCE_PREPARATION_OWNER_REQUIRED")
    owner._guard()


def _compose(conn: Connection[dict[str, Any]], *, receipts: AssessmentReceiptRepository,
             teaching_verifier: PublicPythonTeachingVerifier | None, enabled: bool,
             preparation_owner: object | None) -> tuple[CorpusGovernance, RagSourceAuthority]:
    if not enabled or type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn:
        raise SourceAssessmentDenied("SOURCE_FACTORY_GATE_CLOSED")
    receipts.require_transaction()
    reviews = SourceReviewRepository(conn, verifier=receipts, assessment_receipts=receipts,
                                    teaching_verifier=teaching_verifier)
    governance = CorpusGovernance(conn, authority=PostgresCorpusAuthority(), source_reviews=reviews,
                                  isolated_operator_enabled=True)
    claims = PostgresAssessmentClaimResolver(receipts,preparation_owner=preparation_owner)
    current = CurrentAuthorization(conn, governance=governance,
        gates=AutonomousGates(evidence_consumer=True),
        authority_resolver=PostgresAssessmentConsumeAuthority(receipts,preparation_owner=preparation_owner), claim_resolver=claims,
        execution_resolver=PostgresAssessmentExecutionResolver(receipts,preparation_owner=preparation_owner), enabled=True)
    return governance, RagSourceAuthority(current, claims)


def create_assessment_material(conn: Connection[dict[str, Any]], *,
                               receipts: AssessmentReceiptRepository, authority: RagSourceAuthority,
                               claim_receipt_id: str, draft: DraftScope, node_id: str, goal_hash: str,
                               chunk_id: str | None = None, enabled: bool = False) -> PublicMaterialV2:
    return _create_material(conn,receipts=receipts,authority=authority,claim_receipt_id=claim_receipt_id,draft=draft,
                            node_id=node_id,goal_hash=goal_hash,chunk_id=chunk_id,enabled=enabled,preparation_owner=None)


def create_assessment_preparation_material(conn: Connection[dict[str, Any]], *, owner: object,
                                           receipts: AssessmentReceiptRepository, authority: RagSourceAuthority,
                                           claim_receipt_id: str, draft: DraftScope, node_id: str, goal_hash: str,
                                           chunk_id: str | None = None, enabled: bool = False) -> PublicMaterialV2:
    if not enabled:
        raise SourceAssessmentDenied("SOURCE_FACTORY_GATE_CLOSED")
    _preparation_owner(conn,receipts,owner)
    if type(authority._claims) is not PostgresAssessmentClaimResolver or authority._claims.preparation_owner is not owner:
        raise SourceAssessmentDenied("SOURCE_PREPARATION_OWNER_REQUIRED")
    return _create_material(conn,receipts=receipts,authority=authority,claim_receipt_id=claim_receipt_id,draft=draft,
                            node_id=node_id,goal_hash=goal_hash,chunk_id=chunk_id,enabled=enabled,preparation_owner=owner)


def _create_material(conn: Connection[dict[str, Any]], *, receipts: AssessmentReceiptRepository, authority: RagSourceAuthority,
                      claim_receipt_id: str, draft: DraftScope, node_id: str, goal_hash: str,
                      chunk_id: str | None, enabled: bool, preparation_owner: object | None) -> PublicMaterialV2:
    """Exact existing active corpus chunk -> true current authorization, no new grants.

    Call once per exact chunk for the two approved source units. Never join or
    rewrite them into a paragraph that was not captured/reviewed.
    """
    if (not enabled or type(receipts) is not AssessmentReceiptRepository or receipts.conn is not conn
            or type(authority) is not RagSourceAuthority or authority.connection is not conn
            or not isinstance(authority._claims, PostgresAssessmentClaimResolver)
            or authority._claims.repository is not receipts
            or authority._current.governance.source_reviews is None
            or authority._current.governance.source_reviews.assessment_receipts is not receipts):
        raise SourceAssessmentDenied("SOURCE_FACTORY_GATE_CLOSED")
    receipts.require_transaction()
    draft = revalidate(draft,DraftScope)
    translation = (receipts.private_provenance(claim_receipt_id,draft=draft,node_id=node_id,goal_hash=goal_hash,preparation_owner=preparation_owner)
                   if receipts.is_actual_d_handle(claim_receipt_id) else None)
    # Same established lock order: version before review/evidence/current pointer.
    header = ([{"id": translation.corpus_id}] if translation is not None else conn.execute(
        """SELECT v.id FROM grounding_corpus_versions v
           JOIN rag_corpus_admission_links l ON l.corpus_id=v.id
           JOIN rag_source_claim_receipts c ON c.admission_id=l.admission_id
           WHERE c.receipt_handle=%s ORDER BY v.created_at DESC LIMIT 2""", (claim_receipt_id,),
    ).fetchall())
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
    carrier = translation.public if translation is not None else p
    if isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)) and (
            q.actual_d.draft != draft or q.actual_d.node_id != node_id or q.actual_d.goal_hash != goal_hash):
        raise SourceAssessmentDenied("SOURCE_DEMAND_STALE")
    if (q.demand.plan_ref != "draft."+draft.draft_id or q.demand.node_ref != "node."+node_id
            or q.demand.draft_revision != draft.draft_version
            or current_corpus.subject_id != q.demand.scope.subject_id
            or current_corpus.subject_version != q.demand.scope.subject_version):
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
        (current_corpus.corpus_id,carrier.admission_id,carrier.prepared.document_handle),
    ).fetchall()
    matching = [r for r in rows if (chunk_id is None or r["chunk_id"] == chunk_id)
                and r["content"] in receipts.excerpts(p,capture)]
    if not matching:
        raise SourceAssessmentDenied("SOURCE_CHUNK_STALE")
    chunk = matching[0]
    excerpt_hash = hashlib.sha256(chunk["content"].encode()).hexdigest()
    if chunk["chunk_hash"] != excerpt_hash or tuple(chunk["facets_json"]) != q.demand.scope.facets:
        raise SourceAssessmentDenied("SOURCE_CHUNK_STALE")
    binding = RagEvidenceBinding(scope=q.demand.scope,demand_hash=q.demand.demand_hash,
        purpose="assessment_evidence",source_handle=q.source_handle,document_handle=carrier.prepared.document_handle,
        document_revision=q.document_hash,document_hash=q.document_hash,
        admission_receipt_id=carrier.admission_handle,claim_receipt_id=p.claim_handle)
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
    selection_digest = digest({"demand": q.demand.model_dump(mode="json"),
        "evidence": coordinate.model_dump(mode="json"),"draft": draft.model_dump(mode="json")})
    values: dict[str, Any] = dict(selection_handle="selection."+selection_digest[:32],selection_digest=selection_digest,
        draft=draft,node_id=node_id,goal_hash=goal_hash,purpose="assessment_evidence",evidence=(coordinate,))
    unsealed = EvidenceBindingV2.model_construct(**values,binding_digest="0"*64)
    whole = EvidenceBindingV2(**values,binding_digest=digest(unsealed.payload()))
    access = AccessRequest(demand_hash=q.demand.demand_hash,scope=q.demand.scope,
        purpose="assessment_evidence",actor_id=q.consume_actor,action="consume",policy_id=q.policy_id,
        policy_generation=q.policy_generation,budget=q.budget)
    material = PublicMaterialV2(binding=whole,access_request=access,exact_claims=(exact_claim,),excerpt=chunk["content"])
    authority.authorize(material)
    return material
