from __future__ import annotations

import json
from dataclasses import dataclass

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
    LearningPlanToolStatus,
)
from app.services.learning.planning_questions import build_planning_question_model_descriptor


@dataclass
class FakeService:
    read_result: LearningPlanAgentToolResult
    draft_result: LearningPlanAgentToolResult
    draft_calls: int = 0

    def read_context(self) -> LearningPlanAgentToolResult:
        return self.read_result

    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult:
        assert len(tool_input.modules) >= 2
        self.draft_calls += 1
        return self.draft_result


def _result(status: LearningPlanToolStatus, code: str) -> LearningPlanAgentToolResult:
    return LearningPlanAgentToolResult(status=status, code=code)


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


def test_language_question_descriptor_prevents_natural_language_ambiguity() -> None:
    descriptor = build_planning_question_model_descriptor("language_id")

    assert descriptor["field_key"] == "language_id"
    assert descriptor["exact_question"] == "你想学习哪门编程语言？"
    assert "编程语言" in str(descriptor["meaning"])
    assert "自然语言" in str(descriptor["meaning"])
    assert "中文" not in str(descriptor)
    assert "英文" not in str(descriptor)
    assert "补充括号示例" in str(descriptor["wording_policy"])
    assert descriptor["response_authority"] == "aearn_typed_request"


def test_tool_definitions_expose_only_typed_modules_and_no_authority_fields() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    registry = LearningPlanRuntimeToolRegistry(service)
    definitions = {definition.name: definition for definition in registry.definitions}
    assert set(definitions) == {PLANNING_CONTEXT_TOOL_NAME, LEARNING_PLAN_DRAFT_TOOL_NAME}
    context_definition = definitions[PLANNING_CONTEXT_TOOL_NAME]
    context_schema = context_definition.input_schema
    assert context_schema.get("type") == "object"
    assert "next_missing_fact" in context_definition.description
    assert "exact_question" in context_definition.description
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
async def test_registry_repair_budget_is_bounded_and_never_echoes_raw_invalid_value() -> None:
    service = FakeService(
        _result(LearningPlanToolStatus.COMPLETED, "planning_context_ready"),
        _result(LearningPlanToolStatus.COMPLETED, "learning_plan_draft_completed"),
    )
    registry = LearningPlanRuntimeToolRegistry(
        service,
        budget=LearningPlanToolBudget(max_repairs=1),
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
    cyclic = _valid_modules()
    cyclic[0]["nodes"][0]["prerequisites"] = ["python.files"]  # type: ignore[index]
    invalid = await registry.invoke(_call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": cyclic}))
    assert json.loads(invalid.content)["issues"][0]["code"] == "prerequisite_cycle"

    moments = iter((0.0, 31.0))
    expired = LearningPlanRuntimeToolRegistry(service, clock=lambda: next(moments))
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
    first = await registry.invoke(_call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()}))
    second = await registry.invoke(_call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _valid_modules()}))
    assert first.content == second.content
    assert json.loads(first.content)["replayed"] is True
    assert service.draft_calls == 2


@pytest.mark.asyncio
async def test_registry_bounds_conflict_rebuilds_and_contains_service_exceptions() -> None:
    conflict_service = FakeService(
        _result(LearningPlanToolStatus.CONFLICT, "planning_facts_stale"),
        _result(LearningPlanToolStatus.COMPLETED, "unused"),
    )
    registry = LearningPlanRuntimeToolRegistry(conflict_service)
    first = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    second = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    assert json.loads(first.content)["status"] == "conflict"
    assert second.success is False
    assert json.loads(second.content)["code"] == "tool_conflict_budget_exhausted"

    class ExplodingService(FakeService):
        def read_context(self) -> LearningPlanAgentToolResult:
            raise RuntimeError("raw-private-service-error")

    exploding = LearningPlanRuntimeToolRegistry(
        ExplodingService(
            _result(LearningPlanToolStatus.COMPLETED, "unused"),
            _result(LearningPlanToolStatus.COMPLETED, "unused"),
        )
    )
    failed = await exploding.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}))
    assert failed.success is False
    assert json.loads(failed.content)["code"] == "learning_plan_tool_failed"
    assert "raw-private-service-error" not in failed.content
