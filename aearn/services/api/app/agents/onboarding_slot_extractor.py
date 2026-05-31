from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field, ValidationError

from app.agents.structured_judgement import StructuredJudgement as SlotJudgement
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
    repeated only when the slot status remains confirmed. Ambiguous, missing,
    or unsupported latest-turn judgements must be represented in slot_statuses
    so the service can ask a clarification before committing a new slot value.
    """

    language: Language | None = None
    target_level: TargetLevel | None = None
    goal_text: str | None = None
    time_budget: TimeBudgetSlot | None = None
    focus: str | None = None
    plan_ready: bool = False
    missing_slot_question: str | None = None
    unsupported_language: str | None = None
    revising: bool = False
    slot_statuses: dict[str, SlotJudgement] = Field(default_factory=dict)


_EXTRACTOR_INSTRUCTIONS = (
    "你是 Aearn 的建档槽位提取助手。从对话历史中识别用户的学习目标，填充结构化槽位。\n"
    "\n"
    "规则：\n"
    "1. 只输出符合 schema 的对象，不要附加任何解释文字。\n"
    "2. 累积式合并：上一轮已填的字段，如果本轮用户没有否定或修改，保留旧值。\n"
    "3. 每个槽位都必须在 slot_statuses 中给出结构化判断。键名包括 language、target_level、goal_text、time_budget、focus。\n"
    "   status 只能是 confirmed、ambiguous、missing、unsupported。\n"
    "   confirmed 表示可以写入正式槽位；ambiguous/missing/unsupported 表示不能写入该槽位，必须给 ambiguity_type、evidence、ambiguity_reason 和 clarification_question。\n"
    "   ambiguity_type 可从这些类型中选择，也可以自定义短 snake_case 类型：value_missing、value_too_broad、value_ambiguous、slot_mapping_ambiguous、unit_missing、frequency_missing、scope_missing、level_uncertain、goal_unclear、language_alias_ambiguous、priority_conflict、value_conflict、context_conflict、unsupported_or_alias、revision_ambiguous、confirmation_ambiguous、reference_ambiguous、relative_reference_ambiguous、feasibility_risk。\n"
    "4. language 仅能取 'javascript' | 'python' | 'java' | 'cpp' | 'html_css'。只有 status=confirmed 时才能填 language；做网页、前端、AI、脚本等多义方向应设 ambiguous。\n"
    "5. target_level 仅能取 'beginner' | 'intermediate' | 'advanced' | 'beginner_to_intermediate'。只有 status=confirmed 时才能填 target_level；'学过一点'、'还行'、'看过视频' 等无法落档时设 ambiguous。\n"
    "6. goal_text 用一句中文概述用户的学习目标，至少 10 个汉字。想学编程、做 AI、找工作、提升能力等目标太泛时设 ambiguous，不要填 goal_text。\n"
    "7. time_budget = { minutes_per_day, days_per_week }，两个字段都是正整数。只有明确周期和时长时才能填；任何单位、周期、频率或指代不清都设 ambiguous，不要推断。\n"
    "8. focus 是重点方向自由文本；可选，不阻塞路线生成。没有重点方向时设 missing 且不追问；如果用户最新表达了重点方向但方向过宽、冲突或指代不清，设 ambiguous 并追问。\n"
    "9. plan_ready: 仅当 language、target_level、goal_text 的 status 都是 confirmed 且对应值有意义，并且用户最新给出的可选槽位没有 ambiguous/unsupported 时设 true，否则 false。\n"
    "10. missing_slot_question: plan_ready=false 时使用最高优先级非 confirmed 槽位的 clarification_question；追问优先级为 language -> goal_text -> target_level -> time_budget -> focus；plan_ready=true 时返回 null。\n"
    "11. unsupported_language: 如果用户最新明确选择了无法映射到 language 枚举的语言，填原始语言名（如 'TypeScript'、'Rust'、'Go'）；否则返回 null。\n"
    "    如果用户接受的是 '先学 JavaScript/JS，再过渡 TypeScript/TS'，language='javascript'，unsupported_language=null。\n"
    "12. revising: 如果用户最新一条消息表达了调整方向、语言、水平或时间预算的意图（如 '想调整'、'改成数据分析'、'每周只有 2 小时'），设为 true，否则 false。\n"
    "13. 如果用户表达的语言不在支持范围内，language 保持 null，unsupported_language 填原始语言名，并在 missing_slot_question 中提示支持范围。\n"
    "14. 不要为了让 plan_ready=true 而猜测模糊值；宁可追问，也不要把不确定信息放进正式槽位。\n"
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

    Booleans (`plan_ready`, `revising`), `unsupported_language`, and `missing_slot_question` are
    always taken from the latest extraction since they reflect the current
    turn's judgement.
    """

    slot_statuses = {**prior.slot_statuses, **new.slot_statuses}
    return ExtractedSlots(
        language=_merged_slot_value("language", prior.language, new.language, slot_statuses),
        target_level=_merged_slot_value(
            "target_level", prior.target_level, new.target_level, slot_statuses
        ),
        goal_text=_merged_slot_value("goal_text", prior.goal_text, new.goal_text, slot_statuses),
        time_budget=_merged_slot_value(
            "time_budget", prior.time_budget, new.time_budget, slot_statuses
        ),
        focus=_merged_slot_value("focus", prior.focus, new.focus, slot_statuses),
        plan_ready=new.plan_ready,
        missing_slot_question=new.missing_slot_question or _first_clarification_question(slot_statuses),
        unsupported_language=new.unsupported_language,
        revising=new.revising,
        slot_statuses=slot_statuses,
    )


def _merged_slot_value(
    slot_name: str,
    prior_value,
    new_value,
    slot_statuses: Mapping[str, SlotJudgement],
):
    judgement = slot_statuses.get(slot_name)
    if judgement is not None and judgement.status != "confirmed":
        return None
    return new_value if new_value is not None else prior_value


def _first_clarification_question(
    slot_statuses: Mapping[str, SlotJudgement],
) -> str | None:
    for slot_name in ("language", "goal_text", "target_level", "time_budget", "focus"):
        judgement = slot_statuses.get(slot_name)
        if judgement is not None and judgement.status != "confirmed":
            question = (judgement.clarification_question or "").strip()
            if question:
                return question
    return None


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
        "unsupported_language",
        "revising",
        "slot_statuses",
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
