"""RAG-owned current authority bridge; no fetching, self-issued trust or commits."""
from __future__ import annotations

from uuid import UUID
from typing import Any
from psycopg import Connection

from app.core.source_fence_diagnostics import observe_source_fence

from app.services.grounding.autonomous.assessment_contracts import (
    ClaimEvidenceReceipt, ClaimReceiptResolver,
)
from app.services.grounding.current_authorization import CurrentAuthorization
from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.evidence import (
    SourceEvidenceDenied, material_digest, require_exact_material,
)
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2, SourceReceiptV2
from app.services.learning.item_supply.storage_contracts import checked_model


class RagSourceAuthority:
    def __init__(self, current_authorization: CurrentAuthorization,
                 claim_resolver: ClaimReceiptResolver) -> None:
        self._current = current_authorization
        self._claims = claim_resolver

    @property
    def connection(self) -> Connection[dict[str, Any]]:
        """Expose identity only so the consumer can enforce its transaction fence."""
        return self._current.conn

    def authorize(self, material: PublicMaterialV2) -> SourceReceiptV2:
        return self._authorize(material)

    def assert_current(self, material: PublicMaterialV2,
                       expected: SourceReceiptV2) -> SourceReceiptV2:
        """Final caller-owned transaction; RAG takes the exact publication fence."""
        expected = checked_model(expected, SourceReceiptV2)
        if expected.mode != "current_authority":
            observe_source_fence("rag_assert_current", "native_receipt_mode_invalid")
            raise SourceEvidenceDenied()
        current = self._authorize(material, expected_generation=expected.active_generation)
        if current.model_dump(exclude={"checked_at_iso"}) != expected.model_dump(
                exclude={"checked_at_iso"}):
            observe_source_fence("rag_assert_current", "native_receipt_current_mismatch")
            raise SourceEvidenceDenied()
        return current

    def _authorize(self, material: PublicMaterialV2, *,
                   expected_generation: int | None = None) -> SourceReceiptV2:
        try:
            item = require_exact_material(material)
            coordinate = item.binding.evidence[0]
            claim = item.exact_claims[0]
            resolved = self._claims.resolve(claim.claim_receipt_id)
            if resolved is None:
                observe_source_fence("rag_authorize", "claim_missing_or_denied")
                raise SourceEvidenceDenied()
            receipt = checked_model(resolved, ClaimEvidenceReceipt)
            binding = coordinate.binding
            receipt_hash = canonical_hash(receipt.model_dump(mode="json"))
            if (not receipt.verified or receipt.revoked
                    or receipt.receipt_id != claim.claim_receipt_id
                    or receipt.demand_hash != item.access_request.demand_hash
                    or receipt.purpose != binding.purpose or receipt.scope != claim.scope
                    or receipt.claim_hash != claim.claim_hash
                    or receipt.applicability != claim.applicability
                    or receipt.source_handle != binding.source_handle
                    or receipt.document_handle != binding.document_handle
                    or receipt.document_revision != binding.document_revision
                    or receipt.document_hash != binding.document_hash
                    or receipt.admission_receipt_id != binding.admission_receipt_id
                    or receipt_hash != coordinate.claim_receipt_hash):
                raise SourceEvidenceDenied()
            # RAG re-resolves current source permissions and independent/execution facts.
            if expected_generation is None:
                current = self._current.check_current_authorization(
                    item.binding, "assessment_evidence", request=item.access_request,
                    exact_item_claims=item.exact_claims,
                )
            else:
                current = self._current.assert_publication_fence(
                    item.binding, exact_item_claims=item.exact_claims,
                    expected_generation=expected_generation, request=item.access_request,
                )
            if (current.binding_digest != item.binding.binding_digest
                    or current.purpose != "assessment_evidence"
                    or current.corpus_version_id != coordinate.corpus_version_id
                    or current.active_generation != coordinate.active_generation
                    or binding.admission_receipt_id not in current.admission_receipt_ids):
                raise SourceEvidenceDenied()
            return SourceReceiptV2(
                material_digest=material_digest(item), binding_digest=current.binding_digest,
                corpus_version_id=UUID(current.corpus_version_id),
                active_generation=current.active_generation,
                checked_at_iso=current.checked_at.isoformat(),
                claim_receipt_hashes=(receipt_hash,), mode="current_authority",
            )
        except Exception as exc:
            # No URLs, raw resolver errors, claims or source text leave this boundary.
            observe_source_fence("rag_authorize", "source_authorization_denied", exc)
            raise SourceEvidenceDenied() from None
