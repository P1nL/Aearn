from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.agents.harness.context_budget import (
    TutorContextBudgetPlanner,
    build_tutor_context_budget_policy,
    resolve_tutor_provider_context_capability,
)
from app.agents.harness.context_builder import TutorContextBuilder, Utf8ByteTokenEstimator
from app.agents.harness.capabilities import CapabilitySchemaExporter, LEARNING_PLAN_DRAFT_DESCRIPTOR
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.agents.harness.contracts import (
    TutorContextBudgetMode,
    TutorContextBudgetPolicy,
    TutorContextError,
    TutorContextInput,
    TutorContextSection,
    TutorContextSource,
    TutorPolicySnapshot,
    TutorProviderContextCapability,
    TutorRunSnapshot,
)
from app.core.config import Settings
from app.services.llm.contracts import LLMUsage
from app.agents.harness.provider_request import TutorProviderRequestSerializer


def _capability(*, input_hard_limit: int = 9_000, maximum_dynamic_target: int = 4_000) -> TutorProviderContextCapability:
    return TutorProviderContextCapability(
        context_window_tokens=input_hard_limit + 1_000,
        max_output_reserve_tokens=1_000,
        protocol_reserve_tokens=32,
        safety_margin_tokens=64,
        maximum_dynamic_target_tokens=maximum_dynamic_target,
        capability_version="synthetic-capability-v1",
    )


def _policy(*, capability: TutorProviderContextCapability | None = None) -> TutorContextBudgetPolicy:
    return TutorContextBudgetPolicy(
        capability=capability or _capability(),
        mode_targets=(
            (TutorContextBudgetMode.COMPACT, 500),
            (TutorContextBudgetMode.NORMAL, 1_000),
            (TutorContextBudgetMode.COMPLEX, 2_000),
            (TutorContextBudgetMode.EXTENDED, 4_000),
        ),
        warning_ratio=0.8,
        critical_ratio=0.95,
        max_expansions=1,
        estimator_version="utf8_bytes_v1",
        policy_version="tutor_context_budget_v1",
    )


def _run(policy: TutorContextBudgetPolicy) -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="budget-run",
        conversation_id="budget-conversation",
        user_id="budget-user",
        input_revision=1,
        origin="interactive",
        policy=TutorPolicySnapshot(
            deadline=datetime(2030, 1, 1, tzinfo=UTC),
            context_token_budget=policy.capability.maximum_dynamic_target_tokens,
            context_budget_policy=policy,
        ),
    )


def _context(*, current: str = "Help me understand this function.", source_count: int = 0) -> TutorContextInput:
    return TutorContextInput(
        run_id="budget-run",
        conversation_id="budget-conversation",
        input_revision=1,
        current_input_required=True,
        current_input=TutorContextSource("message-current", current),
        system_descriptors=(TutorContextSource("system", {"policy": "bounded"}),),
        recent_messages=tuple(
            TutorContextSource(
                f"message-{index}",
                {"role": "user", "content": f"prior-{index}-" + ("x" * 180)},
            )
            for index in range(source_count)
        ),
        activity_facts=(TutorContextSource("activity", "a" * 1_000),),
        capability_schemas=(TutorContextSource("schema", {"name": "synthetic.schema", "description": "s" * 1_000}),),
    )


def test_capability_registry_uses_exact_deepseek_evidence_and_conservative_unknown_defaults() -> None:
    deepseek = Settings(llm_type="deepseek", deepseek_model="deepseek-flash")
    exact = resolve_tutor_provider_context_capability(deepseek)

    assert deepseek.tutor_deepseek_v4_flash_context_window_tokens == 1_000_000
    assert deepseek.tutor_deepseek_v4_flash_input_limit_tokens == 131_072
    assert exact.context_window_tokens == 192_512
    assert exact.max_output_reserve_tokens == 61_440
    assert exact.input_hard_limit == 131_072
    assert exact.maximum_dynamic_target_tokens == 130_688
    assert exact.capability_version == "deepseek-flash-responses-v2"

    unknown = resolve_tutor_provider_context_capability(
        Settings(llm_type="deepseek", deepseek_model="deepseek-flash-preview")
    )
    assert unknown.input_hard_limit == 4_096
    assert unknown.maximum_dynamic_target_tokens == 512
    assert unknown.capability_version == "configured-conservative-provider-v1"

    explicit = resolve_tutor_provider_context_capability(
        Settings(
            llm_type="disabled",
            tutor_default_context_window_tokens=100_000,
            tutor_default_output_reserve_tokens=10_000,
            tutor_context_max_dynamic_target_tokens=64_000,
        )
    )
    assert explicit.input_hard_limit == 90_000
    assert explicit.maximum_dynamic_target_tokens == 64_000


