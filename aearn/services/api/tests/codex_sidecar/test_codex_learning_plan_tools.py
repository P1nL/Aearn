from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from app.agents.runtime import (
    LearningPlanRuntimeToolRegistry,
    LearningPlanToolBudget,
    RuntimeToolCall,
)
from app.services.learning.plan_tools import (
    LEARNING_PLAN_DRAFT_TOOL_NAME,
    PLANNING_CONTEXT_TOOL_NAME,
    LearningPlanAgentToolResult,
    LearningPlanDraftToolInput,
    LearningPlanToolIssue,
    LearningPlanToolStatus,
    PlanningContextReadInput,
    PlanningDirectionAction,
)
from app.services.learning.planning_questions import (
    build_planning_question_model_descriptor,
)


@dataclass
class FakeService:
    read_result: LearningPlanAgentToolResult
    draft_result: LearningPlanAgentToolResult
    draft_calls: int = 0
    read_inputs: list[PlanningContextReadInput | None] = field(default_factory=list)

    def read_context(
        self,
        tool_input: PlanningContextReadInput | None = None,
    ) -> LearningPlanAgentToolResult:
        self.read_inputs.append(tool_input)
        if tool_input is None or tool_input.direction_action is None:
            return self.read_result
        action = tool_input.direction_action
        if (
            action is PlanningDirectionAction.ANSWER_AND_REFOCUS
            and self.read_result.status is LearningPlanToolStatus.COMPLETED
        ):
            return LearningPlanAgentToolResult(
                status=LearningPlanToolStatus.REPAIRABLE_INVALID,
                code="planning_direction_answer_refocus_not_applicable",
                issues=(
                    LearningPlanToolIssue(
                        path="direction_action",
                        code="facts_complete",
                        hint="Use continue_mainline for a completed planning context.",
                    ),
                ),
                data=self.read_result.data,
            )
        code = {
            PlanningDirectionAction.CONTINUE_MAINLINE: (
                "planning_direction_continue_ready"
                if self.read_result.status is LearningPlanToolStatus.COMPLETED
                else "planning_direction_continue_accepted"
            ),
            PlanningDirectionAction.ANSWER_AND_REFOCUS: (
                "planning_direction_answer_refocus_accepted"
            ),
            PlanningDirectionAction.CLARIFY_DIRECTION: (
                "planning_direction_clarification_accepted"
            ),
            PlanningDirectionAction.CONFIRMED_SWITCH: (
                "planning_direction_switch_accepted"
            ),
        }[action]
        status = self.read_result.status
        if action in {
            PlanningDirectionAction.CLARIFY_DIRECTION,
            PlanningDirectionAction.CONFIRMED_SWITCH,
        }:
            status = LearningPlanToolStatus.AWAITING_USER
        return LearningPlanAgentToolResult(
            status=status,
            code=code,
            data={
                **dict(self.read_result.data),
                "direction_resolution": {
                    "status": "accepted",
                    "action": action.value,
                },
            },
        )

    def draft(
        self,
        tool_input: LearningPlanDraftToolInput,
    ) -> LearningPlanAgentToolResult:
        assert len(tool_input.modules) >= 2
        self.draft_calls += 1
        return self.draft_result


def _result(
    status: LearningPlanToolStatus,
    code: str,
    *,
    data: dict[str, object] | None = None,
) -> LearningPlanAgentToolResult:
    return LearningPlanAgentToolResult(status=status, code=code, data=data or {})


def _call(tool_name: str, arguments: dict[str, object]) -> RuntimeToolCall:
    return RuntimeToolCall(
        thread_id="thread_safe",
        turn_id="turn_safe",
        call_id="call_safe",
        tool_name=tool_name,
        arguments=arguments,
    )


