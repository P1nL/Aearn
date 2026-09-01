"""Feature-gated application seam for offline Learning Item governance."""
from __future__ import annotations

from datetime import datetime

from psycopg import Connection

from app.core.config import get_settings
from app.services.learning.item_bank.governance_repository import (
    LearningItemHumanApprovalResult,
    LearningItemPilotGovernanceResult,
    LearningItemReviewGovernanceResult,
    PostgresLearningItemGovernanceRepository,
)
from app.services.learning.item_bank.repository import LearningItemPublicationResult
from app.services.learning.item_bank.review import (
    LearningItemReviewOrchestrator,
    LearningItemReviewSubject,
)
from app.services.learning.item_bank.review_contracts import (
    LearningItemPilotTelemetryV1,
    LearningItemReviewReportV1,
)


class LearningItemAgentReviewDisabled(ValueError):
    """The default-off agent review/pilot mutation gate rejected the request."""


class LearningItemGovernanceService:
    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        enabled: bool | None = None,
    ) -> None:
        self._enabled = (
            get_settings().learning_item_bank_agent_review_enabled
            if enabled is None
            else enabled
        )
        self._repository = PostgresLearningItemGovernanceRepository(conn)

    def prepare_review(self, *, handle: str) -> LearningItemReviewSubject:
        self._require_enabled()
        return self._repository.load_review_subject(handle=handle)

    def run_offline_reviews(
        self,
        *,
        subject: LearningItemReviewSubject,
        orchestrator: LearningItemReviewOrchestrator,
    ) -> tuple[LearningItemReviewReportV1, ...]:
        self._require_enabled()
        return orchestrator.review(subject)

    def record_review_bundle(
        self,
        *,
        subject: LearningItemReviewSubject,
        reports: tuple[LearningItemReviewReportV1, ...],
        bundle_key: str,
        occurred_at: datetime,
    ) -> LearningItemReviewGovernanceResult:
        self._require_enabled()
        return self._repository.record_review_bundle(
            subject=subject,
            reports=reports,
            bundle_key=bundle_key,
            occurred_at=occurred_at,
        )

    def start_pilot(
        self,
        *,
        handle: str,
        transition_key: str,
        occurred_at: datetime,
    ) -> LearningItemPublicationResult:
        self._require_enabled()
        return self._repository.start_pilot(
            handle=handle,
            transition_key=transition_key,
            occurred_at=occurred_at,
        )

    def record_pilot_telemetry(
        self,
        *,
        handle: str,
        telemetry: LearningItemPilotTelemetryV1,
        expected_pilot_sequence: int,
        telemetry_key: str,
        occurred_at: datetime,
    ) -> LearningItemPilotGovernanceResult:
        self._require_enabled()
        return self._repository.record_pilot_telemetry(
            handle=handle,
            telemetry=telemetry,
            expected_pilot_sequence=expected_pilot_sequence,
            telemetry_key=telemetry_key,
            occurred_at=occurred_at,
        )

    def approve_high_risk(
        self,
        *,
        handle: str,
        approver_identity: str,
        approval_key: str,
        occurred_at: datetime,
        approval_code: str = "approved",
    ) -> LearningItemHumanApprovalResult:
        self._require_enabled()
        return self._repository.approve_high_risk(
            handle=handle,
            approver_identity=approver_identity,
            approval_key=approval_key,
            approval_code=approval_code,
            occurred_at=occurred_at,
        )

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise LearningItemAgentReviewDisabled(
                "Learning Item Bank agent review is disabled"
            )


__all__ = (
    "LearningItemAgentReviewDisabled",
    "LearningItemGovernanceService",
)