def test_settings_reject_context_reserves_that_leave_no_required_input_capacity() -> None:
    with pytest.raises(ValueError, match="leave positive required input capacity"):
        Settings(
            llm_type="disabled",
            tutor_default_context_window_tokens=1_500,
            tutor_default_output_reserve_tokens=1_200,
            tutor_context_protocol_reserve_tokens=200,
            tutor_context_safety_margin_tokens=100,
        )


@pytest.mark.parametrize(
    ("current", "source_count", "expected"),
    [
        ("short question", 0, TutorContextBudgetMode.COMPACT),
        ("x" * 500, 0, TutorContextBudgetMode.NORMAL),
        ("x" * 4_500, 0, TutorContextBudgetMode.COMPLEX),
        ("x" * 12_500, 0, TutorContextBudgetMode.EXTENDED),
    ],
)
def test_classifier_selects_deterministic_modes(
    current: str,
    source_count: int,
    expected: TutorContextBudgetMode,
) -> None:
    planner = TutorContextBudgetPlanner()
    signals = planner.classify_signals(_context(current=current, source_count=source_count))

    assert planner.classify_mode(signals) is expected
    assert planner.classify_mode(signals) is expected


def test_mode_targets_must_increase_by_mode() -> None:
    with pytest.raises(ValueError, match="increase by mode"):
        TutorContextBudgetPolicy(
            capability=_capability(),
            mode_targets=(
                (TutorContextBudgetMode.COMPACT, 500),
                (TutorContextBudgetMode.NORMAL, 400),
                (TutorContextBudgetMode.COMPLEX, 2_000),
                (TutorContextBudgetMode.EXTENDED, 4_000),
            ),
        )


def test_dynamic_high_water_uses_the_selected_mode_target_not_the_physical_window() -> None:
    policy = _policy()
    context_input = replace(
        _context(current="x" * 4_500, source_count=4),
        recent_messages=tuple(
            TutorContextSource(
                f"long-message-{index}",
                {"role": "user", "content": "r" * 1_000},
            )
            for index in range(4)
        ),
        active_plan=(TutorContextSource("plan", "p" * 1_000),),
        review_snapshot=(TutorContextSource("review", "v" * 1_000),),
        working_summary=(TutorContextSource("summary", "w" * 1_000),),
        learner_memory=tuple(
            TutorContextSource(f"memory-{index}", "m" * 1_000)
            for index in range(4)
        ),
    )
    selection = TutorContextBudgetPlanner().build_context(
        run=_run(policy),
        context_input=context_input,
        builder=TutorContextBuilder(),
    )

    assert selection.checkpoint_metadata.budget_mode is TutorContextBudgetMode.COMPLEX
    assert selection.checkpoint_metadata.warning_reached is True
    assert selection.high_water_compaction_request is not None


