"""Bounded independent DTO adversaries, never native/PG/provider acceptance.

Execution-shaped scaffolding is unauthenticated: these fixtures cannot confer
runner, source, publication, Attempt or Gate authority, or upgrade old policy.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from aearn_shared.execution import SafeExecutionStatus, SandboxInputV1, SandboxResultV1

from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import LearningItemRiskTier, LearningItemSourceV1, canonical_hash, canonical_json
from app.services.learning.item_bank.review_contracts import REQUIRED_REVIEW_ROLES
from app.services.learning.item_supply.admission import evaluate_admission, evaluate_admission_v2
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.diagnostic_policy import (
    AdmissionEvaluation, AdmissionEvaluationV3, AutonomousEvidencePolicyV3, EvidencePolicy,
    ReviewBundle, ReviewBundleV3, completed_blind_allowed, diagnostic_warnings, parse_bundle, policy_for_hash,
)
from app.services.learning.item_supply.review_contracts_v2 import (
    AdmissionEvidenceV2, AdmissionEvaluationV2, BlindScoreV2, BlindSolveReceiptV2,
    CandidateBindingV2, ProbeOutcomeV2, ProviderIdentityV2, ReviewBundleV2, receipt_digest,
)
from app.services.learning.item_supply.review_provider import (
    AutonomousReviewError, JsonBlindSolverV2, JsonReviewerV2, blind_solve_candidate,
    review_candidate, review_candidate_for_policy, review_resource_plan,
)
from app.services.learning.item_supply.storage_contracts import AutonomousEvidencePolicyV2
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution import _candidate_cases
from app.services.learning.item_supply.sandbox.execution_contracts import RunnerTerminalReceipt
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2, validate_candidate
from app.services.llm.llm_client import LLMJsonResponse
from tests.learning.test_item_supply_v2_execution_review import (
    PROFILE_HASH, binding_for, evidence_for, live_validation_fixture, source_fixture,
)
from tests.learning.test_item_supply_python_goal_scorer import ProtocolReceipt
from tests.learning.test_item_supply_shared_validation import _candidate

WRONG_ANSWER = "UNIT_PRIVATE_SOLVER_WRONG"
CORRECT_ANSWER = "UNIT_PRIVATE_SOLVER_CORRECT"


@dataclass
class RecordingClient:
    content: dict[str, object]
    model: str = "independent-unit-model"
    request_attempt_bound: int = 1
    calls: list[tuple[dict[str, str], ...]] = field(default_factory=list)
    error: Exception | None = None

    def complete_json(
        self, messages: Sequence[Mapping[str, str]], *, max_tokens: int | None = None,
        timeout_seconds: float | None = None, output_schema: Mapping[str, object] | None = None,
        schema_name: str = "response", capture_provider_body: bool = True,
    ) -> LLMJsonResponse:
        assert (max_tokens, timeout_seconds, capture_provider_body) == (512, 10, False)
        assert output_schema is not None
        self.calls.append(tuple(dict(message) for message in messages))
        if self.error is not None:
            raise self.error
        return LLMJsonResponse(content=self.content, model=self.model)


class UnitScorer:
    def score(self, source: LearningItemSourceV1, *, answer: str) -> BlindScoreV2:
        return BlindScoreV2(passed=answer == CORRECT_ANSWER, scorer_identity="independent-unit-scorer",
            scorer_version="unit-v1", receipt_hash=canonical_hash((source.source_hash, answer)))


@dataclass(frozen=True)
class Subject:
    source: LearningItemSourceV1
    validation: CandidateValidationV2
    binding: CandidateBindingV2
    policy: EvidencePolicy
    evidence: AdmissionEvidenceV2


@dataclass(frozen=True)
class Ports:
    solver: JsonBlindSolverV2
    reviewers: tuple[JsonReviewerV2, ...]
    clients: tuple[RecordingClient, ...]


def subject(*, policy: EvidencePolicy | None = None, kind: str = "code",
            risk: LearningItemRiskTier = LearningItemRiskTier.MEDIUM) -> Subject:
    policy = policy if policy is not None else AutonomousEvidencePolicyV3()
    if kind == "static":
        source = LearningItemSourceLoader().load(curated_learning_item_source_root(), "knowledge-class-attribute-v1.json").source
        validation = validate_candidate(source)
    else:
        source = source_fixture(sql=kind == "sql", risk=risk)
        validation = live_validation_fixture(source)
    binding = binding_for(source).model_copy(update={"policy_hash": policy.policy_hash})
    if kind == "static":
        evidence = AdmissionEvidenceV2(binding=binding, validation_receipt_hash=receipt_digest(validation),
            source_current=True, source_claim_receipt_hashes=(canonical_hash("unit-claim"),),
            coverage_proof_hash=canonical_hash("unit-coverage"), scorer_available=True,
            probes=tuple(ProbeOutcomeV2.model_validate({"probe": name, "passed": True, "receipt_hash": canonical_hash(name)})
                for name in ("correct", "incorrect", "ambiguity")))
    else:
        evidence = evidence_for(validation, binding)
    return Subject(source, validation, binding, policy, evidence)


def ports(*, wrong: bool = True, prefix: str = "first", model: str = "independent-unit-model") -> Ports:
    clients = (RecordingClient({"answer": WRONG_ANSWER if wrong else CORRECT_ANSWER}, model),) + tuple(
        RecordingClient({"verdict": "approved", "findings": []}, model) for _ in REQUIRED_REVIEW_ROLES)

    def identity(name: str) -> ProviderIdentityV2:
        return ProviderIdentityV2(identity=prefix + "-" + name, provider="unit-provider", model=model)

    solver = JsonBlindSolverV2(clients[0], identity=identity("solver"), profile_hash=PROFILE_HASH,
                              timeout_seconds=10, max_output_tokens=512)
    reviewers = tuple(JsonReviewerV2(client, role=role, identity=identity(role.value), profile_hash=PROFILE_HASH,
        timeout_seconds=10, max_output_tokens=512) for role, client in zip(REQUIRED_REVIEW_ROLES, clients[1:], strict=True))
    return Ports(solver, reviewers, clients)


def solve(s: Subject, p: Ports) -> BlindSolveReceiptV2:
    return blind_solve_candidate(s.source, binding=s.binding, author_identity="author", solver=p.solver, scorer=UnitScorer())


def review(s: Subject, p: Ports, *, version: int = 1) -> ReviewBundle:
    return review_candidate_for_policy(s.source, binding=s.binding, validation_receipt=s.validation, author_identity="author",
        blind_solve_receipt=solve(s, p), reviewers=p.reviewers, policy=s.policy, bundle_version=version)


def evaluate(s: Subject, bundle: ReviewBundle, *, evidence: AdmissionEvidenceV2 | None = None,
             second: ReviewBundle | None = None, enabled: bool = True) -> AdmissionEvaluation:
    return evaluate_admission(s.source, binding=s.binding, policy=s.policy, validation_receipt=s.validation,
        author_identity="author", bundle=bundle, evidence=evidence if evidence is not None else s.evidence,
        second_bundle=second, enabled=enabled)


@pytest.mark.parametrize("kind", ("code", "sql", "static"))
def test_completed_wrong_is_diagnostic_only_and_six_roles_never_receive_solver_output(kind: str) -> None:
    s, p = subject(kind=kind), ports()
    plan = review_resource_plan(s.source, binding=s.binding, validation_receipt=s.validation,
                               solver=p.solver, reviewers=p.reviewers)
    assert plan.requests == 7 and plan.output_tokens == 7 * 512
    assert not any(client.calls for client in p.clients)
    bundle = review(s, p)
    result = evaluate(s, bundle)
    assert type(bundle) is ReviewBundleV3 and type(result) is AdmissionEvaluationV3
    assert result.disposition == "eligible_internal" and result.safe_reasons == ("publication_port_pending",)
    assert diagnostic_warnings(result) == ("blind_solution_incorrect",)
    assert bundle.blind_solve.score.passed is False
    assert bundle.blind_solve.solution_hash == canonical_hash(WRONG_ANSWER)
    assert bundle.blind_solve.run.output_hash == canonical_hash({"answer": WRONG_ANSWER})
    assert bundle.publication_enabled is result.publication_enabled is False
    assert result.bundle_hashes == (bundle.bundle_hash,)
    restored = parse_bundle(json.loads(bundle.model_dump_json()))
    restored_result = AdmissionEvaluationV3.model_validate_json(result.model_dump_json())
    assert type(restored) is ReviewBundleV3 and restored.bundle_hash == bundle.bundle_hash
    assert restored_result.evaluation_hash == result.evaluation_hash
    assert diagnostic_warnings(restored_result) == ("blind_solution_incorrect",)
    assert all(len(client.calls) == 1 for client in p.clients)
    forbidden = {"blind_solve", "blind_solve_receipt", "solution_hash", "score", "reports", "diagnostic_warnings"}
    for role, client in zip(REQUIRED_REVIEW_ROLES, p.clients[1:], strict=True):
        payload = json.loads(client.calls[0][1]["content"])
        assert payload["role"] == role.value and payload["binding"]["policy_hash"] == s.policy.policy_hash
        assert not forbidden.intersection(payload)
        serialized = canonical_json(client.calls[0])
        assert WRONG_ANSWER not in serialized and CORRECT_ANSWER not in serialized
        assert bundle.blind_solve.solution_hash not in serialized
        assert str(bundle.blind_solve.run.run_id) not in serialized
    for report in bundle.reports:
        assert all(str(report.run.run_id) not in canonical_json(client.calls) for client in p.clients[1:])


@pytest.mark.parametrize("wrong", (True, False))
def test_missing_roles_and_invalid_machine_receipt_fail_closed_before_review_io(wrong: bool) -> None:
    s, p = subject(), ports(wrong=wrong)
    blind = solve(s, p)
    with pytest.raises(AutonomousReviewError, match="six_review_roles_required"):
        review_candidate_for_policy(s.source, binding=s.binding, validation_receipt=s.validation,
            author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers[:-1], policy=s.policy)
    bad_check = s.validation.checks[0].model_copy(update={"status": "failed"})
    malformed = s.validation.model_copy(update={"checks": (bad_check,) + s.validation.checks[1:]})
    with pytest.raises(ValueError):
        review_candidate_for_policy(s.source, binding=s.binding, validation_receipt=malformed,
            author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers, policy=s.policy)
    assert not any(client.calls for client in p.clients[1:])
    bundle = review(s, p)
    truncated = bundle.model_copy(update={"reports": bundle.reports[:-1]})
    assert evaluate(s, truncated).safe_reasons == ("invalid_or_stale_evidence",)
    invalid_subject = Subject(s.source, malformed, s.binding, s.policy, s.evidence)
    assert evaluate(invalid_subject, bundle).disposition == "quarantine"


@pytest.mark.parametrize("mutation", ("failed_probe", "misjudgment", "probe_hash", "validation_hash", "execution_hash", "content_hash"))
def test_votes_cannot_override_blockers_or_hash_tampering(mutation: str) -> None:
    s, p = subject(), ports()
    bundle = review(s, p)
    bad_probe = s.evidence.probes[0].model_copy(update={"passed": False})
    stale_probe = s.evidence.probes[-1].model_copy(update={"receipt_hash": "0" * 64})
    variants: dict[str, dict[str, object]] = {
        "failed_probe": {"probes": (bad_probe,) + s.evidence.probes[1:]},
        "misjudgment": {"known_misjudgments": 1},
        "probe_hash": {"probes": s.evidence.probes[:-1] + (stale_probe,)},
        "validation_hash": {"validation_receipt_hash": "0" * 64},
        "execution_hash": {"execution_receipt_hash": "0" * 64},
        "content_hash": {"binding": s.binding.model_copy(update={"content_hash": "0" * 64})},
    }
    updates = variants[mutation]
    result = evaluate(s, bundle, evidence=s.evidence.model_copy(update=updates))
    assert result.disposition == "quarantine"


def test_policy_dispatch_and_cross_version_splicing_cannot_authorize_admission() -> None:
    s, p = subject(), ports()
    bundle = review(s, p)
    assert type(policy_for_hash(s.policy.policy_hash)) is AutonomousEvidencePolicyV3
    assert type(policy_for_hash(AutonomousEvidencePolicyV2().policy_hash)) is AutonomousEvidencePolicyV2
    with pytest.raises(ValueError):
        policy_for_hash("0" * 64)
    with pytest.raises(ValueError):
        parse_bundle({**json.loads(bundle.model_dump_json()), "policy_version": "autonomous_evidence_policy_v2"})
    disguised_v2 = ReviewBundleV2.model_validate_json(canonical_json({
        **bundle.model_dump(mode="json"), "schema_version": "item_supply_review_bundle_v2",
        "policy_version": "autonomous_evidence_policy_v2",
    }))
    assert evaluate(s, disguised_v2).safe_reasons == ("invalid_or_stale_evidence",)
    legacy_subject = Subject(s.source, s.validation, s.binding, AutonomousEvidencePolicyV2(), s.evidence)
    assert evaluate(legacy_subject, bundle).disposition == "quarantine"
    # Deliberately inject the wrong runtime DTO at the legacy typed boundary.
    old = evaluate_admission_v2(s.source, binding=s.binding, policy=cast(AutonomousEvidencePolicyV2, s.policy),
        validation_receipt=s.validation, author_identity="author", bundle=disguised_v2,
        evidence=s.evidence, enabled=True)
    assert type(old) is AdmissionEvaluationV2 and old.disposition == "quarantine"
    assert "diagnostic_warnings" not in old.model_dump(mode="json")
    copied_policy = s.policy.model_copy(update={"required_review_roles": s.policy.required_review_roles[:-1]})
    tampered = Subject(s.source, s.validation, s.binding, copied_policy, s.evidence)
    assert evaluate(tampered, bundle).disposition == "quarantine"


@pytest.mark.parametrize("failure", ("timeout", "malformed"))
def test_solver_runtime_failure_never_becomes_completed_wrong_or_review(failure: str) -> None:
    s, p = subject(), ports()
    if failure == "timeout":
        p.clients[0].error = TimeoutError("UNIT_PRIVATE_TIMEOUT")
    else:
        p.clients[0].content = {"not_answer": "UNIT_PRIVATE_MALFORMED"}
    with pytest.raises(AutonomousReviewError, match="blind_solve_failed") as error:
        solve(s, p)
    assert "UNIT_PRIVATE" not in str(error.value)
    assert len(p.clients[0].calls) == 1 and not any(client.calls for client in p.clients[1:])


def test_high_risk_and_feature_flag_are_not_weakened_by_diagnostic_policy() -> None:
    s, p = subject(risk=LearningItemRiskTier.HIGH), ports()
    first = review(s, p)
    result = evaluate(s, first)
    assert result.disposition == "quarantine"
    assert "independent_second_bundle_missing" in result.safe_reasons
    correlated = review(s, ports(prefix="second"), version=2)
    assert "independent_second_bundle_missing" in evaluate(s, first, second=correlated).safe_reasons
    missing_adapter = evaluate(s, first, evidence=s.evidence.model_copy(update={"critical_risks": ("unit-critical-risk",)}))
    assert missing_adapter.disposition == "quarantine" and "critical_risk_adapter_unverified" in missing_adapter.safe_reasons
    disabled = evaluate(s, first, enabled=False)
    assert disabled.disposition == "blocked" and disabled.safe_reasons == ("feature_disabled",)


def golden_v2() -> tuple[AutonomousEvidencePolicyV2, ReviewBundleV2, AdmissionEvaluationV2, AdmissionEvaluationV2]:
    policy = AutonomousEvidencePolicyV2()
    s = subject(policy=policy, kind="static")
    original = review(s, ports(wrong=False))
    assert type(original) is ReviewBundleV2
    bundle = original.model_copy(update={
        "bundle_id": UUID(int=100),
        "blind_solve": original.blind_solve.model_copy(update={"run": original.blind_solve.run.model_copy(update={"run_id": UUID(int=1)})}),
        "reports": tuple(report.model_copy(update={"run": report.run.model_copy(update={"run_id": UUID(int=index)})})
                         for index, report in enumerate(original.reports, start=2)),
    })
    passed = evaluate(s, bundle)
    wrong = bundle.model_copy(update={"blind_solve": bundle.blind_solve.model_copy(update={
        "score": bundle.blind_solve.score.model_copy(update={"passed": False}),
    })})
    failed = evaluate(s, wrong)
    assert type(passed) is type(failed) is AdmissionEvaluationV2
    return policy, bundle, passed, failed


def test_v2_default_policy_bundle_and_evaluations_keep_frozen_golden_hashes() -> None:
    policy, bundle, passed, failed = golden_v2()
    assert policy.model_dump(mode="json") == {
        "schema_version": "autonomous_evidence_policy_v2", "policy_version": "autonomous_evidence_policy_v2",
        "publication_enabled": False,
        "required_review_roles": ["curriculum", "difficulty", "technical", "ambiguity", "security", "adversarial"],
        "risk_adapter_required": True, "independent_second_bundle_required": True,
    }
    assert passed.disposition == "eligible_internal" and failed.safe_reasons == ("blind_solve_failed",)
    assert all("diagnostic_warnings" not in obj.model_dump(mode="json") for obj in (bundle, passed, failed))
    assert (policy.policy_hash, bundle.bundle_hash, passed.evaluation_hash, failed.evaluation_hash) == (
        "7a5c4801f032843e12bac530991ea1cd34ea76ace08d8e6eb2c50dbeadea43ab",
        "21f8906f111a420c8d93ede3b34370886f72c0baa86c84c1f1ac0e2ece41da25",
        "f40bd950ca02b6f2ed23ce1ecec8e230654f850188874b6ce4bd881a638b6522",
        "15bb156b107f76b8435a5e956ec6f00967bcd221ca7a6fbb742cc4764f78ef70",
    )


def test_rejected_deterministic_validation_never_invokes_reviews() -> None:
    s, p = subject(), ports()
    blind = solve(s, p)
    failed = s.validation.checks[0].model_copy(update={"status": "failed", "safe_code": "unit_failure"})
    rejected = s.validation.model_copy(update={"state": "rejected", "checks": (failed,) + s.validation.checks[1:]})
    with pytest.raises(AutonomousReviewError, match="deterministic_validation_failed"):
        review_candidate_for_policy(s.source, binding=s.binding, validation_receipt=rejected,
            author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers, policy=s.policy)
    assert not any(client.calls for client in p.clients[1:])


def test_presentation_v3_and_extra_boolean_do_not_upgrade_v2_policy() -> None:
    # Only a DTO-boundary check, not evidence of real finite-spec/author binding.
    s = subject(policy=AutonomousEvidencePolicyV2())
    source = s.source.model_copy(update={"blueprint": s.source.blueprint.model_copy(update={"version": "finite-public-spec-v3"})})
    validation = live_validation_fixture(source)
    binding = binding_for(source)
    presented = Subject(source, validation, binding, s.policy, evidence_for(validation, binding))
    p = ports()
    with pytest.raises(AutonomousReviewError, match="blind_solve_not_verified"):
        review(presented, p)
    assert not any(client.calls for client in p.clients[1:])
    with pytest.raises(ValueError):
        AutonomousEvidencePolicyV2.model_validate({"diagnostic_blind": True})


@pytest.mark.parametrize("target", ("python-state-update-v1", "sqlite-predicate-order-v1"))
@pytest.mark.parametrize("outcome", ("semantic_wrong", "timeout", "unavailable", "malformed", "case_infrastructure", "missing_cases"))
def test_original_native_blind_scorer_distinguishes_wrong_from_infrastructure(target: str, outcome: str) -> None:
    """Real scorer methods, explicit unauthenticated runner; NOT OS/493 grants."""
    spec, _, source = _candidate(target)
    current = binding_for(source).model_copy(update={"policy_hash": AutonomousEvidencePolicyV3().policy_hash})
    records: list[RunnerTerminalReceipt] = []
    _, _, _, tests = _candidate_cases(source)

    def run(*, request: SandboxInputV1, run_id: UUID, probe_name: str) -> RunnerTerminalReceipt:
        facts = []
        for test in tests:
            fact = dict(id=test["id"], status="success", code="python_terminal" if spec.python_goal else "sqlite_terminal")
            if spec.python_goal:
                fact.update(stdout=test["expected_output_json"]["stdout"], goal_contract_id=spec.python_goal.goal_contract_id,
                    goal_contract_hash=spec.python_goal.target_hash, goal_status="unsatisfied", goal_satisfied=False)
            else:
                fact.update(columns=test["expected_output"]["columns"], rows=[])
            if outcome == "case_infrastructure":
                fact.update(status="error", code="runtime_unavailable")
            facts.append(fact)
        result = SandboxResultV1(status=SafeExecutionStatus.SUCCESS, diagnostic_code="item_supply_facts_v1",
            stdout="not-json" if outcome == "malformed" else json.dumps({"cases": [] if outcome == "missing_cases" else facts}))
        if outcome in {"timeout", "unavailable"}:
            result = SandboxResultV1.model_validate({"status": outcome, "diagnostic_code": "unit_infrastructure"})
        # This protocol double declares shape, not a real bridge/image seal.
        receipt = cast(RunnerTerminalReceipt, ProtocolReceipt(run_id, probe_name,
            canonical_hash(request.model_dump(mode="json")), result,
            lock_fingerprint=spec.coverage_blueprint.scope.runtime_profile_hash))
        records.append(receipt)
        return receipt

    runner = SimpleNamespace(run=run, verify=lambda receipt, **kwargs: any(receipt is r for r in records))
    scorer = SandboxBlindAnswerScorer(runner, binding=current, finite_spec=spec,
        parent_deadline_at=datetime.now(UTC) + timedelta(minutes=2))
    answer = source.private.content.standard_answer if spec.python_goal else source.private.content.standard_query
    assert scorer.resource_plan(source).execution_seconds == 10 and not records
    if outcome == "semantic_wrong":
        score = scorer.score(source, answer=answer)
        assert score.passed is False and scorer.verify(score, source)
        assert not scorer.verify(score.model_copy(update={"passed": True}), source)
        proof = RunnerTerminalProofV1.model_validate_json(json.dumps(records[0].to_payload()))
        assert proof.result.status.value == "success" and proof.probe_name == "blind_answer"
        assert scorer.score(source, answer=answer) == score and len(records) == 1
    else:
        with pytest.raises(ValueError, match="blind_answer_execution_pending"):
            scorer.score(source, answer=answer)
        assert not scorer._issued
        with pytest.raises(ValueError, match="launch_uncertain"):
            scorer.score(source, answer=answer)
    assert len(records) == 1


def test_505_pins_complete_effective_upstream_bodies_without_database_execution() -> None:
    """Independently recompute known489+491+500/493/494 pins; not PG replay."""
    root = Path(__file__).parents[2] / "app/db/schema"

    def text(name: str) -> str:
        return (root / name).read_text(encoding="utf-8")

    def body(sql: str, name: str) -> str:
        match = re.search(r"CREATE OR REPLACE FUNCTION " + re.escape(name) + r"\(.*?AS \$\$(.*?)\$\$;", sql, re.S)
        assert match is not None
        return match.group(1)

    pipeline = body(text("489_learning_item_shared_pipeline.sql"), "enforce_item_supply_shared_pipeline_artifact")
    continuation = text("491_learning_item_shared_continuation.sql")
    old = re.search(r"old_lookup:='(.*?)';", continuation, re.S)
    new = re.search(r"new_lookup:='(.*?)';", continuation, re.S)
    assert old is not None and new is not None
    old_lookup = old.group(1).replace("'||chr(10)||'", "\n")
    assert pipeline.count(old_lookup) == 1
    pipeline = pipeline.replace(old_lookup, new.group(1))
    flexible = text("500_learning_item_flexible_public_spec.sql")
    old_clause = re.search(r"old_clause CONSTANT text := '((?:''|[^'])*)';", flexible)
    new_clause = re.search(r"new_clause CONSTANT text := '((?:''|[^'])*)';", flexible)
    assert old_clause is not None and new_clause is not None
    old_value = old_clause.group(1).replace("''", "'")
    assert pipeline.count(old_value) == 1
    pipeline = pipeline.replace(old_value, new_clause.group(1).replace("''", "'"))
    upstream = {
        "public.enforce_item_supply_shared_pipeline_artifact": pipeline,
        "public.enforce_item_supply_shared_admission_facts": body(text("493_learning_item_shared_admission_facts.sql"), "enforce_item_supply_shared_admission_facts"),
        "public.enforce_learning_item_native_publication_proof": body(text("494_learning_item_native_publication.sql"), "enforce_learning_item_native_publication_proof"),
        "item_supply_internal.native_publication_event_allowed": body(text("494_learning_item_native_publication.sql"), "item_supply_internal.native_publication_event_allowed"),
    }
    diagnostic = text("505_learning_item_diagnostic_blind_admission.sql")
    assert hashlib.sha256(diagnostic.encode()).hexdigest() == "c78f8febf9893d413e18addb8507f67a449e4d774c0afa0ce6bcfff5e22e7519"
    blocks = re.findall(r"DO \$pin\$.*?END \$pin\$;", diagnostic, re.S)
    assert len(blocks) == len(upstream) == 4
    for block in blocks:
        function = re.search(r"function_oid:=to_regprocedure\('([^(']+)", block)
        baseline = re.search(r"baseline_md5 CONSTANT text := '([0-9a-f]{32})'", block)
        revised = re.search(r"revised_md5 CONSTANT text := '([0-9a-f]{32})'", block)
        replacement = re.search(r"\$newbody\$(.*?)\$newbody\$", block, re.S)
        assert function is not None and baseline is not None and revised is not None and replacement is not None
        assert hashlib.md5(upstream[function.group(1)].encode()).hexdigest() == baseline.group(1)
        assert hashlib.md5(replacement.group(1).encode()).hexdigest() == revised.group(1)


def test_v2_wrong_remains_strict_and_does_not_invoke_reviewers() -> None:
    s, p = subject(policy=AutonomousEvidencePolicyV2()), ports()
    blind = solve(s, p)
    assert not completed_blind_allowed(blind, s.policy)
    with pytest.raises(AutonomousReviewError, match="blind_solve_not_verified"):
        review_candidate(s.source, binding=s.binding, validation_receipt=s.validation,
                         author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers)
    assert not any(client.calls for client in p.clients[1:])


@pytest.mark.parametrize("policy_hash", (AutonomousEvidencePolicyV3().policy_hash, "0" * 64))
def test_legacy_review_rejects_non_v2_binding_before_reviewer_io(policy_hash: str) -> None:
    s, p = subject(policy=AutonomousEvidencePolicyV2()), ports(wrong=False)
    s = Subject(s.source, s.validation, s.binding.model_copy(update={"policy_hash": policy_hash}), s.policy, s.evidence)
    blind = solve(s, p)
    with pytest.raises((AutonomousReviewError, ValueError)):
        review_candidate(s.source, binding=s.binding, validation_receipt=s.validation,
                         author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers)
    assert not any(client.calls for client in p.clients[1:])


def test_v3_review_rejects_v2_bound_blind_before_reviewer_io() -> None:
    s, p = subject(policy=AutonomousEvidencePolicyV2()), ports(wrong=False)
    blind = solve(s, p)
    with pytest.raises((AutonomousReviewError, ValueError)):
        review_candidate_for_policy(s.source, binding=s.binding, validation_receipt=s.validation,
            author_identity="author", blind_solve_receipt=blind, reviewers=p.reviewers, policy=AutonomousEvidencePolicyV3())
    assert not any(client.calls for client in p.clients[1:])


@pytest.mark.parametrize("mutation", ("source", "claims", "coverage", "runner", "scorer", "isolation", "execution", "ambiguity", "equivalent"))
@pytest.mark.parametrize("wrong", (True, False))
def test_blind_success_or_warning_cannot_supply_missing_hard_evidence(mutation: str, wrong: bool) -> None:
    s, p = subject(), ports(wrong=wrong)
    bundle = review(s, p)
    variants: dict[str, dict[str, object]] = {
        "source": {"source_current": False}, "claims": {"source_claim_receipt_hashes": ()},
        "coverage": {"coverage_proof_hash": None}, "runner": {"runner_available": False},
        "scorer": {"scorer_available": False}, "isolation": {"execution_isolated": False},
        "execution": {"execution_receipt_hash": None},
        "ambiguity": {"probes": tuple(probe for probe in s.evidence.probes if probe.probe != "ambiguity")},
        "equivalent": {"probes": tuple(probe for probe in s.evidence.probes if probe.probe != "equivalent")},
    }
    updates = variants[mutation]
    result = evaluate(s, bundle, evidence=s.evidence.model_copy(update=updates))
    assert result.disposition == "evidence_pending"
    assert diagnostic_warnings(result) == (("blind_solution_incorrect",) if wrong else ())
    assert not result.publication_enabled


@pytest.mark.parametrize("role_index", range(6))
def test_each_single_blocking_role_overrides_five_approvals(role_index: int) -> None:
    s, p = subject(), ports()
    p.clients[role_index + 1].content = {"verdict": "approved", "findings": [{
        "severity": "major", "blocking": True, "safe_code": "ambiguity", "evidence_hash": s.binding.content_hash,
    }]}
    result = evaluate(s, review(s, p))
    assert result.disposition == "quarantine" and "material_review_failure" in result.safe_reasons
    assert diagnostic_warnings(result) == ("blind_solution_incorrect",)
