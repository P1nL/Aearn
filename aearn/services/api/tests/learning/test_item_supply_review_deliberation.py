"""Executable OFFLINE fake-owner rounds; not native source/provider/publication proof."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.item_supply.diagnostic_policy import AutonomousEvidencePolicyV3, policy_for_hash
from app.services.learning.item_supply.jobs import JobLeaseV1
from app.services.learning.item_supply.parameter_profiles import FrozenProfileSnapshot, ParameterValuesV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_deliberation import (
    ReviewDeliberation, prepare_review_deliberation, substantive_revision_hash,
)
from app.services.learning.item_supply.review_deliberation_contracts import (
    DeliberationSubjectV1, InvestigationEvidenceV1, ReviewDeliberationPlanV1, ReviewDeliberationResultV1,
)
from app.services.learning.item_supply.review_provider import blind_solve_candidate, review_candidate_for_policy
from app.services.learning.item_supply.shared_review import SharedReviewPipeline, SharedReviewResult
from tests.learning.test_item_supply_autonomous_review import DIGEST, FakeScorer
from tests.learning.test_item_supply_evidenced_review import bundle_fixture, evidenced_ports

NOW = datetime(2026, 10, 9, tzinfo=UTC)
CEILING = ResourceAmounts(requests=100, input_tokens=100_000, output_tokens=100_000,
    execution_seconds=1000, fetches=20, candidates=20, revision_rounds=20, investigation_rounds=20)


def lease(*, discussion=4, revision=3, investigation=3):
    # Explicit offline values, not new production defaults or calibrated values.
    values = ParameterValuesV1(connection_timeout_ms=1000, first_token_timeout_ms=1000,
        stream_idle_timeout_ms=1000, request_timeout_ms=20_000, stage_deadline_ms=100_000,
        parent_deadline_ms=200_000, discussion_rounds=discussion,
        revision_rounds=revision, investigation_rounds=investigation)
    profile = FrozenProfileSnapshot(profile_key_hash=DIGEST, profile_hash=DIGEST, profile_version=1,
        values=values, bound_at=NOW, parent_deadline_at=NOW+timedelta(seconds=200))
    return JobLeaseV1(job_id=uuid4(), visibility="public", lease_owner="offline.worker", generation=1,
        state_version=1, expires_at=NOW+timedelta(seconds=150), parent_deadline=profile.parent_deadline_at, profile=profile)


def fixture(*, material=True, policy=None, ceiling=CEILING, **rounds):
    source, validation, binding, bundle, _ = bundle_fixture(policy=policy,
        label="field_bound_material_claim" if material else "known_good")
    plan = prepare_review_deliberation(source=source, validation=validation, bundle=bundle,
        lease=lease(**rounds), budget_root_id=uuid4(), resource_ceiling=ceiling)
    return plan


def revised_subject(subject, number, *, rename_only=False):
    data = subject.source.model_dump(mode="json")
    for side in ("public", "private"):
        data[side]["item_key"] = "offline.revision."+str(number)
        data[side]["version"] = "v"+str(number)
    if not rename_only:
        data["public"]["content"]["prompt_markdown"] += (
            "\n\nExplain which attribute is shared by all instances; revision " + str(number) + ".")
    source = LearningItemSourceV1.model_validate(data)
    binding = subject.binding.model_copy(update={"candidate_key": "offline.candidate."+str(number),
        "version_key": "offline.version."+str(number), "source_hash": source.source_hash, "content_hash": source.content_hash})
    return DeliberationSubjectV1(source=source, binding=binding)


class FakeOriginalOwner:
    """Explicit test double: root accounting persists across core/job instances.

    No fake machine seals/source grants or publisher. Real pure deterministic
    validation and existing fake JSON blind/six-peer ports execute every round.
    """
    def __init__(self, plan, *, mode="clean", remaining=None):
        self.plan, self.mode = plan, mode
        self.root = plan.budget_root_id
        self.remaining = remaining or CEILING
        self.reservations, self.calls, self.unknown, self.issued, self.rechecks = {}, [], [], {}, []
        self.cap_used = ResourceAmounts(requests=8, input_tokens=100, output_tokens=8192)
        self.current = True
        self.deny_reservation = False
        self.deny_recheck = False
        self.provider_payloads = []
        self.clock_now = NOW + timedelta(seconds=1)
        self.request_records = []

    def clock(self):
        return self.clock_now

    def check_current(self, plan, subject):
        return (self.current and plan.budget_root_id == self.root and plan.lease == self.plan.lease
            and plan.plan_hash == self.plan.plan_hash and subject.binding.profile_hash == DIGEST)

    def resources(self, action, request):
        return {
            "investigate": ResourceAmounts(investigation_rounds=1, fetches=1),
            "revise": ResourceAmounts(revision_rounds=1, candidates=1, requests=1, input_tokens=100, output_tokens=1024),
            "validate": ResourceAmounts(),  # Real PURE static validation, no IO and no invented request.
            "review": ResourceAmounts(requests=7, input_tokens=2000, output_tokens=7*1024),
        }[action]

    def reserve(self, plan, action, request, resources, *, deadline_at):
        key = (plan.budget_root_id, action, canonical_hash(request.model_dump(mode="json")))
        new_used = ResourceAmounts(**{k: v+resources.as_dict()[k] for k,v in self.cap_used.as_dict().items()})
        if self.deny_reservation or key in self.reservations or any(
            v > self.remaining.as_dict()[k] for k,v in new_used.as_dict().items()):
            return None
        token = object()
        self.reservations[key] = token
        self.cap_used = new_used
        self.request_records.append((action, request, resources, deadline_at))
        return token

    def recheck(self, reservation, plan, action, request, *, deadline_at):
        self.rechecks.append(action)
        return reservation in self.reservations.values() and not self.deny_recheck and self.check_current(plan,
            request.investigation.subject if action=="revise" else request.subject)

    def _issue(self, action, result):
        self.issued[id(result)] = (action, canonical_hash(result.model_dump(mode="json")))
        return result

    def investigate(self, request, *, deadline_at):
        self.calls.append("investigate")
        if self.mode == "transport_failure":
            raise RuntimeError("PRIVATE_PROVIDER_BODY_NOT_AN_ERROR")
        if self.mode == "expires_after_io":
            self.clock_now = deadline_at
        result = InvestigationEvidenceV1(binding=request.subject.binding,
            request_hash=canonical_hash(request.model_dump(mode="json")), evidence_version="offline.evidence."+str(request.round_number),
            evidence_hashes=(canonical_hash((request.subject.binding.source_hash, request.round_number)),),
            addressed_disputes=tuple(d.dispute_key for d in request.disputes))
        if self.mode == "cross_round":
            result = result.model_copy(update={"request_hash": "0"*64})
        return self._issue("investigate", result)

    def revise(self, request, *, deadline_at):
        self.calls.append("revise")
        if self.mode == "evidence_only":
            return None
        result = revised_subject(request.investigation.subject, request.investigation.round_number,
            rename_only=self.mode=="rename_only")
        if self.mode == "new_profile":
            result = result.model_copy(update={"binding": result.binding.model_copy(update={"profile_hash": "1"*64})})
        return self._issue("revise", result)

    def validate(self, request, *, deadline_at):
        self.calls.append("validate")
        assert request.validation is None
        result = validate_learning_item(request.subject.source)
        assert result.passed
        if self.mode == "fake_validation":
            checks = list(result.checks)
            checks[0] = checks[0].model_copy(update={"proof_hash": "f"*64})
            result = result.model_copy(update={"checks": tuple(checks)})
        return self._issue("validate", result)

    def review(self, request, *, deadline_at):
        self.calls.append("review")
        payload = request.model_dump(mode="json")
        assert not {"bundle", "verdict", "reports", "blind_solve", "solution_hash"} & payload.keys()
        assert not {"problem", "expected_behavior", "counterexample", "report_hash", "role"} & payload["requirements"][0].keys()
        source, binding = request.subject.source, request.subject.binding
        solver, reviewers, clients = evidenced_ports(
            label="field_bound_material_claim" if self.mode=="still_blocked" else "known_good",
            prefix="round-"+str(request.round_number))
        blind = blind_solve_candidate(source, binding=binding, author_identity="author", solver=solver, scorer=FakeScorer())
        bundle = review_candidate_for_policy(source, binding=binding, validation_receipt=request.validation,
            author_identity="author", blind_solve_receipt=blind, reviewers=reviewers,
            policy=policy_for_hash(binding.policy_hash), bundle_version=request.round_number)
        self.provider_payloads.extend(json.loads(client.calls[0][0][1]["content"]) for client in clients)
        if self.mode == "old_run":
            # A genuinely new output with illegally recycled provider run identity.
            reports = list(bundle.reports)
            reports[0] = reports[0].model_copy(update={"run": reports[0].run.model_copy(update={
                "run_id": self.plan.initial_bundle.reports[0].run.run_id})})
            bundle = bundle.model_copy(update={"reports": tuple(reports)})
        if self.mode == "missing_role":
            bundle = bundle.model_copy(update={"reports": bundle.reports[:-1]})
        if self.mode == "old_input":
            reports = list(bundle.reports)
            reports[0] = reports[0].model_copy(update={"run": reports[0].run.model_copy(update={"input_hash": "0"*64})})
            bundle = bundle.model_copy(update={"reports": tuple(reports)})
        return self._issue("review", bundle)

    def verify_result(self, reservation, action, request, result):
        return (self.mode != "unverified_issuer" and reservation in self.reservations.values()
            and self.issued.get(id(result)) == (action, canonical_hash(result.model_dump(mode="json"))))

    def retain_unknown(self, reservation):
        self.unknown.append(reservation)


def run(plan, owner=None, core=None):
    return (core or ReviewDeliberation()).execute(plan, owner=owner, clock=owner.clock if owner else lambda: NOW)


@pytest.mark.parametrize("policy", [None, AutonomousEvidencePolicyV3()])
def test_executable_dispute_revision_full_independent_review_retains_original_minority(policy):
    plan = fixture(policy=policy)
    owner = FakeOriginalOwner(plan)
    before = plan.initial_bundle.model_dump_json()
    result = run(plan, owner)
    assert owner.calls == ["investigate", "revise", "validate", "review"]
    assert owner.rechecks == owner.calls
    assert len(owner.unknown) == 4 and result.usage_state == "unknown"
    assert result.state == "admission_pending" and result.safe_reason == "independent_admission_owner_pending"
    assert not result.publication_enabled and not result.admission_eligible
    assert len(result.rounds) == 1 and not result.rounds[0].disputes
    assert len(result.rounds[0].bundle.reports) == 6
    assert result.plan.initial_bundle.model_dump_json() == before
    assert result.plan.disputes[0].report_hash == result.plan.initial_bundle.reports[2].report_hash
    assert result.plan.disputes[0].references == result.plan.initial_bundle.reports[2].findings[0].references
    assert result.rounds[0].subject.binding != plan.subject.binding
    assert result.rounds[0].validation == validate_learning_item(result.rounds[0].subject.source)
    assert owner.cap_used.requests == 16  # Original eight calls were NOT cleared.
    assert all("requirements" not in payload for payload in owner.provider_payloads)
    assert all("reports" not in payload and "blind_solve" not in payload for payload in owner.provider_payloads)
    assert all(record[3] == NOW+timedelta(seconds=100) for record in owner.request_records)
    assert ReviewDeliberationResultV1.model_validate_json(result.model_dump_json()) == result


def test_no_material_dispute_early_stop_does_not_call_owner():
    plan = fixture(material=False)
    owner = FakeOriginalOwner(plan)
    result = run(plan, owner)
    assert not owner.calls and not owner.reservations
    assert result.safe_reason == "no_material_dispute" and result.usage_state == "not_called"


@pytest.mark.parametrize("why", ["owner", "deadline", "stale", "reservation", "root", "cap_zero", "profile_limit"])
def test_no_original_owner_fence_or_allowance_means_zero_new_calls(why):
    plan = fixture(discussion=1) if why=="profile_limit" else fixture()
    if why=="cap_zero":
        plan = plan.model_copy(update={"resource_ceiling": CEILING.model_copy(update={"investigation_rounds":0})})
    owner = FakeOriginalOwner(plan)
    if why=="deadline":
        owner.clock_now = NOW+timedelta(seconds=100)
    if why=="stale":
        owner.current = False
    if why=="reservation":
        owner.deny_reservation = True
    if why=="root":
        owner.root = uuid4()
    result = run(plan, None if why=="owner" else owner)
    assert result.state == "disputed_pending" and not result.rounds
    assert not owner.calls and not owner.reservations and result.usage_state == "not_called"


@pytest.mark.parametrize("mode,expected_calls,reason", [
    ("evidence_only", 2, "new_evidence_review_input_pending"),
    ("rename_only", 2, "substantive_new_version_required"),
    ("new_profile", 2, "substantive_new_version_required"),
    ("fake_validation", 3, "new_deterministic_validation_failed"),
    ("old_run", 4, "independent_review_identity_stale"),
    ("missing_role", 4, "deliberation_operation_pending"),
    ("old_input", 4, "deliberation_operation_pending"),
    ("cross_round", 1, "investigation_evidence_stale"),
    ("unverified_issuer", 1, "original_result_issuer_pending"),
    ("transport_failure", 1, "deliberation_operation_pending"),
    ("expires_after_io", 1, "deliberation_deadline_reached"),
])
def test_failed_or_unchanged_revision_cannot_wash_old_blocker(mode, expected_calls, reason):
    plan = fixture()
    owner = FakeOriginalOwner(plan, mode=mode)
    result = run(plan, owner)
    assert len(owner.calls)==expected_calls and len(owner.unknown)==expected_calls
    assert result.safe_reason==reason and result.state=="disputed_pending" and not result.rounds
    assert result.plan.initial_bundle==plan.initial_bundle and result.usage_state=="unknown"
    assert "PRIVATE_PROVIDER_BODY" not in result.model_dump_json()


def test_rename_only_changes_legacy_hash_but_not_substantive_hash():
    plan = fixture()
    renamed = revised_subject(plan.subject, 2, rename_only=True)
    assert renamed.source.content_hash != plan.subject.source.content_hash
    assert renamed.source.public.item_key != plan.subject.source.public.item_key
    assert substantive_revision_hash(renamed.source) == substantive_revision_hash(plan.subject.source)


def test_committed_reservation_recheck_failure_retains_unknown_without_io():
    plan = fixture()
    owner = FakeOriginalOwner(plan)
    owner.deny_recheck = True
    result = run(plan, owner)
    assert not owner.calls and len(owner.reservations)==len(owner.unknown)==1
    assert result.safe_reason=="committed_reservation_or_source_pending" and result.usage_state=="unknown"


@pytest.mark.parametrize("dimension", ["discussion", "revision", "investigation"])
def test_round_bounds_are_frozen_existing_profile_not_fixed_two_rounds(dimension):
    settings = {"discussion":5, "revision":4, "investigation":4}
    settings[dimension] = 3 if dimension=="discussion" else 2
    plan = fixture(**settings)
    owner = FakeOriginalOwner(plan, mode="still_blocked")
    result = run(plan, owner)
    assert len(result.rounds)==2 and owner.calls==["investigate","revise","validate","review"]*2
    assert result.safe_reason=="frozen_round_limit_reached" and result.state=="disputed_pending"
    assert len(result.plan.disputes)==1 and all(len(r.disputes)==1 for r in result.rounds)


def test_original_root_cap_and_replay_survive_new_core_not_new_wallet():
    plan = fixture()
    owner = FakeOriginalOwner(plan, remaining=CEILING.model_copy(update={"requests":10}))
    result = run(plan, owner)
    assert result.state=="disputed_pending" and owner.calls==["investigate","revise","validate"]
    assert result.safe_reason=="original_reservation_pending" and owner.cap_used.requests==9
    replay = run(plan, owner)  # New orchestrator instance, same durable fake budget owner.
    assert replay.safe_reason=="original_reservation_pending" and len(owner.calls)==3
    changed_lease = plan.model_copy(update={"lease": plan.lease.model_copy(update={"job_id":uuid4()})})
    reroute = run(changed_lease, owner)
    assert reroute.safe_reason=="source_lease_or_root_stale" and len(owner.calls)==3


def test_plan_dispute_and_source_hash_tampering_rejected_before_owner_io():
    plan = fixture()
    owner = FakeOriginalOwner(plan)
    tampered = plan.model_copy(update={"disputes": (plan.disputes[0].model_copy(update={"finding_hash":"0"*64}),)})
    with pytest.raises(ValueError, match="plan changed"):
        run(tampered, owner)
    stale = plan.model_copy(update={"subject":plan.subject.model_copy(update={
        "binding":plan.subject.binding.model_copy(update={"source_hash":"0"*64})})})
    with pytest.raises(ValueError):
        run(stale, owner)
    assert not owner.calls and not owner.reservations
    assert ReviewDeliberationPlanV1.model_validate_json(plan.model_dump_json()) == plan


def test_core_one_shot_does_not_dispatch_repeat_to_green():
    plan = fixture()
    owner = FakeOriginalOwner(plan)
    core = ReviewDeliberation()
    run(plan, owner, core)
    with pytest.raises(ValueError, match="already started"):
        run(plan, owner, core)
    assert len(owner.calls)==4


def test_explicit_shared_followup_projects_zero_caps_without_changing_old_result_hash(monkeypatch):
    """Execute the actual post-review route with narrowly labeled owner doubles."""
    plan = fixture()
    bundle = plan.initial_bundle
    p = SimpleNamespace(lease=plan.lease, binding=plan.subject.binding, source=plan.subject.source,
        validation=plan.validation, author_identity=bundle.author_identity, spec=None, review_protocol="evidenced-v1",
        request=SimpleNamespace(materials=()), provider_identities=(bundle.blind_solve.run.provider_identity,)+
            tuple(r.run.provider_identity for r in bundle.reports))
    result = SharedReviewResult(bundle.blind_solve, bundle, "peer_review_staged")
    legacy_hash = canonical_hash({"blind":bundle.blind_solve.model_dump(mode="json"),
        "bundle":bundle.model_dump(mode="json"), "reason":"peer_review_staged", "ambiguity":None})
    assert SharedReviewPipeline._result_hash(result)==legacy_hash
    pipeline = object.__new__(SharedReviewPipeline)
    checked = []
    pipeline.artifacts = SimpleNamespace(require_owner=lambda: checked.append("owner"))
    pipeline._issued = lambda prepared: checked.append("issued")
    pipeline._result = lambda prepared, completed: SimpleNamespace(verify=lambda score,source: True)
    pipeline._fence = lambda prepared: checked.append("fence")
    pipeline._require_settlement = lambda prepared: checked.append("settled")
    pipeline.conn = SimpleNamespace(info=SimpleNamespace(transaction_status=0))
    monkeypatch.setattr("app.services.learning.item_supply.shared_review.server_clock", lambda *args: NOW)
    monkeypatch.setattr("app.services.learning.item_supply.shared_review.finite_review_context", lambda *args, **kwargs: nullcontext())
    limits = [{"resource_kind":k, "cap_amount":0 if k in {"revision_rounds","investigation_rounds"} else v}
        for k,v in CEILING.as_dict().items()]
    pipeline.budget = SimpleNamespace(_job_meta=lambda *args,**kwargs: {"root_id":plan.budget_root_id},
        _active_limits=lambda *args: (limits, []))
    # Non-finite curated KC does not need exact finite descriptor context.
    followup = pipeline.prepare_review_followup(p, result)
    assert checked==["owner","issued","fence","settled"]
    assert followup.budget_root_id==plan.budget_root_id and len(followup.disputes)==1
    assert followup.resource_ceiling.revision_rounds==followup.resource_ceiling.investigation_rounds==0
    assert SharedReviewPipeline._result_hash(result)==legacy_hash
    assert run(followup).safe_reason=="original_owner_pending"
    owner = FakeOriginalOwner(followup)
    assert run(followup, owner).safe_reason=="original_budget_exhausted" and not owner.calls
    forged = replace(result, safe_reason="changed")
    pipeline._result = lambda prepared, completed: (_ for _ in ()).throw(ValueError("original instance required"))
    with pytest.raises(ValueError, match="original instance"):
        pipeline.prepare_review_followup(p, forged)
