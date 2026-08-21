"""Codex dynamic-tool registry for server-owned learning-plan operations."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from psycopg import Connection
from pydantic import ValidationError

from app.agents.harness.contracts import TutorRunSnapshot
from app.services.learning.plan_tools import (
    LEARNING_PLAN_DRAFT_TOOL_NAME,
    PLANNING_CONTEXT_TOOL_NAME,
    LearningPlanAgentToolResult,
    LearningPlanDraftToolInput,
    LearningPlanToolIssue,
    LearningPlanToolService,
    LearningPlanToolStatus,
    PlanningContextReadInput,
    PostgresLearningPlanToolFence,
    build_expected_learning_plan_tool_fence,
)

from .contracts import (
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolRegistry,
    RuntimeToolResult,
)


class LearningPlanToolServicePort(Protocol):
    def read_context(self) -> LearningPlanAgentToolResult: ...
    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult: ...


@dataclass(frozen=True, slots=True)
class LearningPlanToolBudget:
    max_calls: int = 6
    max_repairs: int = 2
    max_conflicts: int = 1
    max_payload_bytes: int = 32_000
    max_wall_seconds: float = 30.0
    max_output_bytes: int = 8_000

    def __post_init__(self) -> None:
        if not 1 <= self.max_calls <= 16:
            raise ValueError("learning plan tool max_calls must be within 1..16")
        if not 0 <= self.max_repairs <= 8:
            raise ValueError("learning plan tool max_repairs must be within 0..8")
        if not 0 <= self.max_conflicts <= 4:
            raise ValueError("learning plan tool max_conflicts must be within 0..4")
        if not 1_024 <= self.max_payload_bytes <= 128_000:
            raise ValueError("learning plan tool max_payload_bytes is invalid")
        if not 0.1 <= self.max_wall_seconds <= 600:
            raise ValueError("learning plan tool max_wall_seconds is invalid")
        if not 1_000 <= self.max_output_bytes <= 8_000:
            raise ValueError("learning plan tool max_output_bytes is invalid")


class LearningPlanRuntimeToolRegistry(RuntimeToolRegistry):
    """Validate typed arguments and return only bounded model-visible results."""

    def __init__(
        self,
        service: LearningPlanToolServicePort,
        *,
        budget: LearningPlanToolBudget | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._service = service
        self._budget = budget or LearningPlanToolBudget()
        self._clock = clock
        self._started_at = clock()
        self._calls = 0
        self._repairs = 0
        self._conflicts = 0
        self._planning_context_result: LearningPlanAgentToolResult | None = None
        self.results: list[LearningPlanAgentToolResult] = []

    @classmethod
    def from_postgres(
        cls,
        conn: Connection[dict[str, object]],
        *,
        run: TutorRunSnapshot,
        runtime_generation: int,
        runtime_generation_reader: Callable[[], int],
        policy_allowed: Callable[[], bool] = lambda: True,
        budget: LearningPlanToolBudget | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> "LearningPlanRuntimeToolRegistry":
        expected = build_expected_learning_plan_tool_fence(
            conn,
            run=run,
            runtime_generation=runtime_generation,
        )
        fence = PostgresLearningPlanToolFence(
            conn,
            expected=expected,
            runtime_generation=runtime_generation_reader,
            policy_allowed=policy_allowed,
        )
        return cls(
            LearningPlanToolService(conn, run=run, expected_fence=expected, fence=fence),
            budget=budget,
            clock=clock,
        )

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (
            RuntimeToolDefinition(
                name=PLANNING_CONTEXT_TOOL_NAME,
                description=(
                    "Read bounded server-authoritative planning facts, missing facts, draft summary, "
                    "and revision constraints. When awaiting_user, next_missing_fact defines the field "
                    "meaning and exact_question; use that question verbatim without invented examples "
                    "or options. Do not supply user, session, run, or database identifiers."
                ),
                input_schema=PlanningContextReadInput.model_json_schema(),
            ),
            RuntimeToolDefinition(
                name=LEARNING_PLAN_DRAFT_TOOL_NAME,
                description=(
                    "Submit 2..8 typed teaching modules for the current planning turn. The server owns "
                    "the learner profile, facts, language/source policy, persistence scope, and confirmation."
                ),
                input_schema=LearningPlanDraftToolInput.model_json_schema(),
            ),
        )

    @property
    def planning_context_result(self) -> LearningPlanAgentToolResult | None:
        return self._planning_context_result

    def prime_context(self) -> LearningPlanAgentToolResult:
        """Read authoritative planning state before the model turn for deterministic elicitation."""
        if self._planning_context_result is None:
            try:
                self._planning_context_result = self._service.read_context()
            except Exception:
                self._planning_context_result = _fatal("learning_plan_tool_failed")
        return self._planning_context_result

    @property
    def call_count(self) -> int:
        return self._calls

    @property
    def repair_count(self) -> int:
        return self._repairs

    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult:
        if self._clock() - self._started_at > self._budget.max_wall_seconds:
            return self._runtime_result(_fatal("tool_deadline_exhausted"))
        if self._calls >= self._budget.max_calls:
            return self._runtime_result(_fatal("tool_call_budget_exhausted"))
        self._calls += 1
        try:
            payload_size = len(
                json.dumps(
                    dict(call.arguments),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return self._record_repair(
                _repairable_issue("arguments", "invalid_payload", "Send one JSON object matching the tool schema.")
            )
        if payload_size > self._budget.max_payload_bytes:
            return self._record_repair(
                _repairable_issue("arguments", "payload_too_large", "Reduce titles, descriptions, modules, or nodes.")
            )

        if call.tool_name == PLANNING_CONTEXT_TOOL_NAME:
            try:
                PlanningContextReadInput.model_validate(dict(call.arguments))
            except ValidationError as exc:
                return self._record_repair(_validation_result(exc))
            try:
                result = self._service.read_context()
            except Exception:
                result = _fatal("learning_plan_tool_failed")
        elif call.tool_name == LEARNING_PLAN_DRAFT_TOOL_NAME:
            try:
                tool_input = LearningPlanDraftToolInput.model_validate(dict(call.arguments))
            except ValidationError as exc:
                return self._record_repair(_validation_result(exc))
            try:
                result = self._service.draft(tool_input)
            except Exception:
                result = _fatal("learning_plan_tool_failed")
        else:
            result = _fatal("unknown_learning_plan_tool")

        if result.status is LearningPlanToolStatus.REPAIRABLE_INVALID:
            return self._record_repair(result)
        if result.status is LearningPlanToolStatus.CONFLICT:
            self._conflicts += 1
            if self._conflicts > self._budget.max_conflicts:
                return self._runtime_result(_fatal("tool_conflict_budget_exhausted"))
        remaining = max(0, self._budget.max_repairs - self._repairs)
        return self._runtime_result(result.model_copy(update={"remaining_repair_attempts": remaining}))

    def _record_repair(self, result: LearningPlanAgentToolResult) -> RuntimeToolResult:
        self._repairs += 1
        if self._repairs > self._budget.max_repairs:
            return self._runtime_result(_fatal("tool_repair_budget_exhausted"))
        return self._runtime_result(
            result.model_copy(
                update={
                    "retry_allowed": True,
                    "remaining_repair_attempts": self._budget.max_repairs - self._repairs,
                }
            )
        )

    def _runtime_result(self, result: LearningPlanAgentToolResult) -> RuntimeToolResult:
        content = result.content()
        if len(content.encode("utf-8")) > self._budget.max_output_bytes:
            result = _fatal("tool_output_budget_exhausted")
            content = result.content()
        self.results.append(result)
        success = result.status in {
            LearningPlanToolStatus.COMPLETED,
            LearningPlanToolStatus.REPAIRABLE_INVALID,
            LearningPlanToolStatus.AWAITING_USER,
            LearningPlanToolStatus.CONFLICT,
        }
        return RuntimeToolResult(success=success, content=content, safe_code=result.code)


def _validation_result(exc: ValidationError) -> LearningPlanAgentToolResult:
    issues: list[LearningPlanToolIssue] = []
    for error in exc.errors(include_input=False, include_url=False):
        path = ".".join(str(item) for item in error.get("loc", ())) or "arguments"
        error_type = str(error.get("type") or "")
        context = error.get("ctx")
        marker = str(context.get("error") or "") if isinstance(context, Mapping) else ""
        code, hint = _validation_code(error_type, marker)
        issues.append(LearningPlanToolIssue(path=path[:200], code=code, hint=hint))
        if len(issues) >= 12:
            break
    if not issues:
        issues.append(
            LearningPlanToolIssue(
                path="arguments",
                code="invalid_structure",
                hint="Send one object matching the declared typed schema.",
            )
        )
    return LearningPlanAgentToolResult(
        status=LearningPlanToolStatus.REPAIRABLE_INVALID,
        code="learning_plan_tool_input_invalid",
        issues=tuple(issues),
        retry_allowed=True,
    )


def _validation_code(error_type: str, marker: str) -> tuple[str, str]:
    known = {
        "duplicate_module_key": ("duplicate_module_key", "Use a unique stable_key for every module."),
        "duplicate_node_key": ("duplicate_node_key", "Use a unique stable_key for every node in the plan."),
        "duplicate_stable_key": ("duplicate_stable_key", "Remove repeated stable keys from this list."),
        "self_prerequisite": ("self_prerequisite", "A node cannot depend on itself."),
        "unknown_prerequisite": ("unknown_prerequisite", "Reference only node stable keys present in this plan."),
        "prerequisite_cycle": ("prerequisite_cycle", "Make prerequisites an acyclic graph."),
    }
    for token, value in known.items():
        if token in marker:
            return value
    if error_type == "extra_forbidden":
        return "unknown_field", "Remove fields that are not declared in the tool schema."
    if error_type in {"too_short", "list_too_short", "tuple_too_short", "missing"}:
        return "required_value_missing", "Add the required field or minimum number of items."
    if error_type in {"too_long", "list_too_long", "tuple_too_long", "string_too_long"}:
        return "value_too_large", "Reduce the value to the declared schema limit."
    if error_type in {"string_pattern_mismatch", "literal_error"}:
        return "invalid_stable_value", "Use the exact schema version or a lowercase stable key."
    return "invalid_structure", "Correct this field to match the declared typed schema."


def _repairable_issue(path: str, code: str, hint: str) -> LearningPlanAgentToolResult:
    return LearningPlanAgentToolResult(
        status=LearningPlanToolStatus.REPAIRABLE_INVALID,
        code="learning_plan_tool_input_invalid",
        issues=(LearningPlanToolIssue(path=path, code=code, hint=hint),),
        retry_allowed=True,
    )


def _fatal(code: str) -> LearningPlanAgentToolResult:
    return LearningPlanAgentToolResult(status=LearningPlanToolStatus.FATAL, code=code)
