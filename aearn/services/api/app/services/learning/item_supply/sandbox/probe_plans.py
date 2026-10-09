"""Bounded server-owned first-batch plans; never executes candidate code.

The oracle is a reviewed local fixture, not candidate/reference execution. Only
the declared finite public task profiles are supported. New semantics need a new reviewed
fixture; unsupported generated candidates are blocked before reservation/IO.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from app.services.learning.item_bank.compiler import curated_learning_item_source_root
from app.services.learning.item_bank.contracts import (
    LearningItemCodeContentV1, LearningItemCodePrivateV1, LearningItemSourceV1,
    LearningItemSqlContentV2, LearningItemSqlDatasetV2, LearningItemSqlPrivateV2,
    canonical_hash,
)
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.execution_contracts import (
    CandidateProbePlanV1, IndependentProbeV1, RunnerPort,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.sandbox.python_goal_scorer import (
    PYTHON_GOAL_ID, PYTHON_GOAL_INSTRUCTION, PYTHON_GOAL_PROFILE, compile_goal_tests, compile_python_test_bundle,
    test_goal_contract,
)
from app.services.learning.item_supply.validation_adapter import CandidateExecutionEvidenceV2
from app.services.runners.sandbox_runner import _run_single_test

PYTHON_PROFILE = "python_stdout_list_total_v1"
SQLITE_PROFILE = "sqlite_filter_track_v2"
SQLITE_EXPLICIT_PROFILE = "sqlite_filter_track_explicit_v1"
SQLITE_PROFILES = (SQLITE_PROFILE, SQLITE_EXPLICIT_PROFILE)
_FILES = {
    PYTHON_PROFILE: "python-stdout-list-total-v1.json",
    PYTHON_GOAL_PROFILE: "python-assignment-sum-print-v1.json",
    SQLITE_PROFILE: "sqlite-filter-track-v2-probes.json",
    SQLITE_EXPLICIT_PROFILE: "sqlite-filter-track-explicit-v1-probes.json",
}


class ProbePlanUnavailable(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def submission_fingerprint(source: LearningItemSourceV1, submission: str) -> str:
    """Ignore comments/formatting, not literal values. No AST evaluation."""
    if source.public.kind.value == "code":
        try:
            text = ast.dump(ast.parse(submission), include_attributes=False)
        except SyntaxError:
            text = submission.strip()
    else:
        # Quoted values remain case-sensitive. Tokenizing comments as units
        # avoids removing '--' or '/*' inside SQL string literals.
        tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/|[A-Za-z_]\w*|\d+|[^\s]", submission)
        text = " ".join(token if token.startswith(("'", '"')) else token.lower() for token in tokens if token != ";" and not token.startswith(("--", "/*")))
    return canonical_hash(text)


def _fixture(profile: str) -> tuple[dict[str, Any], str]:
    filename = _FILES.get(profile)
    if filename is None:
        raise ProbePlanUnavailable("candidate_probe_profile_not_supported")
    raw = (Path(__file__).with_name("probe_fixtures") / filename).read_bytes()
    fixture = json.loads(raw)
    return fixture, hashlib.sha256(raw).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _choose_equivalent(source: LearningItemSourceV1, reference: str, starter: str, fixture: dict[str, Any]) -> str:
    used = {submission_fingerprint(source, value) for value in (reference, starter, fixture["wrong"])}
    for submission in fixture["equivalents"]:
        if submission_fingerprint(source, submission) not in used:
            return str(submission)
    raise ProbePlanUnavailable("candidate_probe_independent_alternative_missing")


def _stdout_case(name: str, stdout: str, *, goal: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    test: dict[str, Any] = {"id": name, "case_type": "hidden", "expected_output_json": {"stdout": stdout}}
    if goal is not None:
        test["input_json"] = {"goal_contract": goal}
    tests = (test,)
    return list(compile_python_test_bundle(tests)), list(tests)


def _sql_case(name: str, fixture: dict[str, Any], dataset: dict[str, Any], columns: list[str], rows: list[list[object]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return ([{"id": name, "case_type": "hidden", "tables": fixture["tables"], "dataset": dataset, "max_rows": 20}], [{"id": name, "case_type": "hidden", "expected_output": {"columns": columns, "rows": rows}, "comparison": "ordered"}])


def _probe(name: str, submission: str, expected: str, cases: list[dict[str, Any]], tests: list[dict[str, Any]]) -> IndependentProbeV1:
    return IndependentProbeV1.model_validate({"name": name, "submission": submission, "expected": expected, "cases_json": _json(cases), "tests_json": _json(tests)})


def _filter_track_oracle(public: LearningItemSqlContentV2, dataset: LearningItemSqlDatasetV2, declaration: dict[str, Any]) -> dict[str, Any]:
    """One exact declarative task, not a SQL interpreter or reference oracle.

    The source model already validates types/PKs/FKs against the fixed schema.
    Expected truth depends only on candidate data and this server-owned rule.
    """
    if declaration != {"kind": "filter_track", "table": "learners", "filter_column": "track", "filter_value": "sql", "order_by": "id", "projection": ["name"]}:
        raise ProbePlanUnavailable("candidate_probe_sql_oracle_not_supported")
    if sum(len(table.rows) for table in dataset.tables) > 256:
        raise ProbePlanUnavailable("candidate_probe_sql_dataset_bound_exceeded")
    table = next(table for table in public.tables if table.name == declaration["table"])
    data = next(table for table in dataset.tables if table.table == declaration["table"])
    columns = [column.name for column in table.columns]
    filter_index = columns.index(declaration["filter_column"])
    order_index = columns.index(declaration["order_by"])
    projection_index = columns.index(declaration["projection"][0])
    matching = [row for row in data.rows if row[filter_index] == declaration["filter_value"]]
    matching.sort(key=lambda row: cast(int, row[order_index]))
    if len(matching) > public.max_rows:
        raise ProbePlanUnavailable("candidate_probe_sql_result_bound_exceeded")
    return {"kind": "table_result_v1", "columns": declaration["projection"], "rows": [[row[projection_index]] for row in matching]}


def build_candidate_probe_plan(source: LearningItemSourceV1, *, profile_id: str | None = None) -> CandidateProbePlanV1:
    """Bind an exact candidate to a finite supported public task and fixed oracle.

    SQL candidate datasets may differ. Their truth is checked against the exact
    server-owned filter_track rule, never executed reference SQL or old hidden
    fixtures. A caller must regenerate an unsupported task, not relabel it.
    """
    source = checked_model(source, LearningItemSourceV1)
    if profile_id is None and source.public.kind.value == "code" and source.public.instruction_markdown == PYTHON_GOAL_INSTRUCTION:
        profile = PYTHON_GOAL_PROFILE
    elif profile_id is None and source.public.kind.value == "sql":
        explicit, _ = _fixture(SQLITE_EXPLICIT_PROFILE)
        profile = SQLITE_EXPLICIT_PROFILE if source.public.instruction_markdown == explicit["instruction"] else SQLITE_PROFILE
    else:
        profile = profile_id or (PYTHON_PROFILE if source.public.kind.value == "code" else SQLITE_PROFILE)
    fixture, digest = _fixture(profile)
    public, private = source.public.content, source.private.content
    if source.public.instruction_markdown != fixture["instruction"]:
        raise ProbePlanUnavailable("candidate_probe_public_task_not_supported")
    if list(source.blueprint.required_capabilities) != fixture["required_capabilities"]:
        raise ProbePlanUnavailable("candidate_probe_capabilities_not_supported")
    if not isinstance(private, (LearningItemCodePrivateV1, LearningItemSqlPrivateV2)) or private.score_policy.kind != "all_tests" or private.score_policy.threshold != 1.0:
        raise ProbePlanUnavailable("candidate_probe_score_policy_not_supported")
    probes: list[IndependentProbeV1] = []
    if profile in (PYTHON_PROFILE, PYTHON_GOAL_PROFILE):
        if not isinstance(public, LearningItemCodeContentV1) or not isinstance(private, LearningItemCodePrivateV1) or source.blueprint.runtime_profile_id != "python_stdout_test" or source.blueprint.language_id != "python" or public.language_id != "python" or public.exercise_type != "code_completion" or public.required_patterns:
            raise ProbePlanUnavailable("candidate_probe_python_stdout_only_required")
        if {test.case_type for test in private.tests} != {"visible", "hidden"}:
            raise ProbePlanUnavailable("candidate_probe_visibility_missing")
        for test in compile_goal_tests(source):
            # The strict source schema has no assertion_code field; arbitrary
            # assertion/return payloads cannot enter this stdout-only profile.
            goal = test_goal_contract(test)
            if goal != (PYTHON_GOAL_ID if profile == PYTHON_GOAL_PROFILE else None):
                raise ProbePlanUnavailable("candidate_probe_stdout_oracle_not_supported")
            # Compare the independent fixture truth against authored expected
            # using the SAME guarded stdout scorer as execution. It ignores
            # trailing LF, not spaces; don't rewrite staged source payloads or
            # invent broader whitespace/CR normalization in a second oracle.
            judged = _run_single_test({}, "unused", test, fixture["expected_stdout"])
            if judged["passed"] is not True:
                raise ProbePlanUnavailable("candidate_probe_stdout_oracle_not_supported")
        reference, starter = private.standard_answer, public.starter_code
        boundary = fixture["boundary"]
        if profile == PYTHON_GOAL_PROFILE and source.public.difficulty.value != "D1":
            raise ProbePlanUnavailable("candidate_probe_python_basic_difficulty_required")
        goal = PYTHON_GOAL_ID if profile == PYTHON_GOAL_PROFILE else None
        cases, tests = _stdout_case("independent_missing_assignment" if goal else "independent_negative_total", boundary["stdout"], goal=goal)
        for semantic in fixture["semantics"]:
            positive_cases, positive_tests = _stdout_case(semantic["name"], semantic["stdout"], goal=goal)
            for suffix, submission, expectation in (("", semantic["correct"], "pass"), ("_wrong", semantic["wrong"], "reject")):
                # The two finite allowed positive forms already run as actual
                # reference/equivalent controls. Do not rename/recount them as
                # four independent positives on otherwise identical goal data.
                if goal is not None and expectation == "pass":
                    continue
                probes.append(_probe(semantic["name"] + suffix, submission, expectation, positive_cases, positive_tests))
    elif profile in SQLITE_PROFILES:
        if not isinstance(public, LearningItemSqlContentV2) or not isinstance(private, LearningItemSqlPrivateV2) or source.blueprint.runtime_profile_id != "sql_query_test" or public.dialect != "sqlite" or public.comparison != "ordered" or public.max_rows != 20:
            raise ProbePlanUnavailable("candidate_probe_sql_profile_not_supported")
        anchor = curated_learning_item_source_root() / fixture["anchor_file"]
        if hashlib.sha256(anchor.read_bytes()).hexdigest() != fixture["anchor_sha256"]:
            raise ProbePlanUnavailable("candidate_probe_curated_anchor_changed")
        if [table.model_dump(mode="json") for table in public.tables] != fixture["tables"] or public.public_dataset.model_dump(mode="json") != fixture["public_dataset"]:
            raise ProbePlanUnavailable("candidate_probe_sql_schema_dataset_or_oracle_not_supported")
        for sql_test in private.tests:
            expected = _filter_track_oracle(public, sql_test.dataset, fixture["oracle"])
            if sql_test.expected_output.model_dump(mode="json") != expected:
                raise ProbePlanUnavailable("candidate_probe_sql_schema_dataset_or_oracle_not_supported")
        reference, starter = private.standard_query, public.starter_query
        boundary = fixture["boundary"]
        cases, tests = _sql_case("independent_filter_boundary", fixture, boundary["dataset"], boundary["columns"], boundary["rows"])
        for semantic in fixture["semantics"]:
            pair_cases, pair_tests = _sql_case(semantic["name"], fixture, semantic.get("dataset", boundary["dataset"]), semantic["columns"], semantic["rows"])
            # Boundary below runs the actual candidate on new independent data;
            # the semantic positive uses a genuinely different known solution.
            correct = _choose_equivalent(source, reference, starter, fixture) if semantic["name"] == "duplicates" else semantic["correct"]
            for suffix, submission, expectation in (("", correct, "pass"), ("_wrong", semantic["wrong"], "reject")):
                probes.append(_probe(semantic["name"] + suffix, submission, expectation, pair_cases, pair_tests))
        for name, query, expectation, dataset in (
            ("read_only", "DELETE FROM learners;", "reject", boundary["dataset"]),
            ("single_statement", "SELECT name FROM learners; SELECT name FROM learners;", "reject", boundary["dataset"]),
            ("bounded_setup", "SELECT name FROM learners;", "sql_setup_invalid", {"tables": [{"table": "mentors", "rows": []}, {"table": "learners", "rows": [[i, "N", "sql", None] for i in range(257)]}]}),
        ):
            protocol_cases, _ = _sql_case(name, fixture, dataset, ["name"], [])
            probes.append(_probe(name, query, expectation, protocol_cases, []))
    else:
        raise ProbePlanUnavailable("candidate_probe_profile_not_supported")
    equivalent = _choose_equivalent(source, reference, starter, fixture)
    boundary_submission = reference if profile in SQLITE_PROFILES else boundary["submission"]
    if profile not in SQLITE_PROFILES and submission_fingerprint(source, boundary_submission) in {submission_fingerprint(source, value) for value in (reference, starter, equivalent, fixture["wrong"])}:
        raise ProbePlanUnavailable("candidate_probe_boundary_not_independent")
    return CandidateProbePlanV1(source_hash=source.source_hash, profile_id=profile, server_fixture_hash=digest, equivalent=equivalent, wrong=fixture["wrong"], boundary=boundary_submission, boundary_cases_json=_json(cases), boundary_tests_json=_json(tests), probes=tuple(probes))


@dataclass(frozen=True)
class ProbeSmokeResult:
    evidence: CandidateExecutionEvidenceV2
    reserved_bound: ResourceAmounts
    usage: ResourceAmounts
    scorer_counts: dict[str, int]
    terminal_receipts: tuple[dict[str, object], ...]


def run_candidate_probe_smoke(source: LearningItemSourceV1, runner: RunnerPort, *, parent_deadline_at: datetime, profile_id: str | None = None) -> ProbeSmokeResult:
    """Standalone main-only entry. Caller reserves the full bound before this IO.

    Runner must be the existing sealed bridge. This does not open a DB/provider,
    create a budget root, extend a deadline, or claim admission/public readiness.
    """
    from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort

    plan = build_candidate_probe_plan(source, profile_id=profile_id)
    port = SandboxCandidateExecutionPort(runner, probe_plan=plan, parent_deadline_at=parent_deadline_at)
    bound = port.resource_plan(source)
    evidence = port.validate(source)
    if not port.verify(evidence, source):
        raise ValueError("runner_terminal_receipt_untrusted")
    return ProbeSmokeResult(evidence, bound, port.resource_usage(evidence), port.scorer_counts(evidence), port.receipts(evidence))
