from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.services.learning.item_bank.compiler import (
    LearningItemCompiler,
    curated_learning_item_source_root,
)
from app.services.learning.item_bank.contracts import (
    LearningItemReviewRole,
    LearningItemRiskTier,
    LearningItemSourceV1,
    canonical_hash,
)
from app.services.learning.item_bank.review import (
    LearningItemReviewError,
    LearningItemReviewOrchestrator,
    LearningItemReviewSubject,
    adjudicate_learning_item_reviews,
)
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemBlindReviewInputV1,
    LearningItemPilotDecision,
    LearningItemPilotTelemetryV1,
    LearningItemReviewBlockerKind,
    LearningItemReviewFindingV1,
    LearningItemReviewReportV1,
    LearningItemReviewSeverity,
    LearningItemReviewVerdict,
    evaluate_pilot,
)
from app.services.learning.item_bank.validation import validate_learning_item


@dataclass
class _FakeReviewer:
    role: LearningItemReviewRole
    reviewer_identity: str
    verdict: LearningItemReviewVerdict = LearningItemReviewVerdict.APPROVED
    findings: tuple[LearningItemReviewFindingV1, ...] = ()
    seen: list[LearningItemBlindReviewInputV1] = field(default_factory=list)

    def review(self, request: LearningItemBlindReviewInputV1) -> LearningItemReviewReportV1:
        self.seen.append(request)
        return LearningItemReviewReportV1(
            item_handle=request.item_handle,
            content_hash=request.content_hash,
            review_input_hash=request.review_input_hash,
            role=self.role,
            reviewer_identity=self.reviewer_identity,
            verdict=self.verdict,
            findings=self.findings,
        )


@dataclass
class _FailingReviewer:
    role: LearningItemReviewRole
    reviewer_identity: str

    def review(self, request: LearningItemBlindReviewInputV1) -> LearningItemReviewReportV1:
        del request
        raise RuntimeError("PRIVATE_PROVIDER_BODY_MARKER")


def _subject(
    source_name: str = "knowledge-class-attribute-v1.json",
    *,
    risk_tier: LearningItemRiskTier = LearningItemRiskTier.LOW,
    creator_identity: str = "author.generator",
) -> LearningItemReviewSubject:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        source_name,
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    payload["blueprint"]["publication_policy"]["risk_tier"] = risk_tier.value  # type: ignore[index]
    payload["blueprint"]["publication_policy"]["human_approval_required"] = (  # type: ignore[index]
        risk_tier is LearningItemRiskTier.HIGH
    )
    source = LearningItemSourceV1.model_validate(payload)
    return LearningItemReviewSubject(
        version_id=str(uuid4()),
        creator_identity=creator_identity,
        source=source,
        validation_receipt=validate_learning_item(source),
    )


def _reviewers(
    *,
    blocker_role: LearningItemReviewRole | None = None,
    blocker_kind: LearningItemReviewBlockerKind = LearningItemReviewBlockerKind.SECURITY,
) -> tuple[_FakeReviewer, ...]:
    reviewers: list[_FakeReviewer] = []
    for role in REQUIRED_REVIEW_ROLES:
        finding = ()
        verdict = LearningItemReviewVerdict.APPROVED
        if role is blocker_role:
            finding = (
                LearningItemReviewFindingV1(
                    finding_key=f"{role.value}.blocker",
                    severity=LearningItemReviewSeverity.CRITICAL,
                    safe_code=f"{role.value}.blocker",
                    blocking=True,
                    blocker_kind=blocker_kind,
                    safe_summary="A bounded blocking review finding.",
                    evidence_hash=canonical_hash(
                        {"role": role.value, "blocker": blocker_kind.value}
                    ),
                ),
            )
            verdict = LearningItemReviewVerdict.REJECTED
        reviewers.append(
            _FakeReviewer(
                role=role,
                reviewer_identity=f"reviewer.{role.value}",
                verdict=verdict,
                findings=finding,
            )
        )
    return tuple(reviewers)


def _contains_forbidden_review_context(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"creator_identity", "reports", "peer_reports", "other_reports"}
            or _contains_forbidden_review_context(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_review_context(item) for item in value)
    return False


def test_orchestrator_uses_six_blind_independent_reviewer_ports() -> None:
    subject = _subject()
    reviewers = _reviewers()

    reports = LearningItemReviewOrchestrator(reviewers).review(subject)

    assert tuple(report.role for report in reports) == REQUIRED_REVIEW_ROLES
    assert len({report.reviewer_identity for report in reports}) == 6
    for reviewer in reviewers:
        assert len(reviewer.seen) == 1
        payload = reviewer.seen[0].model_dump(mode="json")
        assert not _contains_forbidden_review_context(payload)


def test_creator_and_reviewer_independence_is_fail_closed() -> None:
    reviewers = list(_reviewers())
    reviewers[0].reviewer_identity = "AUTHOR.GENERATOR"
    orchestrator = LearningItemReviewOrchestrator(tuple(reversed(reviewers)))
    with pytest.raises(LearningItemReviewError, match="creator cannot review"):
        orchestrator.review(_subject())
    assert all(not reviewer.seen for reviewer in reviewers)

    reviewers = list(_reviewers())
    reviewers[1].reviewer_identity = reviewers[0].reviewer_identity.upper()
    with pytest.raises(LearningItemReviewError, match="identities must be independent"):
        LearningItemReviewOrchestrator(tuple(reviewers))


