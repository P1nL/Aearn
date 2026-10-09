"""Closed private four-family transfer plans, not family-independence evidence.

No candidate execution/eval, terminal, seal, current-source grant, review verdict,
publication or pack readiness is produced. Only the registered reference forms
are transformed; unsupported lawful alignments remain explicit unresolved slots.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from io import StringIO
from itertools import combinations
import json
import re
import tokenize
from typing import Any, Literal, cast

from aearn_shared.execution import ExecutionAction, SafeTableResultPresentationV1, SandboxInputV1

from app.services.learning.item_bank.contracts import (
    LearningItemKnowledgeCheckContentV1, LearningItemSqlDatasetTableV2, LearningItemSqlDatasetV2, canonical_hash,
)
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, build_finite_candidate_spec
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.evidence import material_digest
from app.services.learning.item_supply.finite_family_transfer_contracts import (
    FiniteFamilyPairPlanV1, FiniteFamilyTransferDirectionV1, FiniteFamilyTransferPlanV1,
    FiniteTransferAlignmentV1, FiniteTransferCheckV1,
)
from app.services.learning.item_supply.finite_targets.contracts import FiniteTaskFamilyV1, TargetId
from app.services.learning.item_supply.finite_targets.python_kc import (
    KcTaskKind, PYTHON_KC_SCORER_VERSION, _truth, python_kc_fixture,
)
from app.services.learning.item_supply.finite_targets.python_state import (
    PythonStateTarget, _programs, parse_python_state_target, python_state_expected_stdout,
)
from app.services.learning.item_supply.finite_targets.sqlite_predicates import (
    ConjunctionTargetV1, KeysetAfterTargetV1, OverrideFallbackTargetV1,
    SqlitePredicateTargetV1, parse_sqlite_target, sqlite_fixture_hash,
    sqlite_oracle, sqlite_private_fixture, sqlite_public_task, sqlite_tables,
)
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.python_state_scorer import (
    PYTHON_STATE_SCORER_VERSION, compile_python_state_test_bundle,
)
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _wire(runtime: str, submission: str, cases: tuple[dict[str, Any], ...], *, public_hash: str,
          fixture_hash: str) -> SandboxInputV1:
    # Reference-declaration binding only; NOT a generated LearningItemSource hash.
    request = SandboxInputV1(runtime_id=runtime, action=ExecutionAction.TEST, submission=submission,
        hidden_test_bundle_json=_json(cases), test_reference_hash=canonical_hash(cases),
        source_reference_hash=canonical_hash({"registered_reference_fixture": fixture_hash, "public_task": public_hash}))
    if len(request.wire_bytes()) > 98_304:
        raise ValueError("finite_transfer_wire_bound")
    return request


# Explicit directional alignments, not a search for any conveniently wrong rename.
# Output/state roles remain named; constants come only from target public values.
# Source statement order, operators, dependency edges and print arity stay intact.
_PY_ALIGN: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {
    ("accumulate", "refresh"): (("subtotal", "price", "qty"), ("initial_qty", "price", "updated_qty")),
    ("accumulate", "swap"): (("left", "right", "saved"), ("left", "right", "left")),
    ("accumulate", "transfer"): (("source", "target", "amount"), ("source", "target", "amount")),
    ("refresh", "accumulate"): (("increase", "decrease", "total"), ("increase", "decrease", "initial")),
    ("refresh", "swap"): (("left", "right", "saved"), ("left", "right", "left")),
    ("refresh", "transfer"): (("source", "amount", "target"), ("source", "amount", "target")),
    ("swap", "accumulate"): (("total", "increase", "decrease"), ("initial", "increase")),
    ("swap", "refresh"): (("subtotal", "qty", "price"), ("price", "initial_qty")),
    ("swap", "transfer"): (("source", "target", "amount"), ("source", "target")),
    ("transfer", "accumulate"): (("total", "increase", "decrease"), ("initial", "increase", "decrease")),
    ("transfer", "refresh"): (("qty", "subtotal", "price"), ("initial_qty", "price", "price")),
    ("transfer", "swap"): (("left", "right", "saved"), ("left", "right", "left")),
}
_PY_ROLES = {"accumulate": ("total", "increase", "decrease"), "refresh": ("price", "qty", "subtotal"),
             "swap": ("left", "right", "saved"), "transfer": ("source", "target", "amount")}
_PY_VALUES = {"accumulate": ("initial", "increase", "decrease"), "refresh": ("price", "initial_qty", "updated_qty"),
              "swap": ("left", "right"), "transfer": ("source", "target", "amount")}
_PY_OBSERVED = {"accumulate": ("total",), "refresh": ("subtotal",), "swap": ("left", "right"), "transfer": ("source", "target")}


class _EraseSymbols(ast.NodeTransformer):
    def visit_Name(self, node: ast.Name) -> ast.Name:
        return ast.Name(id="print" if node.id == "print" else "role", ctx=node.ctx)

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.Constant(value=0)


def _python_structure(program: str) -> str:
    return canonical_hash(ast.dump(_EraseSymbols().visit(ast.parse(program)), include_attributes=False))


def _python_legal(program: str, target: PythonStateTarget) -> None:
    """Check defined names and the existing bounded syntax, never run the code."""
    tree = ast.parse(program)
    declared, defined = set(target.variables.values()), set()
    if not 1 <= len(tree.body) <= 12:
        raise ValueError("finite_transfer_python_statement_bound")
    for index, statement in enumerate(tree.body):
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
            expression, output = statement.value, statement.targets[0].id
            if output not in declared:
                raise ValueError("finite_transfer_python_unknown_target")
        elif (index == len(tree.body) - 1 and isinstance(statement, ast.Expr)
              and isinstance(statement.value, ast.Call) and isinstance(statement.value.func, ast.Name)
              and statement.value.func.id == "print" and not statement.value.keywords
              and 1 <= len(statement.value.args) <= 3):
            expression, output = ast.Tuple(elts=statement.value.args, ctx=ast.Load()), None
        else:
            raise ValueError("finite_transfer_python_unsupported_syntax")
        for node in ast.walk(expression):
            if isinstance(node, ast.Name) and (node.id not in declared or node.id not in defined):
                raise ValueError("finite_transfer_python_unbound_name")
            if type(node) not in {ast.Tuple, ast.Load, ast.Name, ast.Constant, ast.BinOp, ast.Add, ast.Sub, ast.Mult}:
                raise ValueError("finite_transfer_python_unsupported_expression")
            if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 1000):
                raise ValueError("finite_transfer_python_literal_bound")
        if output is not None:
            defined.add(output)


def _python_final(target: PythonStateTarget) -> dict[str, int]:
    """Four closed arithmetic derivations, independent of submitted Python."""
    v = target.values
    if target.task_kind == "accumulate":
        return {"total": v["initial"] + v["increase"] - v["decrease"], "increase": v["increase"], "decrease": v["decrease"]}
    if target.task_kind == "refresh":
        return {"price": v["price"], "qty": v["updated_qty"], "subtotal": v["price"] * v["updated_qty"]}
    if target.task_kind == "swap":
        return {"left": v["right"], "right": v["left"], "saved": v["left"]}
    return {"source": v["source"] - v["amount"], "target": v["target"] + v["amount"], "amount": v["amount"]}


def _python_check(spec: FiniteCandidateSpecV1, *, lock: str, submission: str | None = None,
                  prediction: str | None = None) -> FiniteTransferCheckV1:
    goal = spec.python_goal
    if goal is None:
        raise ValueError("finite_transfer_python_goal_required")
    reference = _programs(goal)[2]
    public = spec.public_template.model_dump(mode="json")
    program = reference if submission is None else submission
    tests = ({"id": "family-python", "case_type": "hidden", "input_json": {"goal_contract": goal.model_dump(mode="json")},
              "expected_output_json": {"stdout": python_state_expected_stdout(goal)}},)
    cases = compile_python_state_test_bundle(tests)
    public_hash = spec.public_template.public_hash
    fixture_hash = canonical_hash({"specification": spec.specification_hash, "reference": reference, "tests": tests})
    adapted = submission is not None
    return FiniteTransferCheckV1(kind="python", purpose="transfer_semantic_mismatch" if adapted else "reference_success",
        family_id=spec.allocation.family_id, specification_hash=spec.specification_hash, blueprint_version=spec.blueprint.version,
        public_task_json=_json(public), public_task_hash=public_hash, fixture_hash=fixture_hash, submission=program,
        request=_wire("python-stdout-v1", program, cases, public_hash=public_hash, fixture_hash=fixture_hash),
        runtime_lock_hash=lock, scorer_version=PYTHON_STATE_SCORER_VERSION,
        expected_json=_json({"selected_tests": tests, "predicted_terminal_cases": [{"id": "family-python",
            "stdout": prediction if adapted else python_state_expected_stdout(goal),
            "goal_status": "unsatisfied" if adapted else "satisfied", "goal_satisfied": not adapted}],
            "required_scorer_result": "reject" if adapted else "pass"}),
        required_terminal="successful_supported_semantics")


def _python_direction(left: FiniteTaskFamilyV1, right: FiniteTaskFamilyV1, lock: str,
                      specs: dict[str, FiniteCandidateSpecV1]) -> dict[str, Any]:
    source, target = specs[left.family_id], specs[right.family_id]
    source_goal, target_goal = source.python_goal, target.python_goal
    if source_goal is None or target_goal is None:
        raise ValueError("finite_transfer_python_goal_required")
    reference = _programs(source_goal)[2]
    target_roles, target_value_keys = _PY_ALIGN[(left.task_kind, right.task_kind)]
    source_roles, source_value_keys = _PY_ROLES[left.task_kind], _PY_VALUES[left.task_kind]
    symbols = tuple((source_goal.variables[s], target_goal.variables[t]) for s, t in zip(source_roles, target_roles, strict=True))
    if len({b for _, b in symbols}) != len(symbols):
        raise ValueError("finite_transfer_cannot_collapse_python_roles")
    constants = tuple((s, t, source_goal.values[s], target_goal.values[t]) for s, t in zip(source_value_keys, target_value_keys, strict=True))
    name_map, tokens, index = dict(symbols), [], 0
    # Parameter OCCURRENCES, not numeric equality: equal source literals may
    # represent different roles and must not silently acquire each other's value.
    for token in tokenize.generate_tokens(StringIO(reference).readline):
        if token.type == tokenize.NAME and token.string in name_map:
            token = token._replace(string=name_map[token.string])
        elif token.type == tokenize.NUMBER:
            if index >= len(constants) or int(token.string) != constants[index][2]:
                raise ValueError("finite_transfer_literal_occurrence_changed")
            token = token._replace(string=str(constants[index][3]))
            index += 1
        tokens.append(token)
    if index != len(constants):
        raise ValueError("finite_transfer_literal_occurrence_missing")
    adapted = tokenize.untokenize(tokens)
    structure = _python_structure(reference)
    if _python_structure(adapted) != structure:
        raise ValueError("finite_transfer_changed_reasoning_steps")
    _python_legal(adapted, target_goal)
    common = dict(source_reference=_python_check(source, lock=lock), target_reference=_python_check(target, lock=lock),
        alignment=FiniteTransferAlignmentV1(rule="injective_names_and_declared_literals", symbol_pairs=symbols,
            constant_pairs=constants, unchanged_structure_hash=structure), adapted_submission=adapted)
    try:
        aligned_source = parse_python_state_target({**source_goal.model_dump(mode="json"), "values": {s: n for s, _, _, n in constants}})
    except ValueError:
        return dict(**common, construction="unresolved", transfer_check=None,
                    reasons=("aligned_source_parameters_outside_finite_domain",))
    predicted = {name_map[source_goal.variables[r]]: value for r, value in _python_final(aligned_source).items()}
    expected = {target_goal.variables[r]: _python_final(target_goal)[r] for r in _PY_OBSERVED[right.task_kind]}
    if not set(expected) <= set(predicted):
        raise ValueError("finite_transfer_missing_observable_state")
    differences = {name: {"predicted": predicted[name], "target_expected": expected[name]}
                   for name in expected if predicted[name] != expected[name]}
    if not differences:
        return dict(**common, construction="unresolved", transfer_check=None,
                    reasons=("no_numeric_target_state_counterexample_not_a_print_arity_test",))
    return dict(**common, construction="planned", transfer_check=_python_check(target, lock=lock, submission=adapted,
                    prediction=python_state_expected_stdout(aligned_source)),
        semantic_difference_json=_json({"derivation": "closed_source_arithmetic_after_injective_alignment",
            "predicted_state": predicted, "target_observed_state": expected, "different_state_components": differences,
            "stdout_arity_or_ast_inequality_is_not_the_witness": True}),
        reasons=("successful_execution_and_supported_goal_rejection_still_required", "numeric_state_counterexample_predicted_not_executed"))


_FLAG_COLUMNS = {"active", "override_flag", "default_flag", "flag_a", "flag_b"}
# Missing entries require inventing/collapsing qualification roles; do not do so.
_SQL_ALIGN: dict[tuple[str, str], tuple[tuple[str, str], ...]] = {
    ("conjunction", "override_fallback"): (("active", "override_flag"), ("score", "priority")),
    ("conjunction", "exclusive"): (("active", "flag_a"), ("score", "score")),
    ("override_fallback", "exclusive"): (("override_flag", "flag_a"), ("default_flag", "flag_b"), ("priority", "score")),
    ("exclusive", "override_fallback"): (("flag_a", "override_flag"), ("flag_b", "default_flag"), ("score", "priority")),
    ("keyset_after", "conjunction"): (("score", "score"),),
    ("keyset_after", "override_fallback"): (("score", "priority"),),
    ("keyset_after", "exclusive"): (("score", "score"),),
}


def _sql_comparison_data(target: SqlitePredicateTargetV1, *, score_center: int) -> LearningItemSqlDatasetV2:
    # Keep all finite truth-combination rows, NULLs, duplicates, and complete IDs.
    # Comparable numeric ranks near 70 prevent a conjunction's threshold 60
    # from "distinguishing" families merely because every rank was below 60.
    original = sqlite_private_fixture(target).private_cases[0].dataset
    if isinstance(target, ConjunctionTargetV1):
        return original
    columns = tuple(c.name for c in sqlite_tables(target)[0].columns)
    metric = columns.index("priority" if isinstance(target, OverrideFallbackTargetV1) else "score")
    rows = tuple(tuple(score_center + cell % 3 - 1 if index == metric and type(cell) is int else cell
                       for index, cell in enumerate(row)) for row in original.tables[0].rows)
    return LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(table="entries", rows=rows),))


def _sql_check(spec: FiniteCandidateSpecV1, lock: str, *, submission: str | None = None,
               datasets: tuple[LearningItemSqlDatasetV2, ...] | None = None,
               predictions: tuple[SafeTableResultPresentationV1, ...] | None = None) -> FiniteTransferCheckV1:
    target = spec.sql_target
    if target is None:
        raise ValueError("finite_transfer_sql_target_required")
    fixture, public = sqlite_private_fixture(target), sqlite_public_task(target)
    data = tuple(c.dataset for c in fixture.private_cases) if datasets is None else datasets
    cases = tuple({"id": "family-sql-" + str(i), "case_type": "hidden", "tables": [t.model_dump(mode="json") for t in public.content.tables],
                   "dataset": dataset.model_dump(mode="json"), "max_rows": public.content.max_rows} for i, dataset in enumerate(data))
    truth = tuple(sqlite_oracle(target, dataset) for dataset in data)
    results = truth if predictions is None else predictions
    if len(results) != len(cases):
        raise ValueError("finite_transfer_sql_predictions_mismatch")
    program = fixture.equivalent_queries[0] if submission is None else submission
    public_json = spec.public_template.model_dump(mode="json")
    public_hash = spec.public_template.public_hash
    fh = canonical_hash({"specification": spec.specification_hash, "registered_fixture": sqlite_fixture_hash(fixture), "cases": cases})
    return FiniteTransferCheckV1(kind="sqlite", purpose="reference_success" if submission is None else "transfer_semantic_mismatch",
        family_id=fixture.family_id, specification_hash=spec.specification_hash, blueprint_version=spec.blueprint.version,
        public_task_json=_json(public_json), public_task_hash=public_hash,
        fixture_hash=fh, submission=program,
        request=_wire("sqlite-query-v1", program, cases, public_hash=public_hash, fixture_hash=fh),
        runtime_lock_hash=lock, scorer_version=GATE_PASS_POLICY_VERSION, required_terminal="successful_supported_semantics",
        expected_json=_json({"selected_tests": [{"id": case["id"], "expected_output": value.model_dump(mode="json"), "comparison": "ordered"}
                for case, value in zip(cases, truth, strict=True)],
            "predicted_terminal_cases": [{"id": case["id"], "expected_output": value.model_dump(mode="json")}
                for case, value in zip(cases, results, strict=True)],
            "required_scorer_result": "pass" if submission is None else "reject"}))


def _sql_direction(left: FiniteTaskFamilyV1, right: FiniteTaskFamilyV1, lock: str,
                   specs: dict[str, FiniteCandidateSpecV1]) -> dict[str, Any]:
    source_spec, target_spec = specs[left.family_id], specs[right.family_id]
    source, target = source_spec.sql_target, target_spec.sql_target
    if source is None or target is None:
        raise ValueError("finite_transfer_sql_target_required")
    source_reference, target_reference = _sql_check(source_spec, lock), _sql_check(target_spec, lock)
    pairs = _SQL_ALIGN.get((left.task_kind, right.task_kind))
    if pairs is None:
        return dict(source_reference=source_reference, target_reference=target_reference,
            alignment=FiniteTransferAlignmentV1(rule="injective_typed_column_roles", symbol_pairs=(), constant_pairs=(), unchanged_structure_hash=None),
            adapted_submission=None, transfer_check=None, construction="unresolved",
            reasons=("target_lacks_injective_qualification_column_roles", "no_missing_column_or_aliased_flag_counterexample"))
    mapping = {"entries": "entries", "id": "id", "name": "name", **dict(pairs)}
    source_columns = sqlite_tables(source)[0].columns
    target_columns = {c.name: c for c in sqlite_tables(target)[0].columns}
    if (len(set(mapping.values())) != len(mapping)
            or any(mapping[c.name] not in target_columns or c.data_type != target_columns[mapping[c.name]].data_type
                   or (c.name in _FLAG_COLUMNS) != (mapping[c.name] in _FLAG_COLUMNS) for c in source_columns)):
        raise ValueError("finite_transfer_sql_role_alignment_invalid")
    constants: tuple[tuple[str, str, int, int], ...] = ()
    aligned_source = source
    if isinstance(source, KeysetAfterTargetV1) and isinstance(target, ConjunctionTargetV1):
        constants = (("cut_score", "min_score", source.cut_score, target.min_score),)
        aligned_source = parse_sqlite_target({**source.model_dump(mode="python"), "cut_score": target.min_score})
    # The only substitutions are whole identifiers and one declared score bound.
    numbers = {str(old): str(new) for _, _, old, new in constants}
    program = source_reference.submission
    adapted = re.sub(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", lambda m: mapping.get(m[0], numbers.get(m[0], m[0])), program)
    structure = re.sub(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", lambda m: "ROLE" if m[0] in mapping else "N" if m[0].isdigit() else m[0], program)
    inverse_names = set(mapping.values())
    aligned_structure = re.sub(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+", lambda m: "ROLE" if m[0] in inverse_names else "N" if m[0].isdigit() else m[0], adapted)
    if structure != aligned_structure:
        raise ValueError("finite_transfer_sql_structure_changed")
    center = max(70, source.min_score + 10) if isinstance(source, ConjunctionTargetV1) else source.cut_score if isinstance(source, KeysetAfterTargetV1) else 70
    data = _sql_comparison_data(target, score_center=center)
    target_names = tuple(c.name for c in sqlite_tables(target)[0].columns)
    aligned_rows = []
    for row in data.tables[0].rows:
        record = dict(zip(target_names, row, strict=True))
        aligned_rows.append(tuple(record[mapping[c.name]] for c in source_columns))
    # Relational source semantics over a role-renamed view of the SAME target
    # rows. Oracle validation enforces flag domains; no SQL/reference execution.
    source_data = LearningItemSqlDatasetV2(tables=(LearningItemSqlDatasetTableV2(table="entries", rows=tuple(aligned_rows)),))
    predicted, truth = sqlite_oracle(aligned_source, source_data), sqlite_oracle(target, data)
    alignment = FiniteTransferAlignmentV1(rule="injective_typed_column_roles", symbol_pairs=tuple(mapping.items()),
                                          constant_pairs=constants, unchanged_structure_hash=canonical_hash(structure))
    target_reference = _sql_check(target_spec, lock, datasets=(data,))
    common = dict(source_reference=source_reference, target_reference=target_reference, alignment=alignment, adapted_submission=adapted)
    if predicted == truth:
        return dict(**common, construction="unresolved", transfer_check=None,
                    reasons=("aligned_relational_semantics_have_no_counterexample_on_declared_case",))
    return dict(**common, construction="planned", transfer_check=_sql_check(target_spec, lock, submission=adapted,
                datasets=(data,), predictions=(predicted,)),
        semantic_difference_json=_json({"derivation": "source_relational_oracle_on_injective_target_row_view",
            "target_dataset": data.model_dump(mode="json"), "predicted": predicted.model_dump(mode="json"),
            "target_expected": truth.model_dump(mode="json"), "comparison": "ordered_multiset"}),
        reasons=("successful_read_only_select_and_real_ordered_scorer_rejection_required", "column_role_alignment_not_a_missing_column_error"))


def _kc_check(family: FiniteTaskFamilyV1, spec: FiniteCandidateSpecV1) -> FiniteTransferCheckV1:
    kind = cast(KcTaskKind, family.task_kind)
    fixture = python_kc_fixture(kind)
    truth = _truth(kind, False)
    facts_by_label = {public.label: fact for public, fact in zip(fixture.public_content.options, fixture.option_facts, strict=True)}
    content = spec.public_template.content
    if not isinstance(content, LearningItemKnowledgeCheckContentV1) or set(facts_by_label) != {o.label for o in content.options}:
        raise ValueError("finite_transfer_kc_option_propositions_changed")
    # Full propositions follow the EXACT public permutation, never old fixture IDs.
    options = tuple({"label": option.label, "rhs": facts_by_label[option.label].rhs,
                     "saved": facts_by_label[option.label].saved, "observation": facts_by_label[option.label].observation,
                     "reason": facts_by_label[option.label].reason} for option in content.options)
    selected = tuple(option for option in options if (option["rhs"], option["saved"], option["observation"], option["reason"]) == truth)
    if len(selected) != 1:
        raise ValueError("finite_transfer_kc_complete_proposition_not_unique")
    public = spec.public_template.model_dump(mode="json")
    proposition = {key: selected[0][key] for key in ("rhs", "saved", "observation", "reason")}
    return FiniteTransferCheckV1(kind="static_proposition", purpose="reference_success", family_id=family.family_id,
        specification_hash=spec.specification_hash, blueprint_version=spec.blueprint.version,
        public_task_json=_json(public), public_task_hash=spec.public_template.public_hash,
        fixture_hash=canonical_hash({"specification": spec.specification_hash, "registered_fixture": fixture.fixture_hash}),
        submission=_json(proposition), request=None, runtime_lock_hash=None, scorer_version=PYTHON_KC_SCORER_VERSION,
        expected_json=_json({"complete_options": options, "unique_proposition": proposition,
                            "selected_label": selected[0]["label"], "required_static_result": "unique_complete_proposition"}),
        required_terminal="not_run_static")


def _kc_direction(left: FiniteTaskFamilyV1, right: FiniteTaskFamilyV1,
                  specs: dict[str, FiniteCandidateSpecV1]) -> dict[str, Any]:
    source, target = _kc_check(left, specs[left.family_id]), _kc_check(right, specs[right.family_id])
    source_p, target_p = json.loads(source.submission), json.loads(target.submission)
    source_shape = tuple(len(source_p[key]) for key in ("rhs", "saved", "observation"))
    target_shape = tuple(len(target_p[key]) for key in ("rhs", "saved", "observation"))
    # Padding/truncating, fabricating a causal step, or selecting an arbitrary
    # distractor is NOT alignment. A non-option cannot be a legal static negative.
    reason = ("complete_causal_proposition_alignment_not_registered" if source_shape == target_shape
              else "complete_response_dimensions_require_added_or_removed_reasoning_steps")
    return dict(source_reference=source, target_reference=target,
        alignment=FiniteTransferAlignmentV1(rule="complete_option_propositions", symbol_pairs=(), constant_pairs=(),
            unchanged_structure_hash=canonical_hash({"source_dimensions": source_shape, "target_dimensions": target_shape})),
        adapted_submission=None, transfer_check=None, construction="unresolved",
        reasons=(reason, "not_an_option_id_or_text_hash_counterexample"))


def build_finite_family_transfer_plan(target_id: TargetId, *, specs: tuple[FiniteCandidateSpecV1, ...],
                                     materials: tuple[PublicMaterialV2, ...]) -> FiniteFamilyTransferPlanV1:
    """6 pairs / 12 direction slots bound to FOUR exact unguided public specs.

    These inputs are task declarations, not generated item/source/C authority.
    Blueprint version and full public hash are bound, never V1/V2 interchange.
    Nothing is executed and no field grants family independence or publication.
    """
    target = get_finite_course_target(target_id)
    static = target.target_id == "python-kc-binding-v1"
    if len(specs) != 4:
        raise ValueError("finite_transfer_requires_four_exact_public_specs")
    checked = tuple(checked_model(s, FiniteCandidateSpecV1) for s in specs)
    materials = tuple(checked_model(m, PublicMaterialV2) for m in materials)
    families = families_for_course(target_id)
    by_family = {s.allocation.family_id: s for s in checked}
    if (set(by_family) != {f.family_id for f in families} or len(by_family) != 4
            or any(s.target_id != target_id or s.allocation.guidance != "unguided" for s in checked)
            or len({s.blueprint.version for s in checked}) != 1):
        raise ValueError("finite_transfer_family_or_public_spec_version_mismatch")
    scorer = {"python-state-update-v1": PYTHON_STATE_SCORER_VERSION,
              "sqlite-predicate-order-v1": GATE_PASS_POLICY_VERSION,
              "python-kc-binding-v1": PYTHON_KC_SCORER_VERSION}[target_id]
    for spec in checked:
        scope = spec.coverage_blueprint.scope
        expected = build_finite_candidate_spec(target_id=target_id, variant_id=spec.allocation.variant_id,
            seed=spec.seed, item_key=spec.public_template.item_key, version=spec.public_template.version, materials=materials,
            runtime_profile_hash=None if static else scope.runtime_profile_hash, scorer_version=scope.scorer_version,
            assistance_policy_hash=scope.assistance_policy_hash, policy_version=spec.coverage_blueprint.policy_version,
            difficulty_profile=spec.blueprint.difficulty_profile, publication_policy=spec.blueprint.publication_policy,
            public_spec_version=spec.blueprint.version)
        if spec != expected or scope.scorer_version != scorer:
            raise ValueError("finite_transfer_exact_specification_mismatch")
    runtime_hashes = {s.coverage_blueprint.scope.runtime_profile_hash for s in checked}
    if len(runtime_hashes) != 1 or "0" * 64 in runtime_hashes:
        raise ValueError("finite_transfer_runtime_pin_mismatch")
    lock = None if static else next(iter(runtime_hashes))
    pairs = []
    for left, right in combinations(families, 2):
        directions = []
        for source, destination in ((left, right), (right, left)):
            if target_id == "python-state-update-v1":
                payload = _python_direction(source, destination, cast(str, lock), by_family)
            elif target_id == "sqlite-predicate-order-v1":
                payload = _sql_direction(source, destination, cast(str, lock), by_family)
            else:
                payload = _kc_direction(source, destination, by_family)
            directions.append(FiniteFamilyTransferDirectionV1(
                source_family_id=source.family_id, target_family_id=destination.family_id,
                source_definition_hash=source.definition_hash, target_definition_hash=destination.definition_hash,
                source_structure_signature=source.structure_signature, target_structure_signature=destination.structure_signature,
                **payload))
        status: Literal["conflict", "unresolved", "execution_and_review_pending"] = ("conflict" if any(d.construction == "conflict" for d in directions)
                  else "unresolved" if any(d.construction == "unresolved" for d in directions)
                  else "execution_and_review_pending")
        pairs.append(FiniteFamilyPairPlanV1(left_family_id=left.family_id, right_family_id=right.family_id,
                     directions=(directions[0], directions[1]), construction=status))
    return FiniteFamilyTransferPlanV1(target_id=target.target_id, target_definition_hash=target.definition_hash,
        runtime_lock_hash=lock, specifications=tuple(by_family[f.family_id] for f in families),
        material_digests=tuple(material_digest(m) for m in materials), pairs=tuple(pairs))


@dataclass(frozen=True)
class FiniteFamilyTransferWork:
    """Private deterministic scheduling projection; not a reservation or execution."""
    checks: tuple[FiniteTransferCheckV1, ...]
    resources: ResourceAmounts
    plan_inputs_hash: str


def finite_family_transfer_work(plan: FiniteFamilyTransferPlanV1, *,
                                materials: tuple[PublicMaterialV2, ...]) -> FiniteFamilyTransferWork:
    """Reconstruct exact plan, deduplicate identical checks BEFORE funding/IO.

    Unresolved directions have no negative request. Each check with a request
    needs its ORIGINAL successful sealed terminal and exact scorer expectation;
    an unsupported/failed terminal is pending, never a mismatch witness.
    """
    plan = checked_model(plan, FiniteFamilyTransferPlanV1)
    if plan != build_finite_family_transfer_plan(plan.target_id, specs=plan.specifications, materials=materials):
        raise ValueError("finite_transfer_plan_changed")
    checks: dict[str, FiniteTransferCheckV1] = {}
    for pair in plan.pairs:
        for direction in pair.directions:
            for check in (direction.source_reference, direction.target_reference, direction.transfer_check):
                if check is not None:
                    checks.setdefault(check.check_hash, check)
    return FiniteFamilyTransferWork(tuple(checks.values()),
        ResourceAmounts(execution_seconds=10 * sum(c.request is not None for c in checks.values())), plan.inputs_hash)
