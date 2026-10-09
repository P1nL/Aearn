"""Scoped native review declarations. No runner capability or admission authority.

Native review inputs require their exact typed public spec/materials. Context is
local to the caller's block, never a global registration or hydrated proof seal.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator

from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.finite_candidate_factory import FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import (
    FiniteCandidateValidationInputsV1, prepare_finite_candidate_validation,
)
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.finite_targets.python_state import PYTHON_STATE_GRAMMAR_SHA256
from app.services.learning.item_supply.sandbox.finite_probe_plans import native_python_tests
from app.services.learning.item_supply.sandbox.python_state_scorer import compile_python_state_test_bundle
from app.services.learning.item_supply.storage_contracts import checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2
from app.services.learning.item_supply.validators.profiles import required_probes

if TYPE_CHECKING:
    from app.services.learning.item_supply.review_contracts_v2 import CandidateBindingV2, ValidationReceiptV2


@dataclass(frozen=True)
class _Context:
    source_hash: str
    spec: FiniteCandidateSpecV1
    inputs: FiniteCandidateValidationInputsV1


_CONTEXT: ContextVar[_Context | None] = ContextVar("finite_review_context", default=None)
_NATIVE_PREFIXES = ("finite.python-state-update-v1.", "finite.sqlite-predicate-order-v1.", "finite.python-kc-binding-v1.")


@contextmanager
def finite_review_context(source: LearningItemSourceV1, *, spec: FiniteCandidateSpecV1,
                          materials: tuple[PublicMaterialV2, ...]) -> Iterator[None]:
    source, spec = checked_model(source, LearningItemSourceV1), checked_model(spec, FiniteCandidateSpecV1)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    token = _CONTEXT.set(_Context(source.source_hash, spec, inputs))
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _context(source: LearningItemSourceV1) -> _Context | None:
    if not source.blueprint.blueprint_key.startswith(_NATIVE_PREFIXES):
        return None
    context = _CONTEXT.get()
    if (context is None or context.source_hash != source.source_hash
            or context.spec.specification_hash != context.inputs.specification_hash):
        raise ValueError("finite_review_exact_context_required")
    return context


def review_required_probes(source: LearningItemSourceV1) -> tuple[str, ...]:
    context = _context(source)
    return required_probes(source, finite_spec=None if context is None else context.spec)


def _python_scoring_structure(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1) -> dict[str, object]:
    """Review-only projection of the real compiler, never a new scorer or proof."""
    goal = spec.python_goal
    if goal is None:
        raise ValueError("finite_review_python_goal_required")
    tests = native_python_tests(source)
    cases = compile_python_state_test_bundle(tests)
    structure: dict[str, object] = {
        "schema_version": "finite_python_state_review_structure_v1",
        "public_goal_contract": goal.model_dump(mode="json"),
        "goal_contract_hash": goal.target_hash,
        "grammar_sha256": PYTHON_STATE_GRAMMAR_SHA256,
        "compiled_test_bundle_hash": canonical_hash(tests),
        "compiled_runtime_cases_hash": canonical_hash(cases),
        "case_bindings": [{"id": case["id"], "case_type": case["case_type"],
                           "goal_contract_hash": goal.target_hash} for case in cases],
        "required_terminal_facts": {"status": "success", "code": "python_terminal",
            "goal_contract_id": goal.goal_contract_id, "goal_contract_hash": goal.target_hash,
            "goal_status": "satisfied", "goal_satisfied": True},
        "pass_rule": "After original runner seal/request verification, require the exact terminal facts above (strict boolean true) AND the existing stdout comparison, which strips trailing LF only. Missing, unsupported or infrastructure facts remain pending, not semantic rejection evidence.",
        "case_scope": "Every compiled case uses this same fixed public goal. Visible/hidden labels and duplicate expected outputs do not introduce unseen parameters or prove generalization, coverage or family independence.",
        "syntax_vs_goal": "The allowed AST grammar is only a parsing boundary. Acceptance additionally requires one of the closed, task-kind-specific normalized event sequences; syntactic membership or numeric equivalence alone is insufficient.",
        "completion_metadata_boundary": "code_blanks acceptable_patterns are concept/pattern metadata, not the state-goal predicate. A print regex already matched by starter code does not prove the updates. This descriptor neither repairs weak completion metadata nor establishes pedagogical adequacy.",
    }
    if goal.task_kind == "accumulate":
        structure["task_shape_limitation"] = (
            "The matcher requires exactly one scalar literal initialization per declared role (initialization order may vary), "
            "then exactly two sequential updates of total using increase followed by decrease, then output of total. "
            "Tuple initialization, extra/no-op assignments and substituting literal operands for the declared update roles "
            "do not match, even if permitted by a broader reading of the task prose. "
            "Assess any such public-instruction/scorer mismatch independently; this declaration does not resolve it."
        )
    return structure


def finite_scoring_descriptor(source: LearningItemSourceV1, validation: ValidationReceiptV2,
                              binding: CandidateBindingV2) -> dict[str, object] | None:
    context = _context(source)
    if context is None:
        return None
    if not isinstance(validation, CandidateValidationV2) or validation.state != "machine_verified":
        raise ValueError("finite_review_machine_validation_required")
    spec, inputs = context.spec, context.inputs
    scope = spec.coverage_blueprint.scope
    execution = validation.execution_evidence
    if spec.python_goal is not None:
        rule = ("The service compiles the exact public state goal into every probe/scorer test without changing the staged source. "
                "Author input_json={} does not select stdout-only scoring. Newline-normalized stdout AND successful sealed "
                "in-image state-goal facts must pass; hardcoded output is insufficient. Contradictory declarations fail.")
        limitation = "Only the registered bounded sequential assignment/arithmetic grammar and declared public variables; not arbitrary Python equivalence."
    elif spec.sql_target is not None:
        rule = ("The existing SQLite compiler executes the proposed query on each private typed dataset and the existing scorer "
                "compares exact columns, row multiplicity, NULL semantics and declared total ordering. Private expectations were "
                "independently compared with the finite declarative data oracle, not obtained by trusting the reference query.")
        limitation = "Only the declared single-table SQLite predicate/order family; no generic SQL equivalence or new dialect claim."
    else:
        rule = ("Static exact scoring follows independent finite option-semantic checks. All four current public option labels and "
                "their private expectations must agree with the unique finite result; an option ID alone proves no correctness. "
                "The blind response is scored separately against that verified current instance, without an OS run.")
        limitation = "Only this frozen single-choice public question/options; not arbitrary free-text or executed Python assessment."
    if execution is not None:
        if (validation.mode != "live" or execution.mode != "live" or execution.isolation != "approved_os_boundary"
                or execution.scorer_version != scope.scorer_version):
            raise ValueError("finite_review_execution_descriptor_mismatch")
    elif inputs.static_facts is None or validation != inputs.static_facts.validation:
        raise ValueError("finite_review_static_descriptor_mismatch")
    return {
        "schema_version": "finite_review_scoring_descriptor_v1",
        "authority": "program_owned_declaration_not_verdict_or_receipt_verifier",
        "target_id": spec.target_id, "target_definition_hash": spec.target_definition_hash,
        "family_id": spec.allocation.family_id, "family_definition_hash": spec.family_definition_hash,
        "allocation_intent": spec.allocation.model_dump(mode="json"),
        "specification_hash": spec.specification_hash, "instance_hash": inputs.instance_hash,
        "public_template_hash": source.public.public_hash if spec.blueprint.version == FLEXIBLE_FACTORY_VERSION else spec.public_template.public_hash,
        "source_hash": source.source_hash,
        **({"actual_public_task_hash": source.public.public_hash,
            "server_specification_template_hash": spec.public_template.public_hash,
            "presentation_review_boundary": "V3 title/prose is untrusted: independently check goal consistency, contradictions, ambiguity and answer leakage in all six roles; exact machine preparation is not admission."}
           if spec.blueprint.version == FLEXIBLE_FACTORY_VERSION else {}),
        "content_hash": source.content_hash, "binding_hash": canonical_hash(binding.model_dump(mode="json")),
        "validation_receipt_hash": validation.evidence_hash, "scorer_version": scope.scorer_version,
        "runtime_profile_id": scope.runtime_profile_id, "runtime_identity_hash": scope.runtime_profile_hash,
        "required_probe_names": [] if execution is None else list(review_required_probes(source)),
        "case_compilation_and_scoring_rule": rule, "finite_scope_limitations": limitation,
        **({"python_state_scoring": _python_scoring_structure(source, spec)} if spec.python_goal is not None else {}),
        "authority_boundary": "Committed validation is data, not a revived runner capability. This descriptor proves no current source/lease, blind result, review verdict, family independence, course coverage or publication. Independently report material defects.",
        "unresolved_boundaries": ["finite_ambiguity_verified_separately_by_original_owner", "course_family_coverage_pending", "shared_final_facts_pending"],
    }
