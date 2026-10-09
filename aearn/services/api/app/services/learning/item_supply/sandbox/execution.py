"""Pure candidate composition over sealed OS receipts and the existing scorer.

No Docker, DB, provider, host subprocess, Attempt owner or learning-state writes.
Missing independently supplied alternatives/boundary cases remain pending.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Literal
from uuid import UUID, uuid4

from aearn_shared.execution import (
    ExecutionAction, SafeExecutionResultV1, SafeExecutionStatus, SandboxInputV1,
)

from app.services.learning.item_bank.contracts import (
    LearningItemCodeContentV1, LearningItemCodePrivateV1, LearningItemSourceV1,
    LearningItemSqlContentV2, LearningItemSqlPrivateV2, canonical_hash,
)
from app.services.learning.item_bank.practice_adapter import build_exercise_authority
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.execution_contracts import (
    EXECUTION_WALL_SECONDS, PROBE_PROFILE_VERSION, RUNNER_VERSION,
    CandidateProbePlanV1, RunnerPort, RunnerTerminalReceipt,
)
from app.services.learning.item_supply.sandbox.probe_plans import SQLITE_PROFILES, submission_fingerprint
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_PROFILE, compile_goal_tests, compile_python_test_bundle, score_python_case, source_goal_contract,
    source_scorer_version, test_goal_contract,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateExecutionEvidenceV2, CandidateProbeV2
from app.services.learning.item_supply.validators.profiles import profile_errors, required_probes
from app.services.learning.practice.contracts import ExerciseAttemptOutcome
from app.services.learning.practice.policies import score_execution_result
from app.services.runners.sql_query_runner import _compare_expected


if TYPE_CHECKING:
    from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1


@dataclass(frozen=True)
class _Request:
    name: str
    wire: SandboxInputV1
    expected: Literal["pass", "reject", "time_limit", "memory_limit", "output_limit", "sql_setup_invalid"]
    # Expected results remain API-private, outside the input to candidate children.
    tests: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _Run:
    source: LearningItemSourceV1
    tasks: tuple[_Request, ...]
    receipts: tuple[RunnerTerminalReceipt, ...]
    evidence: CandidateExecutionEvidenceV2


def _wire(source: LearningItemSourceV1, submission: str, cases: tuple[dict[str, Any], ...]) -> SandboxInputV1:
    visible = [case for case in cases if case.get("case_type", "visible") == "visible"]
    hidden = [case for case in cases if case.get("case_type") == "hidden"]
    request = SandboxInputV1(
        runtime_id="python-stdout-v1" if source.public.kind.value == "code" else "sqlite-query-v1",
        action=ExecutionAction.TEST, submission=submission,
        visible_test_bundle_json=json.dumps(visible, separators=(",", ":"), allow_nan=False),
        hidden_test_bundle_json=json.dumps(hidden, separators=(",", ":"), allow_nan=False),
        source_reference_hash=source.source_hash, test_reference_hash=canonical_hash(cases),
    )
    if len(request.wire_bytes()) > 98_304:
        raise ValueError("candidate_execution_input_bound")
    return request


def _candidate_cases(source: LearningItemSourceV1) -> tuple[str, str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    public, private = source.public.content, source.private.content
    # Reuse the existing compiler-to-Practice pure authority adapter; do not call
    # the compiler's legacy SQL validation entrypoint, which executes on a host.
    build_exercise_authority(source)
    if isinstance(public, LearningItemCodeContentV1) and isinstance(private, LearningItemCodePrivateV1):
        tests = compile_goal_tests(source)
        return private.standard_answer, public.starter_code, compile_python_test_bundle(tests), tests
    if isinstance(public, LearningItemSqlContentV2) and isinstance(private, LearningItemSqlPrivateV2):
        tables = [table.model_dump(mode="json") for table in public.tables]
        cases = tuple({"id": test.id, "case_type": test.case_type, "tables": tables, "dataset": test.dataset.model_dump(mode="json"), "max_rows": public.max_rows} for test in private.tests)
        tests_sql = tuple({"id": test.id, "case_type": test.case_type, "expected_output": test.expected_output.model_dump(mode="json"), "comparison": public.comparison} for test in private.tests)
        return private.standard_query, public.starter_query, cases, tests_sql
    raise ValueError("candidate_execution_profile_unavailable")


def _sql_semantic_cases(name: str) -> tuple[dict[str, Any], ...]:
    columns = [
        {"name": "seq", "data_type": "INTEGER", "nullable": False},
        {"name": "value", "data_type": "TEXT", "nullable": True},
        {"name": "amount", "data_type": "REAL", "nullable": True},
    ]
    rows: list[list[object]] = [[2, "a", 1.5], [1, None, 2.0], [3, "a", None]]
    if name == "empty":
        rows = []
    if name == "bounded_setup":
        rows = [[i, "a", 1.5] for i in range(257)]
    return ({"id": name, "case_type": "visible", "tables": [{"name": "t", "columns": columns, "foreign_keys": []}], "dataset": {"tables": [{"table": "t", "rows": rows}]}, "max_rows": 50},)


_SQL_SEMANTICS: dict[str, tuple[str, list[str], list[list[object]]]] = {
    "null": ("SELECT value FROM t WHERE value IS NULL", ["value"], [[None]]),
    "duplicates": ("SELECT value FROM t WHERE value IS NOT NULL ORDER BY seq", ["value"], [["a"], ["a"]]),
    "empty": ("SELECT value FROM t", ["value"], []),
    "order": ("SELECT seq FROM t ORDER BY seq DESC", ["seq"], [[3], [2], [1]]),
    "types": ("SELECT seq, value, amount FROM t WHERE seq=2", ["seq", "value", "amount"], [[2, "a", 1.5]]),
    "joins": ("SELECT a.seq AS seq FROM t a JOIN t b ON a.seq=b.seq WHERE a.seq=2", ["seq"], [[2]]),
}


class SandboxCandidateExecutionPort:
    def __init__(self, runner: RunnerPort, *, probe_plan: CandidateProbePlanV1 | None = None, finite_spec: FiniteCandidateSpecV1 | None = None, parent_deadline_at: datetime | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self._runner = runner
        self._plan = None if probe_plan is None else checked_model(probe_plan, CandidateProbePlanV1)
        self._finite_spec: FiniteCandidateSpecV1 | None = None
        if finite_spec is not None:
            from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1

            self._finite_spec = checked_model(finite_spec, FiniteCandidateSpecV1)
        if parent_deadline_at is not None and parent_deadline_at.tzinfo is None:
            raise ValueError("candidate_probe_deadline_timezone_required")
        self._deadline = parent_deadline_at
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._runs: dict[UUID, _Run] = {}
        self._source_runs: dict[str, UUID] = {}

    def _tasks(self, source: LearningItemSourceV1) -> tuple[_Request, ...]:
        source = checked_model(source, LearningItemSourceV1)
        failures, gaps = profile_errors(source)
        if failures or gaps:
            raise ValueError("candidate_execution_profile_unavailable")
        reference, starter, cases, tests = _candidate_cases(source)
        tasks = [_Request("reference", _wire(source, reference, cases), "pass", tests), _Request("starter_rejected", _wire(source, starter, cases), "reject", tests)]
        plan = self._plan
        native_sql_boundary = False
        native_python_plan = False
        native_fixed_boundary = False
        if self._finite_spec is not None:
            from app.services.learning.item_supply.sandbox.finite_probe_plans import (
                PYTHON_FINITE_PROFILE, SQLITE_FINITE_PROFILE, build_finite_candidate_probe_plan,
            )

            if plan != build_finite_candidate_probe_plan(source, spec=self._finite_spec):
                raise ValueError("candidate_probe_finite_plan_stale")
            native_sql_boundary = plan is not None and plan.profile_id == SQLITE_FINITE_PROFILE
            native_python_plan = self._finite_spec.target_id == "python-state-update-v1"
            native_fixed_boundary = native_python_plan and plan is not None and plan.profile_id == PYTHON_FINITE_PROFILE
        elif source_goal_contract(source) is not None:
            from app.services.learning.item_supply.sandbox.probe_plans import build_candidate_probe_plan
            if plan != build_candidate_probe_plan(source):
                raise ValueError("candidate_probe_goal_plan_stale")
        if plan is not None:
            if plan.source_hash != source.source_hash:
                raise ValueError("candidate_probe_plan_stale")
            identities = [submission_fingerprint(source, value) for value in (reference, starter, plan.equivalent, plan.wrong)]
            if len(set(identities)) != len(identities):
                raise ValueError("candidate_probe_alternatives_missing")
            for name, submission, expected in (("equivalent", plan.equivalent, "pass"), ("wrong_rejected", plan.wrong, "reject")):
                tasks.append(_Request(name, _wire(source, submission, cases), expected, tests))  # type: ignore[arg-type]
            ids = {case["id"] for case in cases}
            if plan.boundary_cases_json is not None and plan.boundary_tests_json is not None:
                candidate_boundary = source.public.kind.value == "sql" and (plan.profile_id in SQLITE_PROFILES or native_sql_boundary) and submission_fingerprint(source, plan.boundary) == identities[0]
                if not candidate_boundary and submission_fingerprint(source, plan.boundary) in set(identities):
                    raise ValueError("candidate_probe_boundary_not_independent")
                boundary_cases, boundary_tests = self._plan_bundles(plan.boundary_cases_json, plan.boundary_tests_json, native_python=native_python_plan)
                if canonical_hash(boundary_cases) == canonical_hash(cases) and not native_fixed_boundary:
                    raise ValueError("candidate_probe_boundary_cases_not_independent")
                if candidate_boundary:
                    # Same candidate + genuinely new data is an independent
                    # behavior test. A case ID/name change alone is not.
                    source_datasets = {canonical_hash(case["dataset"]) for case in cases}
                    if any(canonical_hash(case["dataset"]) in source_datasets for case in boundary_cases):
                        raise ValueError("candidate_probe_boundary_cases_not_independent")
                # The new fixed-list boundary is a same-stdout negative target
                # control, not a relabelled parameterized behavior claim.
                boundary_expected: Literal["pass", "reject"] = "reject" if plan.profile_id == PYTHON_GOAL_PROFILE or native_fixed_boundary else "pass"
                tasks.append(_Request("boundary", _wire(source, plan.boundary, boundary_cases), boundary_expected, boundary_tests))
            elif plan.boundary_case_ids and len(set(plan.boundary_case_ids)) == len(plan.boundary_case_ids) and set(plan.boundary_case_ids) <= ids:
                subset = tuple(case for case in cases if case["id"] in plan.boundary_case_ids)
                subset_tests = tuple(test for test in tests if test["id"] in plan.boundary_case_ids)
                tasks.append(_Request("boundary", _wire(source, plan.boundary, subset), "pass", subset_tests))
            for probe in plan.probes:
                extra_cases, extra_tests = self._plan_bundles(probe.cases_json, probe.tests_json, empty_tests=probe.expected != "pass", native_python=native_python_plan)
                tasks.append(_Request(probe.name, _wire(source, probe.submission, extra_cases), probe.expected, extra_tests))
        if source.public.kind.value == "code":
            limits = {
                "time_limit": "while True: pass",
                "memory_limit": "x = bytearray(200000000)",
                "output_limit": "print('x' * 20000)",
            }
            limit_cases: tuple[dict[str, Any], ...] = ({"id": "resource_probe", "case_type": "visible"},)
        else:
            limits = {
                "time_limit": "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT sum(n) FROM x",
                "memory_limit": "SELECT randomblob(120000000)",
                "output_limit": "SELECT hex(randomblob(20000))",
            }
            limit_cases = (dict(cases[0], id="resource_probe"),) if plan is not None and plan.probes else _sql_semantic_cases("resource_probe")
            if plan is None or not plan.probes:
                for name, (query, columns, rows) in _SQL_SEMANTICS.items():
                    expected_test = ({"id": name, "expected_output": {"columns": columns, "rows": rows}, "comparison": "ordered"},)
                    tasks.append(_Request(name, _wire(source, query, _sql_semantic_cases(name)), "pass", expected_test))
                for name, query, expectation in (
                    ("read_only", "DELETE FROM t", "reject"),
                    ("single_statement", "SELECT value FROM t; SELECT value FROM t", "reject"),
                    ("bounded_setup", "SELECT value FROM t", "sql_setup_invalid"),
                ):
                    tasks.append(_Request(name, _wire(source, query, _sql_semantic_cases(name)), expectation, ()))  # type: ignore[arg-type]
        for name, submission in limits.items():
            tasks.append(_Request(name, _wire(source, submission, limit_cases), name, ()))  # type: ignore[arg-type]
        if len({task.name for task in tasks}) != len(tasks):
            raise ValueError("candidate_probe_names_duplicate")
        # A name change cannot manufacture an independent execution request.
        hashes = [canonical_hash(task.wire.model_dump(mode="json")) for task in tasks]
        if len(set(hashes)) != len(hashes):
            raise ValueError("candidate_probe_request_reused")
        return tuple(tasks)

    @staticmethod
    def _plan_bundles(cases_json: str, tests_json: str, *, empty_tests: bool = False, native_python: bool = False) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
        cases, tests = json.loads(cases_json), json.loads(tests_json)
        if not isinstance(cases, list) or not cases or not isinstance(tests, list):
            raise ValueError("candidate_probe_bundle_invalid")
        if any(not isinstance(case, dict) or not isinstance(case.get("id"), str) or case.get("case_type") not in {"visible", "hidden"} or set(case) - {"id", "case_type", "tables", "dataset", "max_rows", "goal_contract"} for case in cases):
            raise ValueError("candidate_probe_case_facts_invalid")
        for case, test in zip(cases, tests, strict=not empty_tests):
            if "expected_output_json" in test:
                if native_python:
                    from app.services.learning.item_supply.sandbox.python_state_scorer import python_state_test_target

                    expected_goal: object = python_state_test_target(test).model_dump(mode="json")
                else:
                    expected_goal = test_goal_contract(test)
                if case.get("goal_contract") != expected_goal:
                    raise ValueError("candidate_probe_goal_contract_mismatch")
        ids = [case["id"] for case in cases]
        if len(ids) != len(set(ids)) or (not (empty_tests and not tests) and [test.get("id") for test in tests] != ids):
            raise ValueError("candidate_probe_test_ids_invalid")
        return tuple(cases), tuple(tests)

    def resource_plan(self, source: LearningItemSourceV1) -> ResourceAmounts:
        # Five-second OS wall bound + conservative create/cleanup accounting.
        # Requests/tokens/fetches are truly zero: this performs no provider IO.
        bound = len(self._tasks(source)) * (EXECUTION_WALL_SECONDS + 5)
        self._check_deadline(bound)
        return ResourceAmounts(execution_seconds=bound)

    def _check_deadline(self, required_seconds: int) -> None:
        if self._deadline is not None and (self._deadline - self._clock()).total_seconds() < required_seconds:
            raise ValueError("candidate_probe_frozen_deadline_exceeded")

    def validate(self, source: LearningItemSourceV1) -> CandidateExecutionEvidenceV2:
        source = checked_model(source, LearningItemSourceV1)
        previous = self._source_runs.get(source.source_hash)
        if previous is not None:
            return self._runs[previous].evidence
        tasks = self._tasks(source)
        self._check_deadline(len(tasks) * (EXECUTION_WALL_SECONDS + 5))
        run_id = uuid4()
        receipts: list[RunnerTerminalReceipt] = []
        for task in tasks:
            self._check_deadline(EXECUTION_WALL_SECONDS + 5)
            receipt = self._runner.run(request=task.wire, run_id=run_id, probe_name=task.name)
            if (receipt.run_id, receipt.probe_name) != (run_id, task.name) or not self._runner.verify(receipt, request=task.wire):
                raise ValueError("runner_terminal_receipt_untrusted")
            if not math.isfinite(receipt.elapsed_seconds) or receipt.elapsed_seconds < 0:
                raise ValueError("runner_usage_unknown")
            receipts.append(receipt)
            # An overrun cannot become a successful receipt just because it was
            # the last probe. The outer P3 settlement/fence remains authoritative.
            self._check_deadline(0)
        evidence = self._evidence(source, run_id, tasks, tuple(receipts))
        self._runs[run_id] = _Run(source, tasks, tuple(receipts), evidence)
        self._source_runs[source.source_hash] = run_id
        return evidence

    def _probe_status(self, source: LearningItemSourceV1, task: _Request, receipt: RunnerTerminalReceipt) -> Literal["passed", "failed", "pending"]:
        result = receipt.result
        if result.status in {SafeExecutionStatus.UNAVAILABLE, SafeExecutionStatus.CANCELLED} or result.diagnostic_code in {"sandbox_protocol_invalid", "runtime_output_limit_exceeded"}:
            return "pending"
        facts: list[dict[str, Any]] = []
        if result.status is SafeExecutionStatus.SUCCESS:
            try:
                payload = json.loads(result.stdout)
                facts = payload["cases"]
                expected_ids = [case["id"] for case in json.loads(task.wire.visible_test_bundle_json) + json.loads(task.wire.hidden_test_bundle_json)]
                if not isinstance(facts, list) or [fact["id"] for fact in facts] != expected_ids:
                    return "pending"
            except (ValueError, KeyError, TypeError):
                return "pending"
        if task.expected in {"time_limit", "memory_limit", "output_limit", "sql_setup_invalid"}:
            codes = {result.diagnostic_code} | {str(fact.get("code")) for fact in facts}
            if task.expected == "time_limit" and result.status is SafeExecutionStatus.TIMEOUT:
                return "passed"
            return "passed" if task.expected in codes else "pending"
        if task.expected == "reject" and not task.tests:
            # OS/protocol failures cannot establish a read-only/single-query denial.
            return "passed" if facts and all(fact.get("code") == "sql_rejected" for fact in facts) else "pending"
        if len(facts) != len(task.tests):
            return "failed" if task.expected == "pass" else "pending"
        outcomes: list[bool] = []
        fact_by_id = {fact["id"]: fact for fact in facts}
        for test in task.tests:
            fact = fact_by_id[test["id"]]
            if fact.get("status") != "success":
                # Runtime errors may reject starter/wrong, but infrastructure codes
                # cannot serve as an intentional wrong-answer counterexample.
                if fact.get("code") not in {"python_terminal", "sqlite_terminal", "sql_rejected"}:
                    return "pending"
                if (source.public.kind.value == "code" and self._finite_spec is not None
                        and self._finite_spec.target_id == "python-state-update-v1"):
                    # Only a successful terminal carrying checked state-goal facts
                    # can establish a native semantic negative, never a runtime error.
                    return "pending"
                if source.public.kind.value == "code" and test_goal_contract(test) is not None:
                    return "pending"
                outcomes.append(False)
                continue
            if source.public.kind.value == "code":
                judged = score_python_case(test, fact)
                if judged is None:
                    return "pending"
                outcomes.append(judged)
            else:
                columns = fact.get("columns", [])
                rows = fact.get("rows", [])
                expected = test["expected_output"]
                try:
                    if any(len(row) != len(columns) for row in rows):
                        return "pending"
                    actual_rows = [dict(zip(columns, row, strict=True)) for row in rows]
                    expected_rows = [dict(zip(expected["columns"], row, strict=True)) for row in expected["rows"]]
                    outcomes.append(_compare_expected(columns, actual_rows, (expected["columns"], expected_rows), test["comparison"])[0])
                except (TypeError, ValueError):
                    return "pending"
        safe = SafeExecutionResultV1(status=SafeExecutionStatus.SUCCESS, passed_test_count=sum(outcomes), total_test_count=len(outcomes))
        score = score_execution_result(safe, required_capabilities=source.blueprint.required_capabilities, threshold=source.private.content.score_policy.threshold)  # type: ignore[union-attr]
        passed = score.outcome is ExerciseAttemptOutcome.PASSED
        desired = passed if task.expected == "pass" else not passed
        return "passed" if desired else "failed"

    def _evidence(self, source: LearningItemSourceV1, run_id: UUID, tasks: tuple[_Request, ...], receipts: tuple[RunnerTerminalReceipt, ...]) -> CandidateExecutionEvidenceV2:
        profile_version = PROBE_PROFILE_VERSION
        profile_binding: dict[str, object] = {}
        if self._finite_spec is not None:
            if self._plan is None or self._plan.profile_id is None:
                raise ValueError("candidate_probe_finite_plan_stale")
            profile_version = self._plan.profile_id
            profile_binding = {"specification_hash": self._finite_spec.specification_hash,
                               "plan_hash": canonical_hash(self._plan.model_dump(mode="json"))}
        probes: dict[str, CandidateProbeV2] = {}
        for task, receipt in zip(tasks, receipts, strict=True):
            status = self._probe_status(source, task, receipt)
            probes[task.name] = CandidateProbeV2(name=task.name, status=status, proof_hash=canonical_hash({"receipt": receipt.to_payload(), "status": status, **profile_binding}), profile_version=profile_version)
        counts = self._scorer_counts(source, tasks, receipts)
        complete = self._plan is not None and all(name in probes for name in ("reference", "equivalent", "starter_rejected", "wrong_rejected"))
        scorer_status: Literal["passed", "failed", "pending"] = "pending"
        if complete and counts["positive_cases"] and counts["negative_cases"] and not counts["pending_cases"]:
            scorer_status = "failed" if counts["false_positives"] or counts["false_negatives"] else "passed"
        scored_receipts = [{"request_hash": receipt.request_hash, "tests_hash": canonical_hash(task.tests), "expected": task.expected, "receipt": receipt.to_payload()} for task, receipt in zip(tasks, receipts, strict=True) if task.tests and task.expected in {"pass", "reject"}]
        probes["scorer_counterexample"] = CandidateProbeV2(name="scorer_counterexample", status=scorer_status, proof_hash=canonical_hash({"source_hash": source.source_hash, "fixture": None if self._plan is None else self._plan.server_fixture_hash, "counts": counts, "scored_receipts": scored_receipts, "scorer": source_scorer_version(source)}), profile_version=profile_version)
        probe = probes.get("reference")
        isolation_status = "pending" if probe is None else probe.status
        _, _, cases, _ = _candidate_cases(source)
        visible = {case["id"] for case in cases if case["case_type"] == "visible"}
        hidden = {case["id"] for case in cases if case["case_type"] == "hidden"}
        if not visible or not hidden or visible & hidden:
            isolation_status = "pending"
        probes["public_hidden_isolation"] = CandidateProbeV2(name="public_hidden_isolation", status=isolation_status, proof_hash=canonical_hash({"dependency": None if probe is None else probe.model_dump(mode="json"), "visible": sorted(visible), "hidden": sorted(hidden), "status": isolation_status}), profile_version=profile_version)
        ordered = tuple(probes.get(name) or CandidateProbeV2(name=name, status="pending", proof_hash=canonical_hash({"missing": name, "source_hash": source.source_hash}), profile_version=profile_version) for name in required_probes(source, finite_spec=self._finite_spec))
        runtime_profile_id = source.blueprint.runtime_profile_id
        if runtime_profile_id is None:
            raise ValueError("candidate_runtime_profile_missing")
        live = all(receipt.mode == "live" and receipt.isolation == "approved_os_boundary" for receipt in receipts)
        return CandidateExecutionEvidenceV2(
            source_hash=source.source_hash, content_hash=source.content_hash,
            kind="code" if source.public.kind.value == "code" else "sql", language="python" if source.public.kind.value == "code" else "sql",
            runtime_profile_id=runtime_profile_id, dialect="sqlite" if source.public.kind.value == "sql" else None,
            runner_version=RUNNER_VERSION, scorer_version=source_scorer_version(source), run_id=run_id,
            mode="live" if live else "synthetic", isolation="approved_os_boundary" if live else "synthetic", probes=ordered,
        )

    def _scorer_counts(self, source: LearningItemSourceV1, tasks: tuple[_Request, ...], receipts: tuple[RunnerTerminalReceipt, ...]) -> dict[str, int]:
        counts = {"positive_cases": 0, "negative_cases": 0, "false_positives": 0, "false_negatives": 0, "pending_cases": 0}
        for task, receipt in zip(tasks, receipts, strict=True):
            if not task.tests or task.expected not in {"pass", "reject"}:
                continue
            counts["positive_cases" if task.expected == "pass" else "negative_cases"] += 1
            status = self._probe_status(source, task, receipt)
            if status == "pending":
                counts["pending_cases"] += 1
            elif status == "failed":
                counts["false_negatives" if task.expected == "pass" else "false_positives"] += 1
        return counts

    def scorer_counts(self, evidence: CandidateExecutionEvidenceV2) -> dict[str, int]:
        run = self._runs.get(evidence.run_id)
        if run is None or run.evidence != evidence:
            raise ValueError("runner_receipts_unavailable")
        return self._scorer_counts(run.source, run.tasks, run.receipts)

    def verify(self, evidence: CandidateExecutionEvidenceV2, source: LearningItemSourceV1) -> bool:
        try:
            evidence = checked_model(evidence, CandidateExecutionEvidenceV2)
            source = checked_model(source, LearningItemSourceV1)
            run = self._runs.get(evidence.run_id)
            if run is None or run.source.source_hash != source.source_hash or run.tasks != self._tasks(source):
                return False
            if any(not self._runner.verify(receipt, request=task.wire) for task, receipt in zip(run.tasks, run.receipts, strict=True)):
                return False
            return evidence == self._evidence(source, evidence.run_id, run.tasks, run.receipts)
        except (ValueError, TypeError, AttributeError, KeyError):
            return False

    def resource_usage(self, evidence: CandidateExecutionEvidenceV2) -> ResourceAmounts:
        run = self._runs.get(evidence.run_id)
        if run is None or run.evidence != evidence:
            raise ValueError("runner_usage_unknown")
        return ResourceAmounts(execution_seconds=sum(math.ceil(receipt.elapsed_seconds) for receipt in run.receipts))

    def receipts(self, evidence: CandidateExecutionEvidenceV2) -> tuple[dict[str, object], ...]:
        run = self._runs.get(evidence.run_id)
        if run is None or run.evidence != evidence:
            raise ValueError("runner_receipts_unavailable")
        return tuple(receipt.to_payload() for receipt in run.receipts)
