"""Synthetic port facts only; these tests make no live RAG/admission claim."""
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

import pytest

from app.services.grounding.autonomous.access_policy import AccessRequest
from app.services.grounding.autonomous.assessment_contracts import ClaimEvidenceReceipt, VerifiedClaim
from app.services.grounding.autonomous.contracts import RagBudgetDelegation, RagEvidenceBinding, SubjectScope
from app.services.grounding.current_authorization import AuthorizationReceipt, CurrentAuthorization
from app.services.grounding.material_contracts_v2 import (
    DraftScope, EvidenceBindingV2, EvidenceCoordinate, digest,
)
from app.services.learning.item_supply.evidence import SourceEvidenceDenied, require_exact_material
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.privacy import PrivacyDenied, safe_public_url
from app.services.learning.item_supply.rag_evidence_adapter import RagSourceAuthority


def make_material(excerpt: str = "Assignment rebinds a Python name.") -> tuple[
    PublicMaterialV2, ClaimEvidenceReceipt,
]:
    import hashlib

    scope = SubjectScope(subject_id="route.python", subject_version="1.0", facets=("fundamentals",))
    binding = RagEvidenceBinding(
        scope=scope, demand_hash=digest("demand"), purpose="assessment_evidence",
        source_handle="source.python", document_handle="document.python", document_revision="v1",
        document_hash=digest("document"), admission_receipt_id="admission.python",
        claim_receipt_id="claim.python",
    )
    claim = VerifiedClaim(
        claim_hash=digest("claim"), scope=scope, binding=binding,
        claim_receipt_id="claim.python", applicability="Python name rebinding",
    )
    receipt = ClaimEvidenceReceipt(
        receipt_id=claim.claim_receipt_id, demand_hash=binding.demand_hash,
        purpose="assessment_evidence", admission_receipt_id=binding.admission_receipt_id,
        claim_hash=claim.claim_hash, scope=scope, source_handle=binding.source_handle,
        document_handle=binding.document_handle, document_revision=binding.document_revision,
        document_hash=binding.document_hash, applicability=claim.applicability,
        method="independent_source", primary_lineage_family="lineage.primary",
        independent_lineage_family="lineage.independent", independent_source_handle="source.independent",
        independent_document_handle="document.independent", independent_document_revision="v1",
        independent_document_hash=digest("independent"), independent_lineage_verified=True,
        verified=True, revoked=False,
    )
    coordinate = EvidenceCoordinate(
        binding=binding, subject_id=scope.subject_id, corpus_version_id=str(uuid4()),
        active_generation=1, summary_hash=digest("summary"), validation_hash=digest("validation"),
        registry_digest=digest("registry"), source_review_id=str(uuid4()), source_policy_id="policy.python",
        source_policy_generation=1, chunk_id="chunk.python", chunk_hash=digest("chunk"),
        approved_excerpt_hash=hashlib.sha256(excerpt.encode()).hexdigest(),
        retrieval_hash=digest("retrieval"), coverage_hash=digest("coverage"),
        claim_id="claim.python", claim_receipt_hash=digest(receipt.model_dump(mode="json")),
        corroboration_id="corroboration.python",
    )
    draft = DraftScope(
        user_id=str(uuid4()), conversation_id=str(uuid4()), session_id=str(uuid4()), draft_id=str(uuid4()),
        draft_version=1, content_hash=digest("draft"), source_run_id=str(uuid4()), source_input_revision=1,
    )
    payload = dict(
        contract_version="rag_d_binding_v2", selection_handle="selection." + uuid4().hex,
        selection_digest=digest("selection"), draft=draft.model_dump(mode="json"),
        node_id="python.variables", goal_hash=digest("goal"), purpose="assessment_evidence",
        evidence=[coordinate.model_dump(mode="json")],
    )
    evidence = EvidenceBindingV2.model_validate_json(
        __import__("json").dumps({**payload, "binding_digest": digest(payload)}),
    )
    access = AccessRequest(
        demand_hash=binding.demand_hash, scope=scope, purpose="assessment_evidence", actor_id="actor.worker",
        action="consume", policy_id="policy.python", policy_generation=1,
        budget=RagBudgetDelegation(
            root_id="root.synthetic", delegation_id="delegation.synthetic", generation=1,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ),
    )
    return PublicMaterialV2(
        binding=evidence, access_request=access, exact_claims=(claim,), excerpt=excerpt,
    ), receipt


class Claims:
    def __init__(self, receipt: ClaimEvidenceReceipt | None) -> None:
        self.receipt = receipt

    def resolve(self, receipt_id: str) -> ClaimEvidenceReceipt | None:
        return self.receipt


class CurrentPort:
    def __init__(self) -> None:
        self.calls = 0
        self.fences = 0

    def check_current_authorization(self, binding, purpose, *, request, exact_item_claims=()):
        self.calls += 1
        assert purpose == "assessment_evidence" and exact_item_claims
        c = binding.evidence[0]
        return AuthorizationReceipt(
            binding_digest=binding.binding_digest, purpose=purpose, corpus_version_id=c.corpus_version_id,
            active_generation=c.active_generation, source_policy_generations=((c.source_policy_id, 1),),
            admission_receipt_ids=(c.binding.admission_receipt_id,), original_source_digests=(),
            exact_evidence_digest=digest("exact"), covered_facets=request.scope.facets,
            checked_at=datetime.now(timezone.utc),
        )

    def assert_publication_fence(self, binding, *, exact_item_claims, expected_generation, request):
        self.fences += 1
        assert expected_generation == binding.evidence[0].active_generation
        return self.check_current_authorization(
            binding, binding.purpose, request=request, exact_item_claims=exact_item_claims,
        )


def test_rag_adapter_calls_current_and_final_fence() -> None:
    material, claim = make_material()
    port = CurrentPort()
    adapter = RagSourceAuthority(cast(CurrentAuthorization, port), Claims(claim))
    receipt = adapter.authorize(material)
    assert port.calls == 1 and receipt.mode == "current_authority"
    adapter.assert_current(material, receipt)
    assert port.fences == 1 and port.calls == 2
    # Method behavior is verified against a synthetic port, NOT a live current DB.


def test_missing_or_revoked_claim_denies_without_current_io() -> None:
    material, claim = make_material()
    port = CurrentPort()
    for value in (None, claim.model_copy(update={"revoked": True})):
        with pytest.raises(SourceEvidenceDenied, match="^source_unavailable$"):
            RagSourceAuthority(cast(CurrentAuthorization, port), Claims(value)).authorize(material)
    assert port.calls == 0


def test_exact_excerpt_and_hash_fail_closed() -> None:
    material, claim = make_material()
    with pytest.raises(SourceEvidenceDenied):
        require_exact_material(material.model_copy(update={"excerpt": "private replacement"}))
    with pytest.raises(SourceEvidenceDenied):
        RagSourceAuthority(cast(CurrentAuthorization, CurrentPort()), Claims(
            claim.model_copy(update={"document_revision": "v2"}),
        )).authorize(material)


@pytest.mark.parametrize("url", [
    "https://user:secret@example.com/x", "https://example.com/x?token=secret",
    "https://example.com/x#secret", "https://127.0.0.1/x",
])
def test_sensitive_urls_are_not_redacted_into_receipts(url: str) -> None:
    with pytest.raises(PrivacyDenied, match="^privacy_denied$"):
        safe_public_url(url)
    assert safe_public_url("https://docs.python.org/3/reference/")
