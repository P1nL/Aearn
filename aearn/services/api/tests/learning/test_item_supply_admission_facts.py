"""Six bounded pure cases; live-shaped stub terminals are NOT real OS/PG evidence."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aearn_shared.execution import SandboxResultV1

from app.db.schema import SCHEMA_DIRECTORY, SCHEMA_FRAGMENT_NAMES
from app.services.learning.item_bank.compiler import LearningItemSourceLoader, curated_learning_item_source_root
from app.services.learning.item_bank.contracts import LearningItemSourceV1, canonical_hash
from app.services.learning.item_supply.admission_facts import AdmissionFactsOwner
from app.services.learning.item_supply.task_ambiguity_owner import (
    AdmissionFactsPending, SQL_TARGET_INSTRUCTION, TaskAmbiguityOwner, build_sql_admission_candidate_plan, build_task_ambiguity_plan, target_clauses,
)

NOW = datetime(2026,10,2,tzinfo=UTC)


def source_fixture(*, explicit=True):
    source = LearningItemSourceLoader().load(curated_learning_item_source_root(),"sql-filter-track-v2.yaml").source
    payload = source.model_dump(mode="json")
    if explicit:
        payload["public"]["instruction_markdown"] = SQL_TARGET_INSTRUCTION
    return LearningItemSourceV1.model_validate(payload)


class ProtocolStub:
    """Pure declared-data protocol double, never an actual runtime acceptance."""
    def __init__(self, *, mode="live", seal=True, infrastructure=False):
        self.mode,self.seal,self.infrastructure = mode,seal,infrastructure
        self.records = []

    def run(self, *, request,run_id,probe_name):
        facts = []
        for case in json.loads(request.hidden_test_bundle_json):
            rows = next(t["rows"] for t in case["dataset"]["tables"] if t["table"]=="learners")
            matching = sorted((r for r in rows if r[2]=="sql"),key=lambda r:r[0],
                              reverse="counterexample" in probe_name)
            names = [r[1] for r in matching]
            if "counterexample" in probe_name:
                names = list(dict.fromkeys(names))
            facts.append({"id":case["id"],"status":"success","code":"sqlite_terminal",
                          "columns":["name"],"rows":[[name] for name in names]})
        result = SandboxResultV1.model_validate({"status":"unavailable" if self.infrastructure else "success",
            "stdout":json.dumps({"cases":facts}),"diagnostic_code":"item_supply_facts_v1"})
        receipt = SimpleNamespace(run_id=run_id,probe_name=probe_name,
            request_hash=canonical_hash(request.model_dump(mode="json")),lock_fingerprint="a"*64,
            result=result,elapsed_seconds=0.25,mode=self.mode,
            isolation="approved_os_boundary" if self.mode=="live" else "synthetic",seal="protocol-stub-only")
        receipt.to_payload = lambda: dict(schema_version="item_supply_runner_terminal_v1",run_id=str(run_id),
            probe_name=probe_name,request_hash=receipt.request_hash,lock_fingerprint=receipt.lock_fingerprint,
            result=result.model_dump(mode="json"),elapsed_seconds=receipt.elapsed_seconds,
            mode=receipt.mode,isolation=receipt.isolation,seal=receipt.seal)
        self.records.append(receipt)
        return receipt

    def verify(self,receipt,*,request):
        return self.seal and any(r is receipt for r in self.records) and receipt.request_hash==canonical_hash(request.model_dump(mode="json"))


def test_explicit_sql_target_and_independent_duplicate_order_plan():
    source = source_fixture()
    plan = build_task_ambiguity_plan(source)
    assert plan.target.duplicates=="keep" and plan.target.order_by=="id"
    expected = json.loads(plan.expected_json)
    assert expected[1]["expected_output"]["rows"]==[["Ada"],["Ada"]]
    assert expected[2]["expected_output"]["rows"]==[["Ada"],["Bea"],["Zoe"]]
    assert plan.correct.submission != source.public.content.starter_query
    assert "DISTINCT" in plan.counterexample.submission and "DESC" in plan.counterexample.submission
    assert tuple(c.clause_id for c in target_clauses())==("sql.select.where","sql.order_by")
    candidate_plan = build_sql_admission_candidate_plan(source)
    assert candidate_plan.source_hash == source.source_hash and candidate_plan.server_fixture_hash
    assert source.public.instruction_markdown == SQL_TARGET_INSTRUCTION


def test_two_call_protocol_receipt_replay_and_scorer_derivation():
    source = source_fixture()
    runner = ProtocolStub()
    owner = TaskAmbiguityOwner(runner,parent_deadline_at=NOW+timedelta(seconds=40),clock=lambda:NOW)
    plan = build_task_ambiguity_plan(source)
    run_id = uuid4()
    receipt = owner.run(source,plan,run_id=run_id)
    assert receipt.correct_case_results==(True,True,True)
    assert receipt.counterexample_case_results==(False,False,False)
    assert receipt.scorer_outcomes==("passed","failed") and owner.verify(receipt,source)
    assert owner.run(source,plan,run_id=run_id)==receipt and len(runner.records)==2
    changed = receipt.model_copy(update={"correct_case_results":(False,False,False)})
    assert not owner.verify(changed,source)


def test_synthetic_unsealed_and_infrastructure_are_pending_not_wrong_answer_proof():
    source = source_fixture()
    plan = build_task_ambiguity_plan(source)
    for runner in (ProtocolStub(mode="synthetic"),ProtocolStub(seal=False),ProtocolStub(infrastructure=True)):
        owner = TaskAmbiguityOwner(runner,parent_deadline_at=NOW+timedelta(seconds=20),clock=lambda:NOW)
        with pytest.raises(AdmissionFactsPending):
            owner.run(source,plan,run_id=uuid4())


def test_complete_two_call_bound_before_io():
    source = source_fixture()
    plan = build_task_ambiguity_plan(source)
    runner = ProtocolStub()
    owner = TaskAmbiguityOwner(runner,parent_deadline_at=NOW+timedelta(seconds=19),clock=lambda:NOW)
    resources = owner.resource_plan(plan)
    assert resources.execution_seconds==20 and resources.requests==0
    with pytest.raises(AdmissionFactsPending,match="full_execution_bound_missing"):
        owner.run(source,plan,run_id=uuid4())
    assert runner.records==[]


def test_unspecified_task_and_python_stdout_assignment_keep_gap():
    with pytest.raises(AdmissionFactsPending,match="task_semantics_not_explicit"):
        build_task_ambiguity_plan(source_fixture(explicit=False))
    payload = source_fixture().model_dump(mode="json")
    payload["blueprint"].update(item_kind="code",purpose="exercise",language_id="python",
        runtime_profile_id="python_stdout_test",required_capabilities=["python.assignment"],allowed_interactions=["edit","run"])
    payload["public"].update(kind="code",purpose="exercise",allowed_interactions=["edit","run"])
    payload["public"]["content"] = {"type":"code","language_id":"python","editor_language":"python",
        "exercise_type":"code_completion","starter_code":"print(0)","code_blanks":[{
        "blank_key":"total","expected_concept":"assignment","acceptable_patterns":[{"type":"literal","value":"5"}],"is_core":True}]}
    payload["private"].update(kind="code")
    payload["private"]["content"] = {"type":"code","standard_answer":"print(5)","tests":[{
        "id":name,"case_type":visibility,"expected_output_json":{"stdout":"5"},"order_index":index}
        for index,(name,visibility) in enumerate((("visible","visible"),("hidden","hidden")))],
        "score_policy":{"kind":"all_tests","policy_version":"all_tests_v1","threshold":1.0}}
    with pytest.raises(AdmissionFactsPending,match="python_assignment_goal_unproven"):
        build_task_ambiguity_plan(LearningItemSourceV1.model_validate(payload))


def test_default_off_issuer_zero_queries_and_typed_private_schema():
    from app.services.learning.item_supply.pipeline import _require_explicit_sql_review_execution
    from app.services.learning.item_supply.pipeline_repository import PipelineRepositoryError
    from app.services.learning.item_supply.policies import ResourceAmounts

    class Conn:
        autocommit=False
        info=SimpleNamespace(transaction_status=2)
        def execute(self,*args):
            pytest.fail("disabled facts issuer queried DB")
    owner = AdmissionFactsOwner(Conn(),rag_authority=None,execution_owner=None,ambiguity_owner=None)
    with pytest.raises(AdmissionFactsPending,match="gate_closed"):
        owner._transaction()
    sql = (SCHEMA_DIRECTORY/"481_learning_item_supply_admission_facts.sql").read_text(encoding="utf-8")
    assert SCHEMA_FRAGMENT_NAMES[-1]=="481_learning_item_supply_admission_facts.sql"
    assert "ON DELETE CASCADE" in sql and "enforce_item_supply_private_epoch()" in sql
    assert "enforce_item_supply_immutable('private')" in sql and "control.lease_owner<>NEW.lease_owner" in sql
    assert "issued_admission_facts_v1" in sql and "publication_enabled=false" in sql
    pipeline = (Path(__file__).parents[2]/"app/services/learning/item_supply/pipeline.py").read_text(encoding="utf-8")
    assert "facts_owner.verify(facts_receipt, prepared, lease=lease, completed_review=completed)" in pipeline
    explicit = source_fixture()
    with pytest.raises(PipelineRepositoryError,match="REVIEW_EXECUTION_RESOURCE_PLAN_INCOMPLETE"):
        _require_explicit_sql_review_execution(explicit,ResourceAmounts(execution_seconds=29),mode="live")
    _require_explicit_sql_review_execution(explicit,ResourceAmounts(execution_seconds=30),mode="live")
    _require_explicit_sql_review_execution(source_fixture(explicit=False),ResourceAmounts(),mode="live")
    _require_explicit_sql_review_execution(explicit,ResourceAmounts(),mode="synthetic")
    assert pipeline.index("_require_explicit_sql_review_execution(source, resources, mode=mode)") < pipeline.index(
        'reservation = self.budget.reserve(lease=lease, reservation_key=f"review.')
