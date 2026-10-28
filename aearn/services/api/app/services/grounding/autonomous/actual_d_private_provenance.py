"""Private actual-D claim -> independently current PUBLIC source carrier.

No caller mapping IDs, rewritten signed payload, corpus registration or new
permission owner. Identity discovery is unlocked; original corpus locks precede
both signed-proof/current-source checks. Every replay reconstructs the mapping.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

from psycopg.types.json import Jsonb

from app.services.grounding.corpus_repository import CorpusRepository
from app.services.grounding.material_contracts_v2 import DraftScope

from .actual_d_lifecycle import ACTUAL_D_FORMAT, lifecycle_installed
from .source_assessment_profiles import (
    PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment,
    PreparedSQLiteSourceAssessment, SignedSourceAssessment, SourceAssessmentDenied,
    SourceAssessmentPayload, storage_profile_id,
)

if TYPE_CHECKING:
    from .assessment_receipt_repository import AssessmentReceiptRepository


@dataclass(frozen=True)
class PrivatePublicProvenance:
    private: SourceAssessmentPayload
    public: SourceAssessmentPayload
    corpus_id: UUID
    generation: int
    chunks: tuple[dict[str, Any], ...]


def require_private_provenance(repo: AssessmentReceiptRepository) -> None:
    repo.require_transaction()
    if not repo.actual_d_private_provenance_enabled or not lifecycle_installed(repo.conn):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_GATE_CLOSED")
    row = repo.conn.execute(
        "SELECT to_regclass('public.rag_actual_d_private_provenance') IS NOT NULL AS installed",
    ).fetchone()
    if row is None or row.get("installed") is not True:
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_NOT_INSTALLED")


def actual_handle(repo: AssessmentReceiptRepository, handle: str, *, execution: bool = False) -> bool:
    if not repo.enabled or not repo.actual_d_private_provenance_enabled:
        return False
    repo.require_transaction()
    column = "execution_handle" if execution else "claim_handle"
    row = repo.conn.execute(
        f"SELECT id FROM rag_assessment_source_evidence WHERE {column}=%s AND signed_proof->'payload'->>'format'=%s",
        (handle, ACTUAL_D_FORMAT),
    ).fetchone()
    return row is not None


def _same_source(private: SourceAssessmentPayload, public: SourceAssessmentPayload) -> None:
    q, original = private.prepared, public.prepared
    if (not isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
            or public.format == ACTUAL_D_FORMAT or original.profile_id != storage_profile_id(q)
            or (q.capture_id, q.source_handle, q.document_hash, q.policy_id, q.policy_generation, q.budget.root_id,
                q.provenance_digest, q.storage_receipt_id, q.license_id, q.execution_scope, q.spans, q.demand.scope)
            != (original.capture_id, original.source_handle, original.document_hash, original.policy_id,
                original.policy_generation, original.budget.root_id, original.provenance_digest,
                original.storage_receipt_id, original.license_id, original.execution_scope, original.spans, original.demand.scope)
            or q.demand.purpose != original.demand.purpose or q.demand.purpose != "assessment_evidence"):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_MISMATCH")
    if isinstance(q, PreparedActualDSQLiteSourceAssessment):
        if not isinstance(original, PreparedSQLiteSourceAssessment) or q.companions != original.companions:
            # Expiry/preparation instants may legitimately differ, but all actual
            # capture/grant/provenance/span coordinates must be identical.
            if not isinstance(original, PreparedSQLiteSourceAssessment) or tuple(
                c.model_dump(mode="json", exclude={"authority_expires_at", "budget"}) for c in q.companions
            ) != tuple(c.model_dump(mode="json", exclude={"authority_expires_at", "budget"}) for c in original.companions) or tuple(
                c.budget.model_dump(mode="json", exclude={"expires_at"}) for c in q.companions
            ) != tuple(c.budget.model_dump(mode="json", exclude={"expires_at"}) for c in original.companions):
                raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_MISMATCH")


def reconstruct_private_provenance(repo: AssessmentReceiptRepository, handle: str, *, execution: bool = False,
                                   draft: DraftScope | None = None, node_id: str | None = None,
                                   goal_hash: str | None = None, preparation_owner: object | None = None) -> PrivatePublicProvenance:
    require_private_provenance(repo)
    # Caller is already INTRANS. This is a savepoint, never an outer commit;
    # expiry/lock/replay denial cannot leave a newly inserted association behind.
    with repo.conn.transaction():
        return _reconstruct(repo,handle,execution=execution,draft=draft,node_id=node_id,goal_hash=goal_hash,preparation_owner=preparation_owner)


def _phase(repo: AssessmentReceiptRepository, q: PreparedActualDSourceAssessment | PreparedActualDSQLiteSourceAssessment,
           owner: object | None) -> None:
    expected = "confirmed"
    if owner is not None:
        from app.services.grounding.assessment_course_selection import AssessmentCourseSelectionProducer

        if type(owner) is not AssessmentCourseSelectionProducer or owner.conn is not repo.conn or owner.receipts is not repo or not owner.enabled:
            raise SourceAssessmentDenied("SOURCE_PREPARATION_OWNER_REQUIRED")
        owner._guard()
        expected = "draft_ready"
    scope = q.actual_d.draft
    row = repo.conn.execute("SELECT status,current_draft_id FROM tutor_learning_plan_sessions WHERE id=%s AND user_id=%s FOR SHARE NOWAIT",
                            (scope.session_id,scope.user_id)).fetchone()
    if row is None or row["status"] != expected or str(row["current_draft_id"]) != scope.draft_id:
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PHASE_DENIED")


def _reconstruct(repo: AssessmentReceiptRepository, handle: str, *, execution: bool,
                 draft: DraftScope | None, node_id: str | None, goal_hash: str | None,
                 preparation_owner: object | None) -> PrivatePublicProvenance:
    column = "execution_handle" if execution else "claim_handle"
    head = repo.conn.execute(
        f"SELECT id,signed_proof FROM rag_assessment_source_evidence WHERE {column}=%s", (handle,),
    ).fetchone()
    if head is None:
        raise SourceAssessmentDenied("SOURCE_EVIDENCE_MISSING")
    untrusted = SignedSourceAssessment.model_validate_json(json.dumps(head["signed_proof"]))
    q = untrusted.payload.prepared
    if not isinstance(q, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment)):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_MISMATCH")
    if (draft is not None and q.actual_d.draft != draft or node_id is not None and q.actual_d.node_id != node_id
            or goal_hash is not None and q.actual_d.goal_hash != goal_hash):
        raise SourceAssessmentDenied("SOURCE_DEMAND_STALE")
    candidates = repo.conn.execute(
        """SELECT e.id AS public_evidence_id,v.id AS corpus_id,active.generation
           FROM rag_assessment_source_evidence e JOIN rag_source_reviews r ON r.assessment_evidence_id=e.id
           JOIN rag_source_admissions a ON a.review_id=r.id
           JOIN rag_corpus_admission_links l ON l.admission_id=a.id
           JOIN grounding_corpus_versions v ON v.id=l.corpus_id
           JOIN grounding_active_corpora active ON active.corpus_version_id=v.id
           WHERE e.capture_id=%s AND e.document_hash=%s AND e.profile_id=%s AND e.private_user_id IS NULL
             AND e.signed_proof->'payload'->>'format' IN ('aearn.rag.fresh-assessment-source.v1','aearn.rag.fresh-assessment-source.v2')
             AND e.revoked_at IS NULL AND e.issued_at<=clock_timestamp() AND e.expires_at>clock_timestamp()
             AND v.state='published' AND a.active AND a.revoked_at IS NULL
             AND a.allowed_usages=ARRAY['assessment_evidence']::text[]
           ORDER BY e.id LIMIT 2""", (q.capture_id, q.document_hash, storage_profile_id(q)),
    ).fetchall()
    if len(candidates) != 1:
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PUBLIC_CARRIER_MISSING")
    candidate = candidates[0]
    # Identity-only hint before the version lock, never current authority. A
    # stored association is immutable and is fully reread/compared below.
    # First materialization remains a mutation with the original UPDATE lock.
    existing = repo.conn.execute(
        "SELECT private_evidence_id FROM rag_actual_d_private_provenance WHERE private_evidence_id=%s",
        (head["id"],),
    ).fetchone()
    corpus_repo = CorpusRepository(repo.conn)
    corpus = (corpus_repo.version(candidate["corpus_id"], for_share=True) if existing is not None
              else corpus_repo.version(candidate["corpus_id"], for_update=True))
    private, capture, private_row = repo._load(head["id"])
    aq = private.prepared
    assert isinstance(aq, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
    _phase(repo,aq,preparation_owner)
    public, public_capture, public_row = repo._load(candidate["public_evidence_id"])
    _same_source(private, public)
    if (capture != public_capture or corpus.state != "published" or not corpus.summary_hash
            or corpus.subject_id != private.prepared.demand.scope.subject_id
            or corpus.subject_version != private.prepared.demand.scope.subject_version
            or public_row.get("private_user_id") is not None):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_MISMATCH")
    # Original PUBLIC proof/corpus/active-pointer check; never upgraded teaching.
    repo._active(public, public_capture)
    original = public.prepared
    chunks = repo.conn.execute(
        """SELECT c.*,active.generation AS active_generation,r.id AS source_review_id,a.receipt_handle,
                     r.policy_id,r.policy_generation,r.review_receipt_hash
           FROM grounding_corpus_chunks c JOIN grounding_active_corpora active ON active.corpus_version_id=c.corpus_version_id
           JOIN rag_corpus_admission_links l ON l.corpus_id=c.corpus_version_id AND l.document_id=c.document_id
           JOIN rag_source_admissions a ON a.id=l.admission_id JOIN rag_source_reviews r ON r.id=a.review_id
           WHERE c.corpus_version_id=%s AND l.admission_id=%s AND c.document_id=%s
           ORDER BY c.chunk_id FOR SHARE OF c,active,l,a,r""",
        (corpus.corpus_id, public.admission_id, original.document_handle),
    ).fetchall()
    expected = repo.excerpts(private, capture)
    if (not chunks or {c["content"] for c in chunks} != set(expected)
            or any(c["active_generation"] != candidate["generation"] or c["active_generation"] < 1
                   or tuple(c["facets_json"]) != private.prepared.demand.scope.facets for c in chunks)):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_SPANS_STALE")
    if any(c["chunk_hash"] != hashlib.sha256(c["content"].encode()).hexdigest() for c in chunks):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_SPANS_STALE")
    aq = private.prepared
    assert isinstance(aq, (PreparedActualDSourceAssessment, PreparedActualDSQLiteSourceAssessment))
    values = dict(private_evidence_id=private.evidence_id, user_id=UUID(aq.actual_d.draft.user_id), epoch=aq.actual_d.user_epoch,
        draft_id=UUID(aq.actual_d.draft.draft_id), node_id=aq.actual_d.node_id, goal_hash=aq.actual_d.goal_hash,
        target_id=aq.actual_d.target_id, public_evidence_id=public.evidence_id, corpus_id=corpus.corpus_id,
        generation=candidate["generation"], document_id=original.document_handle,
        document_hash=aq.document_hash, private_proof_hash=private_row["proof_hash"], public_proof_hash=public_row["proof_hash"],
        chunks_json=[dict(chunk_id=c["chunk_id"], chunk_hash=c["chunk_hash"]) for c in chunks])
    stored = repo.conn.execute("SELECT * FROM rag_actual_d_private_provenance WHERE private_evidence_id=%s FOR SHARE",
                              (private.evidence_id,)).fetchone()
    if stored is None:
        if existing is not None:
            # A concurrently removed association cannot be recreated on a
            # consumption path (including an original private purge boundary).
            raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_STALE")
        repo.conn.execute("""INSERT INTO rag_actual_d_private_provenance
            (private_evidence_id,user_id,epoch,draft_id,node_id,goal_hash,target_id,public_evidence_id,corpus_id,
             generation,document_id,document_hash,private_proof_hash,public_proof_hash,chunks_json)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(private_evidence_id) DO NOTHING""",
            (*tuple(values.values())[:-1], Jsonb(values["chunks_json"])))
        stored = repo.conn.execute("SELECT * FROM rag_actual_d_private_provenance WHERE private_evidence_id=%s FOR SHARE",
                                  (private.evidence_id,)).fetchone()
    if stored is None or any(stored[k] != v for k, v in values.items()):
        raise SourceAssessmentDenied("SOURCE_PRIVATE_PROVENANCE_STALE")
    # Fresh final clocks after pointer/source/bridge lock waits, both proofs.
    clock = repo._clock()
    if not max(private.issued_at, public.issued_at) <= clock < min(private.expires_at, public.expires_at):
        raise SourceAssessmentDenied("SOURCE_AUTHORITY_STALE")
    return PrivatePublicProvenance(private, public, corpus.corpus_id, candidate["generation"], tuple(chunks))
