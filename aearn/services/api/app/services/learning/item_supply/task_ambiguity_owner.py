"""Finite SQL/Python task ambiguity owner. Exactly two sealed container calls."""
from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from aearn_shared.execution import ExecutionAction, SafeExecutionResultV1, SafeExecutionStatus, SandboxInputV1

from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1, LearningItemCodePrivateV1, LearningItemSqlContentV2, LearningItemSqlDatasetV2,
    LearningItemSqlPrivateV2, canonical_hash,
)
from app.services.learning.item_supply.admission_facts_contracts import (
    PythonTaskTargetV1, RunnerTerminalProofV1, TaskAmbiguityPlanV1, TaskAmbiguityReceiptV1, TaskTargetV1,
)
from app.services.learning.item_supply.contracts import ObjectiveClauseV1
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.execution_contracts import EXECUTION_WALL_SECONDS, CandidateProbePlanV1, RunnerPort, RunnerTerminalReceipt
from app.services.learning.item_supply.sandbox.probe_plans import (
    SQLITE_EXPLICIT_PROFILE, _filter_track_oracle, _fixture, build_candidate_probe_plan, submission_fingerprint,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_CAPABILITIES, PYTHON_GOAL_CORRECT, PYTHON_GOAL_COUNTEREXAMPLE,
    PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION, PYTHON_GOAL_PROFILE,
    PYTHON_GOAL_SCORER_VERSION, compile_python_test_bundle, score_python_case,
)
from app.services.learning.practice.contracts import ExerciseAttemptOutcome
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION, score_execution_result
from app.services.runners.sql_query_runner import _compare_expected

SQL_TARGET_INSTRUCTION = str(_fixture(SQLITE_EXPLICIT_PROFILE)[0]["instruction"])
SQL_CAPABILITIES = ("sql.select.where","sql.order_by")
CORRECT_QUERY = "SELECT name FROM learners WHERE track = 'sql' ORDER BY id ASC"
COUNTEREXAMPLE_QUERY = "SELECT DISTINCT name FROM learners WHERE track = 'sql' ORDER BY id DESC"
PROBE_NAMES = ("admission_ambiguity_correct","admission_ambiguity_counterexample")
CALL_EXECUTION_BOUND = EXECUTION_WALL_SECONDS + 5
EXECUTION_BOUND = 2 * CALL_EXECUTION_BOUND


