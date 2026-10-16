"""Exact historical-publication source continuity; never renew an old receipt."""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt
from app.services.grounding.autonomous.confirmed_source_successor import same_supported_source
from app.services.grounding.autonomous.source_assessment_profiles import (
    PreparedSourceAssessment, SignedSourceAssessment, storage_profile_id, verify_source_assessment,
)
from app.services.grounding.public_course_contracts import PUBLIC_COURSE_ACTOR, PublicCourseEvidenceBindingV1
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2, SourceReceiptV2
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError

if TYPE_CHECKING:
    from app.services.grounding.autonomous.assessment_receipt_repository import AssessmentReceiptRepository


def require_material_continuity(old: PublicMaterialV2, new: PublicMaterialV2) -> None:
    """Compare complete obligations, not just excerpt or target labels."""
    if (type(old.binding) is not PublicCourseEvidenceBindingV1
            or type(new.binding) is not PublicCourseEvidenceBindingV1
            or old.binding.model_dump(exclude={"evidence", "binding_digest"})
            != new.binding.model_dump(exclude={"evidence", "binding_digest"})
            or old.access_request.model_dump(exclude={"policy_id", "policy_generation", "budget"})
            != new.access_request.model_dump(exclude={"policy_id", "policy_generation", "budget"})
            or old.excerpt != new.excerpt
            or old.classification != new.classification
            or len(old.binding.evidence) != 1 or len(new.binding.evidence) != 1
            or len(old.exact_claims) != 1 or len(new.exact_claims) != 1):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_OBLIGATIONS_CHANGED")
    a, b = old.exact_claims[0], new.exact_claims[0]
    if (a.model_dump(exclude={"binding", "claim_receipt_id", "claim_hash"})
            != b.model_dump(exclude={"binding", "claim_receipt_id", "claim_hash"})
            or a.binding.model_dump(exclude={"document_handle", "document_revision", "document_hash", "admission_receipt_id", "claim_receipt_id"})
            != b.binding.model_dump(exclude={"document_handle", "document_revision", "document_hash", "admission_receipt_id", "claim_receipt_id"})
            or old.binding.evidence[0].approved_excerpt_hash != new.binding.evidence[0].approved_excerpt_hash
            or old.binding.evidence[0].subject_id != new.binding.evidence[0].subject_id):
        raise PipelineRepositoryError("CURRENT_PACK_SOURCE_OBLIGATIONS_CHANGED")


def require_signed_access(material: PublicMaterialV2, prepared: PreparedSourceAssessment, *, at: datetime) -> None:
    """Exact original factory access metadata at the caller's proven time.

    The caller verifies OLD signature at published_at or resolves NEW current C.
    This pure binding check does not authorize expired source access now.
    """
    expected = AccessRequest(demand_hash=prepared.demand.demand_hash, scope=prepared.demand.scope,
        purpose="assessment_evidence", actor_id=PUBLIC_COURSE_ACTOR, action="consume",
        policy_id=prepared.policy_id, policy_generation=prepared.policy_generation, budget=prepared.budget)
    if (prepared.consume_actor != PUBLIC_COURSE_ACTOR or material.access_request != expected
            or at.tzinfo is None or not prepared.prepared_at <= at < prepared.authority_expires_at
            or at >= prepared.budget.expires_at):
        raise PipelineRepositoryError("CURRENT_PACK_SIGNED_ACCESS_METADATA_CHANGED")


