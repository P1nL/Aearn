"""Shared-confidential live investigation data; never votes or source capabilities."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.review_contracts_v2 import (
    CandidateBindingV2, ProviderRunV2, ReviewDiagnosticReferenceV1, ReviewInputV2,
)
from app.services.learning.item_supply.review_deliberation import review_disputes
from app.services.learning.item_supply.review_deliberation_contracts import BundleField, ReviewDisputeV1
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model

INVESTIGATION_PROMPT_VERSION = "native-shared-review-investigation-v1"
INVESTIGATION_SCALAR_PROMPT_VERSION = "native-shared-review-investigation-v2"
INVESTIGATION_OUTPUT_SCHEMA = "native_shared_review_investigation_output_v1"
InvestigationProtocol = Literal["legacy-v1", "scalar-evidence-v2"]


def checked_investigation_protocol(protocol: InvestigationProtocol) -> InvestigationProtocol:
    if type(protocol) is not str or protocol not in {"legacy-v1", "scalar-evidence-v2"}:
        raise ValueError("closed investigation protocol required")
    return protocol


def investigation_prompt_version(protocol: InvestigationProtocol) -> str:
    return (INVESTIGATION_PROMPT_VERSION if checked_investigation_protocol(protocol) == "legacy-v1"
            else INVESTIGATION_SCALAR_PROMPT_VERSION)


class NativeReviewInvestigationInputV1(StorageContract):
    schema_version: Literal["native_shared_review_investigation_input_v1"] = "native_shared_review_investigation_input_v1"
    purpose: Literal["live_dispute_investigation"] = "live_dispute_investigation"
    authority: Literal["original_shared_owner_required"] = "original_shared_owner_required"
    review_receipt_id: UUID
    review_receipt_hash: Digest
    review_input: ReviewInputV2 = Field(repr=False)
    bundle: BundleField = Field(repr=False)
    disputes: tuple[ReviewDisputeV1, ...] = Field(min_length=1, max_length=144)

    @model_validator(mode="after")
    def original_subject(self) -> NativeReviewInvestigationInputV1:
        if (self.bundle.binding != self.review_input.binding
                or self.bundle.bundle_hash != self.review_receipt_hash
                or review_disputes(self.bundle) != self.disputes):
            raise ValueError("investigation original disputes mismatch")
        return self

    @property
    def binding(self) -> CandidateBindingV2:
        return self.review_input.binding

    @property
    def evidence_index(self) -> tuple[ReviewDiagnosticReferenceV1, ...]:
        # Investigation uses scalar leaves only; legacy reviewer indexes also
        # include containers and remain unchanged for historical input hashes.
        payload = checked_model(self.review_input, ReviewInputV2).input_payload
        refs: list[ReviewDiagnosticReferenceV1] = []

        def visit(value: object, pointer: str, depth: int) -> None:
            if depth > 24:
                raise ValueError("investigation evidence index depth limit")
            if isinstance(value, dict):
                for key, child in sorted(value.items()):
                    token = key.replace("~", "~0").replace("/", "~1")
                    visit(child, pointer + "/" + token, depth + 1)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, pointer + "/" + str(index), depth + 1)
            else:
                if len(refs) >= 1024:
                    raise ValueError("investigation evidence index count limit")
                refs.append(ReviewDiagnosticReferenceV1(pointer=pointer, value_hash=canonical_hash(value)))

        for section in ("source", "validation_receipt", "scoring_descriptor"):
            value = payload.get(section)
            if isinstance(value, dict):
                for key, child in sorted(value.items()):
                    token = key.replace("~", "~0").replace("/", "~1")
                    visit(child, "/" + section + "/" + token, 0)
        return tuple(refs)

    @property
    def input_payload(self) -> dict[str, object]:
        request = checked_model(self, NativeReviewInvestigationInputV1)
        # Full bundle is kept internally for exact audit/owner verification.
        # Only original material findings reach this one investigation call:
        # no blind answer/score/run, lease, cost ledger or peer vote is sent.
        disputes = []
        for dispute in request.disputes:
            report = next(r for r in request.bundle.reports if r.report_hash == dispute.report_hash)
            finding = None if dispute.finding_index is None else report.findings[dispute.finding_index].model_dump(mode="json")
            disputes.append({"dispute_key": dispute.dispute_key, "role": dispute.role.value,
                "report_hash": dispute.report_hash, "finding_index": dispute.finding_index, "finding_hash": dispute.finding_hash,
                "finding": finding, "safe_code": dispute.safe_code,
                "references": [r.model_dump(mode="json") for r in dispute.references]})
        return {"schema_version": request.schema_version, "purpose": request.purpose,
            "authority": request.authority, "review_receipt_id": str(request.review_receipt_id),
            "review_receipt_hash": request.review_receipt_hash, "review_input": request.review_input.input_payload,
            "disputes": disputes, "evidence_index": [r.model_dump(mode="json") for r in request.evidence_index]}

    @property
    def input_hash(self) -> str:
        return canonical_hash(self.input_payload)


class NativeDisputeAnalysisV1(StorageContract):
    dispute_key: Digest
    finding_status: Literal["supported", "contested", "insufficient_evidence"]
    analysis: str = Field(min_length=1, max_length=1600, pattern=r"\S", repr=False)
    verification_question: str = Field(min_length=1, max_length=1200, pattern=r"\S", repr=False)
    proposed_revision: str | None = Field(default=None, min_length=1, max_length=1600, pattern=r"\S", repr=False)
    references: tuple[ReviewDiagnosticReferenceV1, ...] = Field(min_length=1, max_length=6)


class NativeReviewInvestigationOutputV1(StorageContract):
    schema_version: Literal["native_shared_review_investigation_output_v1"]
    analyses: tuple[NativeDisputeAnalysisV1, ...] = Field(min_length=1, max_length=144, repr=False)


class NativeReviewInvestigationReportV1(StorageContract):
    schema_version: Literal["native_shared_review_investigation_report_v1"] = "native_shared_review_investigation_report_v1"
    publication_enabled: Literal[False] = False
    admission_eligible: Literal[False] = False
    binding: CandidateBindingV2
    review_receipt_id: UUID
    review_receipt_hash: Digest
    run: ProviderRunV2
    output: NativeReviewInvestigationOutputV1 = Field(repr=False)

    def verify_input(self, request: NativeReviewInvestigationInputV1, *,
                     expected_protocol: InvestigationProtocol = "legacy-v1") -> None:
        expected_prompt = investigation_prompt_version(expected_protocol)
        report = checked_model(self, NativeReviewInvestigationReportV1)
        request = checked_model(request, NativeReviewInvestigationInputV1)
        index = {r.pointer: r.value_hash for r in request.evidence_index}
        keys = tuple(a.dispute_key for a in report.output.analyses)
        if (report.binding != request.binding or report.review_receipt_id != request.review_receipt_id
                or report.review_receipt_hash != request.review_receipt_hash
                or report.run.profile_hash != request.binding.profile_hash
                or report.run.prompt_version != expected_prompt
                or report.run.input_hash != request.input_hash
                or report.run.output_hash != canonical_hash(report.output.model_dump(mode="json"))
                or len(set(keys)) != len(keys) or set(keys) != {d.dispute_key for d in request.disputes}):
            raise ValueError("investigation output binding mismatch")
        for analysis in report.output.analyses:
            pointers = tuple(r.pointer for r in analysis.references)
            original = next(d for d in request.disputes if d.dispute_key == analysis.dispute_key)
            if (len(set(pointers)) != len(pointers)
                    or any(index.get(r.pointer) != r.value_hash for r in analysis.references)
                    or (original.references and not any(
                        pointer == ref.pointer or pointer.startswith(ref.pointer + "/")
                        for pointer in pointers for ref in original.references))):
                raise ValueError("investigation field evidence mismatch")
        # supported/contested remain MODEL CLAIMS; neither discharges a blocker.