def _valid_modules() -> list[dict[str, object]]:
    return [
        {
            "stable_key": "foundations",
            "title": "Foundations",
            "nodes": [
                {
                    "stable_key": "python.variables",
                    "title": "Variables",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "stable_key": "automation",
            "title": "Automation",
            "nodes": [
                {
                    "stable_key": "python.files",
                    "title": "Files",
                    "prerequisites": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    ]


def _awaiting_data(field_key: str = "goal_text") -> dict[str, object]:
    data: dict[str, object] = {
        "missing_facts": [field_key],
        "next_missing_fact": build_planning_question_model_descriptor(field_key),
    }
    if field_key == "language_id":
        data["language_candidates"] = [{"language_id": "python"}]
    return data


def test_language_question_descriptor_prevents_natural_language_ambiguity() -> None:
    descriptor = build_planning_question_model_descriptor("language_id")

    assert descriptor["field_key"] == "language_id"
    assert descriptor["exact_question"] == "你想学习哪门编程语言？"
    assert "编程语言" in str(descriptor["meaning"])
    assert "自然语言" in str(descriptor["meaning"])
    assert "中文" not in str(descriptor)
    assert "英文" not in str(descriptor)
    assert "planning-intent-hint-v2" in str(descriptor["wording_policy"])
    assert "clarification" in str(descriptor["wording_policy"])
    assert "完整课程目录" in str(descriptor["wording_policy"])
    assert descriptor["response_authority"] == "aearn_typed_request"


def test_tool_definitions_expose_only_typed_modules_and_no_authority_fields() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    definitions = {
        definition.name: definition
        for definition in LearningPlanRuntimeToolRegistry(service).definitions
    }
    context_definition = definitions[PLANNING_CONTEXT_TOOL_NAME]
    assert context_definition.input_schema.get("type") == "object"
    assert "next_missing_fact" in context_definition.description
    assert "planning_intent_hint" in context_definition.description
    context_properties = context_definition.input_schema["properties"]
    assert "PlanningContextIntentHintV2" in json.dumps(
        context_properties["planning_intent_hint"]
    )
    assert "PlanningDirectionAction" in json.dumps(
        context_properties["direction_action"]
    )
    draft_schema = json.dumps(
        definitions[LEARNING_PLAN_DRAFT_TOOL_NAME].input_schema,
        ensure_ascii=False,
    )
    for forbidden in (
        "profile_json",
        "module_1",
        "user_id",
        "session_id",
        "run_id",
        "source",
        "confirm",
        "runtime_kind",
    ):
        assert forbidden not in draft_schema
    assert '"modules"' in draft_schema
    assert '"stable_key"' in draft_schema


def test_tool_schema_exposes_one_closed_direction_action_and_no_old_booleans() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    definitions = {definition.name: definition for definition in registry.definitions}
    assert set(definitions) == {
        PLANNING_CONTEXT_TOOL_NAME,
        LEARNING_PLAN_DRAFT_TOOL_NAME,
    }
    context_definition = definitions[PLANNING_CONTEXT_TOOL_NAME]
    encoded_context = json.dumps(context_definition.input_schema, ensure_ascii=False)
    assert "direction_action" in encoded_context
    for action in PlanningDirectionAction:
        assert action.value in encoded_context
    context_properties = context_definition.input_schema["properties"]
    assert "clarification_required" not in context_properties
    assert "confirmed_switch" not in context_properties
    assert "First call once" in context_definition.description
    assert "Then call exactly once" in context_definition.description
    draft_schema = json.dumps(
        definitions[LEARNING_PLAN_DRAFT_TOOL_NAME].input_schema,
        ensure_ascii=False,
    )
    for forbidden in (
        "profile_json",
        "module_1",
        "user_id",
        "session_id",
        "run_id",
        "source",
        "confirm",
        "runtime_kind",
    ):
        assert forbidden not in draft_schema
    assert '"modules"' in draft_schema
    assert '"stable_key"' in draft_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("action", list(PlanningDirectionAction))
async def test_initial_read_then_exactly_one_closed_action_records_accepted_marker(
    action: PlanningDirectionAction,
) -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    registry.prime_context()
    registry.configure_direction_intake()

    initial = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    resolved = await registry.invoke(
        _call(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": action.value})
    )

    assert initial.success is True
    assert resolved.success is True
    assert registry.planning_direction_action is action
    assert registry.planning_direction_result is not None
    assert registry.planning_direction_result.data["direction_resolution"] == {
        "status": "accepted",
        "action": action.value,
    }
    assert registry.call_count == 2


@pytest.mark.asyncio
async def test_language_hint_is_allowed_only_with_same_continue_action_after_read() -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data("language_id"),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    hint = {
        "schema_version": "planning-intent-hint-v2",
        "candidate_language_ids": ["python"],
        "confidence": "high",
        "reason_code": "technology_ecosystem_match",
    }
    accepted = await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline", "planning_intent_hint": hint},
        )
    )
    assert accepted.success is True
    assert registry.planning_direction_action is PlanningDirectionAction.CONTINUE_MAINLINE
    assert registry.planning_intent_hint == hint

    invalid = PlanningContextReadInput.model_validate
    with pytest.raises(ValueError):
        invalid(
            {
                "direction_action": "clarify_direction",
                "planning_intent_hint": hint,
            }
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("calls", "expected_code"),
    [
        (
            [(PLANNING_CONTEXT_TOOL_NAME, {"direction_action": "continue_mainline"})],
            "planning_direction_context_read_required",
        ),
        (
            [
                (PLANNING_CONTEXT_TOOL_NAME, {}),
                (PLANNING_CONTEXT_TOOL_NAME, {}),
            ],
            "planning_direction_context_read_duplicate",
        ),
        (
            [
                (PLANNING_CONTEXT_TOOL_NAME, {}),
                (
                    PLANNING_CONTEXT_TOOL_NAME,
                    {"clarification_required": True},
                ),
            ],
            "learning_plan_tool_input_invalid",
        ),
    ],
)
async def test_missing_or_invalid_direction_resolution_fails_closed(
    calls: list[tuple[str, dict[str, object]]],
    expected_code: str,
) -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    last = None
    for tool_name, arguments in calls:
        last = await registry.invoke(_call(tool_name, arguments))
    assert last is not None
    assert json.loads(last.content)["code"] == expected_code
    assert registry.planning_direction_action is None
    assert registry.direction_protocol_invalid is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_action", "expected_code"),
    [
        ("continue_mainline", "planning_direction_action_duplicate"),
        ("confirmed_switch", "planning_direction_action_conflict"),
    ],
)
async def test_duplicate_or_conflicting_action_invalidates_the_marker(
    second_action: str,
    expected_code: str,
) -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    duplicate = await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": second_action},
        )
    )
    assert duplicate.success is False
    assert json.loads(duplicate.content)["code"] == expected_code
    assert registry.planning_direction_action is None
    assert registry.direction_protocol_invalid is True


@pytest.mark.asyncio
async def test_draft_is_forbidden_without_marker_and_during_awaiting_user_intake() -> None:
    completed_service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    missing_marker = LearningPlanRuntimeToolRegistry(completed_service)
    denied = await missing_marker.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    assert denied.success is False
    assert json.loads(denied.content)["code"] == "planning_direction_action_required"
    assert completed_service.draft_calls == 0

    intake_service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    intake = LearningPlanRuntimeToolRegistry(intake_service)
    intake.prime_context()
    intake.configure_direction_intake()
    await intake.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await intake.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    denied_intake = await intake.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    assert denied_intake.success is False
    assert json.loads(denied_intake.content)["code"] == (
        "planning_direction_intake_draft_forbidden"
    )
    assert intake_service.draft_calls == 0


@pytest.mark.asyncio
async def test_completed_context_requires_continue_marker_before_draft() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(
            LearningPlanToolStatus.COMPLETED,
            "learning_plan_draft_completed",
            data={"draft_id": "draft-safe", "receipt": "b" * 64},
        ),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    drafted = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    assert drafted.success is True
    assert registry.draft_completed is True
    assert service.draft_calls == 1


@pytest.mark.asyncio
async def test_registry_repair_budget_is_bounded_and_never_echoes_raw_invalid_value() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    registry = LearningPlanRuntimeToolRegistry(
        service,
        budget=LearningPlanToolBudget(max_repairs=1),
    )
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    invalid: dict[str, object] = {
        "modules": _valid_modules()[:1],
        "profile_json": "raw-private-marker",
    }
    first = await registry.invoke(_call(LEARNING_PLAN_DRAFT_TOOL_NAME, invalid))
    second = await registry.invoke(_call(LEARNING_PLAN_DRAFT_TOOL_NAME, invalid))

    assert first.success is True
    assert json.loads(first.content)["status"] == "repairable_invalid"
    assert "raw-private-marker" not in first.content
    assert second.success is False
    assert json.loads(second.content)["code"] == "tool_repair_budget_exhausted"
    assert service.draft_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_success"),
    [
        (LearningPlanToolStatus.COMPLETED, True),
        (LearningPlanToolStatus.REPAIRABLE_INVALID, True),
        (LearningPlanToolStatus.AWAITING_USER, True),
        (LearningPlanToolStatus.CONFLICT, True),
        (LearningPlanToolStatus.POLICY_BLOCKED, False),
        (LearningPlanToolStatus.UNAVAILABLE, False),
        (LearningPlanToolStatus.FATAL, False),
    ],
)
async def test_registry_preserves_distinct_tool_statuses(
    status: LearningPlanToolStatus,
    expected_success: bool,
) -> None:
    service = FakeService(
        _result(status, f"safe_{status.value}"),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    result = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    assert result.success is expected_success
    assert json.loads(result.content)["status"] == status.value


@pytest.mark.asyncio
async def test_registry_rejects_unknown_fields_cycles_and_expired_wall_clock() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    unknown = await registry.invoke(
        _call(
            LEARNING_PLAN_DRAFT_TOOL_NAME,
            {"modules": _valid_modules(), "profile_json": "forbidden"},
        )
    )
    assert json.loads(unknown.content)["issues"][0]["code"] == "unknown_field"

    cyclic = _valid_modules()
    cyclic[0]["nodes"][0]["prerequisites"] = ["python.files"]  # type: ignore[index]
    invalid = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": cyclic})
    )
    assert json.loads(invalid.content)["issues"][0]["code"] == "prerequisite_cycle"

    assert LearningPlanToolBudget().max_wall_seconds == 300.0
    within_window_moments = iter((0.0, 299.0))
    within_window = LearningPlanRuntimeToolRegistry(
        service,
        clock=lambda: next(within_window_moments),
    )
    accepted = await within_window.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    assert accepted.success is True

    expired_moments = iter((0.0, 301.0))
    expired = LearningPlanRuntimeToolRegistry(
        service,
        clock=lambda: next(expired_moments),
    )
    timed_out = await expired.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    assert timed_out.success is False
    assert json.loads(timed_out.content)["code"] == "tool_deadline_exhausted"


