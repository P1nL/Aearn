"""Explicit bounded business rounds, separate from first-round/admission policy.

No default caller, provider adapter, DB connection or publication port. A trusted
server composition supplies ORIGINAL budget/lease/source owners. Restarts use
original durable reservation/replay fences, never a new budget root. The shared
review seam exposes a verified pending plan without provider/runner IO; its
original-owner checks still read the DB. Evidence-only
re-review remains pending: existing peer inputs cannot bind an evidence version.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1, LearningItemValidationReceiptV1, canonical_hash,
)
from app.services.learning.item_bank.review_contracts import LearningItemReviewSeverity, LearningItemReviewVerdict
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.item_supply.diagnostic_policy import ReviewBundle, ReviewBundleV3, checked_bundle, policy_for_hash
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import (
    EvidencedReviewReportV1, ReviewBundleV2, ValidationReceiptV2, checked_validation_receipt, check_subject,
)
from app.services.learning.item_supply.review_deliberation_contracts import (
    DeliberationAction, DeliberationRoundV1, DeliberationSubjectV1, IndependentRecheckRequestV1,
    InvestigationEvidenceV1, InvestigationRequestV1, NeutralReviewRequirementV1,
    ReviewDeliberationPlanV1, ReviewDeliberationResultV1, ReviewDisputeV1, RevisionRequestV1,
)
from app.services.learning.item_supply.review_protocol import make_review_request, report_protocol, verify_review_report
from app.services.learning.item_supply.blind_protocol import (
    BlindProtocol, blind_prompt_version, blind_protocol_for_prompt_version, checked_blind_protocol,
)
from app.services.learning.item_supply.review_provider import blind_input
from app.services.learning.item_supply.review_rubrics import HARD_CODES
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2

ActionRequest = InvestigationRequestV1 | RevisionRequestV1 | IndependentRecheckRequestV1
ActionResult = InvestigationEvidenceV1 | DeliberationSubjectV1 | ValidationReceiptV2 | ReviewBundle


class DeliberationPending(Exception):
    """Safe internal stop; provider bodies and private findings are not errors."""


class ReviewDeliberationOwner(Protocol):
    """Trusted SERVER port, never provided by a model, DTO or learner request.

    check_current checks exact original root/profile/namespace/lease generation,
    immutable source hashes and CURRENT authorized assessment claims, including
    every new revision. resources prices the actual operation before reservation.
    reserve uses original P3 cumulative/global caps and commits before any IO.
    recheck requires a committed reservation, exact request and a current source
    fence with no open transaction at IO. Operations honor deadline_at and frozen
    request timeouts. An LLM investigation needs explicit one-call high/production
    output pricing, not the retrospective diagnostic adapter. None is added here.
    verify_result checks ORIGINAL issuer-held receipts, not self-asserted DTOs.
    retain_unknown durably retains reservations even on failure/lost lease.
    validate runs the full independent deterministic/live execution validation;
    review runs fresh PUBLIC-only blind solve and ALL SIX peers, with unchanged
    policy/provider bindings. Requirements are neutral server test categories,
    not extra fields smuggled into legacy provider review inputs. No operation
    may admit, publish or manufacture seals/learner facts.
    """
    def check_current(self, plan: ReviewDeliberationPlanV1, subject: DeliberationSubjectV1) -> bool: ...
    def resources(self, action: DeliberationAction, request: ActionRequest) -> ResourceAmounts: ...
    def reserve(self, plan: ReviewDeliberationPlanV1, action: DeliberationAction,
                request: ActionRequest, resources: ResourceAmounts, *, deadline_at: datetime) -> object | None: ...
    def recheck(self, reservation: object, plan: ReviewDeliberationPlanV1,
                action: DeliberationAction, request: ActionRequest, *, deadline_at: datetime) -> bool: ...
    def investigate(self, request: InvestigationRequestV1, *, deadline_at: datetime) -> InvestigationEvidenceV1: ...
    def revise(self, request: RevisionRequestV1, *, deadline_at: datetime) -> DeliberationSubjectV1 | None: ...
    def validate(self, request: IndependentRecheckRequestV1, *, deadline_at: datetime) -> ValidationReceiptV2: ...
    def review(self, request: IndependentRecheckRequestV1, *, deadline_at: datetime) -> ReviewBundle: ...
    def verify_result(self, reservation: object, action: DeliberationAction,
                      request: ActionRequest, result: ActionResult) -> bool: ...
    def retain_unknown(self, reservation: object) -> None: ...


def _material(finding: object) -> bool:
    return (getattr(finding, "blocking", False) or getattr(finding, "safe_code", None) in HARD_CODES
            or getattr(finding, "severity", None) in {LearningItemReviewSeverity.MAJOR, LearningItemReviewSeverity.CRITICAL})


def review_disputes(bundle: ReviewBundle) -> tuple[ReviewDisputeV1, ...]:
    """Keep each minority identity intact; never merge matching allegations."""
    bundle = checked_bundle(bundle)
    disputes: list[ReviewDisputeV1] = []
    for report in bundle.reports:
        found = False
        for index, finding in enumerate(report.findings):
            if not _material(finding):
                continue
            found = True
            finding_hash = canonical_hash(finding.model_dump(mode="json"))
            references = report.findings[index].references if isinstance(report, EvidencedReviewReportV1) else ()
            disputes.append(ReviewDisputeV1(
                dispute_key=canonical_hash((bundle.bundle_hash, report.report_hash, index, finding_hash)),
                role=report.role, report_hash=report.report_hash, run_id=report.run.run_id,
                finding_index=index, finding_hash=finding_hash, safe_code=finding.safe_code, references=references,
            ))
        if not found and report.verdict is not LearningItemReviewVerdict.APPROVED:
            # Legacy unsupported negative verdict stays pending; no invented
            # concrete finding, prose or field evidence to justify it.
            disputes.append(ReviewDisputeV1(dispute_key=canonical_hash((bundle.bundle_hash, report.report_hash)),
                role=report.role, report_hash=report.report_hash, run_id=report.run.run_id,
                safe_code="report_requires_evidence"))
    return tuple(disputes)


def _verify_bundle(subject: DeliberationSubjectV1, validation: ValidationReceiptV2,
                   bundle: ReviewBundle, *, blind_protocol: BlindProtocol | None = None) -> ReviewBundle:
    subject = checked_model(subject, DeliberationSubjectV1)
    validation = checked_validation_receipt(validation)
    bundle = checked_bundle(bundle)
    check_subject(subject.source, subject.binding, validation)
    policy = policy_for_hash(subject.binding.policy_hash)
    if bundle.binding != subject.binding or bundle.policy_version != policy.policy_version:
        raise ValueError("deliberation bundle binding mismatch")
    blind = bundle.blind_solve
    # Recognize only closed versioned DATA. Native callers pass their original
    # sealed expectation; a standalone projection confers no capability.
    protocol = (blind_protocol_for_prompt_version(blind.run.prompt_version)
                if blind_protocol is None else checked_blind_protocol(blind_protocol))
    if (blind.run.input_hash != blind_input(subject.source, subject.binding, blind_protocol=protocol).input_hash
            or blind.run.prompt_version != blind_prompt_version(protocol)
            or blind.run.profile_hash != subject.binding.profile_hash):
        raise ValueError("deliberation blind input mismatch")
    for report in bundle.reports:
        verify_review_report(report, make_review_request(subject.source, binding=subject.binding,
            validation_receipt=validation, role=report.role, protocol=report_protocol(report)))
    return bundle


def prepare_review_deliberation(*, source: LearningItemSourceV1, validation: ValidationReceiptV2,
                               bundle: ReviewBundle, lease: JobLeaseV1, budget_root_id: UUID,
                               resource_ceiling: ResourceAmounts,
                               blind_protocol: BlindProtocol | None = None) -> ReviewDeliberationPlanV1:
    """Structural private projection only; execution needs ORIGINAL live owner.

    Finite native callers retain exact finite_review_context around preparation
    and execution. Frozen spec/source hashes cannot rehydrate live capabilities.
    """
    lease = checked_model(lease, JobLeaseV1)
    subject = DeliberationSubjectV1(source=checked_model(source, LearningItemSourceV1), binding=bundle.binding)
    validation = checked_validation_receipt(validation)
    bundle = _verify_bundle(subject, validation, bundle, blind_protocol=blind_protocol)
    disputes = review_disputes(bundle)
    return ReviewDeliberationPlanV1(lease=lease, budget_root_id=budget_root_id,
        resource_ceiling=checked_model(resource_ceiling, ResourceAmounts), subject=subject, validation=validation,
        initial_bundle=bundle, disputes=disputes, state="disputed_pending" if disputes else "admission_pending")


def substantive_revision_hash(source: LearningItemSourceV1) -> str:
    """Ignore identity/version/title/difficulty/metadata-only green-washing.

    Actual public problem/interface/hints, scoring content and source claim
    declarations count. Source authority is STILL checked by the original owner.
    """
    source = checked_model(source, LearningItemSourceV1)
    return canonical_hash({"instruction": source.public.instruction_markdown,
        "content": source.public.content.model_dump(mode="json"),
        "hints": [h.model_dump(mode="json") for h in source.public.hints],
        "private_content": source.private.content.model_dump(mode="json"),
        "source_references": [ref.model_dump(mode="json") for ref in source.public.source_references]})


_NEUTRAL = {
    "deterministic_failure": "verify_deterministic_contract", "security": "verify_security_boundary",
    "unique_answer": "verify_unique_answer", "rubric_mismatch": "verify_public_scoring_consistency",
    "data_leakage": "verify_public_private_boundary", "adversarial_exploit": "verify_adversarial_cases",
    "technical": "verify_technical_contract", "curriculum": "verify_objective_coverage",
    "difficulty": "verify_difficulty_contract", "ambiguity": "verify_interpretations", "source": "verify_source_claims",
}


def _requirements(disputes: tuple[ReviewDisputeV1, ...]) -> tuple[NeutralReviewRequirementV1, ...]:
    # No old values/hashes, finding text, votes, identities or blind answer.
    return tuple(NeutralReviewRequirementV1.model_validate({
        "check": _NEUTRAL.get(d.safe_code, "verify_full_contract"),
        "pointers": tuple(ref.pointer for ref in d.references),
    }) for d in disputes)


class ReviewDeliberation:
    """In-process one-shot execution; durable replay/budget authority stays P3."""
    def __init__(self) -> None:
        self._started: set[str] = set()

    def execute(self, plan: ReviewDeliberationPlanV1, *, owner: ReviewDeliberationOwner | None,
                clock: Callable[[], datetime]) -> ReviewDeliberationResultV1:
        plan = checked_model(plan, ReviewDeliberationPlanV1)
        verified = prepare_review_deliberation(source=plan.subject.source, validation=plan.validation,
            bundle=plan.initial_bundle, lease=plan.lease, budget_root_id=plan.budget_root_id,
            resource_ceiling=plan.resource_ceiling)
        if verified != plan:
            raise ValueError("deliberation plan changed")
        key = plan.plan_hash
        if key in self._started:
            raise ValueError("deliberation already started")
        rounds: list[DeliberationRoundV1] = []
        spent = ResourceAmounts()
        subject, bundle, disputes = plan.subject, plan.initial_bundle, plan.disputes
        deadline = min(plan.lease.expires_at, plan.lease.parent_deadline, plan.lease.profile.parent_deadline_at,
            plan.lease.profile.bound_at + timedelta(milliseconds=plan.lease.profile.values.stage_deadline_ms))

        def finish(reason: str) -> ReviewDeliberationResultV1:
            return ReviewDeliberationResultV1(plan=plan, rounds=tuple(rounds), reserved_resources=spent,
                state="disputed_pending" if disputes else "admission_pending", safe_reason=reason,
                usage_state="unknown" if spent.positive() else "not_called")

        if not disputes:
            return finish("no_material_dispute")
        if owner is None:
            return finish("original_owner_pending")
        self._started.add(key)

        def fence(active: DeliberationSubjectV1) -> None:
            now = clock()
            if now.tzinfo is None or now < plan.lease.profile.bound_at or now >= deadline:
                raise DeliberationPending("deliberation_deadline_reached")
            if not owner.check_current(plan, active):
                raise DeliberationPending("source_lease_or_root_stale")

        priced: dict[int, ResourceAmounts] = {}

        def invoke(action: DeliberationAction, request: ActionRequest) -> ActionResult | None:
            nonlocal spent
            active = request.investigation.subject if isinstance(request, RevisionRequestV1) else request.subject
            fence(active)
            resources = checked_model(owner.resources(action, request), ResourceAmounts)
            if ((action == "investigate" and resources.investigation_rounds != 1)
                    or (action == "revise" and (resources.revision_rounds != 1 or resources.candidates != 1))
                    or (action != "investigate" and resources.investigation_rounds != 0)
                    or (action != "revise" and (resources.revision_rounds != 0 or resources.candidates != 0))
                    or (action == "review" and resources.requests < 7)):
                raise DeliberationPending("operation_resource_plan_invalid")
            total = ResourceAmounts(**{k: v + resources.as_dict()[k] for k, v in spent.as_dict().items()})
            if any(v > plan.resource_ceiling.as_dict()[k] for k, v in total.as_dict().items()):
                raise DeliberationPending("original_budget_exhausted")
            fence(active)
            reservation = owner.reserve(plan, action, request, resources, deadline_at=deadline)
            if reservation is None:
                raise DeliberationPending("original_reservation_pending")
            spent = total
            priced[id(request)] = resources
            try:
                fence(active)
                if not owner.recheck(reservation, plan, action, request, deadline_at=deadline):
                    raise DeliberationPending("committed_reservation_or_source_pending")
                fence(active)
                if action == "investigate" and isinstance(request, InvestigationRequestV1):
                    result: ActionResult | None = owner.investigate(request, deadline_at=deadline)
                elif action == "revise" and isinstance(request, RevisionRequestV1):
                    result = owner.revise(request, deadline_at=deadline)
                elif action == "validate" and isinstance(request, IndependentRecheckRequestV1):
                    result = owner.validate(request, deadline_at=deadline)
                elif action == "review" and isinstance(request, IndependentRecheckRequestV1):
                    result = owner.review(request, deadline_at=deadline)
                else:
                    raise DeliberationPending("operation_request_invalid")
                fence(active)
                if result is not None and not owner.verify_result(reservation, action, request, result):
                    raise DeliberationPending("original_result_issuer_pending")
                return result
            finally:
                # DTO token counts cannot attest aggregate usage, even on success.
                owner.retain_unknown(reservation)

        used_runs = {bundle.blind_solve.run.run_id, *(r.run.run_id for r in bundle.reports)}
        seen_content = {substantive_revision_hash(subject.source)}
        try:
            while disputes:
                fence(subject)
                values = plan.lease.profile.values
                if (len(rounds) + 1 >= values.discussion_rounds
                        or spent.investigation_rounds >= values.investigation_rounds
                        or spent.revision_rounds >= values.revision_rounds):
                    return finish("frozen_round_limit_reached")
                number = len(rounds) + 2
                investigation = InvestigationRequestV1(plan_hash=key, round_number=number,
                    subject=subject, bundle=bundle, disputes=disputes)
                raw = invoke("investigate", investigation)
                if type(raw) is not InvestigationEvidenceV1:
                    raise DeliberationPending("investigation_evidence_pending")
                evidence = checked_model(raw, InvestigationEvidenceV1)
                if (evidence.binding != subject.binding
                        or evidence.request_hash != canonical_hash(investigation.model_dump(mode="json"))
                        or set(evidence.addressed_disputes) != {d.dispute_key for d in disputes}
                        or len(set(evidence.addressed_disputes)) != len(evidence.addressed_disputes)):
                    raise DeliberationPending("investigation_evidence_stale")
                raw_revision = invoke("revise", RevisionRequestV1(investigation=investigation, evidence=evidence))
                if raw_revision is None:
                    return finish("new_evidence_review_input_pending")
                if type(raw_revision) is not DeliberationSubjectV1:
                    raise DeliberationPending("revision_subject_pending")
                revised = checked_model(raw_revision, DeliberationSubjectV1)
                old, new = subject.binding, revised.binding
                fingerprint = substantive_revision_hash(revised.source)
                if (new.candidate_key == old.candidate_key or new.version_key == old.version_key
                        or new.content_hash == old.content_hash or new.source_hash == old.source_hash
                        or fingerprint in seen_content
                        or revised.source.public.version == subject.source.public.version
                        or (new.profile_hash, new.policy_hash, new.runtime_key, new.risk_tier) != (
                            old.profile_hash, old.policy_hash, old.runtime_key, old.risk_tier)):
                    return finish("substantive_new_version_required")
                fence(revised)
                recheck = IndependentRecheckRequestV1(plan_hash=key, round_number=number,
                    subject=revised, requirements=_requirements(disputes))
                receipt = invoke("validate", recheck)
                if not isinstance(receipt, (LearningItemValidationReceiptV1, CandidateValidationV2)):
                    raise DeliberationPending("new_validation_pending")
                receipt = checked_validation_receipt(receipt)
                check_subject(revised.source, new, receipt)
                if isinstance(receipt, LearningItemValidationReceiptV1):
                    if receipt != validate_learning_item(revised.source) or not receipt.passed:
                        raise DeliberationPending("new_deterministic_validation_failed")
                else:
                    if receipt.state != "machine_verified":
                        raise DeliberationPending("new_deterministic_validation_failed")
                    if receipt.legacy_receipt is not None and receipt.legacy_receipt != validate_learning_item(revised.source):
                        raise DeliberationPending("new_deterministic_validation_failed")
                recheck = recheck.model_copy(update={"validation": receipt})
                fresh = invoke("review", recheck)
                if not isinstance(fresh, (ReviewBundleV2, ReviewBundleV3)):
                    raise DeliberationPending("independent_review_pending")
                fresh = _verify_bundle(revised, receipt, fresh,
                    blind_protocol=blind_protocol_for_prompt_version(plan.initial_bundle.blind_solve.run.prompt_version))
                fresh_runs = {fresh.blind_solve.run.run_id, *(r.run.run_id for r in fresh.reports)}
                if (used_runs & fresh_runs or fresh.bundle_id == bundle.bundle_id
                        or fresh.bundle_version <= bundle.bundle_version
                        or fresh.author_identity != plan.initial_bundle.author_identity
                        or report_protocol(fresh.reports[0]) != report_protocol(plan.initial_bundle.reports[0])):
                    raise DeliberationPending("independent_review_identity_stale")
                request_resources = priced[id(recheck)]
                runs = (fresh.blind_solve.run,) + tuple(r.run for r in fresh.reports)
                if (sum(r.max_output_tokens for r in runs) > request_resources.output_tokens
                        or any(r.timeout_seconds * 1000 > values.request_timeout_ms for r in runs)):
                    raise DeliberationPending("independent_review_limits_stale")
                fence(revised)
                fresh_disputes = review_disputes(fresh)
                rounds.append(DeliberationRoundV1(round_number=number, evidence=evidence,
                    subject=revised, validation=receipt, bundle=fresh, disputes=fresh_disputes))
                subject, bundle, disputes = revised, fresh, fresh_disputes
                used_runs.update(fresh_runs)
                seen_content.add(fingerprint)
            return finish("independent_admission_owner_pending")
        except DeliberationPending as exc:
            return finish(str(exc))
        except Exception:
            return finish("deliberation_operation_pending")
