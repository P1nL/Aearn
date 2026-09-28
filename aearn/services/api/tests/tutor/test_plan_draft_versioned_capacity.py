"""Versioned plan wire -> selected catalog -> existing owner, without DB/network."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.harness.actions import default_action_descriptors
from app.agents.harness.capabilities import (
    LearningPlanDraftCapabilityInput, LearningPlanDraftCapabilityInputV110,
    LearningPlanDraftCapabilityOutput,
)
from app.agents.harness.catalog_context import CatalogContextLoader
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCapabilityStatus, TutorContextInput, TutorContextSource, TutorLease, payload_mapping_from_fields,
)
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.material_selection import parent_snapshot_sources
from app.services.learning.plan_drafting import decode_plan_draft
from app.services.tutor.action_adapters import ControlledCapabilityGateway
from app.services.tutor.action_runtime import InMemoryActionFence, InMemoryActionReceiptStore, SchemaActionVerifier
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from app.services.tutor.capability_policy import CapabilityPolicyContext, InMemoryCapabilityPolicyResolver
from app.services.tutor.ports import FixedClock, InMemoryTutorContextLoader
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.services.tutor.skill_selection import InMemoryTutorSkillSelectionStore, TutorSkillSelection
from tests.tutor.test_plan_draft_semantic_repair import _Client, _repair_run
from tests.tutor.test_tutor_plan_wire_contract import _arguments, _candidate, _valid_parts


def _setup(version):
    catalog = compile_published_skill_catalog()
    run = _repair_run()
    run = replace(run, lease=TutorLease(run.run_id, "worker", datetime(2030, 1, 1, tzinfo=UTC)))
    skill = catalog.resolve_skill("tutor.learning-plan-draft", version)
    assert skill is not None
    selections = InMemoryTutorSkillSelectionStore()
    selections.record(run_id=run.run_id, input_revision=run.input_revision, selection=TutorSkillSelection(
        reference=skill.reference, manifest_hash=skill.manifest_hash, instruction_hash=skill.instruction_hash,
    ))
    policies = InMemoryCapabilityPolicyResolver((CapabilityPolicyContext(
        run_id=run.run_id, user_id=run.user_id, origin=run.origin, input_revision=run.input_revision,
        catalog_digest=catalog.digest, eligible_skill_references=(skill.reference,),
        eligible_capability_ids=("learning.plan.draft",), granted_policy_tags=("plan-drafting",),
        allowed_origins=("interactive",), consent_granted=True,
        runtime_available_capability_ids=("learning.plan.draft",), remaining_capability_budget=1,
    ),))
    base = TutorContextInput(run_id=run.run_id, conversation_id=run.conversation_id,
        input_revision=run.input_revision, current_input_required=True,
        current_input=TutorContextSource("input", "Revise the complete plan without changing its goals."))
    loaded = CatalogContextLoader(base_loader=InMemoryTutorContextLoader({(run.run_id, run.input_revision): base}),
        catalog=catalog, policy_resolver=policies, selection_store=selections).load_context(
            run, input_revision=run.input_revision)
    context = TutorContextBuilder().build(loaded, token_budget=20_000)
    return run, context, catalog, policies, selections


def _parts(size=602):
    profile, first, second = (json.loads(value) for value in _valid_parts())
    profile["teaching_preferences"] = ["a" * 80, "b" * 80]
    if size == 1024:
        profile["teaching_preferences"].append("c" * 7)
    for key, maximum in (("title", 240), ("goal_text", 200), ("pace_summary", 240)):
        remaining = size - len(json.dumps(profile, ensure_ascii=False, separators=(",", ":")))
        profile[key] += "x" * min(remaining, maximum - len(profile[key]))
    if size == 1024:
        for obj, key, maximum in ((first["nodes"][0], "description", 300), (first["nodes"][0], "title", 120),
                                  (first, "description", 300), (first, "title", 120)):
            remaining = size - len(json.dumps(first, ensure_ascii=False, separators=(",", ":")))
            obj[key] += "x" * min(remaining, maximum - len(obj[key]))
    result = tuple(json.dumps(value, ensure_ascii=False, separators=(",", ":")) for value in (profile, first, second))
    assert len(result[0]) == size
    return result


def _ask(run, context, parts, reviewer=None):
    client = _Client([_candidate("learning.plan.draft", _arguments(parts)) for _ in range(2)])
    result = PrimaryTutorProviderGateway(settings=Settings(llm_type="disabled"), client=client,
                                        decision_validator=reviewer).decide(run=run, context=context)
    return result, client


def test_v110_selected_contract_reaches_existing_action_owner_and_legacy_stays_raw360():
    run, context, catalog, policies, selections = _setup("1.1.0")
    parts = _parts()
    result, _ = _ask(run, context, parts)
    assert result.decision is not None
    request = result.decision.capability_requests[0]
    assert request.capability_version == "1.1.0"
    assert payload_mapping_from_fields(request.arguments) == dict(zip(("profile_json", "module_1", "module_2"), parts))
    generated, recorded = [], []

    class Owner:
        def generate(self, *, run, capability_input):
            assert isinstance(capability_input, LearningPlanDraftCapabilityInputV110)
            generated.append(capability_input)
            decode_plan_draft(profile_json=capability_input.profile_json, module_json_values=capability_input.module_values(),
                              sources=(), change_reason="Offline version compatibility")
            return LearningPlanDraftCapabilityOutput(status="completed", draft_id="draft-v110", draft_version=2,
                                                     content_hash="a" * 64, quality_status="passed")

    class Recorder:
        def record_capability_invocation(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(invocation_id="capability-authority")

    gateway = ControlledCapabilityGateway(catalog=catalog, policy_resolver=policies, selection_store=selections,
        authority_gateway=CatalogCapabilityGateway(catalog=catalog, policy_resolver=policies,
            selection_store=selections, learning_plan_handler=Owner()), authority_recorder=Recorder(),
        receipt_store=InMemoryActionReceiptStore(), fence=InMemoryActionFence(),
        clock=FixedClock(datetime(2026, 9, 28, tzinfo=UTC)), policy_fingerprint_loader=lambda _: "b" * 64,
        verifier_factory=lambda _: SchemaActionVerifier())
    dispatched = gateway.dispatch(run=run, request=request)
    assert dispatched.status is TutorCapabilityStatus.COMPLETED
    assert len(generated) == len(recorded) == 1 and recorded[0]["capability_version"] == "1.1.0"
    legacy_run, legacy_context, *_ = _setup("1.0.3")
    refused, _ = _ask(legacy_run, legacy_context, parts)
    assert refused.decision is None and refused.safe_code == "TUTOR_PROVIDER_DECISION_INVALID_VALUE"
    assert catalog.capability("learning.plan.draft").input_model is LearningPlanDraftCapabilityInput
    legacy = catalog.resolve_skill("tutor.learning-plan-draft", "1.0.3")
    assert legacy.instruction_hash == "bed76a0844b626ca5d29e2b82d2274f145d0b450b9b19921fa6b9535eeacf379"
    assert legacy.evaluation_hash == "fa9d79081be1c1e128f1bd24c81865bf0017a6010e0ca4d732f2d88a01ec1525"


def test_v110_semantic_repair_keeps_1024_contract_and_runs_review_again():
    run, context, *_ = _setup("1.1.0")
    attempts = []

    def review(run, context, decision, attempt):
        requests = decision.capability_requests
        assert requests[0].capability_version == "1.1.0"
        LearningPlanDraftCapabilityInputV110.model_validate(payload_mapping_from_fields(requests[0].arguments))
        attempts.append(attempt)
        return "material_readiness_overclaim" if attempt == 1 else None

    result, client = _ask(run, context, _parts(), reviewer=review)
    assert result.decision is not None and attempts == [1, 2]
    assert "1024-character limit" in client.messages[1][-1]["content"]
    assert "360-character limit" not in client.messages[1][-1]["content"]
    # Provider data cannot select a larger contract without the exact selected Skill.
    no_skill = replace(context, items=tuple(item for item in context.items if not item.source_id.startswith("catalog:selected:")))
    rejected, _ = _ask(run, no_skill, _parts())
    assert rejected.decision is None


def test_v110_bound_domain_and_parent_context_keep_existing_limits():
    run, context, *_ = _setup("1.1.0")
    parts = _parts(1024)
    result, _ = _ask(run, context, parts)
    assert result.decision is not None
    fields = result.decision.capability_requests[0].arguments
    assert all(len(field.value) <= 6146 for field in fields)
    candidate = LearningPlanDraftCapabilityInputV110.model_validate(payload_mapping_from_fields(fields))
    artifact = decode_plan_draft(profile_json=candidate.profile_json, module_json_values=candidate.module_values(),
                                 sources=(), change_reason="Offline bounded parent")
    parent = {"profile_json": artifact.profile.model_dump(mode="json"), "plan_json": canonical_plan_payload(artifact.plan)}
    sources = parent_snapshot_sources(parent, "00000000-0000-0000-0000-000000000001")
    assert all(len(json.dumps(source.content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= 1200 for source in sources)
    longer = json.loads(parts[0])
    longer["pace_summary"] += "y"
    oversized, _ = _ask(run, context, (json.dumps(longer, ensure_ascii=False, separators=(",", ":")), *parts[1:]))
    assert oversized.decision is None
    invalid_domain = json.loads(parts[0])
    invalid_domain["weekly_minutes"] = 1
    with pytest.raises(ValidationError):
        decode_plan_draft(profile_json=json.dumps(invalid_domain), module_json_values=candidate.module_values(),
                          sources=(), change_reason="Reject invalid domain")
    old_action = next(item for item in default_action_descriptors() if item.action_id == "learning.plan.draft")
    assert old_action.version == "1.0.0" and old_action.resource_profile.max_input_bytes == 16_384
