"""API-private finite candidate probes, not task-family or execution authority.

Independent truth comes from closed arithmetic/data oracles, never execution of
provider reference code. Nothing in this module is passed to public/blind models.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.services.learning.item_bank.contracts import (
    LearningItemBlueprintV1, LearningItemCodeContentV1, LearningItemCodePrivateV1,
    LearningItemKnowledgeCheckPrivateV1, LearningItemPublicV1,
    LearningItemSourceV1, LearningItemSqlContentV2,
    LearningItemSqlPrivateV2, canonical_hash,
)
from app.services.learning.item_supply.finite_candidate_factory import (
    FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2, FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1, _python_task,
    check_finite_source_spec as check_public_source_spec, public_task_from_blueprint,
)
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_task_families import families_for_course, initial_slot_allocations
from app.services.learning.item_supply.finite_targets.python_state import (
    PYTHON_STATE_GOAL_ID, PythonStateTarget, _programs,
    python_state_expected_stdout,
)
from app.services.learning.item_supply.finite_targets.sqlite_predicates import (
    parse_sqlite_target, sqlite_oracle, sqlite_private_fixture, sqlite_public_task,
)
from app.services.learning.item_supply.sandbox.execution_contracts import CandidateProbePlanV1, IndependentProbeV1
from app.services.learning.item_supply.sandbox.probe_plans import submission_fingerprint
from app.services.learning.item_supply.sandbox.python_state_scorer import (
    compile_python_state_test_bundle, python_state_test_target,
)
from app.services.learning.item_supply.storage_contracts import checked_model

PYTHON_FINITE_PROFILE = "finite_python_state_fixed_goal_v1"
SQLITE_FINITE_PROFILE = "finite_sqlite_predicate_controls_v1"


def public_python_state_target(
    blueprint: LearningItemBlueprintV1, public_template: LearningItemPublicV1,
) -> PythonStateTarget | None:
    """Recognize the frozen public factory task without private candidate content."""
    blueprint = checked_model(blueprint, LearningItemBlueprintV1)
    public_template = checked_model(public_template, LearningItemPublicV1)
    prefix = "finite.python-state-update-v1."
    if not blueprint.blueprint_key.startswith(prefix):
        return None
    if blueprint.version == FLEXIBLE_FACTORY_VERSION:
        goal, _, _ = public_task_from_blueprint(blueprint, public_template, PYTHON_STATE_GOAL_ID)
        return goal
    match = re.fullmatch(re.escape(prefix) + r"(practice-1|practice-2|assessment-1|assessment-2|guided-remediation)\.s([0-9]{1,3})", blueprint.blueprint_key)
    if match is None or blueprint.version not in (FACTORY_VERSION, PYTHON_FACTORY_VERSION_V2) or int(match[2]) > 255:
        raise ValueError("finite_python_public_task_mismatch")
    allocation = next(a for a in initial_slot_allocations(PYTHON_STATE_GOAL_ID)
                      if a.variant_id == PYTHON_STATE_GOAL_ID + ":" + match[1])
    family = next(f for f in families_for_course(PYTHON_STATE_GOAL_ID) if f.family_id == allocation.family_id)
    goal, instruction, content = _python_task(family.task_kind, int(match[2]), allocation.slot == "remediation",
                                             public_spec_version=blueprint.version)
    if (public_template.instruction_markdown != instruction or public_template.content != content
            or blueprint.purpose != public_template.purpose
            or blueprint.item_kind != public_template.kind
            or blueprint.language_id != "python"
            or blueprint.allowed_interactions != public_template.allowed_interactions
            or blueprint.knowledge_key != "finite." + PYTHON_STATE_GOAL_ID
            or public_template.purpose.value != allocation.purpose
            or blueprint.runtime_profile_id != "python_stdout_test"
            or blueprint.required_capabilities != ("python.assignment",)):
        raise ValueError("finite_python_public_task_mismatch")
    return goal



def source_python_state_target(source: LearningItemSourceV1) -> PythonStateTarget | None:
    """Candidate wrapper around the same public-only recognition contract."""
    return public_python_state_target(source.blueprint, source.public)

def native_python_tests(source: LearningItemSourceV1) -> tuple[dict[str, Any], ...]:
    goal = source_python_state_target(source)
    private = source.private.content
    if goal is None or not isinstance(private, LearningItemCodePrivateV1):
        raise ValueError("finite_python_public_task_mismatch")
    tests = []
    for test in private.tests:
        raw = test.model_dump(mode="json")
        # The source is immutable. Compile its public goal into a separate wire
        # bundle, allowing omission but never a contradictory proposed target.
        if raw["input_json"] not in ({}, {"goal_contract": goal.model_dump(mode="json")}):
            raise ValueError("finite_python_test_goal_mismatch")
        raw["input_json"] = {"goal_contract": goal.model_dump(mode="json")}
        if python_state_test_target(raw) != goal:
            raise ValueError("finite_python_expectation_mismatch")
        tests.append(raw)
    return tuple(tests)


def check_finite_source_spec(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> None:
    source = checked_model(source, LearningItemSourceV1)
    spec = checked_model(spec, FiniteCandidateSpecV1)
    target = get_finite_course_target(spec.target_id)
    check_public_source_spec(source, spec)
    if source.blueprint.version != FLEXIBLE_FACTORY_VERSION and (source.public != spec.public_template or source.blueprint != spec.blueprint
            or (source.blueprint.version != FACTORY_VERSION and not (
                spec.target_id == PYTHON_STATE_GOAL_ID and source.blueprint.version == PYTHON_FACTORY_VERSION_V2))
            or source.blueprint.blueprint_key != f"finite.{spec.target_id}.{spec.allocation.variant_id.rsplit(':', 1)[1]}.s{spec.seed}"
            or spec.target_definition_hash != target.definition_hash
            or spec.allocation not in initial_slot_allocations(spec.target_id)):
        raise ValueError("finite_candidate_specification_mismatch")
    family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
    if spec.family_definition_hash != family.definition_hash:
        raise ValueError("finite_candidate_family_declaration_mismatch")
    if spec.target_id == PYTHON_STATE_GOAL_ID:
        if spec.python_goal != source_python_state_target(source) or spec.sql_target is not None:
            raise ValueError("finite_candidate_instance_mismatch")
        native_python_tests(source)
    elif spec.target_id == "sqlite-predicate-order-v1":
        public, private = source.public.content, source.private.content
        if (spec.sql_target is None or spec.python_goal is not None
                or not isinstance(public, LearningItemSqlContentV2)
                or not isinstance(private, LearningItemSqlPrivateV2)
                or public.comparison != "ordered"):
            raise ValueError("finite_sql_candidate_shape_invalid")
        # Reconstruct the factory's exact public SQL instance. A typed target
        # paired with somebody else's instruction is not registered semantics.
        parameters: dict[str, object] = {"task_kind": family.task_kind}
        if family.task_kind == "conjunction":
            parameters["min_score"] = 60 + spec.seed
        elif family.task_kind == "keyset_after":
            parameters.update(cut_score=70 + spec.seed, cut_id=4 + spec.seed)
        expected_target = parse_sqlite_target(parameters)
        expected_task = sqlite_public_task(expected_target)
        instruction = expected_task.instruction
        guided = spec.allocation.slot == "remediation"
        if guided:
            instruction += ("\n先画空表，逐行检查 override_flag 是否为 NULL，再填写选用字段、有效值和入选判断；"
                            "随后检查 priority 的 NULL 位置及同优先级的 id 次序。表格由你填写，不预给筛选结果。")
        expected_content = expected_task.content.model_dump(mode="json")
        for table in expected_content["public_dataset"]["tables"]:
            for index, row in enumerate(table["rows"]):
                row[1] = f"entry-{spec.seed + (17 if guided else 0)}-{index + 1}"
        if (spec.sql_target != expected_target or (source.blueprint.version != FLEXIBLE_FACTORY_VERSION and source.public.instruction_markdown != instruction)
                or public.model_dump(mode="json") != expected_content):
            raise ValueError("finite_sql_public_instance_mismatch")
        for test in private.tests:
            truth = sqlite_oracle(spec.sql_target, test.dataset)
            if test.expected_output != truth or len(truth.rows) > public.max_rows:
                raise ValueError("finite_sql_private_expectation_mismatch")
    if (not isinstance(source.private.content, (LearningItemCodePrivateV1, LearningItemSqlPrivateV2, LearningItemKnowledgeCheckPrivateV1))
            or source.private.content.score_policy.threshold != 1.0):
        raise ValueError("finite_candidate_all_checks_required")


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _alternative(source: LearningItemSourceV1, programs: tuple[str, ...], excluded: tuple[str, ...]) -> str:
    fingerprints = {submission_fingerprint(source, program) for program in excluded}
    for program in programs:
        if submission_fingerprint(source, program) not in fingerprints:
            return program
    raise ValueError("finite_equivalent_alternative_unavailable")


def _probe(name: str, submission: str, expected: str,
           cases: tuple[dict[str, Any], ...], tests: tuple[dict[str, Any], ...]) -> IndependentProbeV1:
    return IndependentProbeV1.model_validate(dict(name=name, submission=submission, expected=expected,
        cases_json=_json(cases), tests_json=_json(tests)))


def build_finite_candidate_probe_plan(source: LearningItemSourceV1, *, spec: FiniteCandidateSpecV1) -> CandidateProbePlanV1:
    """Exact inputs for the existing sealed port. Does not run/sign or admit."""
    check_finite_source_spec(source, spec)
    if spec.target_id == PYTHON_STATE_GOAL_ID:
        return _python_plan(source, spec)
    if spec.target_id == "sqlite-predicate-order-v1":
        return _sqlite_plan(source, spec)
    raise ValueError("finite_static_candidate_has_no_os_probe_plan")


def _python_plan(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> CandidateProbePlanV1:
    goal = spec.python_goal
    private = source.private.content
    if goal is None or not isinstance(private, LearningItemCodePrivateV1):
        raise ValueError("finite_python_candidate_shape_invalid")
    _, _, reference, equivalent, wrongs = _programs(goal)
    if not isinstance(spec.public_template.content, LearningItemCodeContentV1):
        raise ValueError("finite_python_candidate_shape_invalid")
    starter = spec.public_template.content.starter_code
    equivalent = _alternative(source, (reference, equivalent), (private.standard_answer, starter))
    boundary = next(w for w in wrongs if w.name == "hardcoded_stdout")
    if (boundary.expected_stdout != python_state_expected_stdout(goal)
            or submission_fingerprint(source, boundary.submission)
            in {submission_fingerprint(source, p) for p in (private.standard_answer, starter, equivalent)}):
        raise ValueError("finite_fixed_goal_boundary_not_independent")
    wrong = _alternative(source, tuple(w.submission for w in wrongs if w.name != "hardcoded_stdout"),
                         (private.standard_answer, starter, equivalent, boundary.submission))
    tests = native_python_tests(source)
    cases = compile_python_state_test_bundle(tests)
    used = {submission_fingerprint(source, value)
            for value in (private.standard_answer, starter, equivalent, wrong, boundary.submission)}
    probes = [_probe("finite_state_negative_" + w.name, w.submission, "reject", cases, tests)
              for w in wrongs if submission_fingerprint(source, w.submission) not in used]
    digest = canonical_hash({"spec": spec.specification_hash, "source": source.source_hash,
        "instance": goal.target_hash, "expected": python_state_expected_stdout(goal),
        "profile": PYTHON_FINITE_PROFILE, "boundary_mode": "same_goal_same_stdout_semantic_reject_v1",
        "boundary": boundary.submission, "cases": cases, "tests": tests,
        "programs": (reference, equivalent, wrong), "probes": [p.model_dump(mode="json") for p in probes]})
    # Same public goal, expected stdout and cases; a genuinely different program
    # must be rejected by the protected semantic scorer. No parameterized claim.
    return CandidateProbePlanV1(source_hash=source.source_hash, profile_id=PYTHON_FINITE_PROFILE,
        server_fixture_hash=digest, equivalent=equivalent, wrong=wrong, boundary=boundary.submission,
        boundary_cases_json=_json(cases), boundary_tests_json=_json(tests), probes=tuple(probes))


def _sqlite_plan(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> CandidateProbePlanV1:
    target, public, private = spec.sql_target, source.public.content, source.private.content
    if target is None or not isinstance(public, LearningItemSqlContentV2) or not isinstance(private, LearningItemSqlPrivateV2):
        raise ValueError("finite_sql_candidate_shape_invalid")
    fixture = sqlite_private_fixture(target)
    equivalent = _alternative(source, fixture.equivalent_queries, (private.standard_query, public.starter_query))
    wrong = _alternative(source, tuple(n.query for n in fixture.counterexamples),
                         (private.standard_query, public.starter_query, equivalent))
    tables = [t.model_dump(mode="json") for t in public.tables]
    cases = tuple({"id": "finite_" + t.id.replace(".", "_"), "case_type": "hidden", "tables": tables,
                   "dataset": t.dataset.model_dump(mode="json"), "max_rows": public.max_rows}
                  for t in fixture.private_cases)
    tests = tuple({"id": c["id"], "case_type": "hidden",
                   "expected_output": t.expected_output.model_dump(mode="json"), "comparison": "ordered"}
                  for c, t in zip(cases, fixture.private_cases, strict=True))
    proposed_datasets = {canonical_hash(t.dataset.model_dump(mode="json")) for t in private.tests}
    proposed_datasets.add(canonical_hash(public.public_dataset.model_dump(mode="json")))
    independent = tuple((c, t) for c, t in zip(cases, tests, strict=True)
                        if canonical_hash(c["dataset"]) not in proposed_datasets)
    if any(not n.failing_case_ids for n in fixture.counterexamples):
        raise ValueError("finite_sql_negative_not_discriminating")
    probes = tuple(_probe("finite_sql_negative_" + n.fault, n.query, "reject", cases, tests)
                   for n in fixture.counterexamples)
    # Real engine controls, not aliases for target semantics or JOIN coverage.
    control_case = cases[0]
    for name, query in (("read_only", "DELETE FROM entries"),
                        ("single_statement", "SELECT name FROM entries; SELECT name FROM entries")):
        probes += (_probe(name, query, "reject", (dict(control_case, id=name, case_type="visible"),), ()),)
    row = list(fixture.private_cases[0].dataset.tables[0].rows[0])
    identity_index = next(i for i, column in enumerate(public.tables[0].columns) if column.name == "id")
    setup_rows = []
    for identity in range(257):
        entry = list(row)
        entry[identity_index] = identity
        setup_rows.append(entry)
    bounded_case = dict(control_case, id="bounded_setup", case_type="visible",
                       dataset={"tables": [{"table": "entries", "rows": setup_rows}]})
    probes += (_probe("bounded_setup", "SELECT name FROM entries", "sql_setup_invalid", (bounded_case,), ()),)
    digest = canonical_hash({"spec": spec.specification_hash, "source": source.source_hash,
        "instance": target.model_dump(mode="json"), "profile": SQLITE_FINITE_PROFILE,
        "boundary_mode": "unchanged_candidate_independent_dataset_v1", "oracle": "sqlite_finite_data_traversal_v1",
        "cases": cases, "tests": tests, "probes": [p.model_dump(mode="json") for p in probes]})
    return CandidateProbePlanV1(source_hash=source.source_hash, profile_id=SQLITE_FINITE_PROFILE,
        server_fixture_hash=digest, equivalent=equivalent, wrong=wrong, boundary=private.standard_query,
        boundary_cases_json=_json(tuple(c for c, _ in independent)) if independent else None,
        boundary_tests_json=_json(tuple(t for _, t in independent)) if independent else None,
        probes=probes)
