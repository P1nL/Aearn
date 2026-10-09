"""Three offline cases. Fake runner seals are protocol-only, never live evidence."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import SandboxResultV1

from app.services.learning.item_bank.contracts import canonical_hash
from app.services.learning.item_supply.finite_candidate_validation import prepare_finite_candidate_validation
from app.services.learning.item_supply.finite_task_ambiguity import (
    FiniteAmbiguityPending, FiniteTaskAmbiguityOwner, PROBE_NAMES, build_finite_ambiguity_plan,
)
from app.services.learning.item_supply.finite_targets.python_kc import _spec, _truth
from app.services.learning.item_supply.finite_targets.python_state import _programs, python_state_expected_stdout
from app.services.learning.item_supply.finite_targets.sqlite_predicates import sqlite_oracle, sqlite_private_fixture
from tests.learning.test_item_supply_finite_candidate_validation import _context, _source

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)


def _candidate(target):
    spec, materials = _context(target)
    if spec.python_goal is not None:
        private = dict(type="code", standard_answer=_programs(spec.python_goal)[2],
            tests=[dict(id="candidate-" + str(i), case_type="visible" if i == 0 else "hidden", input_json={},
                expected_output_json={"stdout": python_state_expected_stdout(spec.python_goal)}, order_index=i)
                for i in range(2)], score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0))
    elif spec.sql_target is not None:
        fixture = sqlite_private_fixture(spec.sql_target)
        datasets = (spec.public_template.content.public_dataset, fixture.private_cases[0].dataset)
        private = dict(type="sql_v2", standard_query=fixture.equivalent_queries[0],
            tests=[dict(id="candidate-" + str(i), case_type="visible" if i == 0 else "hidden", order_index=i,
                dataset=d.model_dump(mode="json"), expected_output=sqlite_oracle(spec.sql_target, d).model_dump(mode="json"))
                for i, d in enumerate(datasets)], score_policy=dict(kind="all_tests", policy_version="all_tests_v1", threshold=1.0))
    else:
        question, truth = _spec("trace", False), _truth("trace", False)
        accepted = {o.label: (o.rhs, o.saved, o.observation, o.reason) == truth for o in question.options}
        options = spec.public_template.content.options
        private = dict(type="knowledge_check", accepted_answers=[next(o.option_id for o in options if accepted[o.label])],
            answer_explanation_markdown=question.explanation,
            tests=[dict(id="option." + o.option_id, case_type="visible" if i == 0 else "hidden", order_index=i,
                input_json={"answer": o.option_id}, expected_output_json={"accepted": accepted[o.label]}) for i, o in enumerate(options)],
            score_policy=dict(kind="static_exact", policy_version="static_exact_v1", threshold=1.0))
    source = _source(spec, private)
    inputs = prepare_finite_candidate_validation(source, spec=spec, materials=materials)
    return source, spec, inputs


class _ProtocolOnlyRunner:
    """Fabricated facts exercise composition only, not a protected executor."""
    def __init__(self, plan):
        self.plan, self.calls, self.originals, self.valid = plan, 0, [], True

    def run(self, *, request, run_id, probe_name):
        alternative = probe_name == PROBE_NAMES[1]
        tests = json.loads(self.plan.selected_tests_json)
        predictions = json.loads(self.plan.alternative_expected_json)
        facts = []
        for test, prediction in zip(tests, predictions, strict=True):
            if self.plan.interpretation.target_id == "python-state-update-v1":
                goal = test["input_json"]["goal_contract"]
                fact = dict(id=test["id"], status="success", code="python_terminal",
                    stdout=prediction["stdout"] if alternative else test["expected_output_json"]["stdout"],
                    goal_contract_id=goal["goal_contract_id"], goal_contract_hash=canonical_hash(goal),
                    goal_satisfied=not alternative, goal_status="unsatisfied" if alternative else "satisfied")
            else:
                output = prediction["expected_output"] if alternative else test["expected_output"]
                fact = dict(id=test["id"], status="success", code="sqlite_terminal", columns=output["columns"], rows=output["rows"])
            facts.append(fact)
        result = SandboxResultV1.model_validate(dict(status="success", stdout=json.dumps({"cases": facts}),
                                                    diagnostic_code="item_supply_facts_v1"))
        terminal = SimpleNamespace(run_id=run_id, probe_name=probe_name,
            request_hash=canonical_hash(request.model_dump(mode="json")), lock_fingerprint=self.plan.runtime_lock_hash,
            result=result, elapsed_seconds=0.2, mode="live", isolation="approved_os_boundary", seal="protocol-only-not-real")
        terminal.to_payload = lambda: dict(schema_version="item_supply_runner_terminal_v1", run_id=str(run_id),
            probe_name=probe_name, request_hash=terminal.request_hash, lock_fingerprint=terminal.lock_fingerprint,
            result=result.model_dump(mode="json"), elapsed_seconds=0.2, mode="live", isolation="approved_os_boundary", seal=terminal.seal)
        self.calls += 1
        self.originals.append(terminal)
        return terminal

    def verify(self, receipt, *, request):
        return self.valid and any(receipt is old for old in self.originals) and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


@pytest.mark.parametrize("target", ("python-state-update-v1", "sqlite-predicate-order-v1"))
def test_native_named_interpretation_pair_protocol_only(target):
    source, spec, inputs = _candidate(target)
    plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
    assert plan.correct.submission == (source.private.content.standard_answer if spec.python_goal is not None else source.private.content.standard_query)
    assert plan.interpretation.claim_scope == "named_interpretation_pair_only"
    assert "expected_output" not in plan.correct.hidden_test_bundle_json
    assert plan.correct.test_reference_hash == plan.alternative.test_reference_hash
    runner = _ProtocolOnlyRunner(plan)
    owner = FiniteTaskAmbiguityOwner(runner, parent_deadline_at=NOW + timedelta(minutes=3), clock=lambda: NOW)
    assert owner.resource_plan(plan).execution_seconds == 20
    run_id = uuid4()
    receipt = owner.run(source, plan, spec=spec, inputs=inputs, run_id=run_id)
    assert runner.calls == 2 and len(receipt.terminals) == 2
    assert receipt.conclusion == "named_interpretation_distinguished" and not receipt.publication_enabled
    assert all(receipt.selected_case_results) and not any(receipt.alternative_case_results)
    assert owner.verify(receipt, source, spec=spec, inputs=inputs)
    assert owner.run(source, plan, spec=spec, inputs=inputs, run_id=run_id) == receipt and runner.calls == 2
    assert owner.resource_usage(receipt).execution_seconds == 2
    actual, proofs = owner.verified_evidence(receipt, source, spec=spec, inputs=inputs, runner=runner)
    assert actual.execution_seconds == 2 and proofs == receipt.terminals
    with pytest.raises(FiniteAmbiguityPending, match="finite_ambiguity_runner_identity_mismatch"):
        owner.verified_evidence(receipt, source, spec=spec, inputs=inputs, runner=_ProtocolOnlyRunner(plan))
    assert runner.calls == 2
    cold = FiniteTaskAmbiguityOwner(runner, parent_deadline_at=NOW + timedelta(minutes=3), clock=lambda: NOW)
    assert not cold.verify(receipt, source, spec=spec, inputs=inputs)  # no JSON/seal rehydration
    runner.valid = False
    assert not owner.verify(receipt, source, spec=spec, inputs=inputs)


def test_static_kc_full_propositions_no_os_and_current_context_required():
    source, spec, inputs = _candidate("python-kc-binding-v1")
    plan = build_finite_ambiguity_plan(source, spec=spec, inputs=inputs)
    now = [NOW]
    owner = FiniteTaskAmbiguityOwner(None, parent_deadline_at=NOW + timedelta(minutes=3), clock=lambda: now[0])
    assert owner.resource_plan(plan).execution_seconds == 0 and plan.correct is None and plan.alternative is None
    propositions = json.loads(plan.option_propositions_json)
    assert [p["label"] for p in propositions] == [o.label for o in source.public.content.options]
    assert sum(p["accepted"] for p in propositions) == 1
    receipt = owner.run(source, plan, spec=spec, inputs=inputs, run_id=uuid4())
    assert receipt.mode == "static_options" and receipt.terminals == ()
    assert receipt.conclusion == "registered_option_propositions_unique"
    assert owner.verify(receipt, source, spec=spec, inputs=inputs)
    changed = spec.model_copy(update={"target_definition_hash": "0" * 64})
    assert not owner.verify(receipt, source, spec=changed, inputs=inputs)
    now[0] += timedelta(minutes=4)
    assert not owner.verify(receipt, source, spec=spec, inputs=inputs)
    assert owner.resource_usage(receipt).execution_seconds == 0  # static usage, not renewed authority
