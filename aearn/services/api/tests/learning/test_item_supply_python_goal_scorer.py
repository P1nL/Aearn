"""Focused pure API plumbing. Declared protocol doubles are NOT actual OS evidence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from aearn_shared.execution import SandboxResultV1

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
from app.services.learning.item_supply.pipeline import _require_explicit_sql_review_execution
from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_CORRECT, PYTHON_GOAL_COUNTEREXAMPLE, PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION,
    PYTHON_GOAL_PROFILE, PYTHON_GOAL_SCORER_HASH, PYTHON_GOAL_SCORER_VERSION,
    compile_goal_tests, compile_python_test_bundle, score_python_case,
)
from app.services.learning.item_supply.task_ambiguity_owner import (
    AdmissionFactsPending, TaskAmbiguityOwner, build_task_ambiguity_plan, target_clauses,
)
from tests.learning.test_item_supply_probe_plans import python_source

NOW = datetime(2026, 10, 2, tzinfo=UTC)
TOTAL_FORM = "numbers = [3, -1, 0, 3]\ntotal = sum(numbers)\nprint(total)"


def goal_source() -> LearningItemSourceV1:
    payload = python_source().model_dump(mode="json")
    payload["blueprint"].update(blueprint_key="python-assignment-sum-print-basic", version=PYTHON_GOAL_SCORER_VERSION)
    payload["blueprint"]["difficulty_profile"]["base"] = "D1"
    payload["public"].update(item_key="python-assignment-sum-print-basic", version="goal-v1", difficulty="D1",
        instruction_markdown=PYTHON_GOAL_INSTRUCTION)
    payload["private"].update(item_key="python-assignment-sum-print-basic", version="goal-v1")
    payload["public"]["content"]["starter_code"] = "numbers = [3, -1, 0, 3]\nprint(0)"
    payload["private"]["content"]["standard_answer"] = PYTHON_GOAL_CORRECT
    # Author does not have to know a private goal metadata field.
    return LearningItemSourceV1.model_validate(payload)


@dataclass(frozen=True)
class ProtocolReceipt:
    run_id: UUID
    probe_name: str
    request_hash: str
    result: SandboxResultV1
    lock_fingerprint: str = "a" * 64
    elapsed_seconds: float = 0.125
    mode: str = "live"
    isolation: str = "approved_os_boundary"
    seal: str = "protocol-double-NOT-OS-proof"

    def to_payload(self):
        return dict(schema_version="item_supply_runner_terminal_v1", run_id=str(self.run_id),
            probe_name=self.probe_name, request_hash=self.request_hash, result=self.result.model_dump(mode="json"),
            lock_fingerprint=self.lock_fingerprint, elapsed_seconds=self.elapsed_seconds,
            mode=self.mode, isolation=self.isolation, seal=self.seal)


class GoalProtocolDouble:
    """Known fixtures only; no AST, exec, subprocess, Docker, DB or network."""
    def __init__(self, *, missing_goal=False, infrastructure=False):
        self.records = []
        self.trust = True
        self.missing_goal = missing_goal
        self.infrastructure = infrastructure

    def run(self, *, request, run_id, probe_name):
        if probe_name in {"time_limit", "memory_limit", "output_limit"}:
            result = SandboxResultV1(status="failed", diagnostic_code=probe_name)
        else:
            facts = []
            for case in json.loads(request.visible_test_bundle_json) + json.loads(request.hidden_test_bundle_json):
                satisfied = request.submission in (PYTHON_GOAL_CORRECT, TOTAL_FORM)
                fact = dict(id=case["id"], status="success", code="python_terminal", stdout="5\n")
                if not self.missing_goal:
                    fact.update(goal_contract_id=PYTHON_GOAL_ID, goal_satisfied=satisfied)
                facts.append(fact)
            result = SandboxResultV1(status="unavailable" if self.infrastructure else "success", stdout=json.dumps({"cases": facts}), diagnostic_code="item_supply_facts_v1")
        receipt = ProtocolReceipt(run_id, probe_name, canonical_hash(request.model_dump(mode="json")), result)
        self.records.append(receipt)
        return receipt

    def verify(self, receipt, *, request):
        return self.trust and any(record is receipt for record in self.records) and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


def binding(source):
    return CandidateBindingV2(candidate_key="candidate", version_key="version", source_hash=source.source_hash,
        content_hash=source.content_hash, policy_hash="1" * 64, profile_hash="2" * 64,
        runtime_key="python_stdout_test", risk_tier=source.blueprint.publication_policy.risk_tier)


def test_server_owned_compile_binds_explicit_version_and_excludes_expected_wire():
    source = goal_source()
    raw = source.model_dump(mode="json")
    assert all(not test.input_json for test in source.private.content.tests)
    tests = compile_goal_tests(source)
    cases = compile_python_test_bundle(tests)
    assert all(case["goal_contract"] == PYTHON_GOAL_ID for case in cases)
    assert "expected_output" not in json.dumps(cases) and source.model_dump(mode="json") == raw
    plan = build_candidate_probe_plan(source)
    assert plan.profile_id == PYTHON_GOAL_PROFILE and plan.server_fixture_hash
    assert source.blueprint.version.endswith(PYTHON_GOAL_SCORER_HASH) and len(PYTHON_GOAL_SCORER_VERSION) <= 80
    for change in ("contradiction", "legacy", "old_blueprint"):
        changed = source.model_dump(mode="json")
        if change == "contradiction":
            changed["private"]["content"]["tests"][0]["input_json"] = {"goal_contract": "unknown-goal"}
        elif change == "legacy":
            changed["public"]["instruction_markdown"] = "仅输出5"
            changed["private"]["content"]["tests"][0]["input_json"] = {"goal_contract": PYTHON_GOAL_ID}
        else:
            changed["blueprint"]["version"] = "old"
        with pytest.raises(ValueError):
            compile_goal_tests(LearningItemSourceV1.model_validate(changed))


def test_single_goal_scorer_requires_stdout_state_id_and_strict_actual_boolean():
    test = compile_goal_tests(goal_source())[0]
    fact = dict(status="success", code="python_terminal", stdout="5\n", goal_contract_id=PYTHON_GOAL_ID, goal_satisfied=True)
    assert score_python_case(test, fact) is True
    assert score_python_case(test, dict(fact, goal_satisfied=False)) is False
    assert score_python_case(test, dict(fact, stdout="5 \n")) is False
    for change in ({"goal_satisfied": 1}, {"goal_contract_id": "wrong"}, {"status": "failed"}, {"code": "infrastructure"}):
        assert score_python_case(test, dict(fact, **change)) is None
    assert score_python_case({"expected_output_json": {"stdout": "5"}}, {"stdout": "5\n"}) is True


def test_candidate_all_profile_controls_use_same_goal_scorer_and_actual_seal_verifier():
    source = goal_source()
    runner = GoalProtocolDouble()
    port = SandboxCandidateExecutionPort(runner, probe_plan=build_candidate_probe_plan(source))
    evidence = port.validate(source)
    assert len(runner.records) == 12 and all(probe.status == "passed" for probe in evidence.probes)
    assert evidence.scorer_version == PYTHON_GOAL_SCORER_VERSION and port.verify(evidence, source)
    assert port.scorer_counts(evidence) == dict(positive_cases=2, negative_cases=7, false_positives=0, false_negatives=0, pending_cases=0)
    # Exact API owner classes and a caller's live-shaped True are not an OS issuer.
    facts_owner = AdmissionFactsOwner.__new__(AdmissionFactsOwner)
    facts_owner.execution_owner = port
    facts_owner.ambiguity_owner = TaskAmbiguityOwner(runner, parent_deadline_at=NOW+timedelta(seconds=40))
    facts_owner.blind_scorer = SandboxBlindAnswerScorer(runner, binding=binding(source),
        parent_deadline_at=NOW+timedelta(seconds=50))
    with pytest.raises(AdmissionFactsPending, match="actual_runner_issuer_missing"):
        facts_owner._require_python_runner_issuer()
    runner.trust = False
    assert not port.verify(evidence, source)


def test_blind_same_stdout_wrong_goal_is_failed_and_missing_facts_pending():
    source = goal_source()
    runner = GoalProtocolDouble()
    scorer = SandboxBlindAnswerScorer(runner, binding=binding(source), parent_deadline_at=NOW+timedelta(seconds=50), clock=lambda: NOW)
    passed = scorer.score(source, answer=TOTAL_FORM)
    failed = scorer.score(source, answer="print(5)")
    assert passed.passed and not failed.passed and scorer.verify(passed, source)
    assert passed.scorer_version == PYTHON_GOAL_SCORER_VERSION
    runner.trust = False
    assert not scorer.verify(passed, source)
    pending = SandboxBlindAnswerScorer(GoalProtocolDouble(missing_goal=True), binding=binding(source),
        parent_deadline_at=NOW+timedelta(seconds=50), clock=lambda: NOW)
    with pytest.raises(ValueError, match="execution_pending"):
        pending.score(source, answer=PYTHON_GOAL_CORRECT)


def test_ambiguity_exact_two_same_stdout_calls_replay_and_prereserved_thirty_bound():
    source = goal_source()
    runner = GoalProtocolDouble()
    owner = TaskAmbiguityOwner(runner, parent_deadline_at=NOW+timedelta(seconds=40), clock=lambda: NOW)
    plan = build_task_ambiguity_plan(source)
    assert plan.correct.submission == PYTHON_GOAL_CORRECT and plan.counterexample.submission == PYTHON_GOAL_COUNTEREXAMPLE
    assert plan.target.scorer_contract_hash == PYTHON_GOAL_SCORER_HASH
    assert tuple(clause.clause_id for clause in target_clauses(source)) == ("python.assignment",)
    receipt = owner.run(source, plan, run_id=uuid4())
    assert receipt.correct_case_results == (True,) and receipt.counterexample_case_results == (False,)
    assert owner.verify(receipt, source) and owner.run(source, plan, run_id=receipt.run_id) == receipt
    assert len(runner.records) == 2 and owner.resource_plan(plan).execution_seconds == 20
    with pytest.raises(PipelineRepositoryError, match="RESOURCE_PLAN_INCOMPLETE"):
        _require_explicit_sql_review_execution(source, ResourceAmounts(execution_seconds=29), mode="live")
    _require_explicit_sql_review_execution(source, ResourceAmounts(execution_seconds=30), mode="live")


def test_ambiguity_infrastructure_does_not_count_as_same_stdout_wrong_control():
    source = goal_source()
    owner = TaskAmbiguityOwner(GoalProtocolDouble(infrastructure=True),
        parent_deadline_at=NOW+timedelta(seconds=40), clock=lambda: NOW)
    with pytest.raises(AdmissionFactsPending, match="terminal_unverified"):
        owner.run(source, build_task_ambiguity_plan(source), run_id=uuid4())


def test_generation_derived_goal_constraints_are_portable_without_private_author_metadata():
    from app.services.learning.item_supply.generation import generate_candidate
    from tests.learning.test_item_supply_generation import make_request, SyntheticAuthority, SyntheticProvider

    request, _ = make_request()
    payload = goal_source().model_dump(mode="json")
    refs = request.blueprint.model_dump(mode="json")["source_references"]
    payload["blueprint"]["source_references"] = refs
    payload["public"]["source_references"] = refs
    source = LearningItemSourceV1.model_validate(payload)
    request = request.model_copy(update=dict(blueprint=source.blueprint, public_template=source.public,
        item_key=source.public.item_key, version=source.public.version))
    provider = SyntheticProvider(payload)
    result = generate_candidate(request, provider=provider, source_authority=SyntheticAuthority(), enabled=True)
    assert result.state == "staged" and result.source == source and provider.calls == 1
    assert result.source.private.content.score_policy.policy_version == "all_tests_v1"
    assert all(not test.input_json for test in result.source.private.content.tests)
    system = provider.messages[0]["content"]
    assert "compares only stdout" not in system and "every actual runtime case" in system
    schema = json.loads(system.split("AUTHORITATIVE OUTPUT JSON SCHEMA:\n", 1)[1])
    assert schema["properties"]["blueprint"]["const"]["version"] == PYTHON_GOAL_SCORER_VERSION
    assert schema["properties"]["public"]["const"] == source.public.model_dump(mode="json")
    broken = request.model_copy(update={"blueprint": request.blueprint.model_copy(update={"version": "old"})})
    fresh_provider, authority = SyntheticProvider(payload), SyntheticAuthority()
    denied = generate_candidate(broken, provider=fresh_provider, source_authority=authority, enabled=True)
    assert denied.safe_reason == "invalid_request" and fresh_provider.calls == authority.calls == 0
