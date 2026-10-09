"""Closed static binding questions, not published/source-authorized inventory.

The option truth is computed from finite declared arithmetic/binding facts, not
by evaluating submitted programs or treating an option ID as semantic evidence.
Real source review, blind solving, family independence and publication are later
owners. Private facts and explanations never enter the public-content getter.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.services.learning.item_bank.contracts import (
    LearningItemKnowledgeCheckContentV1, LearningItemKnowledgeCheckPrivateV1,
    LearningItemOptionV1, LearningItemRuntimeTestCaseV1, LearningItemScorePolicyV1,
    canonical_hash,
)
from app.services.learning.item_bank.practice_adapter import ExerciseAuthorityMaterial
from app.services.learning.item_supply.finite_course_targets import get_finite_course_target
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.practice.contracts import (
    ExercisePrivateRubric, ExerciseSourceKind, ExerciseType, ExerciseValidationStatus, ExerciseVersion,
)

from ._python_kc_fixtures import COUNTEREXAMPLE, REPAIR, TRACE, QuestionSpec, diagnose_spec

PYTHON_KC_TARGET_ID: Literal["python-kc-binding-v1"] = "python-kc-binding-v1"
KcTaskKind = Literal["trace", "diagnose", "repair", "counterexample"]
_KINDS: tuple[KcTaskKind, ...] = ("trace", "diagnose", "repair", "counterexample")


class KcOptionFactsV1(StorageContract):
    option_id: Literal["a", "b", "c", "d"]
    rhs: tuple[int, ...] = Field(min_length=1, max_length=6)
    saved: tuple[int, ...] = Field(min_length=1, max_length=4)
    observation: tuple[int, ...] = Field(min_length=1, max_length=6)
    reason: str = Field(min_length=1, max_length=80)
    failure_reason: str = Field(max_length=400)
    clause_passes: tuple[bool, bool, bool]


class PythonKcFixtureV1(StorageContract):
    target_id: Literal["python-kc-binding-v1"] = PYTHON_KC_TARGET_ID
    task_kind: KcTaskKind
    guided: bool
    family_id: str = Field(min_length=1, max_length=160)
    target_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    assessment_definition_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["knowledge_check", "remediation"]
    title: str = Field(min_length=1, max_length=240)
    public_content: LearningItemKnowledgeCheckContentV1
    private_content: LearningItemKnowledgeCheckPrivateV1 = Field(repr=False)
    option_facts: tuple[KcOptionFactsV1, ...] = Field(min_length=4, max_length=4, repr=False)
    execution_status: Literal["not_run_static"] = "not_run_static"
    family_independence_status: Literal["pending"] = "pending"

    @property
    def fixture_hash(self) -> str:
        return canonical_hash(checked_model(self, PythonKcFixtureV1).model_dump(mode="json"))


class PythonKcStaticCheckV1(StorageContract):
    status: Literal["consistent_static_fixture"] = "consistent_static_fixture"
    correct_option_id: str
    clause_ids: tuple[Literal["KC-C1"], Literal["KC-C2"], Literal["KC-C3"]] = ("KC-C1", "KC-C2", "KC-C3")
    fixture_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission_eligible: Literal[False] = False
    execution_status: Literal["not_run_static"] = "not_run_static"


def _spec(kind: KcTaskKind, guided: bool) -> QuestionSpec:
    if type(kind) is not str or kind not in _KINDS or type(guided) is not bool:
        raise ValueError("python_kc_target_invalid")
    if guided and kind != "diagnose":
        raise ValueError("python_kc_guided_diagnose_only")
    return diagnose_spec(guided=guided) if kind == "diagnose" else {
        "trace": TRACE, "repair": REPAIR, "counterexample": COUNTEREXAMPLE,
    }[kind]


def _truth(kind: KcTaskKind, guided: bool) -> tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...], str]:
    """Independent finite data derivation; no Python source parser/interpreter."""
    if kind == "trace":
        original, replacement, increment, saved_replacement = 4, 9, 3, 6
        tail = original + increment
        return (original, tail), (original, tail), (replacement, saved_replacement, tail), "snapshot"
    if kind == "diagnose":
        price, quantity = (5, 4) if guided else (6, 3)
        total = price * quantity
        # Rebinding price does not recompute the already stored integer total.
        return (total, total + 1), (total,), (2, total, total + 1), "derived_snapshot"
    if kind == "repair":
        inputs = (3, 8)
        rhs = tuple(value for initial in inputs for value in (initial, initial + 2, (initial + 2) * 2))
        observations = tuple(value for initial in inputs for value in (initial, (initial + 2) * 2))
        return rhs, inputs, observations, "save_then_refresh"
    original, replacement = 4, 9
    return (original,), (original,), (replacement, original), "source_rebound_saved_preserved"


def _build(kind: KcTaskKind, *, guided: bool) -> PythonKcFixtureV1:
    spec = _spec(kind, guided)
    rhs, saved, observation, reason = _truth(kind, guided)
    facts = tuple(KcOptionFactsV1(
        option_id=option.option_id, rhs=option.rhs, saved=option.saved, observation=option.observation,
        reason=option.reason, failure_reason=option.failure_reason,
        clause_passes=(option.rhs == rhs, option.saved == saved,
                       option.observation == observation and option.reason == reason),
    ) for option in spec.options)
    accepted = tuple(f.option_id for f in facts if all(f.clause_passes))
    if len(accepted) != 1 or any(bool(f.failure_reason) == all(f.clause_passes) for f in facts):
        raise ValueError("python_kc_unique_answer_or_distractor_reason_invalid")
    public = LearningItemKnowledgeCheckContentV1(
        response_kind="single_choice", prompt_markdown=spec.prompt,
        options=tuple(LearningItemOptionV1(option_id=o.option_id, label=o.label) for o in spec.options),
    )
    private = LearningItemKnowledgeCheckPrivateV1(
        accepted_answers=accepted, answer_explanation_markdown=spec.explanation,
        tests=tuple(LearningItemRuntimeTestCaseV1(
            id="option." + fact.option_id, case_type="visible" if index == 0 else "hidden",
            input_json={"answer": fact.option_id}, expected_output_json={"accepted": all(fact.clause_passes)},
            is_critical=True, order_index=index,
        ) for index, fact in enumerate(facts)),
        score_policy=LearningItemScorePolicyV1(kind="static_exact", policy_version="static_exact_v1", threshold=1.0),
    )
    target = get_finite_course_target(PYTHON_KC_TARGET_ID)
    return PythonKcFixtureV1(
        task_kind=kind, guided=guided, family_id=PYTHON_KC_TARGET_ID + ":" + kind,
        target_definition_hash=target.definition_hash, assessment_definition_hash=target.assessment.definition_hash,
        purpose="remediation" if guided else "knowledge_check", title=spec.title,
        public_content=public, private_content=private, option_facts=facts,
    )


def python_kc_fixture(task_kind: KcTaskKind, *, guided: bool = False) -> PythonKcFixtureV1:
    return _build(task_kind, guided=guided)


def validate_python_kc_fixture(fixture: PythonKcFixtureV1) -> PythonKcStaticCheckV1:
    fixture = checked_model(fixture, PythonKcFixtureV1)
    expected = _build(fixture.task_kind, guided=fixture.guided)
    # Exact registered text/options and independently computed option facts both
    # matter. Caller-edited labels cannot inherit another option's private truth.
    if fixture != expected:
        raise ValueError("python_kc_registered_fixture_mismatch")
    return PythonKcStaticCheckV1(correct_option_id=fixture.private_content.accepted_answers[0],
                                fixture_hash=fixture.fixture_hash)


def python_kc_public_content(task_kind: KcTaskKind, *, guided: bool = False) -> LearningItemKnowledgeCheckContentV1:
    return _build(task_kind, guided=guided).public_content


def python_kc_exercise_material(task_kind: KcTaskKind, *, guided: bool = False) -> ExerciseAuthorityMaterial:
    """Existing Practice material shape, deliberately REJECTED and unpublished."""
    fixture = _build(task_kind, guided=guided)
    validate_python_kc_fixture(fixture)
    public, private = fixture.public_content, fixture.private_content
    options = [option.model_dump(mode="json") for option in public.options]
    exercise = ExerciseVersion(
        language_id="python", exercise_key="finite.python-kc." + task_kind + (".remediation" if guided else ""),
        exercise_type=ExerciseType.STATIC_CODE_REASONING, version="kc-binding-v1",
        source_kind=ExerciseSourceKind.CURATED_FIXTURE, title=fixture.title,
        learner_prompt={"schema_version": "knowledge_check_prompt_v1", "prompt_markdown": public.prompt_markdown,
                        "response_kind": public.response_kind, "options": options},
        starter_artifact={"schema_version": "knowledge_check_artifact_v1", "response_kind": public.response_kind,
                          "options": options},
        required_capabilities=("python.assignment",), runtime_profile_id=None, execution_required=False,
        public_feedback_policy_version="knowledge_check_feedback_v1", validation_status=ExerciseValidationStatus.REJECTED,
    )
    rubric = ExercisePrivateRubric(
        rubric_version="learning_item_rubric_v1", private_test_bundle=tuple(t.model_dump(mode="json") for t in private.tests),
        reference_answer={"accepted_answers": list(private.accepted_answers),
                          "answer_explanation_markdown": private.answer_explanation_markdown},
        score_policy=private.score_policy.model_dump(mode="json"),
    )
    return ExerciseAuthorityMaterial(exercise=exercise, rubric=rubric, model_review_validation=None,
                                     runner_payload={}, standard_submission=private.accepted_answers[0], starter_submission="")


PYTHON_KC_FIXTURE_HASH = canonical_hash([
    _build(kind, guided=False).model_dump(mode="json") for kind in _KINDS
] + [_build("diagnose", guided=True).model_dump(mode="json")])
PYTHON_KC_SCORER_VERSION = "kc-binding-v1." + canonical_hash({
    "target_id": PYTHON_KC_TARGET_ID, "fixture_hash": PYTHON_KC_FIXTURE_HASH,
    "rule": "unique_single_choice_rhs_saved_observation_and_causal_reason_static_exact",
    "execution": "not_run_static", "authority": "source_blind_review_family_publication_separate",
})
