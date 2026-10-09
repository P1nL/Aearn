"""Native finite candidate preparation; not shared facts, admission or publication.

Strictly joins actual proposed content to the server-owned public specification.
No network/DB/host execution and no private expected truth in public requests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, cast

from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import (
    LearningItemKnowledgeCheckContentV1, LearningItemKnowledgeCheckPrivateV1,
    LearningItemSourceV1, canonical_hash,
)
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_candidate_factory import FiniteCandidateSpecV1, build_finite_candidate_spec
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.finite_targets.python_kc import KcTaskKind, PYTHON_KC_SCORER_VERSION, _spec, _truth
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.generation_contracts import PublicMaterialV2
from app.services.learning.item_supply.sandbox.execution_contracts import CandidateProbePlanV1
from app.services.learning.item_supply.sandbox.finite_probe_plans import build_finite_candidate_probe_plan, check_finite_source_spec
from app.services.learning.item_supply.sandbox.python_state_scorer import PYTHON_STATE_SCORER_VERSION
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.item_supply.validation_adapter import CandidateValidationV2, validate_candidate
from app.services.learning.practice.contracts import ExerciseAttemptOutcome
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION, evaluate_static_reasoning


class FiniteStaticOptionFactV1(StorageContract):
    option_id: str
    accepted: bool
    scorer_outcome: Literal["passed", "failed"]


class FiniteKcValidationFactsV1(StorageContract):
    """Private deterministic option checks; no learner or OS terminal identity."""
    schema_version: Literal["finite_kc_validation_facts_v1"] = "finite_kc_validation_facts_v1"
    source_hash: Digest
    content_hash: Digest
    public_task_hash: Digest
    target_definition_hash: Digest
    instance_hash: Digest
    scorer_version: str = Field(pattern=r"^kc-binding-v1\.[0-9a-f]{64}$")
    correct_option_id: str = Field(repr=False)
    options: tuple[FiniteStaticOptionFactV1, ...] = Field(min_length=4, max_length=4, repr=False)
    validation: CandidateValidationV2
    execution_status: Literal["not_run_static"] = "not_run_static"
    admission_eligible: Literal[False] = False


class FiniteCandidateValidationInputsV1(StorageContract):
    schema_version: Literal["finite_candidate_validation_inputs_v1"] = "finite_candidate_validation_inputs_v1"
    target_id: TargetId
    source_hash: Digest
    content_hash: Digest
    specification_hash: Digest
    public_task_hash: Digest
    target_definition_hash: Digest
    instance_hash: Digest
    probe_plan: CandidateProbePlanV1 | None = Field(default=None, repr=False)
    static_facts: FiniteKcValidationFactsV1 | None = Field(default=None, repr=False)
    pending_boundaries: tuple[str, ...]
    publication_enabled: Literal[False] = False
    family_independence_status: Literal["pending"] = "pending"

    @model_validator(mode="after")
    def bound_shape(self) -> FiniteCandidateValidationInputsV1:
        if self.target_id == "python-kc-binding-v1":
            facts = self.static_facts
            if (self.probe_plan is not None or facts is None
                    or (facts.source_hash, facts.content_hash, facts.public_task_hash,
                        facts.target_definition_hash, facts.instance_hash)
                    != (self.source_hash, self.content_hash, self.public_task_hash,
                        self.target_definition_hash, self.instance_hash)):
                raise ValueError("finite_static_inputs_binding_mismatch")
        elif self.static_facts is not None or self.probe_plan is None or self.probe_plan.source_hash != self.source_hash:
            raise ValueError("finite_execution_inputs_binding_mismatch")
        return self

    @property
    def inputs_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteCandidateValidationInputsV1).model_dump(mode="json"))


def _checked_spec(spec: FiniteCandidateSpecV1, materials: tuple[PublicMaterialV2, ...]) -> FiniteCandidateSpecV1:
    spec = checked_model(spec, FiniteCandidateSpecV1)
    scope = spec.coverage_blueprint.scope
    expected = build_finite_candidate_spec(target_id=spec.target_id, variant_id=spec.allocation.variant_id,
        seed=spec.seed, item_key=spec.public_template.item_key, version=spec.public_template.version,
        materials=materials, runtime_profile_hash=None if spec.blueprint.runtime_profile_id is None else scope.runtime_profile_hash,
        scorer_version=scope.scorer_version, assistance_policy_hash=scope.assistance_policy_hash,
        policy_version=spec.coverage_blueprint.policy_version, difficulty_profile=spec.blueprint.difficulty_profile,
        publication_policy=spec.blueprint.publication_policy, public_spec_version=spec.blueprint.version,
        allocation=spec.allocation)
    if spec != expected:
        raise ValueError("finite_registered_specification_mismatch")
    scorer = {"python-state-update-v1": PYTHON_STATE_SCORER_VERSION,
              "sqlite-predicate-order-v1": GATE_PASS_POLICY_VERSION,
              "python-kc-binding-v1": PYTHON_KC_SCORER_VERSION}[spec.target_id]
    if scope.scorer_version != scorer:
        raise ValueError("finite_registered_scorer_mismatch")
    return spec


def _static_kc_facts(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1,
                     public_hash: str, instance_hash: str) -> FiniteKcValidationFactsV1:
    public, private = source.public.content, source.private.content
    if not isinstance(public, LearningItemKnowledgeCheckContentV1) or not isinstance(private, LearningItemKnowledgeCheckPrivateV1):
        raise ValueError("finite_kc_shape_invalid")
    family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
    kind = cast(KcTaskKind, family.task_kind)
    guided = spec.allocation.slot == "remediation"
    question, truth = _spec(kind, guided), _truth(kind, guided)
    expected_by_label = {o.label: (o.rhs, o.saved, o.observation, o.reason) == truth for o in question.options}
    if len(expected_by_label) != 4 or sum(expected_by_label.values()) != 1:
        raise ValueError("finite_kc_truth_not_unique")
    if {o.label for o in public.options} != set(expected_by_label) or len(public.options) != 4:
        raise ValueError("finite_kc_option_semantics_mismatch")
    expected = {o.option_id: expected_by_label[o.label] for o in public.options}
    answer = next(option for option, accepted in expected.items() if accepted)
    if (private.accepted_answers != (answer,) or private.score_policy.kind != "static_exact"
            or private.score_policy.policy_version != "static_exact_v1" or private.score_policy.threshold != 1.0):
        raise ValueError("finite_kc_answer_mismatch")
    if len(private.tests) != 4:
        raise ValueError("finite_kc_all_options_must_be_checked")
    seen = set()
    for test in private.tests:
        option = test.input_json.get("answer")
        if (type(option) is not str or option not in expected or option in seen
                or test.input_json != {"answer": option}
                or type(test.expected_output_json.get("accepted")) is not bool
                or test.expected_output_json != {"accepted": expected[option]}):
            raise ValueError("finite_kc_private_expectation_mismatch")
        seen.add(option)
    facts = []
    for option, accepted in expected.items():
        scored = evaluate_static_reasoning(answer=option, accepted_answers=private.accepted_answers,
            required_capabilities=source.blueprint.required_capabilities, threshold=1.0,
            now=datetime.now(timezone.utc))
        if (scored.outcome is ExerciseAttemptOutcome.PASSED) != accepted:
            raise ValueError("finite_kc_static_scorer_mismatch")
        facts.append(FiniteStaticOptionFactV1(option_id=option, accepted=accepted,
                                             scorer_outcome="passed" if accepted else "failed"))
    validation = validate_candidate(source)
    if validation.state != "machine_verified" or validation.mode != "static" or validation.execution_evidence is not None:
        raise ValueError("finite_kc_static_contract_denied")
    return FiniteKcValidationFactsV1(source_hash=source.source_hash, content_hash=source.content_hash,
        public_task_hash=public_hash, target_definition_hash=spec.target_definition_hash,
        instance_hash=instance_hash, scorer_version=PYTHON_KC_SCORER_VERSION,
        correct_option_id=answer, options=tuple(facts), validation=validation)


def prepare_finite_candidate_validation(
    source: LearningItemSourceV1, *, spec: FiniteCandidateSpecV1,
    materials: tuple[PublicMaterialV2, ...],
) -> FiniteCandidateValidationInputsV1:
    """Validate actual proposed expectations, then return private sealed-port inputs.

    Material shape is checked, not current C authorization: the later same-conn
    shared facts owner must independently recheck current source and runtime facts.
    """
    source = checked_model(source, LearningItemSourceV1)
    spec = _checked_spec(spec, materials)
    check_finite_source_spec(source, spec)
    public_hash = canonical_hash(source.public.model_dump(mode="json"))
    instance = (spec.python_goal.model_dump(mode="json") if spec.python_goal is not None
                else spec.sql_target.model_dump(mode="json") if spec.sql_target is not None
                else {"public": spec.public_template.content.model_dump(mode="json"),
                      "variant_id": spec.allocation.variant_id, "seed": spec.seed})
    instance_hash = canonical_hash(instance)
    plan, static = None, None
    pending: tuple[str, ...]
    if spec.target_id == "python-kc-binding-v1":
        static = _static_kc_facts(source, spec, public_hash, instance_hash)
        pending = ("shared_facts_and_blind_review_pending",)
    else:
        plan = build_finite_candidate_probe_plan(source, spec=spec)
        pending = (("independent_candidate_boundary_pending",)
                   if plan.boundary_cases_json is None else ())
        pending += ("real_sealed_candidate_execution_pending", "shared_facts_and_ambiguity_pending")
    return FiniteCandidateValidationInputsV1(target_id=spec.target_id, source_hash=source.source_hash,
        content_hash=source.content_hash, specification_hash=spec.specification_hash,
        public_task_hash=public_hash, target_definition_hash=spec.target_definition_hash,
        instance_hash=instance_hash, probe_plan=plan, static_facts=static, pending_boundaries=pending)
