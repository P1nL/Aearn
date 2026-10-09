"""Exact evidence matching only: hashes do not grant source authority."""
from __future__ import annotations

import hashlib

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.storage_contracts import checked_model


class SourceEvidenceDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("source_unavailable")


def material_digest(material: PublicMaterialV2) -> str:
    checked = checked_model(material, PublicMaterialV2)
    return canonical_hash({
        "binding": checked.binding.model_dump(mode="json"),
        "access_request": checked.access_request.model_dump(mode="json"),
        "exact_claims": [c.model_dump(mode="json") for c in checked.exact_claims],
        "excerpt_hash": hashlib.sha256(checked.excerpt.encode("utf-8")).hexdigest(),
    })


def require_exact_material(material: PublicMaterialV2) -> PublicMaterialV2:
    item = checked_model(material, PublicMaterialV2)
    binding = item.binding
    access = item.access_request
    # One exact approved excerpt per request material, never a joined/rewritten body.
    if (binding.purpose != "assessment_evidence" or access.purpose != binding.purpose
            or access.action != "consume" or len(binding.evidence) != 1
            or len(item.exact_claims) != 1):
        raise SourceEvidenceDenied()
    coordinate = binding.evidence[0]
    claim = item.exact_claims[0]
    if (hashlib.sha256(item.excerpt.encode("utf-8")).hexdigest()
            != coordinate.approved_excerpt_hash
            or claim.binding != coordinate.binding or claim.scope != access.scope
            or claim.binding.demand_hash != access.demand_hash
            or claim.claim_receipt_id != coordinate.binding.claim_receipt_id):
        raise SourceEvidenceDenied()
    return item
