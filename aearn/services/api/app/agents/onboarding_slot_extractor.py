from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings, get_settings
from app.models.onboarding import Language, TargetLevel
from app.services.llm_client import (
    LLMConfigurationError,
    LLMInvalidResponseError,
    OpenAICompatibleClient,
)


class TimeBudgetSlot(BaseModel):
    minutes_per_day: int = Field(ge=1)
    days_per_week: int = Field(ge=1, le=7)


class ExtractedSlots(BaseModel):
    """Slot extraction result for the onboarding conversation.

    All fields are cumulative across turns: if a field was set on a prior
    turn and the new turn doesn't change it, the prior value should be
    repeated. The model must judge `plan_ready` based on whether the required
    slots (language, target_level, goal_text) are filled with meaningful values.
    """

    language: Language | None = None
    target_level: TargetLevel | None = None
    goal_text: str | None = None
    time_budget: TimeBudgetSlot | None = None
    focus: str | None = None
    plan_ready: bool = False
    missing_slot_question: str | None = None
    revising: bool = False


_EXTRACTOR_INSTRUCTIONS = (
    "你是 Aearn 的建档槽位提取助手。从对话历史中识别用户的学习目标，填充结构化槽位。\n"
    "\n"
    "规则：\n"
    "1. 只输出符合 schema 的对象，不要附加任何解释文字。\n"
    "2. 累积式合并：上一轮已填的字段，如果本轮用户没有否定或修改，保留旧值。\n"
    "3. language 仅能取 'javascript' | 'python' | 'java' | 'cpp' | 'html_css'，无法判断时返回 null。\n"
    "4. target_level 仅能取 'beginner' | 'intermediate' | 'advanced' | 'beginner_to_intermediate'，无法判断时返回 null。\n"
    "5. goal_text 用一句中文概述用户的学习目标，至少 10 个汉字；信息不足时返回 null。\n"
    "6. time_budget = { minutes_per_day, days_per_week }，两个字段都是正整数；信息不足时返回 null。\n"
    "7. focus 是重点方向自由文本（如 'Web 开发'、'数据分析'、'算法竞赛'）；不明确时返回 null。\n"
    "8. plan_ready: 仅当 language、target_level、goal_text 都已填上有意义的值时设为 true，否则 false。\n"
    "9. missing_slot_question: plan_ready=false 时给出下一轮最该追问的中文问题（按缺啥问啥），plan_ready=true 时返回 null。\n"
    "10. revising: 如果用户最新一条消息表达了调整方向、语言、水平或时间预算的意图（如 '想调整'、'改成数据分析'、'每周只有 2 小时'），设为 true，否则 false。\n"
    "11. 如果用户表达的语言不在支持范围内，language 保持 null，并在 missing_slot_question 中提示支持范围。\n"
    "12. '学过一点'、'看过基础语法'、'会一点'、'接触过'、'写过一点' 通常归为 beginner_to_intermediate，除非用户同时给出更明确的水平。\n"
)


class ResponsesOnboardingSlotExtractor:
    """LLM-based slot extractor using the streaming Responses JSON path."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: OpenAICompatibleClient | None = None,
    ) -> None:
        self._client = client or OpenAICompatibleClient(settings)

    @property
    def model(self) -> str:
        return self._client.model

    def extract(
        self,
        history: Sequence[Mapping[str, str]],
        prior_slots: ExtractedSlots,
    ) -> ExtractedSlots:
        """Run the extractor synchronously.

        Raises LLMCallError / LLMInvalidResponseError on provider or schema
        failures. The underlying client always requests streaming Responses
        output and parses the final JSON object before returning.
        """

        response = self._client.complete_json(
            [
                {"role": "system", "content": _EXTRACTOR_INSTRUCTIONS},
                {"role": "user", "content": _format_extractor_input(history, prior_slots)},
            ]
        )
        try:
            return ExtractedSlots.model_validate(response.content)
        except ValidationError as exc:
            raise LLMInvalidResponseError(
                "Onboarding slot extractor returned invalid structured output"
            ) from exc


def merge_slots(prior: ExtractedSlots, new: ExtractedSlots) -> ExtractedSlots:
    """Cumulative merge: never let a None overwrite a previously set value.

    Booleans (`plan_ready`, `revising`) and `missing_slot_question` are
    always taken from the latest extraction since they reflect the current
    turn's judgement.
    """

    return ExtractedSlots(
        language=new.language if new.language is not None else prior.language,
        target_level=new.target_level if new.target_level is not None else prior.target_level,
        goal_text=new.goal_text if new.goal_text is not None else prior.goal_text,
        time_budget=new.time_budget if new.time_budget is not None else prior.time_budget,
        focus=new.focus if new.focus is not None else prior.focus,
        plan_ready=new.plan_ready,
        missing_slot_question=new.missing_slot_question,
        revising=new.revising,
    )


def slots_from_context(extracted_context: Mapping[str, object]) -> ExtractedSlots:
    """Hydrate ExtractedSlots from a stored extracted_context mapping.

    Unknown / missing fields fall back to defaults; invalid stored values
    are silently ignored so a corrupt blob doesn't break the conversation.
    """

    payload: dict[str, object] = {}
    for key in (
        "language",
        "target_level",
        "goal_text",
        "time_budget",
        "focus",
        "plan_ready",
        "missing_slot_question",
        "revising",
    ):
        if key in extracted_context:
            payload[key] = extracted_context[key]
    try:
        return ExtractedSlots.model_validate(payload)
    except Exception:  # noqa: BLE001 - best-effort hydration
        return ExtractedSlots()


def _format_extractor_input(
    history: Sequence[Mapping[str, str]],
    prior_slots: ExtractedSlots,
) -> str:
    lines: list[str] = ["对话历史："]
    for msg in history:
        role = str(msg.get("role", "")).lower()
        speaker = "User" if role == "user" else "Assistant"
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        lines.append(f"{speaker}: {content}")
    lines.append("")
    lines.append("上一轮已经填好的槽位（请累积式合并，不要清空已填字段）：")
    lines.append(
        json.dumps(
            prior_slots.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        )
    )
    lines.append("")
    lines.append("请输出新的 ExtractedSlots 结构。")
    return "\n".join(lines)


def build_slot_extractor(
    settings: Settings | None = None,
) -> ResponsesOnboardingSlotExtractor | None:
    effective = settings or get_settings()
    if not effective.openai_compatible_configured:
        return None
    try:
        return ResponsesOnboardingSlotExtractor(effective)
    except LLMConfigurationError:
        return None
