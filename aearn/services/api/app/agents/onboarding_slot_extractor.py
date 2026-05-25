from __future__ import annotations

import asyncio
import json
import queue
import re
import threading
from collections.abc import Mapping, Sequence
from typing import Any, cast

from agents import Agent, ModelSettings
from pydantic import BaseModel, Field

from app.agents.sdk_runtime import AgentsSDKRunner, build_run_config
from app.core.config import Settings, get_settings
from app.models.onboarding import Language, TargetLevel
from app.services.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
)


ONBOARDING_SLOT_EXTRACTOR_AGENT_NAME = "Aearn Onboarding Slot Extractor"


class TimeBudgetSlot(BaseModel):
    minutes_per_day: int = Field(ge=1)
    days_per_week: int = Field(ge=1, le=7)


class ExtractedSlots(BaseModel):
    """Slot extraction result for the onboarding conversation.

    All fields are cumulative across turns: if a field was set on a prior
    turn and the new turn doesn't change it, the prior value should be
    repeated. The agent (or keyword fallback) must judge `plan_ready` based
    on whether the required slots (language, target_level, goal_text) are
    filled with meaningful values.
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
    "10. revising: 如果用户最新一条消息表达了 '想调整 / 换语言 / 不对 / 改一下' 等修订计划的意图，设为 true，否则 false。\n"
    "11. 如果用户表达的语言不在支持范围内，language 保持 null，并在 missing_slot_question 中提示支持范围。\n"
)


class AgentsSDKOnboardingSlotExtractor:
    """LLM-based slot extractor using the Agents SDK structured output."""

    def __init__(
        self,
        settings: Settings,
        *,
        runner: AgentsSDKRunner | None = None,
    ) -> None:
        self._settings = settings
        self._run_config = build_run_config(settings)
        self._runner = runner

    @property
    def model(self) -> str:
        return str(self._settings.openai_model or "")

    def extract(
        self,
        history: Sequence[Mapping[str, str]],
        prior_slots: ExtractedSlots,
    ) -> ExtractedSlots:
        """Run the extractor synchronously.

        Internally spawns a worker thread that executes the async runner so
        callers (sync or async) get a single ExtractedSlots instance back.
        Raises LLMCallError / LLMInvalidResponseError on failure.
        """

        agent = Agent(
            name=ONBOARDING_SLOT_EXTRACTOR_AGENT_NAME,
            instructions=_EXTRACTOR_INSTRUCTIONS,
            model=self.model,
            model_settings=ModelSettings(temperature=None),
            tools=[],
            output_type=ExtractedSlots,
        )

        runner = self._runner
        if runner is None:
            from agents import Runner

            runner = cast(AgentsSDKRunner, Runner)

        input_text = _format_extractor_input(history, prior_slots)

        result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        async def consume() -> ExtractedSlots:
            run_result = await runner.run(  # type: ignore[attr-defined]
                agent,
                input_text,
                max_turns=2,
                run_config=self._run_config,
            )
            final = getattr(run_result, "final_output", None)
            if isinstance(final, ExtractedSlots):
                return final
            if isinstance(final, Mapping):
                return ExtractedSlots.model_validate(final)
            raise LLMInvalidResponseError(
                "Onboarding slot extractor returned no structured output"
            )

        def worker() -> None:
            try:
                result = asyncio.run(consume())
                result_queue.put(("ok", result))
            except BaseException as exc:  # noqa: BLE001 - bridge thread errors
                result_queue.put(("err", exc))

        thread = threading.Thread(
            target=worker, name="aearn-slot-extractor", daemon=True
        )
        thread.start()
        thread.join()

        if result_queue.empty():
            raise LLMCallError("Onboarding slot extractor produced no result")

        status, payload = result_queue.get()
        if status == "err":
            if isinstance(payload, (LLMCallError, LLMConfigurationError, LLMInvalidResponseError)):
                raise payload
            raise LLMCallError("Onboarding slot extractor failed") from payload
        return cast(ExtractedSlots, payload)


_LANGUAGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("python", re.compile(r"\bpython\b|蟒蛇|派森", re.IGNORECASE)),
    ("javascript", re.compile(r"\bjavascript\b|\bjs\b|node|前端", re.IGNORECASE)),
    ("html_css", re.compile(r"\bhtml\b|\bcss\b|网页|静态页面", re.IGNORECASE)),
    ("java", re.compile(r"\bjava\b(?!script)", re.IGNORECASE)),
    ("cpp", re.compile(r"c\+\+|\bcpp\b", re.IGNORECASE)),
]
_TARGET_LEVEL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("beginner", re.compile(r"零基础|入门|从零|新手|完全没学过|什么都不会")),
    ("advanced", re.compile(r"高级|资深|多年经验|高阶")),
    ("intermediate", re.compile(r"进阶|中级|有经验|有基础")),
]
_REVISE_PATTERN = re.compile(r"调整|换一?个|不对|改一改|改一下|重新")
_FOCUS_PATTERN = re.compile(
    r"web|后端|前端|全栈|数据(?:分析|科学|挖掘)?|算法|爬虫|游戏|自动化|测试|机器学习|ai|脚本",
    re.IGNORECASE,
)
_TIME_HOUR_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:个)?\s*(小时|h|hr)", re.IGNORECASE)
_TIME_MINUTE_PATTERN = re.compile(r"(\d+)\s*(分钟|min)", re.IGNORECASE)
_DAYS_WEEK_PATTERN = re.compile(r"每?周\s*(\d+)\s*(?:天|次)")
_DAILY_PATTERN = re.compile(r"每[天日]")


def keyword_extract_slots(
    history: Sequence[Mapping[str, str]],
    prior_slots: ExtractedSlots,
) -> ExtractedSlots:
    """Deterministic fallback when the LLM extractor is unavailable.

    Scans the user-side messages with regex/substring rules and merges the
    findings on top of the prior slots. Only sets a field when the latest
    history clearly evidences it; otherwise prior values are preserved.
    """

    user_text = "\n".join(
        str(msg.get("content", ""))
        for msg in history
        if str(msg.get("role", "")).lower() == "user"
    )
    last_user_message = ""
    for msg in reversed(list(history)):
        if str(msg.get("role", "")).lower() == "user":
            last_user_message = str(msg.get("content", ""))
            break

    language: Language | None = prior_slots.language
    for code, pattern in _LANGUAGE_PATTERNS:
        if pattern.search(user_text):
            language = cast(Language, code)
            break

    target_level: TargetLevel | None = prior_slots.target_level
    for level, pattern in _TARGET_LEVEL_PATTERNS:
        if pattern.search(user_text):
            target_level = cast(TargetLevel, level)
            break

    focus: str | None = prior_slots.focus
    focus_match = _FOCUS_PATTERN.search(user_text)
    if focus_match:
        focus = focus_match.group(0)

    time_budget = prior_slots.time_budget
    minutes_per_day: int | None = None
    hour_match = _TIME_HOUR_PATTERN.search(user_text)
    if hour_match:
        try:
            minutes_per_day = int(round(float(hour_match.group(1)) * 60))
        except ValueError:
            minutes_per_day = None
    if minutes_per_day is None:
        minute_match = _TIME_MINUTE_PATTERN.search(user_text)
        if minute_match:
            try:
                minutes_per_day = int(minute_match.group(1))
            except ValueError:
                minutes_per_day = None

    days_per_week: int | None = None
    week_match = _DAYS_WEEK_PATTERN.search(user_text)
    if week_match:
        try:
            days_per_week = max(1, min(7, int(week_match.group(1))))
        except ValueError:
            days_per_week = None
    if days_per_week is None and _DAILY_PATTERN.search(user_text):
        days_per_week = 7

    if minutes_per_day and minutes_per_day > 0:
        time_budget = TimeBudgetSlot(
            minutes_per_day=minutes_per_day,
            days_per_week=days_per_week or 5,
        )

    goal_text: str | None = prior_slots.goal_text
    candidate_goal = _build_keyword_goal_text(
        language=language, focus=focus, target_level=target_level, history=history
    )
    if candidate_goal:
        goal_text = candidate_goal

    revising = bool(_REVISE_PATTERN.search(last_user_message))

    plan_ready = bool(language and target_level and goal_text and len(goal_text) >= 10)
    missing_slot_question = (
        None if plan_ready else _next_missing_slot_question(
            language=language, target_level=target_level, goal_text=goal_text
        )
    )

    return ExtractedSlots(
        language=language,
        target_level=target_level,
        goal_text=goal_text,
        time_budget=time_budget,
        focus=focus,
        plan_ready=plan_ready,
        missing_slot_question=missing_slot_question,
        revising=revising,
    )


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


def _build_keyword_goal_text(
    *,
    language: Language | None,
    focus: str | None,
    target_level: TargetLevel | None,
    history: Sequence[Mapping[str, str]],
) -> str | None:
    if not language:
        return None
    parts: list[str] = []
    parts.append(f"学习 {_language_display(language)}")
    if focus:
        parts.append(f"聚焦 {focus}")
    if target_level == "beginner":
        parts.append("从零基础入门")
    elif target_level == "intermediate":
        parts.append("从已有基础进阶")
    elif target_level == "advanced":
        parts.append("达到高级水平")
    elif target_level == "beginner_to_intermediate":
        parts.append("从入门到进阶")
    base = "，".join(parts)
    # If we still don't have ≥10 chars, append the last user message excerpt.
    if len(base) < 10:
        for msg in reversed(list(history)):
            if str(msg.get("role", "")).lower() == "user":
                snippet = str(msg.get("content", "")).strip()[:60]
                if snippet:
                    base = f"{base}（{snippet}）" if base else snippet
                break
    return base if len(base) >= 10 else None


def _language_display(language: Language) -> str:
    return {
        "python": "Python",
        "javascript": "JavaScript",
        "java": "Java",
        "cpp": "C++",
        "html_css": "HTML / CSS",
    }.get(language, str(language))


def _next_missing_slot_question(
    *,
    language: Language | None,
    target_level: TargetLevel | None,
    goal_text: str | None,
) -> str:
    if not language:
        return "你想学的是哪门编程语言？目前主要支持 Python、JavaScript、HTML / CSS。"
    if not target_level:
        return "你目前的水平大致是哪一档？零基础 / 有一些基础 / 已经比较进阶？"
    if not goal_text or len(goal_text) < 10:
        return "可以再多说一两句你的学习目标吗？比如想做哪类项目，或者达到什么效果。"
    return "还想补充什么具体目标或时间安排吗？"


def build_slot_extractor(
    settings: Settings | None = None,
) -> AgentsSDKOnboardingSlotExtractor | None:
    effective = settings or get_settings()
    if not effective.openai_compatible_configured:
        return None
    try:
        return AgentsSDKOnboardingSlotExtractor(effective)
    except LLMConfigurationError:
        return None