@pytest.mark.asyncio
async def test_completed_duplicate_replay_returns_same_safe_receipt() -> None:
    completed = LearningPlanAgentToolResult(
        status=LearningPlanToolStatus.COMPLETED,
        code="learning_plan_draft_completed",
        data={
            "draft_id": "draft-safe",
            "draft_version": 1,
            "content_hash": "a" * 64,
            "receipt": "b" * 64,
        },
        replayed=True,
    )
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        completed,
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    first = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    second = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    assert first.content == second.content
    assert json.loads(first.content)["replayed"] is True
    assert service.draft_calls == 2


@pytest.mark.asyncio
async def test_registry_bounds_conflict_rebuilds_and_contains_service_exceptions() -> None:
    conflict_service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.CONFLICT, "planning_facts_stale"),
    )
    registry = LearningPlanRuntimeToolRegistry(conflict_service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    first = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    second = await registry.invoke(
        _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()})
    )
    assert json.loads(first.content)["status"] == "conflict"
    assert second.success is False
    assert json.loads(second.content)["code"] == "tool_conflict_budget_exhausted"

    class ExplodingService(FakeService):
        def read_context(
            self,
            tool_input: PlanningContextReadInput | None = None,
        ) -> LearningPlanAgentToolResult:
            if tool_input is not None:
                raise RuntimeError("raw-private-service-error")
            return super().read_context(tool_input)

    exploding = LearningPlanRuntimeToolRegistry(
        ExplodingService(
            _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
            _result(LearningPlanToolStatus.COMPLETED, "unused"),
        )
    )
    initial = await exploding.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    failed = await exploding.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    assert initial.success is True
    assert failed.success is False
    assert json.loads(failed.content)["code"] == "learning_plan_tool_failed"
    assert "raw-private-service-error" not in failed.content
    assert exploding.planning_direction_action is None


