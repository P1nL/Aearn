"""Central dispatch for fresh evidence and exact historical review bytes."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, cast

from app.services.learning.item_bank.contracts import LearningItemReviewRole, LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.review_contracts_v2 import (
    CandidateBindingV2, EvidencedReviewInputV1, EvidencedReviewReportV1,
    ReviewInputV2, ReviewReport, ReviewReportV2, ValidationReceiptV2,
)
from app.services.learning.item_supply.review_rubrics import (
    EVIDENCED_REVIEW_PROMPT_VERSION, EVIDENCED_REVIEW_PROTOCOL, LEGACY_REVIEW_PROTOCOL, ReviewProtocol,
)
from app.services.learning.item_supply.storage_contracts import checked_model

ReviewRequest = ReviewInputV2 | EvidencedReviewInputV1
REVIEW_PROMPT_VERSION = "item-supply-peer-review-v2.2"
PYTHON_GOAL_REVIEW_PROMPT_VERSION = "item-supply-peer-review-python-goal-v2.3"


def evidenced_protocol_marker() -> dict[str, object]:
    """Trusted fresh campaign snapshot; absence means historical legacy only."""
    return {"protocol_version": EVIDENCED_REVIEW_PROTOCOL,
            "prompt_version": EVIDENCED_REVIEW_PROMPT_VERSION,
            "input_schema": "item_supply_evidenced_review_input_v1",
            "output_schema": "item_supply_evidenced_review_output_v1",
            "report_schema": "item_supply_evidenced_review_report_v1",
            "thinking_mode": "enabled", "reasoning_effort": "high", "temperature": None}


class _RolePort(Protocol):
    @property
    def role(self) -> LearningItemReviewRole: ...


def configured_review_protocol(reviewers: Sequence[_RolePort]) -> ReviewProtocol:
    # Historical/offline ports without a marker remain precisely legacy.
    versions = {getattr(r, "review_protocol", LEGACY_REVIEW_PROTOCOL) for r in reviewers}
    if len(versions) != 1 or not versions <= {LEGACY_REVIEW_PROTOCOL, EVIDENCED_REVIEW_PROTOCOL}:
        raise ValueError("mixed or unknown review protocols")
    return cast(ReviewProtocol, next(iter(versions)))


def make_review_request(source: LearningItemSourceV1, *, binding: CandidateBindingV2,
                        validation_receipt: ValidationReceiptV2, role: LearningItemReviewRole,
                        protocol: ReviewProtocol = LEGACY_REVIEW_PROTOCOL) -> ReviewRequest:
    old = ReviewInputV2(binding=binding, role=role, source=source, validation_receipt=validation_receipt)
    if protocol == LEGACY_REVIEW_PROTOCOL:
        return old
    if protocol == EVIDENCED_REVIEW_PROTOCOL:
        return EvidencedReviewInputV1(review_input=old)
    raise ValueError("unknown review protocol")


def checked_review_request(request: ReviewRequest) -> ReviewRequest:
    if type(request) is EvidencedReviewInputV1:
        return checked_model(request, EvidencedReviewInputV1)
    return checked_model(request, ReviewInputV2)


def checked_review_report(report: ReviewReport) -> ReviewReport:
    if type(report) is EvidencedReviewReportV1:
        return checked_model(report, EvidencedReviewReportV1)
    return checked_model(report, ReviewReportV2)


def report_protocol(report: ReviewReport) -> ReviewProtocol:
    return EVIDENCED_REVIEW_PROTOCOL if type(report) is EvidencedReviewReportV1 else LEGACY_REVIEW_PROTOCOL


def review_prompt_version(request: ReviewRequest) -> str:
    if isinstance(request, EvidencedReviewInputV1):
        return EVIDENCED_REVIEW_PROMPT_VERSION
    return PYTHON_GOAL_REVIEW_PROMPT_VERSION if request.scoring_descriptor is not None else REVIEW_PROMPT_VERSION


def verify_review_report(report: ReviewReport, request: ReviewRequest) -> ReviewReport:
    report, request = checked_review_report(report), checked_review_request(request)
    if type(report) is EvidencedReviewReportV1:
        if type(request) is not EvidencedReviewInputV1:
            raise ValueError("cross-protocol review")
        report.verify_input(request)
    else:
        if type(request) is not ReviewInputV2:
            raise ValueError("cross-protocol review")
        if (report.binding != request.binding or report.role is not request.role
                or report.run.input_hash != request.input_hash
                or report.run.prompt_version != review_prompt_version(request)
                or report.run.output_hash != canonical_hash({"verdict": report.verdict.value,
                    "findings": [f.model_dump(mode="json") for f in report.findings]})):
            raise ValueError("stale review input or output")
    return report
