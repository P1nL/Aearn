"""PUBLIC relation-repair DATA, not a restored native batch or phase capability.

Only public phase/slot/version identities occur here. PRIVATE batch IDs,
user IDs, mapping IDs and private receipt hashes remain in the original store.
"""
from __future__ import annotations
from typing import Any, Literal
from uuid import UUID
from pydantic import Field, field_validator, model_validator
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash, canonical_json
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.native_type_contracts import NativeRelationJudgment, NativeRelationReport
from app.services.learning.item_supply.persistent_pack_repair import PersistentInvestigationInputV1, PersistentRevisionFindingEvidenceV1
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.native_review_investigation_contracts import ReviewDisputeV1, ReviewDiagnosticReferenceV1
from app.services.learning.item_supply.storage_contracts import StorageContract

RELATION_PROTOCOL = "persistent-normal-relation-investigation-v1"
RELATION_PROMPT = "persistent-normal-relation-investigation-v1"

def public_parent_scalar_references(source: LearningItemSourceV1) -> tuple[ReviewDiagnosticReferenceV1, ...]:
    """Original diagnostic paths; not model-vote references or external paths."""
    refs: list[ReviewDiagnosticReferenceV1] = []
    def visit(value: Any, pointer: str) -> None:
        if isinstance(value, dict):
            for key, child in sorted(value.items()):
                visit(child, pointer+"/"+key.replace("~","~0").replace("/","~1"))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, pointer+"/"+str(index))
        elif len(refs) < 32:
            refs.append(ReviewDiagnosticReferenceV1(pointer=pointer,value_hash=canonical_hash(value)))
    payload = source.model_dump(mode="json")
    visit(payload["public"]["content"],"/source/public/content")
    if not refs:
        raise ValueError("actual bounded original public source scalars required")
    return tuple(refs)



class PersistentPublicRelationFindingV1(StorageContract):
    schema_version: Literal["persistent_public_relation_finding_v1"] = "persistent_public_relation_finding_v1"
    role: Literal["relation"] = "relation"
    public_relation_phase_id: UUID
    public_slot_id: UUID
    parent_revision_id: UUID
    parent_version_id: UUID
    pair: tuple[UUID, UUID]
    pair_kind: Literal["assessment_assessment", "assessment_training"]
    pair_sources: tuple[LearningItemSourceV1, LearningItemSourceV1] = Field(repr=False)
    report: NativeRelationReport = Field(repr=False)
    judgment: NativeRelationJudgment = Field(repr=False)
    safe_code: Literal["assessment_relation_conflict", "assessment_relation_uncertain"]
    references: tuple[ReviewDiagnosticReferenceV1, ...] = Field(min_length=1, max_length=32)
    dispute_key: Digest
    historical_finding_resolved: Literal[False] = False
    publication_enabled: Literal[False] = False

    @model_validator(mode="after")
    def exact_negative(self) -> PersistentPublicRelationFindingV1:
        expected = "assessment_relation_conflict" if self.judgment.conclusion == "conflict" else "assessment_relation_uncertain"
        if (len(set(self.pair)) != 2 or self.parent_version_id not in self.pair
                or self.judgment.conclusion not in ("conflict", "uncertain")
                or self.judgment not in self.report.judgments
                or {r.version_id for r in self.judgment.references} != set(self.pair)
                or self.safe_code != expected
                or self.references != public_parent_scalar_references(self.pair_sources[self.pair.index(self.parent_version_id)])
                or self.dispute_key != canonical_hash(self.model_dump(mode="json", exclude={"dispute_key"}))):
            raise ValueError("exact original negative pair/report DATA required")
        return self

class PersistentRelationInvestigationInputV1(PersistentInvestigationInputV1):
    # The existing envelope's field set is retained, but the new finding schema
    # selects an explicit receiver/sender branch. This is not an old v1 grant.
    disputes: tuple[Any, ...] = Field(min_length=1, max_length=144)

    @field_validator("disputes", mode="before")
    @classmethod
    def typed_finding_data(cls, value: Any) -> tuple[Any, ...]:
        if not isinstance(value, (tuple, list)):
            raise ValueError("bounded typed dispute DATA sequence required")
        result = []
        for item in value:
            if type(item) in (ReviewDisputeV1, PersistentPublicRelationFindingV1):
                result.append(item)
            elif isinstance(item, dict):
                model = PersistentPublicRelationFindingV1 if item.get("schema_version") == "persistent_public_relation_finding_v1" else ReviewDisputeV1
                result.append(model.model_validate_json(canonical_json(item)))
            else:
                raise ValueError("closed original DATA models required")
        return tuple(result)

    @model_validator(mode="after")
    def original_findings(self) -> PersistentRelationInvestigationInputV1:
        peers = tuple(d for d in self.disputes if type(d) is ReviewDisputeV1)
        relations = tuple(d for d in self.disputes if type(d) is PersistentPublicRelationFindingV1)
        if (any(type(d) not in (ReviewDisputeV1, PersistentPublicRelationFindingV1) for d in self.disputes)
                or peers != review_disputes(self.bundle) or len(relations) != 1
                or self.revision_allocation is None
                or self.bundle.binding != self.review_input.binding
                or self.bundle.bundle_hash != self.review_receipt_hash
                or len({d.dispute_key for d in self.disputes}) != len(self.disputes)):
            raise ValueError("one exact relation plus every original peer finding required")
        # Typed field equality alone is not an authority. The original issuer
        # re-resolves the committed four-role batch and current pair each fence.
        return self

    @property
    def relation_finding(self) -> PersistentPublicRelationFindingV1:
        return next(d for d in self.disputes if type(d) is PersistentPublicRelationFindingV1)

    @property
    def evidence_index(self) -> tuple[ReviewDiagnosticReferenceV1, ...]:
        return super().evidence_index

    @property
    def input_payload(self) -> dict[str, Any]:
        # Existing peer serialization is preserved; no fake six-peer report.
        peers = tuple(d for d in self.disputes if type(d) is ReviewDisputeV1)
        peer_payloads: list[dict[str, Any]] = []
        for d in peers:
            report = next(r for r in self.bundle.reports if r.report_hash == d.report_hash)
            finding = None if d.finding_index is None else report.findings[d.finding_index].model_dump(mode="json")
            peer_payloads.append(dict(dispute_key=d.dispute_key, role=d.role.value, report_hash=d.report_hash,
                finding_index=d.finding_index, finding_hash=d.finding_hash, finding=finding, safe_code=d.safe_code,
                references=[r.model_dump(mode="json") for r in d.references]))
        return dict(schema_version=self.schema_version, purpose=self.purpose, authority=self.authority,
            review_receipt_id=str(self.review_receipt_id), review_receipt_hash=self.review_receipt_hash,
            review_input=self.review_input.input_payload, execution_profile_hash=self.execution_profile_hash,
            revision_allocation=self.revision_allocation.model_dump(mode="json") if self.revision_allocation else None,
            disputes=[*peer_payloads, self.relation_finding.model_dump(mode="json")],
            evidence_index=[r.model_dump(mode="json") for r in self.evidence_index])

class PersistentRelationRevisionFindingEvidenceV1(PersistentRevisionFindingEvidenceV1):
    original_dispute: Any

    @model_validator(mode="after")
    def exact_relation(self) -> PersistentRelationRevisionFindingEvidenceV1:
        if type(self.original_dispute) is not PersistentPublicRelationFindingV1:
            raise ValueError("exact retained original public relation DATA required")
        return self
