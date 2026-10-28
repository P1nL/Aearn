"""Codex dynamic-tool registry for server-owned learning-plan operations."""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Protocol, cast

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
    PlanningDirectionAction,
    PostgresLearningPlanToolFence,
    build_expected_learning_plan_tool_fence,
)

from .contracts import (
    RuntimePlanningStepResult,
    RuntimeToolCall,
    RuntimeToolDefinition,
    RuntimeToolRegistry,
    RuntimeToolResult,
)


class LearningPlanToolServicePort(Protocol):
    def read_context(
        self,
        tool_input: PlanningContextReadInput | None = None,
    ) -> LearningPlanAgentToolResult: ...
    def draft(self, tool_input: LearningPlanDraftToolInput) -> LearningPlanAgentToolResult: ...


@dataclass(frozen=True, slots=True)
class LearningPlanToolBudget:
    max_calls: int = 6
    max_repairs: int = 5
    max_conflicts: int = 1
    max_payload_bytes: int = 32_000
    max_wall_seconds: float = 300.0
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
        if not 0.1 <= self.max_wall_seconds <= 2_400:
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
        self._calls_before_turn = 0
        self._repairs_before_turn = 0
        self._primed_context_result: LearningPlanAgentToolResult | None = None
        self._planning_context_result: LearningPlanAgentToolResult | None = None
        self._planning_intent_hint: dict[str, object] | None = None
        self._model_context_read = False
        self._accepted_direction_action: PlanningDirectionAction | None = None
        self._accepted_direction_result: LearningPlanAgentToolResult | None = None
        self._direction_protocol_invalid = False
        self._intake_mode = False
        self._draft_completed = False
        self._saved_draft_result: LearningPlanAgentToolResult | None = None
        self._order_repair_used = False
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
        committed_state: Mapping[str, object] | None = None,
        recover_committed_draft: bool = False,
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
        service = LearningPlanToolService(conn, run=run, expected_fence=expected, fence=fence)
        registry = cls(
            service,
            budget=budget,
            clock=clock,
        )
        if committed_state is not None or recover_committed_draft:
            registry.prime_context()
        if committed_state is not None:
            registry.restore_committed_direction(committed_state)
            registry._direction_protocol_invalid = committed_state.get("direction_protocol_invalid") is True
            counters = tuple(committed_state.get(key, 0) for key in (
                "tool_call_count", "tool_repair_count", "tool_conflict_count",
            ))
            if any(type(value) is not int or value < 0 for value in counters):
                raise ValueError("planning_committed_tool_counters_invalid")
            registry._calls, registry._repairs, registry._conflicts = (cast(int, value) for value in counters)
            registry._calls_before_turn = registry._calls
            registry._repairs_before_turn = registry._repairs
        if recover_committed_draft:
            saved = service.recover_committed_draft()
            expected_hash = committed_state.get("draft_content_hash") if committed_state is not None else None
            if expected_hash is not None and (
                saved is None or saved.data.get("content_hash") != expected_hash
            ):
                raise ValueError("learning_plan_saved_result_stale")
            if saved is not None:
                if saved.status is not LearningPlanToolStatus.COMPLETED or saved.code != "learning_plan_draft_completed":
                    raise ValueError(saved.code)
                if registry._accepted_direction_action is not PlanningDirectionAction.CONTINUE_MAINLINE:
                    raise ValueError("learning_plan_saved_direction_missing")
                registry._saved_draft_result = saved
                registry._draft_completed = True
        return registry

    @property
    def continuation_state(self) -> Mapping[str, object]:
        """Dependency-bound DATA to record in the durable step result, not a cap."""
        context = self._planning_context_result or self._primed_context_result
        draft = self._saved_draft_result or next((
            result for result in reversed(self.results)
            if result.status is LearningPlanToolStatus.COMPLETED and result.code == "learning_plan_draft_completed"
        ), None)
        return {
            "schema_version": "learning-plan-runtime-checkpoint-v1",
            "facts_fingerprint": context.data.get("facts_fingerprint") if context else None,
            "facts_revision": context.data.get("facts_revision") if context else None,
            "direction_action": self._accepted_direction_action.value if self._accepted_direction_action else None,
            "direction_protocol_invalid": self._direction_protocol_invalid,
            "planning_intent_hint": self._planning_intent_hint,
            "draft_content_hash": draft.data.get("content_hash") if draft else None,
            "tool_call_count": self._calls,
            "tool_repair_count": self._repairs,
            "tool_conflict_count": self._conflicts,
        }

    def configure_work_deadline(self, seconds: float) -> None:
        self._budget = replace(self._budget, max_wall_seconds=min(self._budget.max_wall_seconds, seconds))
        self._started_at = self._clock()

    def restore_recorded_tool_results(self, saved: RuntimePlanningStepResult) -> None:
        """Restore counters/status DATA only after reading the exact owner result."""
        self.results = [LearningPlanAgentToolResult.model_validate(item) for item in saved.tool_results]
        # The checkpoint contains cumulative guards, whereas the DTO counters
        # charge only this native step. Do not reset guards or double-charge a
        # recovered step during original-owner acceptance.
        self._calls_before_turn = self._calls - saved.tool_call_count
        self._repairs_before_turn = self._repairs - saved.tool_repair_count
        if self._calls_before_turn < 0 or self._repairs_before_turn < 0:
            raise ValueError("planning_committed_tool_counters_invalid")

    def restore_committed_direction(self, state: Mapping[str, object]) -> None:
        """Revalidate owner-loaded committed DATA against this fresh registry."""
        context = self.prime_context()
        if (
            state.get("schema_version") != "learning-plan-runtime-checkpoint-v1"
            or context.status not in {LearningPlanToolStatus.COMPLETED, LearningPlanToolStatus.AWAITING_USER}
            or state.get("facts_fingerprint") != context.data.get("facts_fingerprint")
            or state.get("facts_revision") != context.data.get("facts_revision")
            or not state.get("facts_fingerprint")
        ):
            raise ValueError("planning_committed_direction_stale")
        if state.get("direction_action") is None:
            return
        tool_input = PlanningContextReadInput.model_validate({
            "direction_action": state["direction_action"],
            "planning_intent_hint": state.get("planning_intent_hint"),
        })
        action = tool_input.direction_action
        if action is None:
            raise ValueError("planning_committed_direction_missing")
        result = self._service.read_context(tool_input)
        if not _direction_result_is_accepted(action, result):
            raise ValueError("planning_committed_direction_stale")
        self._model_context_read = True
        self._accepted_direction_action = action
        self._accepted_direction_result = result
        self._planning_context_result = result
        self._planning_intent_hint = (
            tool_input.planning_intent_hint.model_dump(mode="json")
            if tool_input.planning_intent_hint else None
        )

    @property
    def definitions(self) -> tuple[RuntimeToolDefinition, ...]:
        return (
            RuntimeToolDefinition(
                name=PLANNING_CONTEXT_TOOL_NAME,
                description=(
                    "First call once without direction_action to read current server facts, "
                    "including data.next_missing_fact when facts are incomplete. "
                    "Then call exactly once with direction_action: continue_mainline, "
                    "answer_and_refocus, clarify_direction, or confirmed_switch. A "
                    "planning_intent_hint is allowed only with continue_mainline after "
                    "reading current language candidates. Never send rationale, learner "
                    "text, labels, course ids, options, or scope ids."
                ),
                input_schema=PlanningContextReadInput.model_json_schema(),
            ),
            RuntimeToolDefinition(
                name=LEARNING_PLAN_DRAFT_TOOL_NAME,
                description=(
                    "Submit 2..8 typed teaching modules only after an accepted "
                    "continue_mainline action and complete planning facts. The server owns "
                    "the learner profile, language/source policy, persistence, and confirmation. "
                    "Keep stable_key as course-step identity; optional catalog_knowledge_key must copy an exact published "
                    "key and capabilities from planning context, never a title-derived alias."
                ),
                input_schema=LearningPlanDraftToolInput.model_json_schema(),
            ),
        )

    @property
    def primed_context_result(self) -> LearningPlanAgentToolResult | None:
        return self._primed_context_result

    @property
    def planning_context_result(self) -> LearningPlanAgentToolResult | None:
        return self._planning_context_result

    @property
    def planning_intent_hint(self) -> Mapping[str, object] | None:
        return self._planning_intent_hint

    @property
    def planning_direction_action(self) -> PlanningDirectionAction | None:
        if self._direction_protocol_invalid:
            return None
        return self._accepted_direction_action

    @property
    def planning_direction_result(self) -> LearningPlanAgentToolResult | None:
        if self._direction_protocol_invalid:
            return None
        return self._accepted_direction_result

    @property
    def direction_protocol_invalid(self) -> bool:
        return self._direction_protocol_invalid

    @property
    def intake_mode(self) -> bool:
        return self._intake_mode

    @property
    def draft_completed(self) -> bool:
        return self._draft_completed and not self._direction_protocol_invalid

    @property
    def requires_server_terminalization(self) -> bool:
        action = self.planning_direction_action
        if action is None or self._intake_mode:
            return True
        if action is PlanningDirectionAction.CONTINUE_MAINLINE:
            return not self.draft_completed
        return True

    def prime_context(self) -> LearningPlanAgentToolResult:
        """Read authoritative planning state before the model turn."""
        if self._primed_context_result is None:
            try:
                result = self._service.read_context()
            except Exception:
                result = _fatal("learning_plan_tool_failed")
            self._primed_context_result = result
            self._planning_context_result = result
        return self._primed_context_result

    def configure_direction_intake(
        self,
        *,
        max_wall_seconds: float = 45.0,
    ) -> None:
        """Restrict an awaiting-user turn to one read and one resolution call."""
        self._intake_mode = True
        self._budget = LearningPlanToolBudget(
            max_calls=min(self._budget.max_calls, 2),
            max_repairs=min(self._budget.max_repairs, 5),
            max_conflicts=0,
            max_payload_bytes=self._budget.max_payload_bytes,
            max_wall_seconds=min(self._budget.max_wall_seconds, max_wall_seconds),
            max_output_bytes=self._budget.max_output_bytes,
        )

    @property
    def call_count(self) -> int:
        return self._calls - self._calls_before_turn

    @property
    def repair_count(self) -> int:
        return self._repairs - self._repairs_before_turn

    async def invoke(self, call: RuntimeToolCall) -> RuntimeToolResult:
        if (
            call.tool_name == PLANNING_CONTEXT_TOOL_NAME
            and self._accepted_direction_action is not None
        ):
            self._direction_protocol_invalid = True
            try:
                repeated = PlanningContextReadInput.model_validate(dict(call.arguments))
            except ValidationError:
                return self._runtime_result(
                    _fatal("planning_direction_action_conflict")
                )
            code = (
                "planning_direction_action_duplicate"
                if repeated.direction_action is self._accepted_direction_action
                else "planning_direction_action_conflict"
            )
            return self._runtime_result(_fatal(code))
        if call.tool_name == LEARNING_PLAN_DRAFT_TOOL_NAME and self._intake_mode:
            self._direction_protocol_invalid = True
            return self._runtime_result(
                _fatal("planning_direction_intake_draft_forbidden")
            )
        if self._clock() - self._started_at > self._budget.max_wall_seconds:
            self._direction_protocol_invalid = True
            return self._runtime_result(_fatal("tool_deadline_exhausted"))
        # A repairable result grants exactly one bounded follow-up call without
        # consuming another normal read/action slot.
        if self._calls >= self._budget.max_calls + self._repairs:
            self._direction_protocol_invalid = True
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
            self._direction_protocol_invalid = True
            return self._record_repair(
                _repairable_issue(
                    "arguments",
                    "invalid_payload",
                    "Send one JSON object matching the tool schema.",
                )
            )
        if payload_size > self._budget.max_payload_bytes:
            self._direction_protocol_invalid = True
            return self._record_repair(
                _repairable_issue(
                    "arguments",
                    "payload_too_large",
                    "Reduce titles, descriptions, modules, or nodes.",
                )
            )

        if call.tool_name == PLANNING_CONTEXT_TOOL_NAME:
            result = self._invoke_context(call)
        elif call.tool_name == LEARNING_PLAN_DRAFT_TOOL_NAME:
            result = self._invoke_draft(call)
        else:
            result = _fatal("unknown_learning_plan_tool")

        if result.status is LearningPlanToolStatus.REPAIRABLE_INVALID:
            return self._record_repair(result)
        if result.status is LearningPlanToolStatus.CONFLICT:
            self._conflicts += 1
            if self._conflicts > self._budget.max_conflicts:
                return self._runtime_result(_fatal("tool_conflict_budget_exhausted"))
        remaining = max(0, self._budget.max_repairs - self._repairs)
        return self._runtime_result(
            result.model_copy(update={"remaining_repair_attempts": remaining})
        )

    def _invoke_context(self, call: RuntimeToolCall) -> LearningPlanAgentToolResult:
        try:
            context_input = PlanningContextReadInput.model_validate(dict(call.arguments))
        except ValidationError as exc:
            self._direction_protocol_invalid = True
            return _validation_result(exc)
        action = context_input.direction_action
        if action is None:
            if self._model_context_read or self._accepted_direction_action is not None:
                self._direction_protocol_invalid = True
                return _fatal("planning_direction_context_read_duplicate")
            try:
                result = self._service.read_context()
            except Exception:
                result = _fatal("learning_plan_tool_failed")
            self._model_context_read = True
            self._planning_context_result = result
            return result
        if not self._model_context_read:
            if (
                not self._direction_protocol_invalid
                and not self._order_repair_used
                and self._repairs < self._budget.max_repairs
            ):
                self._order_repair_used = True
                return LearningPlanAgentToolResult(
                    status=LearningPlanToolStatus.REPAIRABLE_INVALID,
                    code="planning_direction_context_read_required",
                    issues=(LearningPlanToolIssue(
                        path="direction_action",
                        code="context_read_required",
                        hint="Call aearn_planning_context_read without direction_action first, then submit exactly one direction_action.",
                    ),),
                )
            self._direction_protocol_invalid = True
            return _fatal("planning_direction_context_read_required")
        if self._accepted_direction_action is not None:
            self._direction_protocol_invalid = True
            code = (
                "planning_direction_action_duplicate"
                if action is self._accepted_direction_action
                else "planning_direction_action_conflict"
            )
            return _fatal(code)
        if self._direction_protocol_invalid:
            return _fatal("planning_direction_protocol_invalid")
        try:
            result = self._service.read_context(context_input)
        except Exception:
            result = _fatal("learning_plan_tool_failed")
        self._planning_context_result = result
        if _direction_result_is_accepted(action, result):
            self._accepted_direction_action = action
            self._accepted_direction_result = result
            self._planning_intent_hint = (
                context_input.planning_intent_hint.model_dump(mode="json")
                if context_input.planning_intent_hint is not None
                else None
            )
        elif result.status is not LearningPlanToolStatus.REPAIRABLE_INVALID:
            self._direction_protocol_invalid = True
        return result

    def _invoke_draft(self, call: RuntimeToolCall) -> LearningPlanAgentToolResult:
        if self.planning_direction_action is not PlanningDirectionAction.CONTINUE_MAINLINE:
            self._direction_protocol_invalid = True
            return _fatal("planning_direction_action_required")
        if self._intake_mode:
            self._direction_protocol_invalid = True
            return _fatal("planning_direction_intake_draft_forbidden")
        if self._saved_draft_result is not None:
            # Recovery DATA is not a lease/input/source capability. Re-read the
            # original owner on each callback, just as a non-recovered tool does.
            saved = cast(LearningPlanToolService, self._service).recover_committed_draft()
            if saved is None or (
                saved.status is LearningPlanToolStatus.COMPLETED
                and saved.data.get("content_hash") != self._saved_draft_result.data.get("content_hash")
            ):
                return _fatal("learning_plan_saved_result_stale")
            return saved
        try:
            draft_input = LearningPlanDraftToolInput.model_validate(dict(call.arguments))
        except ValidationError as exc:
            return _validation_result(exc)
        try:
            result = self._service.draft(draft_input)
        except Exception:
            result = _fatal("learning_plan_tool_failed")
        if (
            result.status is LearningPlanToolStatus.COMPLETED
            and result.code == "learning_plan_draft_completed"
        ):
            self._draft_completed = True
        return result

    def _record_repair(self, result: LearningPlanAgentToolResult) -> RuntimeToolResult:
        if self._repairs >= self._budget.max_repairs:
            self._direction_protocol_invalid = True
            return self._runtime_result(_fatal("tool_repair_budget_exhausted"))
        self._repairs += 1
        return self._runtime_result(
            result.model_copy(
                update={
                    "retry_allowed": True,
                    "remaining_repair_attempts": self._budget.max_repairs
                    - self._repairs,
                }
            )
        )

    def _runtime_result(self, result: LearningPlanAgentToolResult) -> RuntimeToolResult:
        content = result.content()
        if len(content.encode("utf-8")) > self._budget.max_output_bytes:
            self._accepted_direction_action = None
            self._accepted_direction_result = None
            self._planning_intent_hint = None
            self._draft_completed = False
            self._direction_protocol_invalid = True
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


