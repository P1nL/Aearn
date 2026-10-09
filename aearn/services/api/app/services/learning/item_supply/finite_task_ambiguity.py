"""Native finite interpretation sidecar: two original sealed calls, or static KC.

Private plans/facts only. A named interpretation distinction is NOT general
unambiguity, source currency, family independence, coverage or admission.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Callable, Literal, cast
from uuid import UUID

from aearn_shared.execution import ExecutionAction, SafeExecutionStatus, SandboxInputV1
from pydantic import Field, model_validator

from app.services.learning.item_bank.contracts import (
    LearningItemCodePrivateV1, LearningItemKnowledgeCheckContentV1,
    LearningItemSourceV1, LearningItemSqlContentV2, LearningItemSqlPrivateV2, canonical_hash,
)
from app.services.learning.item_supply.admission_facts_contracts import RunnerTerminalProofV1
from app.services.learning.item_supply.contracts import Digest
from app.services.learning.item_supply.finite_candidate_factory import FLEXIBLE_FACTORY_VERSION, FiniteCandidateSpecV1
from app.services.learning.item_supply.finite_candidate_validation import (
    FiniteCandidateValidationInputsV1, _static_kc_facts,
)
from app.services.learning.item_supply.finite_task_families import families_for_course
from app.services.learning.item_supply.finite_targets.contracts import TargetId
from app.services.learning.item_supply.finite_targets.python_kc import KcTaskKind, PYTHON_KC_SCORER_VERSION, _spec, _truth, python_kc_public_content
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.finite_targets.sqlite_predicates import (
    SqliteFault, sqlite_counterexample_output, sqlite_oracle, sqlite_private_fixture, sqlite_public_task,
)
from app.services.learning.item_supply.policies import ResourceAmounts
from app.services.learning.item_supply.sandbox.execution_contracts import (
    EXECUTION_WALL_SECONDS, RunnerPort, RunnerTerminalReceipt,
)
from app.services.learning.item_supply.sandbox.finite_probe_plans import (
    build_finite_candidate_probe_plan, check_finite_source_spec,
)
from app.services.learning.item_supply.sandbox.probe_plans import submission_fingerprint
from app.services.learning.item_supply.sandbox.python_state_scorer import (
    PYTHON_STATE_SCORER_VERSION, compile_python_state_test_bundle, score_python_state_case,
)
from app.services.learning.item_supply.storage_contracts import StorageContract, checked_model
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION
from app.services.runners.sandbox_runner import _run_single_test
from app.services.runners.sql_query_runner import _compare_expected

CALL_BOUND = EXECUTION_WALL_SECONDS + 5
PROBE_NAMES = ("native_finite_ambiguity_selected", "native_finite_ambiguity_alternative")
ProfileId = Literal["native_python_fixed_goal_ambiguity_v1", "native_sqlite_predicate_ambiguity_v1", "native_kc_propositions_ambiguity_v1"]


class FiniteAmbiguityPending(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class FiniteInterpretationV1(StorageContract):
    """A closed descriptor rebuilt from the registered task, not arbitrary prose."""
    profile_id: ProfileId
    target_id: TargetId
    task_kind: str
    selected_rule: str
    selected_statement: str
    alternative_rule: str
    alternative_statement: str
    claim_scope: Literal["named_interpretation_pair_only", "complete_registered_option_propositions"]


class FiniteAmbiguityPlanV1(StorageContract):
    schema_version: Literal["native_finite_ambiguity_plan_v1"] = "native_finite_ambiguity_plan_v1"
    source_hash: Digest
    content_hash: Digest
    public_task_hash: Digest
    specification_hash: Digest
    target_definition_hash: Digest
    instance_hash: Digest
    inputs_hash: Digest
    interpretation: FiniteInterpretationV1
    scorer_version: str
    runtime_lock_hash: Digest | None
    correct: SandboxInputV1 | None = Field(default=None, repr=False)
    alternative: SandboxInputV1 | None = Field(default=None, repr=False)
    selected_tests_json: str = Field(default="[]", max_length=24000, repr=False)
    alternative_expected_json: str = Field(default="[]", max_length=24000, repr=False)
    option_propositions_json: str = Field(default="[]", max_length=24000, repr=False)

    @model_validator(mode="after")
    def shape(self) -> FiniteAmbiguityPlanV1:
        static = self.interpretation.profile_id == "native_kc_propositions_ambiguity_v1"
        if static:
            if self.correct is not None or self.alternative is not None or self.runtime_lock_hash is not None:
                raise ValueError("finite_static_ambiguity_has_no_os_wire")
        elif self.correct is None or self.alternative is None or self.runtime_lock_hash in (None, "0" * 64):
            raise ValueError("finite_ambiguity_runtime_binding_missing")
        return self

    @property
    def plan_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteAmbiguityPlanV1).model_dump(mode="json"))


class FiniteAmbiguityReceiptV1(StorageContract):
    schema_version: Literal["native_finite_ambiguity_receipt_v1"] = "native_finite_ambiguity_receipt_v1"
    plan: FiniteAmbiguityPlanV1 = Field(repr=False)
    run_id: UUID
    started_at: datetime
    completed_at: datetime
    parent_deadline_at: datetime
    mode: Literal["sealed_pair", "static_options"]
    terminals: tuple[RunnerTerminalProofV1, ...] = Field(max_length=2, repr=False)
    selected_case_results: tuple[bool, ...] = Field(min_length=1, max_length=48)
    alternative_case_results: tuple[bool, ...] = Field(min_length=1, max_length=48)
    alternative_predictions_matched: tuple[bool, ...] = Field(min_length=1, max_length=48)
    conclusion: Literal["named_interpretation_distinguished", "registered_option_propositions_unique"]
    publication_enabled: Literal[False] = False

    @model_validator(mode="after")
    def bounded(self) -> FiniteAmbiguityReceiptV1:
        if (any(t.tzinfo is None for t in (self.started_at, self.completed_at, self.parent_deadline_at))
                or not self.started_at <= self.completed_at < self.parent_deadline_at
                or not all(self.selected_case_results) or any(self.alternative_case_results)
                or not all(self.alternative_predictions_matched)
                or len(self.alternative_case_results) != len(self.alternative_predictions_matched)):
            raise ValueError("finite_ambiguity_distinction_unproven")
        static = self.plan.interpretation.profile_id == "native_kc_propositions_ambiguity_v1"
        if (self.mode != ("static_options" if static else "sealed_pair")
                or len(self.terminals) != (0 if static else 2)
                or self.conclusion != ("registered_option_propositions_unique" if static else "named_interpretation_distinguished")):
            raise ValueError("finite_ambiguity_receipt_mode_invalid")
        return self

    @property
    def receipt_hash(self) -> str:
        return canonical_hash(checked_model(self, FiniteAmbiguityReceiptV1).model_dump(mode="json"))


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _checked_inputs(source: LearningItemSourceV1, spec: FiniteCandidateSpecV1,
                    inputs: FiniteCandidateValidationInputsV1) -> None:
    check_finite_source_spec(source, spec)
    expected_runtime, expected_scorer = {
        "python-state-update-v1": ("python-stdout-v1", PYTHON_STATE_SCORER_VERSION),
        "sqlite-predicate-order-v1": ("sqlite-query-v1", GATE_PASS_POLICY_VERSION),
        "python-kc-binding-v1": ("static-exact-v1", PYTHON_KC_SCORER_VERSION),
    }[spec.target_id]
    scope = spec.coverage_blueprint.scope
    if (scope.runtime_profile_id != expected_runtime or scope.scorer_version != expected_scorer
            or scope.assessment_contract_version != spec.target_id):
        raise FiniteAmbiguityPending("finite_ambiguity_runtime_scorer_stale")
    instance = (spec.python_goal.model_dump(mode="json") if spec.python_goal is not None
                else spec.sql_target.model_dump(mode="json") if spec.sql_target is not None
                else {"public": spec.public_template.content.model_dump(mode="json"),
                      "variant_id": spec.allocation.variant_id, "seed": spec.seed})
    if ((inputs.target_id, inputs.source_hash, inputs.content_hash, inputs.public_task_hash,
         inputs.specification_hash, inputs.target_definition_hash, inputs.instance_hash)
            != (spec.target_id, source.source_hash, source.content_hash, source.public.public_hash,
                spec.specification_hash, spec.target_definition_hash, canonical_hash(instance))):
        raise FiniteAmbiguityPending("finite_ambiguity_inputs_stale")
    if spec.target_id == "python-kc-binding-v1":
        if inputs.static_facts != _static_kc_facts(source, spec, inputs.public_task_hash, inputs.instance_hash):
            raise FiniteAmbiguityPending("finite_ambiguity_static_facts_stale")
    elif inputs.probe_plan != build_finite_candidate_probe_plan(source, spec=spec):
        raise FiniteAmbiguityPending("finite_ambiguity_probe_inputs_stale")


def _wire(source: LearningItemSourceV1, submission: str,
          cases: tuple[dict[str, Any], ...]) -> SandboxInputV1:
    request = SandboxInputV1(runtime_id="python-stdout-v1" if source.public.kind.value == "code" else "sqlite-query-v1",
        action=ExecutionAction.TEST, submission=submission, hidden_test_bundle_json=_json(cases),
        source_reference_hash=source.source_hash, test_reference_hash=canonical_hash(cases))
    if len(request.wire_bytes()) > 98_304:
        raise FiniteAmbiguityPending("finite_ambiguity_wire_bound")
    return request


def build_finite_ambiguity_plan(source: LearningItemSourceV1, *, spec: FiniteCandidateSpecV1,
                                inputs: FiniteCandidateValidationInputsV1) -> FiniteAmbiguityPlanV1:
    """Rebuild a closed private interpretation pair; performs no IO or execution."""
    source = checked_model(source, LearningItemSourceV1)
    spec = checked_model(spec, FiniteCandidateSpecV1)
    inputs = checked_model(inputs, FiniteCandidateValidationInputsV1)
    _checked_inputs(source, spec, inputs)
    family = next(f for f in families_for_course(spec.target_id) if f.family_id == spec.allocation.family_id)
    common: dict[str, Any] = dict(source_hash=source.source_hash, content_hash=source.content_hash,
        public_task_hash=inputs.public_task_hash, specification_hash=spec.specification_hash,
        target_definition_hash=spec.target_definition_hash, instance_hash=inputs.instance_hash,
        inputs_hash=inputs.inputs_hash, scorer_version=spec.coverage_blueprint.scope.scorer_version,
        runtime_lock_hash=spec.coverage_blueprint.scope.runtime_profile_hash)
    tests: tuple[dict[str, Any], ...]
    alternatives: tuple[dict[str, Any], ...]
    if spec.python_goal is not None:
        private = source.private.content
        if not isinstance(private, LearningItemCodePrivateV1):
            raise FiniteAmbiguityPending("finite_ambiguity_python_shape")
        goal = spec.python_goal
        counter = next(w for w in _programs(goal)[4] if w.name == "hardcoded_stdout")
        if counter.expected_stdout != python_state_expected_stdout(goal):
            raise FiniteAmbiguityPending("finite_ambiguity_oracle_mismatch")
        tests = ({"id": "native_ambiguity_state", "case_type": "hidden",
            "input_json": {"goal_contract": goal.model_dump(mode="json")},
            "expected_output_json": {"stdout": python_state_expected_stdout(goal)}},)
        cases = compile_python_state_test_bundle(tests)
        interpretation = FiniteInterpretationV1(profile_id="native_python_fixed_goal_ambiguity_v1",
            target_id=spec.target_id, task_kind=family.task_kind,
            selected_rule="state_transition_and_observation", selected_statement=source.public.instruction_markdown,
            alternative_rule="stdout_without_state_transition",
            alternative_statement="Accept the numerically identical stdout without performing the declared state transitions.",
            claim_scope="named_interpretation_pair_only")
        correct, alternative = private.standard_answer, counter.submission
        alternatives = ({"id": tests[0]["id"], "stdout": counter.expected_stdout,
                         "goal_status": "unsatisfied", "goal_satisfied": False},)
    elif spec.sql_target is not None:
        public, private = source.public.content, source.private.content
        if not isinstance(public, LearningItemSqlContentV2) or not isinstance(private, LearningItemSqlPrivateV2):
            raise FiniteAmbiguityPending("finite_ambiguity_sql_shape")
        target = spec.sql_target
        faults: dict[str, SqliteFault] = {"conjunction": "or_instead_of_and", "override_fallback": "ignores_override",
            "exclusive": "inclusive_or", "keyset_after": "includes_cursor"}
        fault = faults[target.task_kind]
        fixture = sqlite_private_fixture(target)
        counter_sql = next(c for c in fixture.counterexamples if c.fault == fault)
        selected = []
        alternate = []
        wire_cases = []
        for case in fixture.private_cases:
            truth = sqlite_oracle(target, case.dataset)
            other = sqlite_counterexample_output(target, case.dataset, fault)
            if truth == other:
                continue
            wire_cases.append({"id": case.id, "case_type": "hidden", "tables": [t.model_dump(mode="json") for t in public.tables],
                               "dataset": case.dataset.model_dump(mode="json"), "max_rows": public.max_rows})
            selected.append({"id": case.id, "expected_output": truth.model_dump(mode="json"), "comparison": "ordered"})
            alternate.append({"id": case.id, "expected_output": other.model_dump(mode="json")})
        if not wire_cases:
            raise FiniteAmbiguityPending("finite_ambiguity_no_discriminating_cases")
        cases, tests, alternatives = tuple(wire_cases), tuple(selected), tuple(alternate)
        interpretation = FiniteInterpretationV1(profile_id="native_sqlite_predicate_ambiguity_v1",
            target_id=spec.target_id, task_kind=family.task_kind,
            selected_rule="declared_predicate_ordered_multiset", selected_statement=sqlite_public_task(target).instruction,
            alternative_rule=fault, alternative_statement={
                "conjunction": "Accept either conjunct instead of requiring both.",
                "override_fallback": "Use default_flag even when a non-NULL override was declared.",
                "exclusive": "Accept inclusive OR instead of exactly one flag.",
                "keyset_after": "Include the cursor row instead of the strict after-cursor boundary.",
            }[target.task_kind], claim_scope="named_interpretation_pair_only")
        correct, alternative = private.standard_query, counter_sql.query
    else:
        public = source.public.content
        if not isinstance(public, LearningItemKnowledgeCheckContentV1) or inputs.static_facts is None:
            raise FiniteAmbiguityPending("finite_ambiguity_static_shape")
        kind = cast(KcTaskKind, family.task_kind)
        question, kc_truth = _spec(kind, spec.allocation.slot == "remediation"), _truth(kind, spec.allocation.slot == "remediation")
        originals = question.options[spec.seed % 4:] + question.options[:spec.seed % 4]
        expected_public = python_kc_public_content(kind, guided=spec.allocation.slot == "remediation")
        options = expected_public.options[spec.seed % 4:] + expected_public.options[:spec.seed % 4]
        expected_public = expected_public.model_copy(update={"options": tuple(
            option.model_copy(update={"option_id": f"choice-{i + 1}"}) for i, option in enumerate(options))})
        if (public != expected_public
                or (source.blueprint.version != FLEXIBLE_FACTORY_VERSION
                    and source.public.instruction_markdown != "阅读给定顺序程序与候选解释，选择唯一同时满足数值、时刻及因果要求的一项；提交该选项。")
                or source.public.purpose.value != spec.allocation.purpose
                or public.prompt_markdown != question.prompt or len(public.options) != 4
                or any((o.option_id, o.label) != (f"choice-{i + 1}", original.label)
                       for i, (o, original) in enumerate(zip(public.options, originals, strict=True)))):
            raise FiniteAmbiguityPending("finite_ambiguity_static_public_mismatch")
        propositions = tuple({"option_id": option.option_id, "label": option.label,
            "rhs": original.rhs, "saved": original.saved, "observation": original.observation,
            "reason": original.reason, "accepted": (original.rhs, original.saved, original.observation, original.reason) == kc_truth}
            for option, original in zip(public.options, originals, strict=True))
        interpretation = FiniteInterpretationV1(profile_id="native_kc_propositions_ambiguity_v1",
            target_id=spec.target_id, task_kind=family.task_kind,
            selected_rule="complete_rhs_saved_observation_causal_proposition",
            selected_statement=question.prompt, alternative_rule="other_registered_option_propositions",
            alternative_statement="Every other full option proposition in the exact registered public question.",
            claim_scope="complete_registered_option_propositions")
        return FiniteAmbiguityPlanV1(**{**common, "runtime_lock_hash": None}, interpretation=interpretation,
                                     option_propositions_json=_json(propositions))
    if submission_fingerprint(source, correct) == submission_fingerprint(source, alternative):
        raise FiniteAmbiguityPending("finite_ambiguity_pair_not_distinct")
    return FiniteAmbiguityPlanV1(**common, interpretation=interpretation,
        correct=_wire(source, correct, cases), alternative=_wire(source, alternative, cases),
        selected_tests_json=_json(tests), alternative_expected_json=_json(alternatives))


class FiniteTaskAmbiguityOwner:
    """Same-process original-seal owner; JSON receipts cannot rehydrate its authority."""
    def __init__(self, runner: RunnerPort | None, *, parent_deadline_at: datetime,
                 clock: Callable[[], datetime] | None = None) -> None:
        if parent_deadline_at.tzinfo is None:
            raise FiniteAmbiguityPending("finite_ambiguity_deadline_missing")
        self._runner, self._deadline = runner, parent_deadline_at
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._attempts: set[UUID] = set()
        self._runs: dict[UUID, tuple[tuple[RunnerTerminalReceipt, ...], FiniteAmbiguityReceiptV1]] = {}

    def resource_plan(self, plan: FiniteAmbiguityPlanV1) -> ResourceAmounts:
        plan = checked_model(plan, FiniteAmbiguityPlanV1)
        return ResourceAmounts(execution_seconds=0 if plan.correct is None else 2 * CALL_BOUND)

    def _score(self, plan: FiniteAmbiguityPlanV1, terminal: RunnerTerminalReceipt, *, alternative: bool) -> tuple[bool, ...]:
        result = terminal.result
        if (terminal.mode != "live" or terminal.isolation != "approved_os_boundary"
                or terminal.lock_fingerprint != plan.runtime_lock_hash
                or not terminal.seal or not math.isfinite(terminal.elapsed_seconds)
                or not 0 <= terminal.elapsed_seconds <= CALL_BOUND
                or result.status is not SafeExecutionStatus.SUCCESS or result.stderr
                or result.diagnostic_code != "item_supply_facts_v1"):
            raise FiniteAmbiguityPending("finite_ambiguity_terminal_unverified")
        try:
            tests, predictions = json.loads(plan.selected_tests_json), json.loads(plan.alternative_expected_json)
            facts = json.loads(result.stdout)["cases"]
            if not isinstance(facts, list) or [f["id"] for f in facts] != [t["id"] for t in tests]:
                raise ValueError("case identities")
            outcomes = []
            for fact, test, prediction in zip(facts, tests, predictions, strict=True):
                if plan.interpretation.target_id == "python-state-update-v1":
                    judged = score_python_state_case(test, fact)
                    stdout = _run_single_test({}, "unused", test, fact.get("stdout", ""))["passed"] is True
                    if (judged is None or not stdout or (alternative and
                            (fact.get("stdout") != prediction["stdout"] or fact.get("goal_status") != prediction["goal_status"]
                             or fact.get("goal_satisfied") is not prediction["goal_satisfied"]))):
                        raise ValueError("state distinction")
                    outcomes.append(judged)
                else:
                    if fact.get("status") != "success" or fact.get("code") != "sqlite_terminal":
                        raise ValueError("SQL facts missing")
                    columns, rows = fact["columns"], fact["rows"]
                    actual_rows = [dict(zip(columns, row, strict=True)) for row in rows]
                    def matches(table: dict[str, Any]) -> bool:
                        expected_rows = [dict(zip(table["columns"], row, strict=True)) for row in table["rows"]]
                        return _compare_expected(columns, actual_rows, (table["columns"], expected_rows), "ordered")[0]
                    if alternative and not matches(prediction["expected_output"]):
                        raise ValueError("alternative prediction mismatch")
                    outcomes.append(matches(test["expected_output"]))
            return tuple(outcomes)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise FiniteAmbiguityPending("finite_ambiguity_semantics_unproven") from None

    def _receipt(self, plan: FiniteAmbiguityPlanV1, run_id: UUID,
                 terminals: tuple[RunnerTerminalReceipt, ...], *, started: datetime, completed: datetime) -> FiniteAmbiguityReceiptV1:
        if self._clock() >= self._deadline:
            raise FiniteAmbiguityPending("finite_ambiguity_deadline_exhausted")
        positive: tuple[bool, ...]
        negative: tuple[bool, ...]
        proofs: tuple[RunnerTerminalProofV1, ...]
        if plan.correct is None:
            if terminals:
                raise FiniteAmbiguityPending("finite_static_ambiguity_has_no_os_wire")
            propositions = json.loads(plan.option_propositions_json)
            if (len(propositions) != 4 or any(type(p["accepted"]) is not bool for p in propositions)
                    or sum(p["accepted"] is True for p in propositions) != 1):
                raise FiniteAmbiguityPending("finite_static_ambiguity_not_unique")
            positive = tuple(p["accepted"] for p in propositions if p["accepted"])
            negative = tuple(p["accepted"] for p in propositions if not p["accepted"])
            proofs = ()
        else:
            if self._runner is None or plan.alternative is None or len(terminals) != 2:
                raise FiniteAmbiguityPending("finite_ambiguity_original_runner_required")
            for name, request, terminal in zip(PROBE_NAMES, (plan.correct, plan.alternative), terminals, strict=True):
                if ((terminal.run_id, terminal.probe_name) != (run_id, name)
                        or terminal.request_hash != canonical_hash(request.model_dump(mode="json"))
                        or not self._runner.verify(terminal, request=request)):
                    raise FiniteAmbiguityPending("finite_ambiguity_seal_unverified")
            positive, negative = self._score(plan, terminals[0], alternative=False), self._score(plan, terminals[1], alternative=True)
            if not all(positive) or any(negative):
                raise FiniteAmbiguityPending("finite_ambiguity_distinction_unproven")
            proofs = tuple(RunnerTerminalProofV1.model_validate_json(_json(t.to_payload())) for t in terminals)
        return FiniteAmbiguityReceiptV1(plan=plan, run_id=run_id, started_at=started, completed_at=completed,
            parent_deadline_at=self._deadline, mode="static_options" if plan.correct is None else "sealed_pair",
            terminals=proofs, selected_case_results=positive, alternative_case_results=negative,
            alternative_predictions_matched=tuple(True for _ in negative),
            conclusion="registered_option_propositions_unique" if plan.correct is None else "named_interpretation_distinguished")

    def run(self, source: LearningItemSourceV1, plan: FiniteAmbiguityPlanV1, *, spec: FiniteCandidateSpecV1,
            inputs: FiniteCandidateValidationInputsV1, run_id: UUID) -> FiniteAmbiguityReceiptV1:
        plan = checked_model(plan, FiniteAmbiguityPlanV1)
        if plan != build_finite_ambiguity_plan(source, spec=spec, inputs=inputs):
            raise FiniteAmbiguityPending("finite_ambiguity_plan_stale")
        if run_id in self._runs:
            terminals, receipt = self._runs[run_id]
            if receipt.plan != plan:
                raise FiniteAmbiguityPending("finite_ambiguity_replay_conflict")
            return self._receipt(plan, run_id, terminals, started=receipt.started_at, completed=receipt.completed_at)
        if run_id in self._attempts:
            raise FiniteAmbiguityPending("finite_ambiguity_attempt_consumed")
        required = self.resource_plan(plan).execution_seconds
        if (self._deadline - self._clock()).total_seconds() < required or self._clock() >= self._deadline:
            raise FiniteAmbiguityPending("finite_ambiguity_full_bound_missing")
        if plan.correct is not None and self._runner is None:
            raise FiniteAmbiguityPending("finite_ambiguity_original_runner_required")
        self._attempts.add(run_id)
        started = self._clock()
        collected: list[RunnerTerminalReceipt] = []
        if plan.correct is not None:
            assert self._runner is not None and plan.alternative is not None
            for index, (name, request) in enumerate(zip(PROBE_NAMES, (plan.correct, plan.alternative), strict=True)):
                if (self._deadline - self._clock()).total_seconds() < (2 - index) * CALL_BOUND:
                    raise FiniteAmbiguityPending("finite_ambiguity_deadline_exhausted")
                try:
                    terminal = self._runner.run(request=request, run_id=run_id, probe_name=name)
                except Exception:
                    raise FiniteAmbiguityPending("finite_ambiguity_execution_unknown") from None
                if ((terminal.run_id, terminal.probe_name) != (run_id, name)
                        or terminal.request_hash != canonical_hash(request.model_dump(mode="json"))
                        or not self._runner.verify(terminal, request=request)):
                    raise FiniteAmbiguityPending("finite_ambiguity_seal_unverified")
                collected.append(terminal)
        receipt = self._receipt(plan, run_id, tuple(collected), started=started, completed=self._clock())
        self._runs[run_id] = (tuple(collected), receipt)
        return receipt

    def verify(self, receipt: FiniteAmbiguityReceiptV1, source: LearningItemSourceV1, *,
               spec: FiniteCandidateSpecV1, inputs: FiniteCandidateValidationInputsV1) -> bool:
        try:
            receipt = checked_model(receipt, FiniteAmbiguityReceiptV1)
            stored = self._runs.get(receipt.run_id)
            if stored is None or stored[1] != receipt or receipt.plan != build_finite_ambiguity_plan(source, spec=spec, inputs=inputs):
                return False
            return receipt == self._receipt(receipt.plan, receipt.run_id, stored[0],
                                           started=receipt.started_at, completed=receipt.completed_at)
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def verified_evidence(self, receipt: FiniteAmbiguityReceiptV1, source: LearningItemSourceV1, *,
                          spec: FiniteCandidateSpecV1, inputs: FiniteCandidateValidationInputsV1,
                          runner: RunnerPort | None) -> tuple[ResourceAmounts, tuple[RunnerTerminalProofV1, ...]]:
        """Current class-bound evidence for the issuer holding the SAME runner.

        Proof DTOs are projections only; verification above them always uses the
        original in-process terminals, never a reconstructed JSON seal.
        """
        if type(self) is not FiniteTaskAmbiguityOwner or self._runner is not runner:
            raise FiniteAmbiguityPending("finite_ambiguity_runner_identity_mismatch")
        if not self.verify(receipt, source, spec=spec, inputs=inputs):
            raise FiniteAmbiguityPending("finite_ambiguity_evidence_unverified")
        original = self._runs[receipt.run_id][1]
        return self.resource_usage(original), tuple(checked_model(p, RunnerTerminalProofV1) for p in original.terminals)

    def resource_usage(self, receipt: FiniteAmbiguityReceiptV1) -> ResourceAmounts:
        stored = self._runs.get(receipt.run_id)
        if stored is None or stored[1] != receipt:
            raise FiniteAmbiguityPending("finite_ambiguity_usage_unavailable")
        # Historical usage is readable after expiry; it cannot authorize use.
        return ResourceAmounts(execution_seconds=sum(math.ceil(t.elapsed_seconds) for t in stored[1].terminals))