@pytest.mark.asyncio
async def test_output_budget_failure_clears_direction_and_draft_markers() -> None:
    class OversizedDirectionService(FakeService):
        def read_context(
            self,
            tool_input: PlanningContextReadInput | None = None,
        ) -> LearningPlanAgentToolResult:
            if tool_input is None or tool_input.direction_action is None:
                return self.read_result
            return LearningPlanAgentToolResult(
                status=LearningPlanToolStatus.AWAITING_USER,
                code="planning_direction_continue_accepted",
                data={
                    **_awaiting_data(),
                    "direction_resolution": {
                        "status": "accepted",
                        "action": "continue_mainline",
                    },
                    "oversized": "x" * 8_000,
                },
            )

    service = OversizedDirectionService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    failed = await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    assert failed.success is False
    assert json.loads(failed.content)["code"] == "tool_output_budget_exhausted"
    assert registry.planning_direction_action is None
    assert registry.planning_direction_result is None
    assert registry.draft_completed is False
    assert registry.direction_protocol_invalid is True


@pytest.mark.asyncio
async def test_registry_bounds_wall_clock_before_direction_action() -> None:
    service = FakeService(
        _result(
            LearningPlanToolStatus.AWAITING_USER,
            "planning_facts_missing",
            data=_awaiting_data(),
        ),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    moments = iter((0.0, 44.0, 46.0))
    registry = LearningPlanRuntimeToolRegistry(service, clock=lambda: next(moments))
    registry.configure_direction_intake()
    initial = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    timed_out = await registry.invoke(
        _call(
            PLANNING_CONTEXT_TOOL_NAME,
            {"direction_action": "continue_mainline"},
        )
    )
    assert initial.success is True
    assert timed_out.success is False
    assert json.loads(timed_out.content)["code"] == "tool_deadline_exhausted"
    assert registry.planning_direction_action is None
