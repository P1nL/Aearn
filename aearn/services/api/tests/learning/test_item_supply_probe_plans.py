"""Pure plan/scorer plumbing only; synthetic facts are NOT runner acceptance."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID

import pytest
from aearn_shared.execution import SafeExecutionStatus, SandboxInputV1, SandboxResultV1

from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2
from app.services.learning.item_supply.sandbox.blind_scorer import SandboxBlindAnswerScorer
from app.services.learning.item_supply.sandbox.execution_contracts import CandidateProbePlanV1, RunnerTerminalReceipt
from app.services.learning.item_supply.sandbox.probe_plans import (
    PYTHON_PROFILE, SQLITE_PROFILE, ProbePlanUnavailable, build_candidate_probe_plan,
    run_candidate_probe_smoke, submission_fingerprint,
)
from app.services.learning.item_supply.validation_adapter import validate_candidate


def sql_source() -> LearningItemSourceV1:
    return LearningItemSourceLoader().load(curated_learning_item_source_root(), "sql-filter-track-v2.yaml").source


def python_source() -> LearningItemSourceV1:
    payload = sql_source().model_dump(mode="json")
    payload["blueprint"].update(item_kind="code", purpose="exercise", language_id="python", runtime_profile_id="python_stdout_test", required_capabilities=["python.assignment"], allowed_interactions=["edit", "run"])
    payload["public"].update(kind="code", purpose="exercise", instruction_markdown="计算列表 `[3, -1, 0, 3]` 中所有整数的和，仅输出总和。", allowed_interactions=["edit", "run"])
    payload["public"]["content"] = {"type": "code", "language_id": "python", "editor_language": "python", "exercise_type": "code_completion", "starter_code": "print(0)", "code_blanks": [{"blank_key": "total", "expected_concept": "assignment", "acceptable_patterns": [{"type": "literal", "value": "5"}], "is_core": True}]}
    payload["private"].update(kind="code")
    payload["private"]["content"] = {"type": "code", "standard_answer": "total = sum([3, -1, 0, 3])\nprint(total)", "tests": [{"id": name, "case_type": visibility, "expected_output_json": {"stdout": "5"}, "order_index": index} for index, (name, visibility) in enumerate((("visible", "visible"), ("hidden", "hidden")))], "score_policy": {"kind": "all_tests", "policy_version": "all_tests_v1", "threshold": 1.0}}
    return LearningItemSourceV1.model_validate(payload)


@dataclass(frozen=True)
class FixtureReceipt:
    run_id: UUID
    probe_name: str
    request_hash: str
    result: SandboxResultV1
    lock_fingerprint: str = "0" * 64
    elapsed_seconds: float = 0.125
    mode: Literal["live", "synthetic"] = "synthetic"
    isolation: Literal["approved_os_boundary", "synthetic"] = "synthetic"
    seal: str = "pure-test-only"

    def to_payload(self) -> dict[str, object]:
        return {"run_id": str(self.run_id), "probe_name": self.probe_name, "request_hash": self.request_hash, "result": self.result.model_dump(mode="json"), "mode": self.mode, "isolation": self.isolation, "seal": self.seal}


class FixtureRunner:
    """Synthetic protocol plumbing. No exec/subprocess/sqlite/Docker/network."""

    def __init__(self, source: LearningItemSourceV1, plan: CandidateProbePlanV1, *, flip: str | None = None, infrastructure: str | None = None) -> None:
        self.tasks = {task.name: task for task in SandboxCandidateExecutionPort(self, probe_plan=plan)._tasks(source)}
        self.flip = flip
        self.infrastructure = infrastructure
        self.records: list[FixtureReceipt] = []

    def run(self, *, request: SandboxInputV1, run_id: UUID, probe_name: str) -> FixtureReceipt:
        task = self.tasks[probe_name]
        facts: list[dict[str, Any]] = []
        if probe_name == self.infrastructure:
            result = SandboxResultV1(status=SafeExecutionStatus.UNAVAILABLE, diagnostic_code="runtime_adapter_unavailable")
        elif task.expected in {"time_limit", "memory_limit", "output_limit"}:
            result = SandboxResultV1(status=SafeExecutionStatus.FAILED, diagnostic_code=task.expected)
        else:
            cases = json.loads(request.visible_test_bundle_json) + json.loads(request.hidden_test_bundle_json)
            for index, case in enumerate(cases):
                if task.expected == "sql_setup_invalid":
                    facts.append({"id": case["id"], "status": "failed", "code": "sql_setup_invalid"})
                elif not task.tests:
                    facts.append({"id": case["id"], "status": "failed", "code": "sql_rejected"})
                else:
                    matches = (task.expected == "pass") != (probe_name == self.flip)
                    test = task.tests[index]
                    fact: dict[str, Any] = {"id": case["id"], "status": "success"}
                    if request.runtime_id == "python-stdout-v1":
                        fact.update(code="python_terminal", stdout=test["expected_output_json"]["stdout"] + "\n" if matches else "deliberate wrong value")
                    else:
                        output = test["expected_output"]
                        fact.update(code="sqlite_terminal", columns=output["columns"], rows=output["rows"] if matches else [["deliberate wrong value"] * len(output["columns"])])
                    facts.append(fact)
            result = SandboxResultV1(status=SafeExecutionStatus.SUCCESS, stdout=json.dumps({"cases": facts}), passed_test_count=48, total_test_count=48)
        receipt = FixtureReceipt(run_id, probe_name, canonical_hash(request.model_dump(mode="json")), result)
        self.records.append(receipt)
        return receipt

    def verify(self, receipt: RunnerTerminalReceipt, *, request: SandboxInputV1) -> bool:
        return receipt in self.records and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


def test_builder_is_stable_source_bound_and_independent() -> None:
    for source, profile in ((python_source(), PYTHON_PROFILE), (sql_source(), SQLITE_PROFILE)):
        plan = build_candidate_probe_plan(source)
        assert plan == build_candidate_probe_plan(source, profile_id=profile)
        assert plan.profile_id == profile and plan.source_hash == source.source_hash
        assert plan.server_fixture_hash and plan.boundary_cases_json and plan.boundary_tests_json
        tasks = SandboxCandidateExecutionPort(FixtureRunner(source, plan), probe_plan=plan)._tasks(source)
        by_name = {task.name: task for task in tasks}
        assert submission_fingerprint(source, by_name["reference"].wire.submission) != submission_fingerprint(source, by_name["equivalent"].wire.submission)
        assert by_name["boundary"].wire.test_reference_hash != by_name["reference"].wire.test_reference_hash
        hashes = [canonical_hash(task.wire.model_dump(mode="json")) for task in tasks]
        assert len(hashes) == len(set(hashes))
    payload = python_source().model_dump(mode="json")
    for test in payload["private"]["content"]["tests"]:
        test["expected_output_json"]["stdout"] = "5\n"
    newline_source = LearningItemSourceV1.model_validate(payload)
    assert build_candidate_probe_plan(newline_source).source_hash == newline_source.source_hash
    assert newline_source.private.content.tests[0].expected_output_json == {"stdout": "5\n"}
    payload["private"]["content"]["tests"][0]["expected_output_json"]["stdout"] = "5 \n"
    with pytest.raises(ProbePlanUnavailable, match="stdout_oracle"):
        build_candidate_probe_plan(LearningItemSourceV1.model_validate(payload))


def test_sql_semantics_use_actual_schema_independent_oracles_and_mutations() -> None:
    source = sql_source()
    plan = build_candidate_probe_plan(source)
    tasks = SandboxCandidateExecutionPort(FixtureRunner(source, plan), probe_plan=plan)._tasks(source)
    by_name = {task.name: task for task in tasks}
    for name in ("null", "duplicates", "empty", "order", "types", "joins"):
        positive, wrong = by_name[name], by_name[name + "_wrong"]
        wire = positive.wire.visible_test_bundle_json + positive.wire.hidden_test_bundle_json
        assert '"name":"learners"' in wire and '"name":"mentors"' in wire
        assert "expected_output" not in wire and "expected_output_json" not in wire
        assert positive.tests == wrong.tests and positive.wire.submission != wrong.wire.submission
        assert positive.wire.test_reference_hash != by_name["reference"].wire.test_reference_hash
    duplicate_test = by_name["duplicates"].tests[0]
    assert duplicate_test["expected_output"]["rows"] == [["Ada"], ["Ada"], ["Zoe"]]
    assert by_name["null"].tests[0]["expected_output"]["rows"] == [[None], [None]]
    assert "CAST(id AS TEXT)" in by_name["types_wrong"].wire.submission
    assert "LEFT JOIN" in by_name["joins"].wire.submission and "INNER JOIN" in by_name["joins_wrong"].wire.submission


def test_unsupported_candidate_semantics_block_without_runner() -> None:
    for base, mutate, reason in (
        (python_source(), lambda p: p["private"]["content"]["tests"][0].update(input_json={"args": [1]}), "stdout_oracle"),
        (python_source(), lambda p: p["private"]["content"]["tests"][0].update(expected_output_json={"stdout": "6"}), "stdout_oracle"),
        (sql_source(), lambda p: p["public"]["content"].update(comparison="unordered"), "sql_profile"),
        (sql_source(), lambda p: p["private"]["content"]["tests"][1]["expected_output"].update(rows=[["invented"]]), "schema_dataset_or_oracle"),
        (sql_source(), lambda p: p["public"].update(instruction_markdown="Find all learners"), "public_task"),
    ):
        payload = base.model_dump(mode="json")
        mutate(payload)
        with pytest.raises(ProbePlanUnavailable, match=reason):
            build_candidate_probe_plan(LearningItemSourceV1.model_validate(payload))


def test_source_hash_and_comment_only_alternative_cannot_be_relabelled() -> None:
    source = python_source()
    plan = build_candidate_probe_plan(source)
    runner = FixtureRunner(source, plan)
    stale = plan.model_copy(update={"source_hash": "f" * 64})
    with pytest.raises(ValueError, match="stale"):
        SandboxCandidateExecutionPort(runner, probe_plan=stale).resource_plan(source)
    renamed = plan.model_copy(update={"equivalent": source.private.content.standard_answer + "\n# different name only"})
    with pytest.raises(ValueError, match="alternatives_missing"):
        SandboxCandidateExecutionPort(runner, probe_plan=renamed).resource_plan(source)
    assert not runner.records


def test_all_calls_are_reserved_and_frozen_deadline_is_not_extended() -> None:
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    for source, calls in ((python_source(), 16), (sql_source(), 23)):
        plan = build_candidate_probe_plan(source)
        runner = FixtureRunner(source, plan)
        port = SandboxCandidateExecutionPort(runner, probe_plan=plan, parent_deadline_at=now + timedelta(seconds=calls * 10), clock=lambda: now)
        bound = port.resource_plan(source)
        assert bound.execution_seconds == calls * 10
        assert bound.requests == bound.input_tokens == bound.output_tokens == bound.fetches == 0
        expired = SandboxCandidateExecutionPort(runner, probe_plan=plan, parent_deadline_at=now + timedelta(seconds=calls * 10 - 1), clock=lambda: now)
        with pytest.raises(ValueError, match="frozen_deadline"):
            expired.validate(source)
        assert not runner.records


def test_actual_scorer_counts_zero_known_mismatches_without_trusting_raw_counts() -> None:
    for source in (python_source(), sql_source()):
        plan = build_candidate_probe_plan(source)
        runner = FixtureRunner(source, plan)
        port = SandboxCandidateExecutionPort(runner, probe_plan=plan)
        evidence = port.validate(source)
        assert all(probe.status == "passed" for probe in evidence.probes)
        counts = port.scorer_counts(evidence)
        assert counts["positive_cases"] > 4 and counts["negative_cases"] > 4
        assert counts["false_positives"] == counts["false_negatives"] == counts["pending_cases"] == 0
        assert evidence.mode == evidence.isolation == "synthetic" and port.verify(evidence, source)
        assert port.resource_usage(evidence).execution_seconds == len(runner.records)
        assert port.validate(source) == evidence  # No second set of terminal calls.
        assert validate_candidate(source, execution_port=port).state != "machine_verified"


def test_false_positive_is_not_hidden_behind_wrong_probe_rename() -> None:
    source = sql_source()
    plan = build_candidate_probe_plan(source)
    runner = FixtureRunner(source, plan, flip="duplicates_wrong")
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan)
    evidence = port.validate(source)
    assert next(probe for probe in evidence.probes if probe.name == "wrong_rejected").status == "passed"
    assert next(probe for probe in evidence.probes if probe.name == "scorer_counterexample").status == "failed"
    assert port.scorer_counts(evidence)["false_positives"] == 1


def test_false_negative_and_infrastructure_pending_are_separate() -> None:
    source = python_source()
    plan = build_candidate_probe_plan(source)
    runner = FixtureRunner(source, plan, flip="stdout_zero")
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan)
    evidence = port.validate(source)
    assert port.scorer_counts(evidence)["false_negatives"] == 1
    assert next(probe for probe in evidence.probes if probe.name == "scorer_counterexample").status == "failed"
    runner = FixtureRunner(source, plan, infrastructure="stdout_zero")
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan)
    evidence = port.validate(source)
    assert port.scorer_counts(evidence)["pending_cases"] == 1
    assert next(probe for probe in evidence.probes if probe.name == "scorer_counterexample").status == "pending"


def test_standalone_driver_keeps_synthetic_and_verifies_each_terminal() -> None:
    source = python_source()
    plan = build_candidate_probe_plan(source)
    runner = FixtureRunner(source, plan)
    result = run_candidate_probe_smoke(source, runner, parent_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    assert result.evidence.mode == "synthetic" and result.scorer_counts["false_positives"] == 0
    assert result.usage.requests == result.usage.input_tokens == result.usage.output_tokens == 0
    assert len(result.terminal_receipts) == 16
    runner = FixtureRunner(source, plan)
    runner.verify = lambda receipt, *, request: False  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="receipt_untrusted"):
        run_candidate_probe_smoke(source, runner, parent_deadline_at=datetime.now(timezone.utc) + timedelta(minutes=10))
    assert len(runner.records) == 1


def test_generated_hidden_dataset_uses_declarative_oracle_not_old_fixture_truth() -> None:
    payload = sql_source().model_dump(mode="json")
    hidden = payload["private"]["content"]["tests"][1]
    hidden["dataset"]["tables"][1]["rows"] = [[40, "Aster", "sql", None], [30, "Blue", "python", 10], [10, "Cedar", "sql", 10]]
    hidden["expected_output"]["rows"] = [["Cedar"], ["Aster"]]
    generated = LearningItemSourceV1.model_validate(payload)
    plan = build_candidate_probe_plan(generated)
    assert plan.source_hash == generated.source_hash
    assert generated.source_hash != sql_source().source_hash
    # Author does not need the old hidden Barbara row. Sorting/filter truth is
    # server-declared, not read from authored standard_query or expected rows.
    hidden["expected_output"]["rows"] = [["Aster"], ["Cedar"]]
    with pytest.raises(ProbePlanUnavailable, match="schema_dataset_or_oracle"):
        build_candidate_probe_plan(LearningItemSourceV1.model_validate(payload))


def test_actual_hardcoded_candidate_query_is_sent_to_independent_boundary() -> None:
    payload = sql_source().model_dump(mode="json")
    query = "SELECT CASE WHEN EXISTS (SELECT 1 FROM learners WHERE id = 10) THEN 'Barbara' ELSE 'Grace' END AS name;"
    payload["private"]["content"]["standard_query"] = query
    source = LearningItemSourceV1.model_validate(payload)
    plan = build_candidate_probe_plan(source)
    runner = FixtureRunner(source, plan, flip="boundary")
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan)
    tasks = {task.name: task for task in port._tasks(source)}
    assert tasks["boundary"].wire.submission == tasks["reference"].wire.submission == query
    assert tasks["boundary"].wire.test_reference_hash != tasks["reference"].wire.test_reference_hash
    original_datasets = {canonical_hash(case["dataset"]) for case in json.loads(tasks["reference"].wire.visible_test_bundle_json) + json.loads(tasks["reference"].wire.hidden_test_bundle_json)}
    assert all(canonical_hash(case["dataset"]) not in original_datasets for case in json.loads(tasks["boundary"].wire.hidden_test_bundle_json))
    evidence = port.validate(source)
    assert next(probe for probe in evidence.probes if probe.name == "boundary").status == "failed"
    assert next(probe for probe in evidence.probes if probe.name == "reference").status == "passed"


def test_one_terminal_blind_scorer_is_live_bound_and_opaque_without_raw_answer() -> None:
    # Synthetic protocol fixtures below are NOT actual OS acceptance evidence.
    class AnswerRunner:
        def __init__(self, source: LearningItemSourceV1, *, live: bool) -> None:
            self.source = source
            self.live = live
            self.records: list[FixtureReceipt] = []

        def run(self, *, request: SandboxInputV1, run_id: UUID, probe_name: str) -> FixtureReceipt:
            tests = {test.id: test for test in self.source.private.content.tests}
            cases = json.loads(request.visible_test_bundle_json) + json.loads(request.hidden_test_bundle_json)
            facts: list[dict[str, Any]] = []
            for case in cases:
                test = tests[case["id"]]
                if request.runtime_id == "python-stdout-v1":
                    facts.append({"id": case["id"], "status": "success", "code": "python_terminal", "stdout": "5\n"})
                else:
                    facts.append({"id": case["id"], "status": "success", "code": "sqlite_terminal", "columns": ["name"], "rows": test.expected_output.model_dump(mode="json")["rows"]})
            receipt = FixtureReceipt(run_id, probe_name, canonical_hash(request.model_dump(mode="json")), SandboxResultV1(status=SafeExecutionStatus.SUCCESS, stdout=json.dumps({"cases": facts}), passed_test_count=48, total_test_count=48), lock_fingerprint="a" * 64, mode="live" if self.live else "synthetic", isolation="approved_os_boundary" if self.live else "synthetic")
            self.records.append(receipt)
            return receipt

        def verify(self, receipt: RunnerTerminalReceipt, *, request: SandboxInputV1) -> bool:
            return receipt in self.records and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))

    for source, answer in ((python_source(), "print(5)"), (sql_source(), "SELECT name FROM learners WHERE track = 'sql' ORDER BY id;")):
        binding = CandidateBindingV2(candidate_key="blind-candidate", version_key="blind-version", content_hash=source.content_hash, source_hash=source.source_hash, policy_hash=canonical_hash("policy"), profile_hash=canonical_hash("profile"), runtime_key=source.blueprint.runtime_profile_id, risk_tier=source.blueprint.publication_policy.risk_tier)
        deadline = datetime.now(timezone.utc) + timedelta(minutes=5)
        synthetic = SandboxBlindAnswerScorer(AnswerRunner(source, live=False), binding=binding, parent_deadline_at=deadline)
        with pytest.raises(ValueError, match="live_os_required"):
            synthetic.score(source, answer=answer)
        runner = AnswerRunner(source, live=True)
        scorer = SandboxBlindAnswerScorer(runner, binding=binding, parent_deadline_at=deadline)
        bound = scorer.resource_plan(source)
        assert bound.execution_seconds == 10 and bound.requests == bound.input_tokens == bound.output_tokens == 0
        score = scorer.score(source, answer=answer)
        assert score.passed and scorer.verify(score, source)
        assert len(runner.records) == 1 and scorer.resource_usage(score).execution_seconds == 1
        artifacts = scorer.receipts(score)
        assert artifacts[0]["answer_hash"] == canonical_hash({"answer": answer})
        assert artifacts[0]["binding_hash"] == canonical_hash(binding.model_dump(mode="json"))
        assert answer not in json.dumps(artifacts) and "stdout" not in json.dumps(artifacts)
        assert not scorer.verify(score.model_copy(update={"passed": False}), source)
        assert scorer.score(source, answer=answer) == score and len(runner.records) == 1


def test_versioned_explicit_sql_semantics_allowlist_keeps_legacy_and_real_ports() -> None:
    from app.services.learning.item_supply.sandbox.probe_plans import SQLITE_EXPLICIT_PROFILE, _fixture

    legacy = sql_source()
    assert build_candidate_probe_plan(legacy).profile_id == SQLITE_PROFILE
    fixture, _ = _fixture(SQLITE_EXPLICIT_PROFILE)
    payload = legacy.model_dump(mode="json")
    payload["public"]["instruction_markdown"] = fixture["instruction"]
    explicit = LearningItemSourceV1.model_validate(payload)
    plan = build_candidate_probe_plan(explicit)
    assert plan.profile_id == SQLITE_EXPLICIT_PROFILE and plan.source_hash == explicit.source_hash
    # The same actual port accepts its candidate/reference-on-independent-data
    # boundary, and the blind port's source preflight accepts the new profile.
    runner = FixtureRunner(explicit, plan)
    assert SandboxCandidateExecutionPort(runner, probe_plan=plan)._tasks(explicit)
    binding = CandidateBindingV2(candidate_key="explicit-candidate", version_key="explicit-version",
        source_hash=explicit.source_hash, content_hash=explicit.content_hash,
        policy_hash=canonical_hash("pure-policy"), profile_hash=canonical_hash("pure-profile"),
        runtime_key=explicit.blueprint.runtime_profile_id, risk_tier=explicit.blueprint.publication_policy.risk_tier)
    scorer = SandboxBlindAnswerScorer(runner, binding=binding,
        parent_deadline_at=datetime.now(timezone.utc)+timedelta(seconds=30))
    assert scorer.resource_plan(explicit).execution_seconds == 10
    payload["public"]["instruction_markdown"] += " 任意其他语义。"
    with pytest.raises(ProbePlanUnavailable, match="public_task_not_supported"):
        build_candidate_probe_plan(LearningItemSourceV1.model_validate(payload))