def require_historical_material(repo: AssessmentReceiptRepository, material: PublicMaterialV2,
                                receipt: SourceReceiptV2, *, published_at: datetime,
                                new: PublicMaterialV2) -> None:
    require_material_continuity(material, new)
    old_claim = material.exact_claims[0]
    row = repo.conn.execute(
        "SELECT e.*,r.status,r.quality_code,r.reading_fit,r.version_fit,r.technical_status,r.conflict_status,r.known_error,"
        "r.review_receipt_hash,r.quality_evidence_hash,a.receipt_handle AS admission_handle,"
        "a.active,a.revoked_at AS admission_revoked,c.revoked_at AS claim_revoked,"
        "c.verification_receipt_hash,c.applicability,c.claim_hash AS actual_claim_hash,"
        "c.execution_scope_json,c.source_document_hash "
        "FROM rag_assessment_source_evidence e JOIN rag_source_reviews r ON r.assessment_evidence_id=e.id "
        "JOIN rag_source_admissions a ON a.review_id=r.id "
        "JOIN rag_source_claim_receipts c ON c.assessment_evidence_id=e.id AND c.admission_id=a.id "
        "WHERE e.claim_handle=%s AND c.receipt_handle=e.claim_handle FOR SHARE OF e,r,a,c",
        (old_claim.claim_receipt_id,),
    ).fetchone()
    if row is None:
        raise PipelineRepositoryError("CURRENT_PACK_HISTORICAL_SOURCE_MISSING")
    signed = SignedSourceAssessment.model_validate_json(json.dumps(row["signed_proof"]))
    p = verify_source_assessment(signed, service_keys=repo.service_keys, now=published_at)
    q = p.prepared
    require_signed_access(material, q, at=published_at)
    coordinate = material.binding.evidence[0]
    digest = canonical_hash(signed.model_dump(mode="json"))
    expected = ClaimEvidenceReceipt(receipt_id=p.claim_handle, demand_hash=q.demand.demand_hash,
        purpose="assessment_evidence", admission_receipt_id=p.admission_handle, claim_hash=q.claim_hash,
        scope=q.demand.scope, source_handle=q.source_handle, document_handle=q.document_handle,
        document_revision=q.document_hash, document_hash=q.document_hash, applicability=row["applicability"],
        method="isolated_execution", execution_receipt_id=p.execution_handle, execution_scope=q.execution_scope,
        verified=True, revoked=False)
    if (row["revoked_at"] is not None or row["admission_revoked"] is not None
            or row["claim_revoked"] is not None or row["active"] is not True or row["quality_code"] != "QUALIFIED"
            or (row["status"],row["reading_fit"],row["version_fit"],row["technical_status"],row["conflict_status"],row["known_error"])
            != ("reviewed","suitable","current","correct","resolved","absent")
            or any(row[k] != digest for k in ("proof_hash","review_receipt_hash","quality_evidence_hash","verification_receipt_hash"))
            or (row["id"],row["claim_handle"],row["admission_handle"],row["actual_claim_hash"],row["source_document_hash"])
            != (p.evidence_id,p.claim_handle,p.admission_handle,q.claim_hash,q.document_hash)
            or (row["capture_id"],row["source_handle"],row["document_handle"],row["document_hash"],
                row["policy_id"],row["policy_generation"],row["root_id"],row["profile_id"],row["service_key_id"],row["issued_at"],row["expires_at"])
            != (q.capture_id,q.source_handle,q.document_handle,q.document_hash,q.policy_id,q.policy_generation,
                q.budget.root_id,storage_profile_id(q),signed.service_key_id,p.issued_at,p.expires_at)
            or old_claim.binding != coordinate.binding or old_claim.claim_hash != q.claim_hash
            or (old_claim.binding.source_handle,old_claim.binding.document_handle,old_claim.binding.document_revision,
                old_claim.binding.document_hash,old_claim.binding.admission_receipt_id,old_claim.binding.demand_hash,
                old_claim.binding.scope,old_claim.binding.purpose)
            != (q.source_handle,q.document_handle,q.document_hash,q.document_hash,p.admission_handle,
                q.demand.demand_hash,q.demand.scope,"assessment_evidence")
            or old_claim.scope != q.demand.scope or old_claim.execution_scope != q.execution_scope
            or old_claim.applicability != expected.applicability
            or coordinate.claim_receipt_hash != canonical_hash(expected.model_dump(mode="json"))
            or coordinate.execution_receipt_id != p.execution_handle
            or receipt.mode != "current_authority" or receipt.material_digest != material_digest(material)
            or receipt.binding_digest != material.binding.binding_digest
            or str(receipt.corpus_version_id) != coordinate.corpus_version_id
            or receipt.active_generation != coordinate.active_generation
            or receipt.claim_receipt_hashes != (coordinate.claim_receipt_hash,)
            or datetime.fromisoformat(receipt.checked_at_iso) > published_at):
        raise PipelineRepositoryError("CURRENT_PACK_HISTORICAL_SOURCE_CHANGED")
    current, _, _ = repo._find(new.exact_claims[0].claim_receipt_id)
    require_signed_access(new, current.prepared, at=repo._clock())
    same_supported_source(q, current.prepared)