def _direction_result_is_accepted(
    action: PlanningDirectionAction,
    result: LearningPlanAgentToolResult,
) -> bool:
    resolution = result.data.get("direction_resolution")
    if not isinstance(resolution, Mapping):
        return False
    if resolution.get("status") != "accepted" or resolution.get("action") != action.value:
        return False
    accepted_codes = {
        PlanningDirectionAction.CONTINUE_MAINLINE: {
            "planning_direction_continue_accepted",
            "planning_direction_continue_ready",
        },
        PlanningDirectionAction.ANSWER_AND_REFOCUS: {
            "planning_direction_answer_refocus_accepted",
        },
        PlanningDirectionAction.CLARIFY_DIRECTION: {
            "planning_direction_clarification_accepted",
        },
        PlanningDirectionAction.CONFIRMED_SWITCH: {
            "planning_direction_switch_accepted",
        },
    }
    return result.code in accepted_codes[action] and result.status in {
        LearningPlanToolStatus.COMPLETED,
        LearningPlanToolStatus.AWAITING_USER,
    }


def _awaiting_language_candidates(result: LearningPlanAgentToolResult) -> bool:
    missing = result.data.get("missing_facts")
    candidates = result.data.get("language_candidates")
    return (
        isinstance(missing, list | tuple)
        and bool(missing)
        and str(missing[0]) == "language_id"
        and isinstance(candidates, list | tuple)
    )


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