def test_planner_estimates_the_exact_serialized_request_and_keeps_cache_out_of_preflight() -> None:
    policy = _policy()
    run = _run(policy)
    planner = TutorContextBudgetPlanner()
    selection = planner.build_context(
        run=run,
        context_input=_context(source_count=4),
        builder=TutorContextBuilder(),
    )
    metadata = selection.checkpoint_metadata
    serialized = json.dumps(
        TutorProviderRequestSerializer().build_messages(run=run, context=selection),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    exact_estimate = (
        Utf8ByteTokenEstimator().estimate_tokens(serialized)
        + policy.capability.protocol_reserve_tokens
        + policy.capability.safety_margin_tokens
    )

    assert metadata.estimated_total_input_tokens == exact_estimate
    assert metadata.estimated_total_input_tokens <= policy.capability.input_hard_limit
    assert metadata.budget_mode is TutorContextBudgetMode.NORMAL
    assert metadata.estimator_version == "utf8_bytes_v1"
    assert metadata.capability_version == "synthetic-capability-v1"
    assert metadata.optional_token_budget == 1_000
    assert selection.current_input is not None


class _MetadataShrinkingSerializer(TutorProviderRequestSerializer):
    def build_messages(self, *, run, context):
        del run
        estimate = context.checkpoint_metadata.estimated_total_input_tokens
        content = "x" * 400 if estimate is None else "x"
        return [{"role": "system", "content": content}]


def test_fixed_point_estimate_never_drops_below_the_required_request_floor() -> None:
    policy = _policy()
    run = _run(policy)
    planner = TutorContextBudgetPlanner(serializer=_MetadataShrinkingSerializer())

    selection = planner.build_context(
        run=run,
        context_input=_context(source_count=1),
        builder=TutorContextBuilder(),
    )

    estimate = selection.checkpoint_metadata.estimated_total_input_tokens
    assert estimate is not None
    serialized = json.dumps(
        _MetadataShrinkingSerializer().build_messages(run=run, context=selection),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    exact_estimate = (
        Utf8ByteTokenEstimator().estimate_tokens(serialized)
        + policy.capability.protocol_reserve_tokens
        + policy.capability.safety_margin_tokens
    )
    assert estimate > exact_estimate


def test_tight_dynamic_budget_evicts_low_priority_optional_context_before_current_input() -> None:
    capability = _capability(input_hard_limit=2_500, maximum_dynamic_target=120)
    policy = _policy(capability=capability)
    selection = TutorContextBudgetPlanner().build_context(
        run=_run(policy),
        context_input=_context(source_count=4),
        builder=TutorContextBuilder(),
    )
    selected_sections = [item.section.value for item in selection.items]

    assert selection.current_input is not None
    assert selection.current_input.content == "Help me understand this function."
    assert "activity" not in selected_sections
    assert "capability_schemas" not in selected_sections
    assert sum(section.skipped_count for section in selection.checkpoint_metadata.sections) > 0


def test_required_serialized_request_overflow_fails_before_any_provider_boundary() -> None:
    capability = _capability(input_hard_limit=300, maximum_dynamic_target=100)
    policy = _policy(capability=capability)

    with pytest.raises(TutorContextError) as exc_info:
        TutorContextBudgetPlanner().build_context(
            run=_run(policy),
            context_input=_context(),
            builder=TutorContextBuilder(),
        )

    assert exc_info.value.safe_code == "TUTOR_CONTEXT_REQUIRED_OVERFLOW"


def test_required_request_exact_fit_and_one_token_below_are_distinct() -> None:
    # No optional sources: binary-search the actual serialized request boundary
    # instead of assuming a fixed prompt size. Required facts must stay intact.
    context_input = replace(
        _context(),
        required_facts=(TutorContextSource("required-a", {"fact": "bounded"}),),
        system_descriptors=(),
        activity_facts=(),
        capability_schemas=(),
    )
    planner = TutorContextBudgetPlanner()
    builder = TutorContextBuilder()

    def select(input_limit: int):
        policy = _policy(capability=_capability(
            input_hard_limit=input_limit, maximum_dynamic_target=100,
        ))
        run = _run(policy)
        return run, planner.build_context(run=run, context_input=context_input, builder=builder)

    lower, upper = 500, 4_096
    while lower < upper:
        middle = (lower + upper) // 2
        try:
            select(middle)
        except TutorContextError as error:
            assert error.safe_code == "TUTOR_CONTEXT_REQUIRED_OVERFLOW"
            lower = middle + 1
        else:
            upper = middle

    run, selection = select(lower)
    assert selection.checkpoint_metadata.required_fact_selected_count == 1
    assert selection.checkpoint_metadata.required_fact_missing_count == 0
    required_items = [
        item for item in selection.items
        if item.section is TutorContextSection.REQUIRED_FACTS
    ]
    assert len(required_items) == 1
    assert required_items[0].source_id == "required-a"
    assert json.loads(required_items[0].content) == {"fact": "bounded"}
    serialized = json.dumps(
        TutorProviderRequestSerializer().build_messages(run=run, context=selection),
        ensure_ascii=False, separators=(",", ":"),
    )
    exact = (Utf8ByteTokenEstimator().estimate_tokens(serialized)
             + run.policy.context_budget_policy.capability.protocol_reserve_tokens
             + run.policy.context_budget_policy.capability.safety_margin_tokens)
    assert exact == lower == selection.checkpoint_metadata.estimated_total_input_tokens
    with pytest.raises(TutorContextError) as exc_info:
        select(lower - 1)
    assert exc_info.value.safe_code == "TUTOR_CONTEXT_REQUIRED_OVERFLOW"


def test_calibration_uses_provider_input_as_physical_total_without_adding_cached_tokens_again() -> None:
    policy = build_tutor_context_budget_policy(
        Settings(llm_type="deepseek", deepseek_model="deepseek-flash")
    )
    planner = TutorContextBudgetPlanner()
    selection = planner.build_context(
        run=_run(policy),
        context_input=_context(source_count=2),
        builder=TutorContextBuilder(),
    )
    estimated = selection.checkpoint_metadata.estimated_total_input_tokens
    assert estimated is not None

    calibration = planner.calibrate(
        metadata=selection.checkpoint_metadata,
        usage=LLMUsage(
            input_tokens=estimated + 5,
            cached_input_tokens=max(0, estimated - 20),
            output_tokens=10,
            total_tokens=estimated + 15,
        ),
        safety_margin_tokens=policy.capability.safety_margin_tokens,
    )

    assert calibration.actual_input_tokens == estimated + 5
    assert calibration.cached_input_tokens == max(0, estimated - 20)
    assert calibration.absolute_error_tokens == 5
    assert calibration.within_safety_margin is True


def _published_planning_context() -> tuple[TutorContextInput, str, dict[str, object]]:
    skill = compile_published_skill_catalog().resolve_skill("tutor.learning-plan-draft", "1.0.3")
    assert skill is not None
    instruction = skill.instruction
    schema = CapabilitySchemaExporter.export(LEARNING_PLAN_DRAFT_DESCRIPTOR)
    facts = tuple(
        TutorContextSource(f"fact:{key}", {"kind": "planning_fact", "key": key, "value": value})
        for key, value in (
            ("language_id", "python"), ("goal_text", "learn Python"),
            ("weekly_minutes", 180), ("experience_level", "beginner"),
            ("parent_profile", "current parent profile"),
            ("parent_plan", "current parent plan"),
            ("material_feedback", "partial source coverage; preserve core goals"),
        )
    )
    return replace(
        _context(),
        required_facts=facts,
        system_descriptors=(TutorContextSource(
            f"catalog:selected:{skill.reference.key}",
            {"id": skill.manifest.id, "version": skill.manifest.version,
             "manifest_hash": skill.manifest_hash, "instruction_hash": skill.instruction_hash,
             "instruction": instruction},
        ),),
        capability_schemas=(TutorContextSource("catalog:capability:learning.plan.draft", schema),),
    ), instruction, schema


def test_published_planning_skill_and_real_exported_schema_fit_formal_profile_intact() -> None:
    context, instruction, schema = _published_planning_context()
    settings = Settings(llm_type="deepseek", deepseek_model="deepseek-flash")
    policy = build_tutor_context_budget_policy(settings)
    assert settings.tutor_decision_max_output_tokens == 16_384
    assert policy.capability.input_hard_limit == 131_072
    selection = TutorContextBudgetPlanner().build_context(
        run=_run(policy), context_input=context, builder=TutorContextBuilder(),
    )
    skill_items = [item for item in selection.items if item.source_id.startswith("catalog:selected:")]
    schema_items = [item for item in selection.items if item.section is TutorContextSection.CAPABILITY_SCHEMAS]
    assert len(skill_items) == len(schema_items) == 1
    assert json.loads(skill_items[0].content)["instruction"] == instruction
    assert "never use `continuation_kind=approval`" in skill_items[0].content
    assert "every `value` is a JSON string" in skill_items[0].content
    assert json.loads(schema_items[0].content) == schema
    wire = TutorProviderRequestSerializer().build_messages(run=_run(policy), context=selection)
    sent_items = json.loads(wire[1]["content"])["context"]
    assert json.loads(next(item["content"] for item in sent_items if item["source_id"] == skill_items[0].source_id))["instruction"] == instruction
    assert json.loads(next(item["content"] for item in sent_items if item["source_id"] == schema_items[0].source_id)) == schema
    assert len([item for item in sent_items if item["section"] == TutorContextSection.REQUIRED_FACTS.value]) == 7
    assert len([item for item in selection.items if item.section is TutorContextSection.REQUIRED_FACTS]) == 7
    metadata = selection.checkpoint_metadata
    assert metadata.truncated_count == 0
    assert metadata.estimated_total_input_tokens is not None
    assert metadata.estimated_total_input_tokens <= policy.capability.input_hard_limit
    assert metadata.required_fact_missing_count == 0
    assert next(item for item in metadata.sections if item.section is TutorContextSection.SYSTEM).selected_count == 1
    assert next(item for item in metadata.sections if item.section is TutorContextSection.CAPABILITY_SCHEMAS).selected_count == 1


def test_published_planning_skill_tight_formal_limit_fails_before_any_partial_skill() -> None:
    context, _, _ = _published_planning_context()
    with pytest.raises(TutorContextError, match="TUTOR_SELECTED_SKILL_UNREPRESENTABLE"):
        TutorContextBudgetPlanner().build_context(
            run=_run(_policy(capability=_capability(input_hard_limit=500, maximum_dynamic_target=300))),
            context_input=context, builder=TutorContextBuilder(),
        )
