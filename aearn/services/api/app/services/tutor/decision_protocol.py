"""Typed provider protocol and authoritative Tutor decision assembly."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agents.harness.contracts import (
    MAX_TUTOR_PAYLOAD_FIELDS,
    MAX_TUTOR_PAYLOAD_VALUE_LENGTH,
    MAX_TUTOR_PUBLIC_MESSAGE_LENGTH,
    MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH,
    TUTOR_PLANNING_QUESTION_KEYS,
    TutorCapabilityRequest,
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorDecision,
    TutorEffectProposal,
    TutorPlanningQuestionKey,
    TutorRunSnapshot,
    TutorSkillReference,
    TutorTerminalOutcome,
    payload_fields_from_mapping,
)
from app.services.learning.teaching_contracts import (
    TeachingAction,
    TeachingFocusResolution,
    TeachingInteractionDecision,
    TeachingInteractionIntent,
    TeachingLearnerResponseMode,
    TeachingMove,
    TeachingPauseReason,
    TeachingStepDecision,
)
from app.services.llm.llm_client import LLMInvalidResponseError


TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION = "tutor_provider_items_v5"
TUTOR_PROVIDER_ITEMS_SCHEMA_NAME = "tutor_provider_items_v5"

_FORBIDDEN_NESTED_PAYLOAD_FIELD_NAMES = frozenset(
    {
        "reasoning",
        "diagnostic",
        "diagnostics",
        "solutionreference",
        "referenceanswer",
        "rawprompt",
        "systemprompt",
        "providerpayload",
        "providererror",
        "apikey",
        "secret",
        "secretkey",
        "authtoken",
        "stacktrace",
        "traceback",
    }
)

TutorProviderValue: TypeAlias = str | int | float | bool | None | list[str]


@dataclass(frozen=True)
class TutorDecisionValidationIssue:
    """Log-safe schema issue containing no provider-supplied value or message."""

    path: str
    category: str


class TutorDecisionValidationError(LLMInvalidResponseError):
    """A JSON response that cannot be assembled into one authoritative decision."""

    def __init__(
        self,
        message: str,
        *,
        issues: Sequence[TutorDecisionValidationIssue] = (),
    ) -> None:
        super().__init__(message)
        self.issues = tuple(issues[:8])


class _StrictProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class TutorProviderPayloadField(_StrictProviderModel):
    key: str = Field(min_length=1, max_length=120)
    value: TutorProviderValue

    @field_validator("key")
    @classmethod
    def _reject_internal_key(cls, value: str) -> str:
        compact_key = "".join(
            character for character in value.lower() if character.isalnum()
        )
        if (
            compact_key in _FORBIDDEN_NESTED_PAYLOAD_FIELD_NAMES
            or compact_key.startswith("hiddentest")
        ):
            raise ValueError("internal-only payload key")
        return value

    @field_validator("value")
    @classmethod
    def _bound_list_value(cls, value: TutorProviderValue) -> TutorProviderValue:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("payload number must be finite")
        if isinstance(value, list) and (
            len(value) > 4 or any(len(item) > 120 for item in value)
        ):
            raise ValueError("oversized payload list")
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) > MAX_TUTOR_PAYLOAD_VALUE_LENGTH:
            raise ValueError("oversized payload value")
        return value


class TutorProviderAgentMessageItem(_StrictProviderModel):
    type: Literal["agent_message"]
    public_thinking_text: str = Field(
        min_length=1,
        max_length=MAX_TUTOR_PUBLIC_THINKING_TEXT_LENGTH,
    )
    text: str = Field(min_length=1, max_length=MAX_TUTOR_PUBLIC_MESSAGE_LENGTH)
    conversation_title: str | None = Field(max_length=48)


class TutorProviderTurnCompletedItem(_StrictProviderModel):
    type: Literal["turn_completed"]


class TutorProviderSelectSkillItem(_StrictProviderModel):
    type: Literal["select_skill"]
    skill_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)


class TutorProviderRequestCapabilityItem(_StrictProviderModel):
    type: Literal["request_capability"]
    capability_id: str = Field(min_length=1, max_length=120)
    arguments: list[TutorProviderPayloadField] = Field(
        max_length=MAX_TUTOR_PAYLOAD_FIELDS
    )

    @field_validator("arguments")
    @classmethod
    def _unique_argument_keys(
        cls,
        value: list[TutorProviderPayloadField],
    ) -> list[TutorProviderPayloadField]:
        _ensure_unique_provider_keys(value, label="capability arguments")
        return value


class TutorProviderProposeEffectItem(_StrictProviderModel):
    type: Literal["propose_effect"]
    effect_type: str = Field(min_length=1, max_length=120)
    payload: list[TutorProviderPayloadField] = Field(
        max_length=MAX_TUTOR_PAYLOAD_FIELDS
    )

    @field_validator("payload")
    @classmethod
    def _unique_payload_keys(
        cls,
        value: list[TutorProviderPayloadField],
    ) -> list[TutorProviderPayloadField]:
        _ensure_unique_provider_keys(value, label="effect payload")
        return value


class TutorProviderTeachingStepItem(_StrictProviderModel):
    type: Literal["teaching_step"]
    action: TeachingAction
    objective_id: str = Field(min_length=1, max_length=160)
    focus_id: str = Field(min_length=1, max_length=160)
    source_handles: list[str] = Field(default_factory=list, max_length=8)
    public_message: str = Field(min_length=1, max_length=4000)
    focus_resolution: TeachingFocusResolution
    pause_kind: TeachingPauseReason
    escalation_hint: str | None = Field(default=None, min_length=1, max_length=180)
    teaching_moves: list[TeachingMove] | None = Field(default=None, max_length=4)
    learner_response_mode: TeachingLearnerResponseMode | None = None
    interaction: TeachingInteractionDecision | None = None

    @field_validator("source_handles")
    @classmethod
    def _unique_handles(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("teaching source handles must be unique")
        return value

    @model_validator(mode="after")
    def _one_interaction_contract(self) -> "TutorProviderTeachingStepItem":
        if self.interaction is not None and self.learner_response_mode is not None:
            raise ValueError("teaching_step cannot combine v2 and v3 interaction fields")
        return self


class TutorProviderWaitForInputItem(_StrictProviderModel):
    type: Literal["wait_for_input"]
    continuation_kind: TutorContinuationKind
    question_key: TutorPlanningQuestionKey | None = None

    @model_validator(mode="after")
    def _validate_question_key_contract(self) -> "TutorProviderWaitForInputItem":
        if self.continuation_kind is TutorContinuationKind.PLANNING_INPUT:
            if self.question_key is None:
                raise ValueError("planning_input requires question_key")
        elif self.question_key is not None:
            raise ValueError("question_key is only valid for planning_input")
        return self


TutorProviderActionItem: TypeAlias = Annotated[
    TutorProviderTurnCompletedItem
    | TutorProviderSelectSkillItem
    | TutorProviderRequestCapabilityItem
    | TutorProviderProposeEffectItem
    | TutorProviderTeachingStepItem
    | TutorProviderWaitForInputItem,
    Field(discriminator="type"),
]


class TutorProviderItemsEnvelope(_StrictProviderModel):
    schema_version: Literal["tutor_provider_items_v4", "tutor_provider_items_v5"]
    message: TutorProviderAgentMessageItem
    action: TutorProviderActionItem

    @model_validator(mode="after")
    def _require_current_teaching_contract(self) -> "TutorProviderItemsEnvelope":
        if (
            self.schema_version == TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION
            and isinstance(self.action, TutorProviderTeachingStepItem)
            and self.action.interaction is None
        ):
            raise ValueError("current teaching_step requires the v3 interaction contract")
        return self


def tutor_provider_output_schema() -> dict[str, object]:
    """Return the generated schema with exact continuation/question-key branches."""

    schema = TutorProviderItemsEnvelope.model_json_schema()
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):  # pragma: no cover - Pydantic schema invariant.
        raise RuntimeError("Tutor provider schema definitions are missing")
    definitions["TutorProviderWaitForInputItem"] = _wait_for_input_output_schema()
    definitions["TutorProviderTeachingStepItem"] = _teaching_step_output_schema()
    properties = schema.get("properties")
    if not isinstance(properties, dict):  # pragma: no cover - Pydantic schema invariant.
        raise RuntimeError("Tutor provider schema properties are missing")
    properties["schema_version"] = {
        "const": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "title": "Schema Version",
        "type": "string",
    }
    return schema


def _wait_for_input_output_schema() -> dict[str, object]:
    branches: list[dict[str, object]] = []
    for continuation_kind in (
        TutorContinuationKind.CLARIFICATION,
        TutorContinuationKind.APPROVAL,
        TutorContinuationKind.CAPABILITY_RESULT,
        TutorContinuationKind.EXTERNAL_RESULT,
    ):
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {"const": "wait_for_input", "type": "string"},
                    "continuation_kind": {
                        "const": continuation_kind.value,
                        "type": "string",
                    },
                },
                "required": ["type", "continuation_kind"],
            }
        )
    branches.insert(
        1,
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "type": {"const": "wait_for_input", "type": "string"},
                "continuation_kind": {
                    "const": TutorContinuationKind.PLANNING_INPUT.value,
                    "type": "string",
                },
                "question_key": {
                    "enum": sorted(TUTOR_PLANNING_QUESTION_KEYS),
                    "type": "string",
                },
            },
            "required": ["type", "continuation_kind", "question_key"],
        },
    )
    return {"title": "TutorProviderWaitForInputItem", "anyOf": branches}


def _teaching_step_output_schema() -> dict[str, object]:
    interaction_branches: list[dict[str, object]] = [
        _teaching_interaction_branch(
            mode=TeachingLearnerResponseMode.NONE,
            intent=TeachingInteractionIntent.NONE,
            artifact=False,
        ),
        _teaching_interaction_branch(
            mode=TeachingLearnerResponseMode.COMPOSER,
            intent=TeachingInteractionIntent.TEXT_ANSWER,
            artifact=False,
        ),
    ]
    interaction_branches.extend(
        _teaching_interaction_branch(
            mode=TeachingLearnerResponseMode.ARTIFACT,
            intent=intent,
            artifact=True,
        )
        for intent in (
            TeachingInteractionIntent.STRUCTURED_ANSWER,
            TeachingInteractionIntent.EDIT_CODE,
            TeachingInteractionIntent.RUN_CODE,
            TeachingInteractionIntent.REVIEW_DIFF,
            TeachingInteractionIntent.EXECUTE_QUERY,
            TeachingInteractionIntent.INTERACT_WITH_DEMO,
        )
    )
    return {
        "title": "TutorProviderTeachingStepItem",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "type": {"const": "teaching_step", "type": "string"},
            "action": {
                "enum": [item.value for item in TeachingAction],
                "type": "string",
            },
            "objective_id": {
                "minLength": 1,
                "maxLength": 160,
                "pattern": "^[a-z0-9][a-z0-9._:-]{0,159}$",
                "type": "string",
            },
            "focus_id": {
                "minLength": 1,
                "maxLength": 160,
                "pattern": "^[a-z0-9][a-z0-9._:-]{0,159}$",
                "type": "string",
            },
            "source_handles": {
                "type": "array",
                "items": {
                    "minLength": 1,
                    "maxLength": 160,
                    "pattern": "^[a-z0-9][a-z0-9._:-]{0,159}$",
                    "type": "string",
                },
                "maxItems": 8,
                "uniqueItems": True,
            },
            "public_message": {
                "minLength": 1,
                "maxLength": 4000,
                "type": "string",
            },
            "focus_resolution": {
                "enum": [item.value for item in TeachingFocusResolution],
                "type": "string",
            },
            "pause_kind": {
                "enum": [item.value for item in TeachingPauseReason],
                "type": "string",
            },
            "escalation_hint": {
                "anyOf": [
                    {"minLength": 1, "maxLength": 180, "type": "string"},
                    {"type": "null"},
                ]
            },
            "teaching_moves": {
                "type": "array",
                "items": {
                    "enum": [item.value for item in TeachingMove],
                    "type": "string",
                },
                "minItems": 2,
                "maxItems": 4,
                "uniqueItems": True,
            },
            "interaction": {
                "title": "TeachingInteractionDecision",
                "anyOf": interaction_branches,
            },
        },
        "required": [
            "type",
            "action",
            "objective_id",
            "focus_id",
            "source_handles",
            "public_message",
            "focus_resolution",
            "pause_kind",
            "escalation_hint",
            "teaching_moves",
            "interaction",
        ],
    }


def _teaching_interaction_branch(
    *,
    mode: TeachingLearnerResponseMode,
    intent: TeachingInteractionIntent,
    artifact: bool,
) -> dict[str, object]:
    artifact_handle: dict[str, object] = (
        {
            "type": "string",
            "minLength": 67,
            "maxLength": 67,
            "pattern": "^li:[0-9a-f]{64}$",
        }
        if artifact
        else {"type": "null"}
    )
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mode": {"const": mode.value, "type": "string"},
            "intent": {"const": intent.value, "type": "string"},
            "artifact_handle": artifact_handle,
        },
        "required": ["mode", "intent", "artifact_handle"],
    }


def tutor_provider_output_schema_hash() -> str:
    canonical = json.dumps(
        tutor_provider_output_schema(),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_tutor_provider_items_example() -> str:
    """Small direct-reply example used by JSON-object-only providers."""

    return _canonical_provider_example(
        text="请从一个很小的练习开始。",
        thinking_text=(
            "把目标缩小到一个可以立即验证的函数练习，更容易发现理解偏差。\n\n"
            "一次输入输出检查可以判断是否需要补充参数与返回值知识。"
        ),
        title="函数基础练习",
        action={"type": "turn_completed"},
    )


def canonical_tutor_teaching_step_example() -> str:
    message = (
        "先比较两个 HTML 片段：`<p>你好` 的缺失闭合通常会被浏览器修复；"
        "现在请找出 `<p><strong>你好</p>` 的结构错误，并预测浏览器会怎样调整 DOM。"
    )
    return _canonical_provider_example(
        text=message,
        thinking_text=(
            "学习者已经在阅读 HTML 文档，因此本单元不复述标签定义；"
            "用误区对比和找错任务检查其对嵌套规则的真实理解。"
        ),
        title="HTML 嵌套诊断",
        action={
            "type": "teaching_step", "action": "check_understanding",
            "objective_id": "knowledge:html.nesting", "focus_id": "knowledge:html.nesting",
            "source_handles": ["knowledge:html.nesting"],
            "public_message": message,
            "focus_resolution": "stay", "pause_kind": "soft_pause", "escalation_hint": None,
            "teaching_moves": ["misconception_contrast", "error_detection"],
            "interaction": {
                "mode": "composer",
                "intent": "text_answer",
                "artifact_handle": None,
            },
        },
    )


def canonical_tutor_wait_for_input_examples() -> str:
    """Canonical examples for every same-run continuation reason."""

    examples = {
        "clarification": _canonical_provider_example(
            text="你说的“基础”是指语法基础，还是已经会写简单函数？",
            thinking_text="这个词有两种常见含义，先澄清可以避免给出不匹配的内容。",
            title="澄清学习起点",
            action={"type": "wait_for_input", "continuation_kind": "clarification"},
        ),
        "planning_input": _canonical_provider_example(
            text="你每周大约能安排多少分钟学习？",
            thinking_text="学习时长会直接影响计划节奏，因此需要先补齐这一项计划事实。",
            title="制定学习计划",
            action={
                "type": "wait_for_input",
                "continuation_kind": "planning_input",
                "question_key": "weekly_minutes",
            },
        ),
        "approval": _canonical_provider_example(
            text="是否允许执行这项需要明确授权的受控操作？",
            thinking_text="这项操作会改变受控状态，执行前需要你的明确授权。",
            title="确认受控操作",
            action={"type": "wait_for_input", "continuation_kind": "approval"},
        ),
        "capability_result": _canonical_provider_example(
            text="请在已授权的能力检查完成后继续本轮。",
            thinking_text="后续判断依赖能力检查结果，现在不应猜测结果。",
            title="等待能力检查",
            action={"type": "wait_for_input", "continuation_kind": "capability_result"},
        ),
        "external_result": _canonical_provider_example(
            text="请在外部步骤完成并返回结果后继续本轮。",
            thinking_text="外部结果尚未到达，继续推断会产生不可靠结论。",
            title="等待外部结果",
            action={"type": "wait_for_input", "continuation_kind": "external_result"},
        ),
    }
    return " ".join(f"{name}={payload}" for name, payload in examples.items())


def _canonical_provider_example(
    *,
    text: str,
    thinking_text: str,
    title: str,
    action: Mapping[str, object],
) -> str:
    return json.dumps(
        {
            "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
            "message": {
                "type": "agent_message",
                "public_thinking_text": thinking_text,
                "text": text,
                "conversation_title": title,
            },
            "action": dict(action),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def parse_tutor_provider_items(
    payload: Mapping[str, object],
    *,
    run: TutorRunSnapshot,
) -> TutorDecision:
    """Validate typed provider items and assemble server-owned control fields."""

    try:
        envelope = TutorProviderItemsEnvelope.model_validate(payload)
    except ValidationError as exc:
        raise TutorDecisionValidationError(
            "Tutor provider items failed strict schema validation",
            issues=_sanitize_validation_issues(exc),
        ) from exc

    message = envelope.message
    action = envelope.action
    skill_references: tuple[TutorSkillReference, ...] = ()
    capability_requests: tuple[TutorCapabilityRequest, ...] = ()
    effect_proposals: tuple[TutorEffectProposal, ...] = ()
    checkpoint_reason: TutorCheckpointReason | None = None
    continuation_kind: TutorContinuationKind | None = None
    terminal_outcome: TutorTerminalOutcome | None = None
    question_key: TutorPlanningQuestionKey | None = None
    teaching_step: TeachingStepDecision | None = None

    try:
        if isinstance(action, TutorProviderTurnCompletedItem):
            terminal_outcome = TutorTerminalOutcome.COMPLETED
        elif isinstance(action, TutorProviderSelectSkillItem):
            skill_references = (
                TutorSkillReference(skill_id=action.skill_id, version=action.version),
            )
        elif isinstance(action, TutorProviderRequestCapabilityItem):
            capability_requests = (
                TutorCapabilityRequest(
                    request_id=_server_action_id(run=run, prefix="capability"),
                    capability_id=action.capability_id,
                    arguments=payload_fields_from_mapping(
                        _payload_mapping(action.arguments)
                    ),
                ),
            )
        elif isinstance(action, TutorProviderProposeEffectItem):
            effect_proposals = (
                TutorEffectProposal(
                    effect_id=_server_action_id(run=run, prefix="effect"),
                    effect_type=action.effect_type,
                    expected_input_revision=run.input_revision,
                    payload=payload_fields_from_mapping(
                        _payload_mapping(action.payload)
                    ),
                ),
            )
        elif isinstance(action, TutorProviderTeachingStepItem):
            if action.public_message != message.text:
                raise ValueError("teaching action message must match agent message text")
            teaching_step = TeachingStepDecision(
                action=action.action, objective_id=action.objective_id, focus_id=action.focus_id,
                source_handles=tuple(action.source_handles), public_message=action.public_message,
                focus_resolution=action.focus_resolution, pause_kind=action.pause_kind,
                escalation_hint=action.escalation_hint,
                teaching_moves=(tuple(action.teaching_moves) if action.teaching_moves is not None else None),
                learner_response_mode=action.learner_response_mode,
                interaction=action.interaction,
            )
            terminal_outcome = TutorTerminalOutcome.COMPLETED
        elif isinstance(action, TutorProviderWaitForInputItem):
            checkpoint_reason = TutorCheckpointReason.CAPABILITY_RESULT
            continuation_kind = action.continuation_kind
            question_key = action.question_key
        else:  # pragma: no cover - discriminated union is exhaustive.
            raise ValueError("unsupported provider action")

        return TutorDecision(
            public_message=message.text,
            public_thinking_text=message.public_thinking_text,
            conversation_title=message.conversation_title,
            question_key=question_key,
            skill_references=skill_references,
            capability_requests=capability_requests,
            effect_proposals=effect_proposals,
            checkpoint_reason=checkpoint_reason,
            continuation_kind=continuation_kind,
            terminal_outcome=terminal_outcome,
            teaching_step=teaching_step,
        )
    except (TypeError, ValueError) as exc:
        raise TutorDecisionValidationError(
            "Tutor provider items failed authoritative assembly",
            issues=(
                TutorDecisionValidationIssue(path="action", category="invalid_action"),
            ),
        ) from exc


def build_tutor_replacement_message(
    issues: Sequence[TutorDecisionValidationIssue],
    *,
    teaching_policy: str,
) -> str:
    """Build a fresh replacement request from safe paths/categories only."""

    issue_text = (
        ", ".join(f"{issue.path}:{issue.category}" for issue in issues[:8])
        or "root:invalid_contract"
    )
    return (
        "Your previous candidate was rejected. Generate a fresh replacement; do not quote or patch the earlier output. "
        "Return exactly one JSON object and no Markdown or explanation. "
        f"Use schema_version={TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION}. "
        "Return exactly one agent_message in message and exactly one typed action. "
        "message.public_thinking_text must contain one fresh learner-visible public explanation text block before message.text. "
        "Choose its wording, paragraphs, line breaks, tone, and granularity naturally for the current request; do not force "
        "numbered steps or a fixed linguistic template. It is authored public explanation text, not provider-native hidden "
        "reasoning, and must not mention prompts, policies, diagnostics, or secrets. "
        "teaching_step for tutor.lesson-teaching@1.2.0 must use one closed action, exact objective/focus/source handles, "
        "one focus_resolution, one pause_kind, 2..4 unique teaching_moves, and one v3 interaction object. "
        "interaction pairs are none/none/null, composer/text_answer/null, or artifact with one closed artifact intent and an "
        "exact handle advertised for that intent in current artifact_candidates. No candidate or disabled artifact mode means "
        "do not promise editing, running, review, query, structured-answer, or demo interaction. composer requires "
        "check_understanding or wait_for_input plus a diagnostic move; none cannot use those waiting actions. "
        "wait_for_input.continuation_kind must be clarification, planning_input, approval, capability_result, or "
        "external_result. planning_input requires exactly one allowlisted question_key; every other continuation must omit it. "
        "The server owns request_id, effect_id, expected_input_revision, checkpoints, and terminal state; never emit them. "
        f"Validation issues (safe field paths and categories only): {issue_text}. "
        f"Minimal valid direct-reply example: {canonical_tutor_provider_items_example()} "
        f"Valid teaching-step example: {canonical_tutor_teaching_step_example()} "
        f"Valid continuation branch examples: {canonical_tutor_wait_for_input_examples()} "
        f"Keep following this teaching policy: {teaching_policy}"
    )


def validation_diagnostic_code(issues: Sequence[TutorDecisionValidationIssue]) -> str:
    category = issues[0].category if issues else "invalid_contract"
    suffix = {
        "missing": "MISSING_FIELD",
        "extra": "EXTRA_FIELD",
        "invalid_literal": "INVALID_ENUM",
        "invalid_type": "INVALID_TYPE",
        "invalid_action": "INVALID_ACTION",
        "invalid_value": "INVALID_VALUE",
    }.get(category, "INVALID")
    return f"TUTOR_PROVIDER_DECISION_{suffix}"


def _ensure_unique_provider_keys(
    fields: Sequence[TutorProviderPayloadField],
    *,
    label: str,
) -> None:
    keys = [item.key for item in fields]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label} contain duplicate keys")


def _payload_mapping(
    fields: Sequence[TutorProviderPayloadField],
) -> dict[str, TutorProviderValue]:
    return {field.key: field.value for field in fields}


def _server_action_id(*, run: TutorRunSnapshot, prefix: str) -> str:
    seed = f"{run.run_id}:{run.input_revision}:{run.model_call_count}:{prefix}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _sanitize_validation_issues(
    exc: ValidationError,
) -> tuple[TutorDecisionValidationIssue, ...]:
    issues: list[TutorDecisionValidationIssue] = []
    for error in exc.errors(
        include_url=False, include_context=False, include_input=False
    )[:8]:
        raw_location = error.get("loc", ())
        path = ".".join(str(part) for part in raw_location if str(part)) or "root"
        raw_type = str(error.get("type", ""))
        category = _validation_category(raw_type)
        issues.append(TutorDecisionValidationIssue(path=path[:160], category=category))
    return tuple(issues)


def _validation_category(raw_type: str) -> str:
    if raw_type == "missing":
        return "missing"
    if raw_type == "extra_forbidden":
        return "extra"
    if raw_type in {"literal_error", "enum"}:
        return "invalid_literal"
    if raw_type.startswith(("string_", "int_", "float_", "bool_", "list_", "dict_")):
        return "invalid_type"
    if raw_type in {"model_type", "union_tag_invalid", "union_tag_not_found"}:
        return "invalid_type"
    return "invalid_value"