class AdmissionFactsPending(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def target_clauses(source: LearningItemSourceV1 | None = None) -> tuple[ObjectiveClauseV1, ...]:
    target = (TaskTargetV1() if source is None else require_finite_target(source)).model_dump(mode="json")
    capabilities = PYTHON_GOAL_CAPABILITIES if source is not None and source.public.kind.value == "code" else SQL_CAPABILITIES
    return tuple(ObjectiveClauseV1(clause_id=capability,
        clause_hash=canonical_hash({"capability":capability,"target":target}))
        for capability in capabilities)


def require_python_target(source: LearningItemSourceV1) -> PythonTaskTargetV1:
    source = checked_model(source, LearningItemSourceV1)
    if source.public.instruction_markdown != PYTHON_GOAL_INSTRUCTION:
        raise AdmissionFactsPending("python_assignment_goal_unproven")
    try:
        build_candidate_probe_plan(source, profile_id=PYTHON_GOAL_PROFILE)
    except ValueError:
        raise AdmissionFactsPending("python_assignment_goal_unproven") from None
    return PythonTaskTargetV1()


def require_finite_target(source: LearningItemSourceV1) -> TaskTargetV1 | PythonTaskTargetV1:
    if source.public.kind.value == "code":
        return require_python_target(source)
    require_sql_target(source)
    return TaskTargetV1()


def require_sql_target(source: LearningItemSourceV1) -> None:
    source = checked_model(source,LearningItemSourceV1)
    if source.public.kind.value == "code":
        raise AdmissionFactsPending("python_assignment_goal_unproven")
    public,private = source.public.content,source.private.content
    if not isinstance(public,LearningItemSqlContentV2) or not isinstance(private,LearningItemSqlPrivateV2):
        raise AdmissionFactsPending("finite_target_profile_unsupported")
    if source.public.instruction_markdown != SQL_TARGET_INSTRUCTION:
        raise AdmissionFactsPending("task_semantics_not_explicit")
    fixture,_ = _fixture(SQLITE_EXPLICIT_PROFILE)
    if (source.blueprint.required_capabilities != SQL_CAPABILITIES
            or public.dialect != "sqlite" or public.comparison != "ordered" or public.max_rows != 20
            or [table.model_dump(mode="json") for table in public.tables] != fixture["tables"]):
        raise AdmissionFactsPending("finite_target_interface_mismatch")
    allowed = {submission_fingerprint(source,CORRECT_QUERY),
               submission_fingerprint(source,CORRECT_QUERY.removesuffix(" ASC"))}
    if submission_fingerprint(source,private.standard_query) not in allowed:
        raise AdmissionFactsPending("candidate_target_query_unproven")
    for test in private.tests:
        if test.expected_output.model_dump(mode="json") != _filter_track_oracle(public,test.dataset,fixture["oracle"]):
            raise AdmissionFactsPending("candidate_target_oracle_mismatch")


def build_task_ambiguity_plan(source: LearningItemSourceV1) -> TaskAmbiguityPlanV1:
    if source.public.kind.value == "code":
        target = require_python_target(source)
        tests = ({"id": "same_stdout_assignment_goal", "case_type": "hidden",
            "input_json": {"goal_contract": PYTHON_GOAL_ID}, "expected_output_json": {"stdout": "5"}},)
        python_cases = compile_python_test_bundle(tests)
        def python_wire(submission: str) -> SandboxInputV1:
            return SandboxInputV1(runtime_id="python-stdout-v1", action=ExecutionAction.TEST,
                submission=submission, hidden_test_bundle_json=json.dumps(python_cases,separators=(",", ":")),
                source_reference_hash=source.source_hash, test_reference_hash=canonical_hash(python_cases))
        return TaskAmbiguityPlanV1(source_hash=source.source_hash, content_hash=source.content_hash,
            public_task_hash=canonical_hash(source.public.model_dump(mode="json")), target=target,
            scorer_version=PYTHON_GOAL_SCORER_VERSION, correct=python_wire(PYTHON_GOAL_CORRECT),
            counterexample=python_wire(PYTHON_GOAL_COUNTEREXAMPLE), expected_json=json.dumps(tests,separators=(",", ":")))
    require_sql_target(source)
    public = source.public.content
    assert isinstance(public,LearningItemSqlContentV2)
    fixture,_ = _fixture(SQLITE_EXPLICIT_PROFILE)
    # Duplicates-only has no observable name order; order-only has no duplicates.
    datasets = (
        ("matching",[[9,"Zoe","sql",None],[1,"Other","python",None],[2,"Ada","sql",None]]),
        ("duplicates",[[9,"Ada","sql",None],[2,"Ada","sql",None],[1,"Other","python",None]]),
        ("ordering",[[9,"Zoe","sql",None],[2,"Ada","sql",None],[4,"Bea","sql",None]]),
    )
    cases: list[dict[str,Any]] = []
    expected: list[dict[str,Any]] = []
    for name,rows in datasets:
        dataset = LearningItemSqlDatasetV2.model_validate_json(json.dumps({"tables":[
            {"table":"mentors","rows":[]},{"table":"learners","rows":rows}]}))
        oracle = _filter_track_oracle(public,dataset,fixture["oracle"])
        cases.append({"id":name,"case_type":"hidden","tables":fixture["tables"],
            "dataset":dataset.model_dump(mode="json"),"max_rows":20})
        expected.append({"id":name,"expected_output":oracle,"comparison":"ordered"})
    def wire(query: str) -> SandboxInputV1:
        return SandboxInputV1(runtime_id="sqlite-query-v1",action=ExecutionAction.TEST,submission=query,
            hidden_test_bundle_json=json.dumps(cases,separators=(",",":")),
            source_reference_hash=source.source_hash,test_reference_hash=canonical_hash(cases))
    return TaskAmbiguityPlanV1(source_hash=source.source_hash,content_hash=source.content_hash,
        public_task_hash=canonical_hash(source.public.model_dump(mode="json")),target=TaskTargetV1(),
        scorer_version=GATE_PASS_POLICY_VERSION,correct=wire(CORRECT_QUERY),
        counterexample=wire(COUNTEREXAMPLE_QUERY),expected_json=json.dumps(expected,separators=(",",":")))


def build_sql_admission_candidate_plan(source: LearningItemSourceV1) -> CandidateProbePlanV1:
    """New versioned exact fixture, no temporary source/instruction rewrite."""
    require_sql_target(source)
    return build_candidate_probe_plan(source,profile_id=SQLITE_EXPLICIT_PROFILE)


def build_python_admission_candidate_plan(source: LearningItemSourceV1) -> CandidateProbePlanV1:
    require_python_target(source)
    return build_candidate_probe_plan(source, profile_id=PYTHON_GOAL_PROFILE)


class TaskAmbiguityOwner:
    def __init__(self, runner: RunnerPort, *, parent_deadline_at: datetime,
                 clock: Callable[[],datetime] | None = None) -> None:
        if parent_deadline_at.tzinfo is None:
            raise AdmissionFactsPending("ambiguity_deadline_missing")
        self._runner = runner
        self._deadline = parent_deadline_at
        self._clock = clock or (lambda: datetime.now(UTC))
        self._runs: dict[UUID,tuple[LearningItemSourceV1,tuple[RunnerTerminalReceipt,...],TaskAmbiguityReceiptV1]] = {}

    def resource_plan(self, plan: TaskAmbiguityPlanV1) -> ResourceAmounts:
        checked_model(plan,TaskAmbiguityPlanV1)
        return ResourceAmounts(execution_seconds=EXECUTION_BOUND)

    def _score(self, source: LearningItemSourceV1, plan: TaskAmbiguityPlanV1,
               terminal: RunnerTerminalReceipt) -> tuple[tuple[bool,...],str]:
        result = terminal.result
        if (terminal.mode != "live" or terminal.isolation != "approved_os_boundary"
                or not math.isfinite(terminal.elapsed_seconds) or not 0 <= terminal.elapsed_seconds <= CALL_EXECUTION_BOUND
                or result.status is not SafeExecutionStatus.SUCCESS or result.stderr
                or result.diagnostic_code != "item_supply_facts_v1"):
            raise AdmissionFactsPending("ambiguity_terminal_unverified")
        expected = json.loads(plan.expected_json)
        try:
            facts = json.loads(result.stdout)["cases"]
            if not isinstance(facts,list) or [f["id"] for f in facts] != [t["id"] for t in expected]:
                raise ValueError("facts shape")
            outcomes = []
            for fact,test in zip(facts,expected,strict=True):
                if isinstance(plan.target, PythonTaskTargetV1):
                    judged = score_python_case(test, fact)
                    if judged is None:
                        raise ValueError("semantic goal facts missing")
                    outcomes.append(judged)
                    continue
                if fact["status"] != "success" or fact["code"] != "sqlite_terminal":
                    raise ValueError("semantic facts missing")
                columns,rows = fact["columns"],fact["rows"]
                oracle = test["expected_output"]
                actual_rows = [dict(zip(columns,row,strict=True)) for row in rows]
                expected_rows = [dict(zip(oracle["columns"],row,strict=True)) for row in oracle["rows"]]
                outcomes.append(_compare_expected(columns,actual_rows,(oracle["columns"],expected_rows),"ordered")[0])
            private = source.private.content
            assert isinstance(private,(LearningItemSqlPrivateV2, LearningItemCodePrivateV1))
            score = score_execution_result(SafeExecutionResultV1(status=SafeExecutionStatus.SUCCESS,
                passed_test_count=sum(outcomes),total_test_count=len(outcomes)),
                required_capabilities=source.blueprint.required_capabilities,threshold=private.score_policy.threshold)
            return tuple(outcomes),"passed" if score.outcome is ExerciseAttemptOutcome.PASSED else "failed"
        except (ValueError,TypeError,KeyError):
            raise AdmissionFactsPending("ambiguity_semantic_facts_missing") from None

    def _receipt(self, source: LearningItemSourceV1, plan: TaskAmbiguityPlanV1,
                 run_id: UUID, terminals: tuple[RunnerTerminalReceipt,...], *,
                 started_at: datetime, completed_at: datetime) -> TaskAmbiguityReceiptV1:
        if (plan != build_task_ambiguity_plan(source) or len(terminals) != 2
                or started_at.tzinfo is None or not started_at <= completed_at < self._deadline):
            raise AdmissionFactsPending("ambiguity_plan_stale")
        for name,request,terminal in zip(PROBE_NAMES,(plan.correct,plan.counterexample),terminals,strict=True):
            if ((terminal.run_id,terminal.probe_name)!=(run_id,name)
                    or terminal.request_hash != canonical_hash(request.model_dump(mode="json"))
                    or not self._runner.verify(terminal,request=request)):
                raise AdmissionFactsPending("ambiguity_seal_unverified")
        positive,pos_score = self._score(source,plan,terminals[0])
        negative,neg_score = self._score(source,plan,terminals[1])
        if not all(positive) or any(negative) or (pos_score,neg_score)!=("passed","failed"):
            raise AdmissionFactsPending("ambiguity_counterexample_failed")
        proofs = tuple(RunnerTerminalProofV1.model_validate_json(json.dumps(t.to_payload())) for t in terminals)
        return TaskAmbiguityReceiptV1(plan=plan,run_id=run_id,started_at=started_at,
            completed_at=completed_at,parent_deadline_at=self._deadline,terminals=proofs,
            correct_case_results=positive,counterexample_case_results=negative,
            scorer_outcomes=("passed","failed"), derivation="explicit_python_goal_same_stdout_pair"
                if isinstance(plan.target, PythonTaskTargetV1) else "declarative_task_and_independent_duplicate_order_pair")

    def run(self, source: LearningItemSourceV1, plan: TaskAmbiguityPlanV1, *, run_id: UUID) -> TaskAmbiguityReceiptV1:
        source = checked_model(source,LearningItemSourceV1)
        plan = checked_model(plan,TaskAmbiguityPlanV1)
        if plan != build_task_ambiguity_plan(source):
            raise AdmissionFactsPending("ambiguity_plan_stale")
        if run_id in self._runs:
            original,terminals,receipt = self._runs[run_id]
            if original.source_hash != source.source_hash or receipt.plan != plan:
                raise AdmissionFactsPending("ambiguity_replay_conflict")
            return self._receipt(source,plan,run_id,terminals,started_at=receipt.started_at,completed_at=receipt.completed_at)
        if (self._deadline-self._clock()).total_seconds() < EXECUTION_BOUND:
            raise AdmissionFactsPending("ambiguity_full_execution_bound_missing")
        started_at = self._clock()
        fresh_terminals: list[RunnerTerminalReceipt] = []
        for index,(name,request) in enumerate(zip(PROBE_NAMES,(plan.correct,plan.counterexample),strict=True)):
            if (self._deadline-self._clock()).total_seconds() < (2-index)*CALL_EXECUTION_BOUND:
                raise AdmissionFactsPending("ambiguity_deadline_exhausted")
            fresh_terminals.append(self._runner.run(request=request,run_id=run_id,probe_name=name))
        if self._clock() >= self._deadline:
            raise AdmissionFactsPending("ambiguity_deadline_exhausted")
        receipt = self._receipt(source,plan,run_id,tuple(fresh_terminals),
            started_at=started_at,completed_at=self._clock())
        self._runs[run_id] = (source,tuple(fresh_terminals),receipt)
        return receipt

    def verify(self, receipt: TaskAmbiguityReceiptV1, source: LearningItemSourceV1) -> bool:
        try:
            receipt = checked_model(receipt,TaskAmbiguityReceiptV1)
            run = self._runs.get(receipt.run_id)
            if run is None or run[0].source_hash != source.source_hash:
                return False
            return receipt == self._receipt(source,receipt.plan,receipt.run_id,run[1],
                started_at=run[2].started_at,completed_at=run[2].completed_at)
        except (ValueError,TypeError,KeyError,AttributeError):
            return False

    def resource_usage(self, receipt: TaskAmbiguityReceiptV1) -> ResourceAmounts:
        run = self._runs.get(receipt.run_id)
        if run is None or run[2] != receipt:
            raise AdmissionFactsPending("ambiguity_usage_unavailable")
        return ResourceAmounts(execution_seconds=sum(math.ceil(t.elapsed_seconds) for t in run[1]))
