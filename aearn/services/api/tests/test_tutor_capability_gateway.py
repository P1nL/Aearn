from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.agents.harness.catalog_context import CatalogContextLoader
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorContextInput,
    TutorContextSource,
    TutorDecision,
    TutorDecisionGateStatus,
    TutorEffectProposal,
    TutorEffectStatus,
    TutorPolicySnapshot,
    TutorProviderResult,
    TutorRunSnapshot,
    TutorRunStatus,
    TutorSkillReference,
    TutorTerminalOutcome,
    payload_fields_from_mapping,
)
from app.agents.harness.skill_catalog import (
    PublishedSkill,
    SkillCatalogSnapshot,
    compile_published_skill_catalog,
)
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from app.services.tutor.capability_policy import CapabilityPolicyContext, InMemoryCapabilityPolicyResolver
from app.services.tutor.decision_gate import CatalogTutorDecisionGate
from app.services.tutor.grounding_lookup import InMemoryGroundingLookup
from app.services.tutor.ports import (
    DefaultDenyEffectCommitter,
    FixedClock,
    InMemoryTutorCompactionPublisher,
    InMemoryTutorContextLoader,
    InMemoryTutorRunStore,
    RecordingEffectCommitter,
    SequenceTutorProvider,
)
from app.services.tutor.run_loop import TutorRunLoop
from app.services.tutor.skill_selection import InMemoryTutorSkillSelectionStore, TutorSkillSelection


NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _run(*, max_capability_calls: int = 1) -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="catalog-run",
        conversation_id="catalog-conversation",
        user_id="catalog-user",
        origin="interactive",
        input_revision=0,
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC),
            max_iterations=3,
            max_model_calls=3,
            max_capability_calls=max_capability_calls,
            max_effects=1,
            context_token_budget=1200,
        ),
    )


def _context() -> TutorContextInput:
    return TutorContextInput(
        run_id="catalog-run",
        conversation_id="catalog-conversation",
        input_revision=0,
        current_input_required=True,
        current_input=TutorContextSource("message-current", "Please explain this capability."),
        system_descriptors=(TutorContextSource("base-system", {"policy": "bounded"}),),
        capability_schemas=(TutorContextSource("legacy-capability", {"name": "never-expose"}),),
    )


def _registry_skill(catalog):
    return next(skill for skill in catalog.skills if skill.reference.key == "tutor.registry-grounding@1.0.0")


def _policy(catalog, run: TutorRunSnapshot, *, runtime_available: bool = True) -> CapabilityPolicyContext:
    return CapabilityPolicyContext(
        run_id=run.run_id,
        user_id=run.user_id,
        origin=run.origin,
        input_revision=run.input_revision,
        catalog_digest=catalog.digest,
        eligible_skill_references=(_registry_skill(catalog).reference,),
        eligible_capability_ids=("grounding.retrieve",),
        granted_policy_tags=("registry-grounding",),
        allowed_origins=("interactive",),
        consent_granted=True,
        runtime_available_capability_ids=(("grounding.retrieve",) if runtime_available else ()),
        remaining_capability_budget=1,
        allowed_source_ids=("python-tutorial",),
    )


def _request(*, extra: dict[str, object] | None = None) -> TutorCapabilityRequest:
    arguments: dict[str, object] = {
        "language_id_or_alias": "python",
        "query_text": "What does a function return?",
        "topic_tags": ["functions"],
        "top_k": 1,
    }
    if extra:
        arguments.update(extra)
    return TutorCapabilityRequest(
        request_id="retrieve-1",
        capability_id="grounding.retrieve",
        arguments=payload_fields_from_mapping(arguments),
    )