def test_reviewer_port_failure_does_not_chain_private_provider_details() -> None:
    reviewers: list[object] = list(_reviewers())
    reviewers[2] = _FailingReviewer(
        role=LearningItemReviewRole.TECHNICAL,
        reviewer_identity="reviewer.technical",
    )
    with pytest.raises(LearningItemReviewError) as exc_info:
        LearningItemReviewOrchestrator(tuple(reviewers)).review(_subject())  # type: ignore[arg-type]

    assert str(exc_info.value) == "Learning Item reviewer port failed"
    assert exc_info.value.__cause__ is None


@pytest.mark.parametrize(
    "blocker_kind",
    [
        LearningItemReviewBlockerKind.SECURITY,
        LearningItemReviewBlockerKind.UNIQUE_ANSWER,
        LearningItemReviewBlockerKind.RUBRIC_MISMATCH,
        LearningItemReviewBlockerKind.DETERMINISTIC_FAILURE,
    ],
)
def test_adjudication_never_allows_consensus_to_override_veto(
    blocker_kind: LearningItemReviewBlockerKind,
) -> None:
    subject = _subject()
    reports = LearningItemReviewOrchestrator(
        _reviewers(
            blocker_role=LearningItemReviewRole.SECURITY,
            blocker_kind=blocker_kind,
        )
    ).review(subject)

    adjudication = adjudicate_learning_item_reviews(subject, reports)

    assert adjudication.verdict == "rejected"
    assert blocker_kind in adjudication.blocker_kinds


def test_old_review_reports_are_invalid_after_content_version_changes() -> None:
    original = _subject()
    reports = LearningItemReviewOrchestrator(_reviewers()).review(original)
    successor = _subject(risk_tier=LearningItemRiskTier.HIGH)

    with pytest.raises(LearningItemReviewError, match="report is stale"):
        adjudicate_learning_item_reviews(successor, reports)


def test_only_high_risk_policy_can_require_human_approval() -> None:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        "knowledge-class-attribute-v1.json",
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    payload["blueprint"]["publication_policy"]["risk_tier"] = "medium"  # type: ignore[index]
    payload["blueprint"]["publication_policy"]["human_approval_required"] = True  # type: ignore[index]

    with pytest.raises(ValueError, match="only high-risk"):
        LearningItemSourceV1.model_validate(payload)


def test_medium_risk_requires_machine_execution_but_low_and_high_pilot_rules_differ() -> None:
    executable = _subject(
        "html-browser-active-card-v1.yaml",
        risk_tier=LearningItemRiskTier.MEDIUM,
    )
    executable_reports = LearningItemReviewOrchestrator(_reviewers()).review(executable)
    executable_adjudication = adjudicate_learning_item_reviews(executable, executable_reports)
    assert executable_adjudication.verdict == "approved"
    assert executable_adjudication.machine_execution_verified is True

    static = _subject(risk_tier=LearningItemRiskTier.MEDIUM)
    static_reports = LearningItemReviewOrchestrator(_reviewers()).review(static)
    static_adjudication = adjudicate_learning_item_reviews(static, static_reports)
    assert static_adjudication.verdict == "rejected"
    assert LearningItemReviewBlockerKind.DETERMINISTIC_FAILURE in static_adjudication.blocker_kinds

    handle = "li:" + "a" * 64
    content_hash = "b" * 64
    assert evaluate_pilot(
        risk_tier=LearningItemRiskTier.LOW,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=handle,
            content_hash=content_hash,
            observation_window_hash="c" * 64,
            sample_count=1,
            completed_count=1,
            cohort_complete=True,
        ),
    ).decision is LearningItemPilotDecision.PROMOTE
    assert evaluate_pilot(
        risk_tier=LearningItemRiskTier.MEDIUM,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=handle,
            content_hash=content_hash,
            observation_window_hash="d" * 64,
            sample_count=2,
            completed_count=2,
            cohort_complete=True,
        ),
    ).decision is LearningItemPilotDecision.COLLECTING
    assert evaluate_pilot(
        risk_tier=LearningItemRiskTier.HIGH,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=handle,
            content_hash=content_hash,
            observation_window_hash="e" * 64,
            sample_count=3,
            completed_count=3,
            cohort_complete=True,
        ),
    ).decision is LearningItemPilotDecision.AWAITING_HUMAN_APPROVAL


def test_pilot_anomalies_quarantine_or_retire() -> None:
    base = {
        "item_handle": "li:" + "1" * 64,
        "content_hash": "2" * 64,
        "sample_count": 3,
        "completed_count": 3,
        "cohort_complete": True,
    }
    quarantine = evaluate_pilot(
        risk_tier=LearningItemRiskTier.LOW,
        telemetry=LearningItemPilotTelemetryV1(
            **base,
            observation_window_hash="3" * 64,
            ambiguity_count=1,
        ),
    )
    retire = evaluate_pilot(
        risk_tier=LearningItemRiskTier.LOW,
        telemetry=LearningItemPilotTelemetryV1(
            **base,
            observation_window_hash="4" * 64,
            security_incident_count=1,
        ),
    )
    assert quarantine.decision is LearningItemPilotDecision.QUARANTINE
    assert retire.decision is LearningItemPilotDecision.RETIRE


def test_agent_review_feature_flag_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED", raising=False)
    assert Settings().learning_item_bank_agent_review_enabled is False
