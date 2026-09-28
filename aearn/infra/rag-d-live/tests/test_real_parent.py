"""Explicit offline fakes for the opt-in real-parent driver and provenance guard."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare
import real_parent
import run
from parent_provenance import ParentProvenanceDenied, verify_parent_provenance
from app.agents.harness.contracts import TutorRunStatus, TutorTerminalOutcome


def outcome(*, failed=False):
    return SimpleNamespace(status=TutorRunStatus.FAILED if failed else TutorRunStatus.COMPLETED,
                           capability_call_count=0 if failed else 1,
                           terminal_outcome=TutorTerminalOutcome.FAILED if failed else TutorTerminalOutcome.COMPLETED)


def test_real_parent_is_double_opt_in_before_any_file_or_db(monkeypatch):
    monkeypatch.setattr(prepare, "_root_json", lambda *_: pytest.fail("file IO"))
    with pytest.raises(ValueError, match="DEFAULT_OFF"):
        prepare.prepare(execute=False, real_parent=True)
    with pytest.raises(ValueError, match="REAL_PARENT_OPT_IN_REQUIRED"):
        prepare.prepare(execute=True, control_config="/not/read", real_parent=True)
    with pytest.raises(ValueError, match="REAL_PARENT_OPT_IN_REQUIRED"):
        prepare.prepare(execute=True, control_config="/not/read", provider_config="/not/read")


def test_caller_real_label_without_provenance_denies_before_io():
    with pytest.raises(run.Denied, match="PARENT_PROVENANCE_REQUIRED"):
        run.run(SimpleNamespace(execute=True, parent_kind="real_provider", parent_provenance=None))


def test_driver_single_real_shape_result_is_not_manufactured():
    calls = []
    parent = {"id": "existing-persisted-draft"}
    def accept(**fields):
        calls.append(fields)
        return {"run_id": "one", "input_revision": 1}
    runs = []
    result = real_parent.drive_parent(accept=accept, dispatch=lambda **_: outcome(),
                                     find_draft=lambda _: parent, runs=runs)
    assert result is parent and len(calls) == 1
    assert calls[0]["planning_facts"] == real_parent.LEARNER_FACTS
    assert set(calls[0]) == {"content", "planning_facts"}
    assert "already understand basic tables" in calls[0]["content"]
    assert "exactly two modules" in calls[0]["content"]
    assert "sql.queries does not depend on the optional refresher" in calls[0]["content"]
    assert runs == [{"run_id": "one", "input_revision": 1}]


def test_driver_allows_one_declared_clarification_then_stops():
    calls = []
    def accept(**fields):
        calls.append(fields)
        return {"run_id": str(len(calls)), "input_revision": 1}
    with pytest.raises(run.Denied, match="PARENT_NOT_PERSISTED_AFTER_TWO_INPUTS"):
        real_parent.drive_parent(accept=accept, dispatch=lambda **_: outcome(), find_draft=lambda _: None, runs=[])
    assert len(calls) == 2
    assert calls[1]["planning_facts"] is real_parent.LEARNER_FACTS


def test_model_failure_does_not_spend_a_second_run():
    calls = []
    def accept(**fields):
        calls.append(fields)
        return {"run_id": "one", "input_revision": 1}
    with pytest.raises(run.Denied, match="PARENT_PROVIDER_STAGE_FAILED"):
        real_parent.drive_parent(accept=accept, dispatch=lambda **_: outcome(failed=True), find_draft=lambda _: None, runs=[])
    assert len(calls) == 1


def fixture_provenance():
    parent = {"id": "parent", "user_id": "user", "session_id": "session", "content_hash": "a" * 64,
              "source_run_id": "run", "source_input_revision": 1, "predecessor_draft_id": None, "draft_version": 1}
    receipt = {"id": "receipt", "run_id": "run", "input_revision": 1, "decision_iteration": 1,
               "attempt_index": 1, "provider_type": "deepseek", "model": "configured-model",
               "protocol": "deepseek_responses", "outcome": "accepted", "diagnostic_code": None,
               "input_tokens": 12, "output_tokens": 10, "reported_total_tokens": 22,
               "reasoning_tokens": None, "usage_available": True}
    audit = {"format": "rag_d_real_parent_v2", "status": "parent_persisted", "database_name": "db",
             "user_id": "user", "session_id": "session", "conversation_id": "conversation",
             "parent_draft_id": "parent", "parent_content_hash": "a" * 64, "source_run_id": "run",
             "source_input_revision": 1, "subject_id": "route.sql", "subject_version": "sqlite-docs-v1",
             "provider_type": "deepseek", "model": "configured-model", "model_http_attempts": 1,
             "client_calls": 1, "usage_per_call": [{"input_tokens": 12}], "response_models": ["configured-model"], "phase_http_cap": 4,
             "prior_http_attempts": 15, "cumulative_http_cap": 20, "profile": "formal",
             "runtime_profile": {"format": "rag_d_runtime_profile_v1", "effective": {"input": 131072}},
             "runs": [{"run_id": "run", "input_revision": 1}], "provider_receipts": [receipt]}
    conn = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchall=lambda: [receipt]))
    kwargs = dict(conn=conn, audit=audit, parent=parent, database_name="db", conversation_id="conversation",
                  subject_id="route.sql", subject_version="sqlite-docs-v1",
                  expected_runtime_profile=audit["runtime_profile"], profile="formal",
                  prior_http_attempts=15, cumulative_http_cap=20)
    return kwargs


def test_provenance_rechecks_exact_persisted_receipts():
    args = fixture_provenance()
    assert verify_parent_provenance(**args)["parent_http_attempts"] == 1
    args["conn"] = SimpleNamespace(execute=lambda *_: SimpleNamespace(fetchall=lambda: []))
    with pytest.raises(ParentProvenanceDenied, match="PARENT_PROVIDER_RECEIPTS_DENIED"):
        verify_parent_provenance(**args)


@pytest.mark.parametrize("field,value", [("model_http_attempts", 0), ("model_http_attempts", 9),
                                        ("parent_draft_id", "another"), ("subject_version", "v1"),
                                        ("client_calls", 0), ("cumulative_http_cap", 99)])
def test_bad_parent_proof_denied(field, value):
    args = fixture_provenance()
    args["audit"] = deepcopy(args["audit"])
    args["audit"][field] = value
    with pytest.raises(ParentProvenanceDenied):
        verify_parent_provenance(**args)


def illustrative_capability_input():
    """Offline schema example only, never substituted for a real provider draft."""
    profile = {**real_parent.LEARNER_FACTS,
        "pace_summary": "Four short sessions weekly, 240 minutes total.",
        "title": "SQLite WHERE and LIMIT"}
    profile.pop("pace_constraints")
    modules = [
        {"module_key": "sql-schema-refresher", "title": "Optional schema refresher",
         "is_core": False, "is_skippable": True, "nodes": [
             {"knowledge_key": "sql.schema", "title": "Recall existing tables and columns",
              "is_core": False, "prerequisite_keys": [], "required_capabilities": ["sql"]}]},
        {"module_key": "sql-queries", "title": "Query existing tables",
         "is_core": True, "is_skippable": False, "nodes": [
             {"knowledge_key": "sql.queries", "title": "SELECT WHERE and LIMIT",
              "is_core": True, "prerequisite_keys": [], "required_capabilities": ["sql"]}]},
    ]
    def compact(value):
        return json.dumps(value, separators=(",", ":"))
    return {"profile_json": compact(profile), "module_1": compact(modules[0]), "module_2": compact(modules[1])}


def test_two_module_fixture_parses_real_capability_and_draft_contract():
    from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
    from app.services.learning.plan_drafting import decode_plan_draft
    from app.services.grounding.material_contracts_v2 import DraftScope
    from uuid import uuid4

    fields = illustrative_capability_input()
    assert all(isinstance(value, str) and len(value) <= 360 for value in fields.values())
    parsed = LearningPlanDraftCapabilityInput.model_validate(fields)
    artifact = decode_plan_draft(profile_json=parsed.profile_json, module_json_values=parsed.module_values(),
                                 sources=(), change_reason="Initial synthetic learner plan")
    assert artifact.profile.goal_text == real_parent.LEARNER_FACTS["goal_text"]
    assert artifact.profile.weekly_minutes == 240
    assert [m.is_core for m in artifact.plan.modules] == [False, True]
    assert [m.is_skippable for m in artifact.plan.modules] == [True, False]
    assert {n.knowledge_key: n.prerequisite_keys for n in artifact.plan.nodes} == {
        "sql.schema": (), "sql.queries": ()}
    plan = {"modules": [{"is_core": m.is_core, "is_skippable": m.is_skippable,
                          "nodes": [{"knowledge_key": n.knowledge_key, "is_core": n.is_core,
                                     "prerequisite_keys": list(n.prerequisite_keys)} for n in m.nodes]}
                        for m in artifact.plan.modules]}
    nodes = real_parent.pilot_nodes(plan)
    scope = DraftScope(user_id=str(uuid4()), conversation_id=str(uuid4()), session_id=str(uuid4()),
                       draft_id=str(uuid4()), draft_version=1, content_hash="a" * 64,
                       source_run_id=str(uuid4()), source_input_revision=1)
    requirements = run.SqlRequirements("route.sql", "sqlite-docs-v1").resolve(
        scope, artifact.profile.model_dump(mode="json"), nodes)
    assert {(r.node_id, r.demand.purpose) for r in requirements} == {
        (key, purpose) for key in ("sql.schema", "sql.queries")
        for purpose in ("main_teaching", "supplementary_explanation")}


@pytest.mark.parametrize("mutate", [
    lambda plan: plan["modules"].pop(),
    lambda plan: plan["modules"][0].update(is_core=True),
    lambda plan: plan["modules"][0].update(is_skippable=False),
    lambda plan: plan["modules"][1]["nodes"][0].update(prerequisite_keys=["sql.schema"]),
    lambda plan: plan["modules"][1]["nodes"][0].update(knowledge_key="sql.admin"),
])
def test_invalid_pilot_shape_is_denied_not_repaired(mutate):
    fields = illustrative_capability_input()
    plan = {"modules": [json.loads(fields["module_1"]), json.loads(fields["module_2"])]}
    mutate(plan)
    before = deepcopy(plan)
    with pytest.raises(run.Denied, match="PARENT_PILOT_SHAPE_DENIED"):
        real_parent.pilot_nodes(plan)
    assert plan == before


def test_wall_signal_cannot_be_swallowed_by_provider_exception_repairs():
    assert issubclass(run.WallDeadlineExceeded, BaseException)
    assert not issubclass(run.WallDeadlineExceeded, Exception)


def test_provider_redirect_is_denied_without_hidden_extra_http(monkeypatch):
    import urllib.request
    old = urllib.request.HTTPRedirectHandler.redirect_request
    budget = run.SharedHttpBudget(SimpleNamespace(llm_base_url="https://example.invalid/v1"), 8)
    with budget.enforce(), pytest.raises(run.Denied, match="PROVIDER_REDIRECT_DENIED"):
        urllib.request.HTTPRedirectHandler().redirect_request(None, None, None, None, None, None)
    assert budget.count == 0
    assert urllib.request.HTTPRedirectHandler.redirect_request is old


def test_observed_model_alias_is_checked_against_db_not_assumed():
    args = fixture_provenance()
    args["audit"]["model"] = "configured-alias"
    assert verify_parent_provenance(**args)["parent_kind"] == "real_provider"
    args["audit"]["response_models"] = ["different-actual-model"]
    with pytest.raises(ParentProvenanceDenied, match="PARENT_PROVIDER_RECEIPTS_DENIED"):
        verify_parent_provenance(**args)

@pytest.mark.parametrize("profile", ("formal", "boundary-test"))
def test_selected_planning_capability_schema_fits_acceptance_budget(profile):
    from datetime import UTC, datetime
    from app.agents.harness.capabilities import CapabilitySchemaExporter, LEARNING_PLAN_DRAFT_DESCRIPTOR
    from app.agents.harness.context_budget import TutorContextBudgetPlanner, build_tutor_context_budget_policy
    from app.agents.harness.context_builder import TutorContextBuilder
    from app.agents.harness.contracts import (TutorContextInput, TutorContextSection, TutorContextSource,
                                              TutorPolicySnapshot, TutorRunSnapshot)
    from app.core.config import Settings
    reductions = ({"tutor_deepseek_v4_flash_context_window_tokens": 12288,
                   "tutor_deepseek_v4_flash_input_limit_tokens": 8192,
                   "tutor_deepseek_v4_flash_max_output_tokens": 4096,
                   "tutor_deepseek_v4_flash_decision_max_output_tokens": 4096,
                   "tutor_deepseek_v4_flash_max_dynamic_target_tokens": 2048}
                  if profile == "boundary-test" else {})
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-flash", **reductions)
    policy = build_tutor_context_budget_policy(settings)
    context = TutorContextInput(
        run_id="run", conversation_id="conversation", input_revision=1,
        current_input_required=True, current_input=TutorContextSource("current", real_parent.LEARNER_REQUEST),
        system_descriptors=(TutorContextSource("selected-skill", {"id": "tutor.learning-plan-draft",
            "version": "1.0.3", "instruction": "Use learning.plan.draft for this selected Skill."}),),
        required_facts=tuple(TutorContextSource(f"fact-{i}", {"fact": "SQL queries " + "x" * 80}) for i in range(7)),
        recent_messages=(TutorContextSource("prior", {"role": "user", "content": "y" * 320}),),
        capability_schemas=(TutorContextSource("catalog:capability:learning.plan.draft",
            CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR)),),
    )
    run_snapshot = TutorRunSnapshot(run_id="run", conversation_id="conversation", user_id="user",
        input_revision=1, origin="interactive", policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC), context_token_budget=settings.tutor_context_token_budget,
            context_budget_policy=policy))
    selected = TutorContextBudgetPlanner().build_context(
        run=run_snapshot, context_input=context, builder=TutorContextBuilder())
    schemas = [item for item in selected.items if item.section is TutorContextSection.CAPABILITY_SCHEMAS]
    assert len(schemas) == 1
    assert schemas[0].source_id == "catalog:capability:learning.plan.draft"
    schema_wire = __import__("json").loads(schemas[0].content)
    assert schema_wire == CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR)
    assert schema_wire["name"] == "learning.plan.draft"
    assert set(schema_wire["inputSchema"]["required"]) == {"profile_json", "module_1", "module_2"}
    assert all(schema_wire["inputSchema"]["properties"][field]["type"] == "string"
               and schema_wire["inputSchema"]["properties"][field]["maxLength"] == 360
               for field in ("profile_json", "module_1", "module_2"))
    from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
    assert LearningPlanDraftCapabilityInput.model_validate(illustrative_capability_input()).module_values()
    from app.agents.harness.provider_request import TutorProviderRequestSerializer
    from app.services.tutor.provider_request_budget import assert_tutor_provider_request_budget
    messages = TutorProviderRequestSerializer().build_messages(run=run_snapshot, context=selected)
    assert 'action.type=request_capability' in messages[0]['content']
    assert 'NEVER propose_effect or payload' in messages[0]['content']
    assert 'JSON-encoded STRINGS' in messages[0]['content']
    wire_items = __import__("json").loads(messages[1]["content"])["context"]
    assert next(item["content"] for item in wire_items if item["section"] == "capability_schemas") == schemas[0].content
    assert_tutor_provider_request_budget(messages, capability=policy.capability)
    assert selected.checkpoint_metadata.estimated_total_input_tokens < settings.deepseek_v4_flash_input_hard_limit_tokens
    assert selected.checkpoint_metadata.optional_token_budget <= settings.tutor_context_max_dynamic_target_capacity_tokens


def test_counted_client_preserves_gateway_thinking_and_call_cap():
    seen = []

    class Client:
        model = 'configured-real-provider-in-production'

        def complete_json(self, *args, **kwargs):
            seen.append(kwargs)
            return SimpleNamespace(model=self.model, usage=None)

    counted = run.CountedClient(Client(), 1)
    counted.complete_json([], thinking_mode=None)
    assert seen == [{'thinking_mode': None}]
    with pytest.raises(run.Denied, match='MODEL_HTTP_CAP'):
        counted.complete_json([])
    assert counted.count == 1 and len(seen) == 1


def test_reduced_parent_http_cap_is_audited_and_enforced():
    args = fixture_provenance()
    args["audit"]["phase_http_cap"] = 4
    assert verify_parent_provenance(**args)["parent_http_attempts"] == 1
    args["audit"]["model_http_attempts"] = 5
    with pytest.raises(ParentProvenanceDenied, match="PARENT_TRANSPORT_PROOF_MISSING"):
        verify_parent_provenance(**args)
    with pytest.raises(run.Denied, match="MODEL_BOUND_DENIED"):
        real_parent.prepare_real(config={}, settings=None, provenance_out="not-read", wall_seconds=240, max_http=9)


def test_old_failed_audit_cannot_be_promoted_to_v2_success():
    args = fixture_provenance()
    args["audit"]["format"] = "rag_d_real_parent_v1"
    with pytest.raises(ParentProvenanceDenied, match="PARENT_PROVENANCE_MISMATCH"):
        verify_parent_provenance(**args)
    args["audit"]["format"] = "rag_d_real_parent_v2"
    args["audit"]["status"] = "failed"
    with pytest.raises(ParentProvenanceDenied, match="PARENT_PROVENANCE_MISMATCH"):
        verify_parent_provenance(**args)


def test_cumulative_cap_does_not_reset_between_parent_and_successor():
    args = fixture_provenance()
    proof = verify_parent_provenance(**args)
    assert proof["prior_http_attempts"] == 16
    assert proof["cumulative_http_cap"] == 20
    args["audit"]["phase_http_cap"] = 6  # 15 + 6 exceeds approved 20 even if only one POST happened
    with pytest.raises(ParentProvenanceDenied, match="PARENT_TRANSPORT_PROOF_MISSING"):
        verify_parent_provenance(**args)