def _select(store: InMemoryTutorSkillSelectionStore, catalog, run: TutorRunSnapshot) -> None:
    skill = _registry_skill(catalog)
    store.record(
        run_id=run.run_id,
        input_revision=run.input_revision,
        selection=TutorSkillSelection(
            reference=skill.reference,
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )


def test_catalog_context_loader_exposes_only_policy_eligible_summaries_schema_and_selected_instruction() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    policy_resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    store = InMemoryTutorSkillSelectionStore()
    base_loader = InMemoryTutorContextLoader({(run.run_id, 0): _context()})
    loader = CatalogContextLoader(
        base_loader=base_loader,
        catalog=catalog,
        policy_resolver=policy_resolver,
        selection_store=store,
    )

    before_selection = loader.load_context(run, input_revision=0)
    before_json = json.dumps([source.content for source in before_selection.system_descriptors])
    assert "tutor.registry-grounding" in before_json
    assert "instruction" not in before_json
    assert [source.source_id for source in before_selection.capability_schemas] == [
        "catalog:capability:grounding.retrieve@1.0.0"
    ]
    assert "never-expose" not in json.dumps([source.content for source in before_selection.capability_schemas])

    _select(store, catalog, run)
    after_selection = loader.load_context(run, input_revision=0)
    after_json = json.dumps([source.content for source in after_selection.system_descriptors])
    assert "Registry grounding" in after_json
    assert "tutor.registry-grounding" in after_json
    assert "eligible-skills" not in json.dumps([source.source_id for source in after_selection.system_descriptors])


def test_catalog_gate_denies_unversioned_unknown_mixed_and_effect_decisions() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    store = InMemoryTutorSkillSelectionStore()
    gate = CatalogTutorDecisionGate(catalog=catalog, policy_resolver=resolver, selection_store=store)

    unversioned = gate.validate(
        run=run,
        decision=TutorDecision(skill_references=(TutorSkillReference("tutor.registry-grounding", "current"),)),
    )
    unknown = gate.validate(
        run=run,
        decision=TutorDecision(skill_references=(TutorSkillReference("tutor.unknown", "1.0.0"),)),
    )
    mixed = gate.validate(
        run=run,
        decision=TutorDecision(
            skill_references=(TutorSkillReference("tutor.registry-grounding", "1.0.0"),),
            capability_requests=(_request(),),
        ),
    )

    assert unversioned.status is TutorDecisionGateStatus.DENIED
    assert unversioned.diagnostic_code == "skill_version_invalid"
    assert unknown.diagnostic_code == "unknown_skill_reference"
    assert mixed.diagnostic_code == "mixed_skill_selection_action"
    assert store.records == []

    selected = gate.validate(
        run=run,
        decision=TutorDecision(skill_references=(TutorSkillReference("tutor.registry-grounding", "1.0.0"),)),
    )
    assert selected.status is TutorDecisionGateStatus.REBUILD_CONTEXT
    assert len(store.records) == 1

    extra_field = gate.validate(
        run=run,
        decision=TutorDecision(capability_requests=(_request(extra={"user_id": "other-user"}),)),
    )
    effect = gate.validate(
        run=run,
        decision=TutorDecision(effect_proposals=(TutorEffectProposal("effect-1", "note.write", 0),)),
    )
    assert extra_field.diagnostic_code == "capability_arguments_invalid"
    assert effect.diagnostic_code == "unknown_effect_type"


def test_catalog_gate_denies_ambiguous_action_skill_inference() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    registry_skill = _registry_skill(catalog)
    alternate_skill = PublishedSkill(
        manifest=registry_skill.manifest.model_copy(
            update={"id": "tutor.registry-grounding-alternate"}
        ),
        instruction=registry_skill.instruction,
        instruction_hash=registry_skill.instruction_hash,
        evaluation_hash=registry_skill.evaluation_hash,
        manifest_hash="a" * 64,
    )
    ambiguous_catalog = SkillCatalogSnapshot(
        skills=(*catalog.skills, alternate_skill),
        capability_descriptors=catalog.capability_descriptors,
        effect_descriptors=catalog.effect_descriptors,
        digest="b" * 64,
    )
    policy = replace(
        _policy(ambiguous_catalog, run),
        eligible_skill_references=(registry_skill.reference, alternate_skill.reference),
    )
    store = InMemoryTutorSkillSelectionStore()
    gate = CatalogTutorDecisionGate(
        catalog=ambiguous_catalog,
        policy_resolver=InMemoryCapabilityPolicyResolver([policy]),
        selection_store=store,
    )

    result = gate.validate(
        run=run,
        decision=TutorDecision(capability_requests=(_request(),)),
    )

    assert result.status is TutorDecisionGateStatus.DENIED
    assert result.diagnostic_code == "action_skill_ambiguous"
    assert store.records == []


def test_unique_action_skill_rebuilds_context_before_grounding_dispatch_and_effect_never_commits() -> None:
    catalog = compile_published_skill_catalog()
    run = _run()
    store = InMemoryTutorRunStore([run])
    selection_store = InMemoryTutorSkillSelectionStore()
    resolver = InMemoryCapabilityPolicyResolver([_policy(catalog, run)])
    provider = SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    capability_requests=(_request(),),
                )
            ),
            TutorProviderResult(
                decision=TutorDecision(
                    capability_requests=(_request(),),
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            ),
        ]
    )
    base_loader = InMemoryTutorContextLoader({(run.run_id, 0): _context()})
    context_loader = CatalogContextLoader(
        base_loader=base_loader,
        catalog=catalog,
        policy_resolver=resolver,
        selection_store=selection_store,
    )
    lookup = InMemoryGroundingLookup()
    loop = TutorRunLoop(
        store=store,
        context_loader=context_loader,
        context_builder=TutorContextBuilder(),
        provider=provider,
        capability_gateway=CatalogCapabilityGateway(
            catalog=catalog,
            policy_resolver=resolver,
            selection_store=selection_store,
            grounding_lookup=lookup,
        ),
        effect_committer=DefaultDenyEffectCommitter(),
        clock=FixedClock(NOW),
        compaction_publisher=InMemoryTutorCompactionPublisher(),
        decision_gate=CatalogTutorDecisionGate(
            catalog=catalog,
            policy_resolver=resolver,
            selection_store=selection_store,
        ),
    )

    result = loop.run(run_id=run.run_id, lease_owner_id="worker-1")

    assert result.status is TutorRunStatus.COMPLETED
    assert result.model_call_count == 2
    assert len(selection_store.records) == 1
    assert selection_store.records[0][2].reference == _registry_skill(catalog).reference
    assert len(lookup.calls) == 1
    first_context = json.dumps(provider.calls[0][1].as_prompt_context())
    second_context = json.dumps(provider.calls[1][1].as_prompt_context())
    assert "eligible-skills" in first_context
    assert "Registry grounding" in second_context

    selected_store = InMemoryTutorRunStore([run])
    committer = RecordingEffectCommitter(status=TutorEffectStatus.COMMITTED)
    effect_loop = TutorRunLoop(
        store=selected_store,
        context_loader=context_loader,
        context_builder=TutorContextBuilder(),
        provider=SequenceTutorProvider(
            [
                TutorProviderResult(
                    decision=TutorDecision(
                        effect_proposals=(TutorEffectProposal("effect-2", "note.write", 0),),
                    )
                )
            ]
        ),
        capability_gateway=CatalogCapabilityGateway(
            catalog=catalog,
            policy_resolver=resolver,
            selection_store=selection_store,
            grounding_lookup=lookup,
        ),
        effect_committer=committer,
        clock=FixedClock(NOW),
        compaction_publisher=InMemoryTutorCompactionPublisher(),
        decision_gate=CatalogTutorDecisionGate(
            catalog=catalog,
            policy_resolver=resolver,
            selection_store=selection_store,
        ),
    )

    effect_result = effect_loop.run(run_id=run.run_id, lease_owner_id="worker-2")
    assert effect_result.status is TutorRunStatus.BLOCKED_POLICY
    assert effect_result.diagnostic_code == "unknown_effect_type"
    assert committer.calls == []


