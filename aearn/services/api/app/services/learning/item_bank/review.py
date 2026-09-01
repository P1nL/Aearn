"""Offline reviewer ports, blind orchestration, and deterministic adjudication."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.services.learning.item_bank.contracts import (
    LearningItemReviewRole,
    LearningItemSourceV1,
    LearningItemValidationReceiptV1,
    learning_item_handle,
    stable_key,
)
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemBlindReviewInputV1,
    LearningItemReviewAdjudicationV1,
    LearningItemReviewBlockerKind,
    LearningItemReviewReportV1,
    LearningItemReviewSeverity,
    LearningItemReviewVerdict,
    validation_proves_machine_execution,
)


class LearningItemReviewError(ValueError):
    """Safe review failure that never includes provider/reviewer payloads."""


@dataclass(frozen=True, slots=True)
class LearningItemReviewSubject:
    version_id: str
    creator_identity: str
    source: LearningItemSourceV1
    validation_receipt: LearningItemValidationReceiptV1

    def __post_init__(self) -> None:
        try:
            UUID(self.version_id)
        except ValueError as exc:
            raise LearningItemReviewError("Learning Item review version id is invalid") from exc
        object.__setattr__(
            self,
            "creator_identity",
            stable_key(self.creator_identity, label="Learning Item creator identity"),
        )
        if not self.validation_receipt.passed:
            raise LearningItemReviewError("Learning Item review subject is not machine verified")
        if (
            self.validation_receipt.item_handle != self.item_handle
            or self.validation_receipt.content_hash != self.source.content_hash
        ):
            raise LearningItemReviewError("Learning Item review subject validation is stale")

    @property
    def item_handle(self) -> str:
        return learning_item_handle(
            self.source.public.item_key,
            self.source.public.version,
            self.source.content_hash,
        )

    def blind_input(self, role: LearningItemReviewRole) -> LearningItemBlindReviewInputV1:
        return LearningItemBlindReviewInputV1(
            item_handle=self.item_handle,
            content_hash=self.source.content_hash,
            role=role,
            risk_tier=self.source.blueprint.publication_policy.risk_tier,
            source=self.source,
            validation_receipt=self.validation_receipt,
        )


class LearningItemReviewerPort(Protocol):
    @property
    def role(self) -> LearningItemReviewRole: ...

    @property
    def reviewer_identity(self) -> str: ...

    def review(self, request: LearningItemBlindReviewInputV1) -> LearningItemReviewReportV1: ...


class LearningItemReviewOrchestrator:
    """Invoke six independent ports without exposing peer reports to any reviewer."""

    def __init__(self, reviewers: tuple[LearningItemReviewerPort, ...]) -> None:
        by_role = {reviewer.role: reviewer for reviewer in reviewers}
        if set(by_role) != set(REQUIRED_REVIEW_ROLES) or len(reviewers) != len(
            REQUIRED_REVIEW_ROLES
        ):
            raise LearningItemReviewError("Learning Item reviewer ports must cover all six roles")
        self._reviewers = tuple(by_role[role] for role in REQUIRED_REVIEW_ROLES)
        self._reviewer_identities = tuple(
            stable_key(reviewer.reviewer_identity, label="Learning Item reviewer identity")
            for reviewer in self._reviewers
        )
        if len(self._reviewer_identities) != len(set(self._reviewer_identities)):
            raise LearningItemReviewError("Learning Item reviewer identities must be independent")

    def review(self, subject: LearningItemReviewSubject) -> tuple[LearningItemReviewReportV1, ...]:
        if subject.creator_identity in self._reviewer_identities:
            raise LearningItemReviewError("Learning Item creator cannot review their own item")
        requests = {
            role: subject.blind_input(role)
            for role in REQUIRED_REVIEW_ROLES
        }
        try:
            with ThreadPoolExecutor(max_workers=len(REQUIRED_REVIEW_ROLES)) as executor:
                futures = {
                    role: executor.submit(self._reviewers[index].review, requests[role])
                    for index, role in enumerate(REQUIRED_REVIEW_ROLES)
                }
                reports = tuple(futures[role].result() for role in REQUIRED_REVIEW_ROLES)
        except Exception:
            raise LearningItemReviewError("Learning Item reviewer port failed") from None
        for index, (report, role) in enumerate(
            zip(reports, REQUIRED_REVIEW_ROLES, strict=True)
        ):
            request = requests[role]
            if (
                report.role is not role
                or report.reviewer_identity != self._reviewer_identities[index]
                or report.item_handle != request.item_handle
                or report.content_hash != request.content_hash
                or report.review_input_hash != request.review_input_hash
            ):
                raise LearningItemReviewError("Learning Item reviewer returned stale or foreign output")
        return reports


def adjudicate_learning_item_reviews(
    subject: LearningItemReviewSubject,
    reports: tuple[LearningItemReviewReportV1, ...],
) -> LearningItemReviewAdjudicationV1:
    """Adjudicate exact reports; blockers and veto classes can never be outvoted."""

    if len(reports) != len(REQUIRED_REVIEW_ROLES):
        raise LearningItemReviewError("Learning Item adjudication requires six reports")
    by_role = {report.role: report for report in reports}
    if set(by_role) != set(REQUIRED_REVIEW_ROLES):
        raise LearningItemReviewError("Learning Item adjudication report roles are incomplete")
    reviewers = tuple(report.reviewer_identity for report in reports)
    if len(reviewers) != len(set(reviewers)) or subject.creator_identity in reviewers:
        raise LearningItemReviewError("Learning Item adjudication reviewer independence failed")

    blockers: set[LearningItemReviewBlockerKind] = set()
    highest = LearningItemReviewSeverity.NONE
    role_blockers = {
        LearningItemReviewRole.CURRICULUM: LearningItemReviewBlockerKind.CURRICULUM_MISMATCH,
        LearningItemReviewRole.DIFFICULTY: LearningItemReviewBlockerKind.DIFFICULTY_MISMATCH,
        LearningItemReviewRole.TECHNICAL: LearningItemReviewBlockerKind.TECHNICAL_FAILURE,
        LearningItemReviewRole.AMBIGUITY: LearningItemReviewBlockerKind.AMBIGUITY,
        LearningItemReviewRole.SECURITY: LearningItemReviewBlockerKind.SECURITY,
        LearningItemReviewRole.ADVERSARIAL: LearningItemReviewBlockerKind.ADVERSARIAL_EXPLOIT,
    }
    report_hashes: dict[LearningItemReviewRole, str] = {}
    for role in REQUIRED_REVIEW_ROLES:
        report = by_role[role]
        request = subject.blind_input(role)
        if (
            report.item_handle != subject.item_handle
            or report.content_hash != subject.source.content_hash
            or report.review_input_hash != request.review_input_hash
        ):
            raise LearningItemReviewError("Learning Item adjudication report is stale")
        report_hashes[role] = report.report_hash
        blockers.update(report.blocker_kinds)
        if report.verdict is not LearningItemReviewVerdict.APPROVED:
            blockers.add(role_blockers[role])
            blockers.add(LearningItemReviewBlockerKind.REVIEW_CHANGES_REQUIRED)
        if _severity_rank(report.highest_severity) > _severity_rank(highest):
            highest = report.highest_severity

    machine_execution = validation_proves_machine_execution(
        subject.source,
        subject.validation_receipt,
    )
    if not subject.validation_receipt.passed or (
        subject.source.blueprint.publication_policy.risk_tier.value == "medium"
        and not machine_execution
    ):
        blockers.add(LearningItemReviewBlockerKind.DETERMINISTIC_FAILURE)
        highest = LearningItemReviewSeverity.CRITICAL

    return LearningItemReviewAdjudicationV1(
        item_handle=subject.item_handle,
        content_hash=subject.source.content_hash,
        risk_tier=subject.source.blueprint.publication_policy.risk_tier,
        report_hashes=report_hashes,
        verdict="rejected" if blockers else "approved",
        highest_severity=highest,
        blocker_kinds=tuple(blockers),
        machine_execution_verified=machine_execution,
    )


def _severity_rank(value: LearningItemReviewSeverity) -> int:
    return {
        LearningItemReviewSeverity.NONE: 0,
        LearningItemReviewSeverity.INFO: 1,
        LearningItemReviewSeverity.MINOR: 2,
        LearningItemReviewSeverity.MAJOR: 3,
        LearningItemReviewSeverity.CRITICAL: 4,
    }[value]


__all__ = (
    "LearningItemReviewError",
    "LearningItemReviewerPort",
    "LearningItemReviewOrchestrator",
    "LearningItemReviewSubject",
    "adjudicate_learning_item_reviews",
)
