from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import pytest
from aearn_shared.execution import SafeExecutionStatus, SandboxInputV1, SandboxResultV1

from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.sandbox.execution import SandboxCandidateExecutionPort
from app.services.learning.item_supply.sandbox.execution_contracts import CandidateProbePlanV1, RunnerTerminalReceipt


def python_source() -> LearningItemSourceV1:
    source = sql_source().model_dump(mode="json")
    source["blueprint"].update(item_kind="code", purpose="exercise", language_id="python", runtime_profile_id="python_stdout_test", required_capabilities=["python.assignment"], allowed_interactions=["edit", "run"])
    source["public"].update(kind="code", purpose="exercise", allowed_interactions=["edit", "run"])
    source["public"]["content"] = {
        "type": "code", "language_id": "python", "editor_language": "python", "exercise_type": "code_completion",
        "starter_code": "print(0)", "code_blanks": [{"blank_key": "value", "expected_concept": "assignment", "acceptable_patterns": [{"type": "literal", "value": "1"}], "is_core": True}],
    }
    source["private"].update(kind="code")
    source["private"]["content"] = {
        "type": "code", "standard_answer": "print(1)",
        "tests": [{"id": case, "case_type": visibility, "expected_output_json": {"stdout": "1"}, "order_index": order} for order, (case, visibility) in enumerate((("visible", "visible"), ("hidden", "hidden")))],
        "score_policy": {"kind": "all_tests", "policy_version": "all_tests_v1", "threshold": 1.0},
    }
    return LearningItemSourceV1.model_validate(source)


def sql_source() -> LearningItemSourceV1:
    return LearningItemSourceLoader().load(curated_learning_item_source_root(), "sql-filter-track-v2.yaml").source


@dataclass(frozen=True)
class SyntheticReceipt:
    run_id: UUID
    probe_name: str
    request_hash: str
    result: SandboxResultV1
    lock_fingerprint: str = "0" * 64
    elapsed_seconds: float = 0.02
    mode: Literal["live", "synthetic"] = "synthetic"
    isolation: Literal["approved_os_boundary", "synthetic"] = "synthetic"
    seal: str = "fixture-not-live"

    def to_payload(self) -> dict[str, object]:
        return {"run_id": str(self.run_id), "probe_name": self.probe_name, "request_hash": self.request_hash, "result": self.result.model_dump(mode="json"), "seal": self.seal}


class SyntheticRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.records: list[SyntheticReceipt] = []

    def run(self, *, request: SandboxInputV1, run_id: UUID, probe_name: str) -> SyntheticReceipt:
        self.calls += 1
        cases = json.loads(request.visible_test_bundle_json) + json.loads(request.hidden_test_bundle_json)
        if probe_name in {"time_limit", "memory_limit", "output_limit"}:
            result = SandboxResultV1(status=SafeExecutionStatus.FAILED, diagnostic_code=probe_name)
        else:
            output = "1\n" if probe_name in {"reference", "equivalent", "boundary"} else "0\n"
            facts = [{"id": case["id"], "status": "success", "code": "python_terminal", "stdout": output} for case in cases]
            # Even maliciously supplied pass counts cannot replace raw facts/scorer.
            result = SandboxResultV1(status=SafeExecutionStatus.SUCCESS, stdout=json.dumps({"cases": facts}), passed_test_count=48, total_test_count=48)
        receipt = SyntheticReceipt(run_id, probe_name, canonical_hash(request.model_dump(mode="json")), result)
        self.records.append(receipt)
        return receipt

    def verify(self, receipt: RunnerTerminalReceipt, *, request: SandboxInputV1) -> bool:
        return receipt in self.records and receipt.request_hash == canonical_hash(request.model_dump(mode="json"))


def test_missing_independent_alternatives_block_and_execution_only_usage() -> None:
    source = python_source()
    runner = SyntheticRunner()
    port = SandboxCandidateExecutionPort(runner)
    plan = port.resource_plan(source)
    assert plan.execution_seconds == 50
    assert plan.requests == plan.input_tokens == plan.output_tokens == plan.fetches == 0
    evidence = port.validate(source)
    probes = {probe.name: probe.status for probe in evidence.probes}
    assert evidence.mode == evidence.isolation == "synthetic"
    assert probes["equivalent"] == probes["wrong_rejected"] == probes["boundary"] == "pending"
    assert probes["reference"] == probes["starter_rejected"] == "passed"
    assert port.verify(evidence, source)
    assert port.resource_usage(evidence).execution_seconds == 5
    assert port.validate(source) == evidence and runner.calls == 5


def test_real_scorer_counterexample_and_sealed_evidence_tampering() -> None:
    source = python_source()
    plan = CandidateProbePlanV1(source_hash=source.source_hash, equivalent="x=1; print(x)", wrong="print(2)", boundary="print(1)", boundary_case_ids=("hidden",))
    port = SandboxCandidateExecutionPort(SyntheticRunner(), probe_plan=plan)
    evidence = port.validate(source)
    assert all(probe.status == "passed" for probe in evidence.probes)
    assert evidence.mode == "synthetic"  # Green fixture probes are never live approval.
    forged = evidence.model_copy(update={"mode": "live", "isolation": "approved_os_boundary"})
    assert not port.verify(forged, source)
    assert not port.verify(evidence.model_copy(update={"source_hash": "f" * 64}), source)
    assert len(port.receipts(evidence)) == 8


def test_stale_server_plan_and_non_stdout_code_fail_closed_without_io() -> None:
    source = python_source()
    runner = SyntheticRunner()
    stale = CandidateProbePlanV1(source_hash="0" * 64, equivalent="print(3)", wrong="print(2)", boundary="print(1)")
    with pytest.raises(ValueError, match="stale"):
        SandboxCandidateExecutionPort(runner, probe_plan=stale).resource_plan(source)
    payload = source.model_dump(mode="json")
    payload["private"]["content"]["tests"][0]["expected_output_json"] = {"return": 1}
    with pytest.raises(ValueError, match="stdout"):
        SandboxCandidateExecutionPort(runner).resource_plan(LearningItemSourceV1.model_validate(payload))
    assert runner.calls == 0


def test_sql_cases_keep_expected_answers_out_of_wire_and_hidden_db_independent() -> None:
    source = sql_source()
    port = SandboxCandidateExecutionPort(SyntheticRunner())
    tasks = port._tasks(source)
    reference = next(task.wire for task in tasks if task.name == "reference")
    visible = json.loads(reference.visible_test_bundle_json)
    hidden = json.loads(reference.hidden_test_bundle_json)
    assert visible[0]["dataset"] != hidden[0]["dataset"]
    assert "expected_output" not in reference.visible_test_bundle_json + reference.hidden_test_bundle_json
    names = {task.name for task in tasks}
    assert {"null", "duplicates", "empty", "order", "types", "joins", "read_only", "single_statement", "bounded_setup"} <= names
    plan = port.resource_plan(source)
    assert plan.execution_seconds == 140 and plan.requests == plan.input_tokens == 0


def test_unissued_evidence_and_schema_extras_are_not_verified() -> None:
    source = python_source()
    issuer = SandboxCandidateExecutionPort(SyntheticRunner())
    evidence = issuer.validate(source)
    assert not SandboxCandidateExecutionPort(SyntheticRunner()).verify(evidence, source)
    forged = evidence.model_copy(update={"extra_authority": True})
    assert not issuer.verify(forged, source)