def test_catalog_and_tutor_source_never_import_retired_or_unbounded_execution_surfaces() -> None:
    api_root = Path(__file__).resolve().parents[1]
    files = [
        *sorted((api_root / "app" / "agents" / "harness").glob("*.py")),
        *sorted((api_root / "app" / "services" / "tutor").glob("*.py")),
    ]
    retired_agent_packages = (
        "graphs",
        "learning",
        "notes",
        "onboarding",
        "review",
        "runtime",
        "tooling",
    )
    retired_source_paths = tuple(
        api_root / "app" / "agents" / package_name / "__init__.py"
        for package_name in retired_agent_packages
    )
    assert all(not path.exists() for path in retired_source_paths), retired_source_paths

    retired_module_prefixes = tuple(
        ".".join(("app", "agents", package_name)) for package_name in retired_agent_packages
    )
    forbidden = (
        "app.db",
        "psycopg",
        "grounding_index_repository",
        "app.services.runners",
        "subprocess",
    )

    for path in files:
        source = path.read_text(encoding="utf-8")
        forbidden_for_path = forbidden
        if path.name in {"persistence.py", "proactive_repository.py", "learner_state.py", "action_adapters.py", "action_persistence.py"}:
            # Child 02 owns durable replay and Child 04 owns scheduler queue
            # leases. Keep the SQL exception narrow while retaining every
            # execution, legacy, route, and unbounded-runtime boundary.
            forbidden_for_path = tuple(marker for marker in forbidden if marker not in {"app.db", "psycopg"})
        if path.name == "execution.py":
            # Child 03 owns the target SQL intent/job repository and may adapt
            # the immutable runner result dataclass only. It must not import a
            # runner implementation or launch a host path.
            forbidden_for_path = tuple(marker for marker in forbidden if marker not in {"psycopg"})
            source = source.replace("app.services.runners.runtime_contracts", "")
        if path.name == "proactive_worker.py":
            # Child 04 uses a bounded API-side worker adapter only; routes and
            # legacy Graph/runner surfaces remain forbidden.
            forbidden_for_path = tuple(marker for marker in forbidden_for_path if marker != "app.db")
        if path.name in {"cutover.py", "interactive.py", "public_api.py"}:
            # Children 06/07 own these database-backed target adapters. They may
            # open target connections, but they must remain independent from
            # Graph/router/tool/runner implementation paths.
            forbidden_for_path = tuple(marker for marker in forbidden if marker not in {"app.db", "psycopg"})
        assert not any(marker in source for marker in retired_module_prefixes), path
        assert not any(marker in source for marker in forbidden_for_path), path
