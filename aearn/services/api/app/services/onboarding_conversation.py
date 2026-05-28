from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from psycopg import Connection

from app.agents.onboarding_conversation_agent import AgentsSDKOnboardingConversationClient
from app.agents.onboarding_slot_extractor import (
    ExtractedSlots,
    build_slot_extractor,
    merge_slots,
    slots_from_context,
)
from app.core.config import Settings, get_settings
from app.models.onboarding import (
    PlanDraft,
    PlanGenerateRequest,
    TimeBudget,
)
from app.services.catalog import get_course
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError
from app.services.plan_generator import build_plan_draft, has_supported_mvp_runtime
from app.services.user_repository import get_user


ONBOARDING_MESSAGE_OPERATION = "onboarding_message"
ROUTE_CARD_READY_MESSAGE = "信息够了，我生成一份路线卡片。想改方向、时间或难度，直接回复我就行。"


class OnboardingTextCompletionClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_text_stream(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> Iterable[str]: ...


class OnboardingSessionNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OnboardingIdempotencyConflictError(ValueError):
    pass


class OnboardingPlanDraftError(ValueError):
    """Raised when the stashed plan draft cannot be built or hydrated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OnboardingConversationContext:
    conversation_id: str
    user_id: str
    status: str
    extracted_context: Mapping[str, object]
    history: Sequence[Mapping[str, str]]


@dataclass(frozen=True)
class PreparedOnboardingMessage:
    conversation_id: str
    user_id: str
    message_id: str
    client_message_id: str
    context: OnboardingConversationContext
    stored_content: str | None
    stored_tool_calls: Sequence[Mapping[str, object]]


@dataclass(frozen=True)
class OnboardingMessageGeneration:
    chunks: Iterable[str]
    generation_source: str
    generation_model: str


def create_onboarding_session(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
) -> str:
    row = conn.execute(
        """
        INSERT INTO onboarding_conversations (user_id, status, extracted_context)
        VALUES (%s, 'active', '{}'::jsonb)
        RETURNING id
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("failed to create onboarding conversation")
    return str(row["id"])


def prepare_onboarding_message(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    user_id: str,
    content: str,
    client_message_id: str,
) -> PreparedOnboardingMessage:
    existing = conn.execute(
        """
        SELECT id, content, role
        FROM onboarding_messages
        WHERE client_message_id = %s
        LIMIT 1
        """,
        (client_message_id,),
    ).fetchone()

    if existing is not None:
        # Idempotency: find the agent response that followed this user message
        agent_msg = conn.execute(
            """
            SELECT content, metadata
            FROM onboarding_messages
            WHERE conversation_id = %s AND role = 'agent' AND created_at > (
                SELECT created_at FROM onboarding_messages WHERE client_message_id = %s
            )
            ORDER BY created_at
            LIMIT 1
            """,
            (conversation_id, client_message_id),
        ).fetchone()
        stored_content = str(agent_msg["content"]) if agent_msg else None
        stored_tool_calls: list[Mapping[str, object]] = []
        if agent_msg is not None:
            metadata = agent_msg.get("metadata") or {}
            if isinstance(metadata, Mapping):
                raw_tool_calls = metadata.get("tool_calls") or []
                if isinstance(raw_tool_calls, list):
                    stored_tool_calls = [
                        tool_call
                        for tool_call in raw_tool_calls
                        if isinstance(tool_call, Mapping)
                    ]
        context = load_onboarding_context(conn, conversation_id=conversation_id, user_id=user_id)
        return PreparedOnboardingMessage(
            conversation_id=conversation_id,
            user_id=user_id,
            message_id=_message_id(conversation_id, client_message_id),
            client_message_id=client_message_id,
            context=context,
            stored_content=stored_content,
            stored_tool_calls=stored_tool_calls,
        )

    # Persist user message
    conn.execute(
        """
        INSERT INTO onboarding_messages (conversation_id, role, content, client_message_id)
        VALUES (%s, 'user', %s, %s)
        """,
        (conversation_id, content, client_message_id),
    )

    context = load_onboarding_context(conn, conversation_id=conversation_id, user_id=user_id)
    return PreparedOnboardingMessage(
        conversation_id=conversation_id,
        user_id=user_id,
        message_id=_message_id(conversation_id, client_message_id),
        client_message_id=client_message_id,
        context=context,
        stored_content=None,
        stored_tool_calls=[],
    )


def store_onboarding_agent_message(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    content: str,
    metadata: Mapping[str, object] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO onboarding_messages (conversation_id, role, content, metadata)
        VALUES (%s, 'agent', %s, %s::jsonb)
        """,
        (conversation_id, content, json.dumps(metadata) if metadata else None),
    )


def list_onboarding_messages(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
) -> list[dict[str, object]]:
    """Return persisted messages with parsed `tool_calls` from metadata.

    Used on session resume so the desktop app can re-render generative-ui
    cards without replaying the live SSE stream.
    """
    conversation = conn.execute(
        """
        SELECT id
        FROM onboarding_conversations
        WHERE id = %s
        """,
        (conversation_id,),
    ).fetchone()
    if conversation is None:
        raise OnboardingSessionNotFoundError("ONBOARDING_SESSION_NOT_FOUND", "建档会话不存在")

    rows = conn.execute(
        """
        SELECT id, role, content, metadata, created_at
        FROM onboarding_messages
        WHERE conversation_id = %s
        ORDER BY created_at
        """,
        (conversation_id,),
    ).fetchall()

    result: list[dict[str, object]] = []
    for row in rows:
        created_at = row.get("created_at")
        metadata = row.get("metadata") or {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        tool_calls = metadata.get("tool_calls") or []
        if not isinstance(tool_calls, list):
            tool_calls = []
        result.append(
            {
                "id": str(row["id"]),
                "role": str(row["role"]),
                "content": str(row["content"]),
                "tool_calls": tool_calls,
                "created_at": created_at.isoformat() if isinstance(created_at, datetime) else None,
            }
        )
    return result


def update_onboarding_status(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    status: str,
) -> None:
    conn.execute(
        """
        UPDATE onboarding_conversations
        SET status = %s
        WHERE id = %s
        """,
        (status, conversation_id),
    )


def load_onboarding_context(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    user_id: str,
) -> OnboardingConversationContext:
    conversation = conn.execute(
        """
        SELECT id, user_id, status, extracted_context
        FROM onboarding_conversations
        WHERE id = %s
        """,
        (conversation_id,),
    ).fetchone()
    if conversation is None:
        raise OnboardingSessionNotFoundError("ONBOARDING_SESSION_NOT_FOUND", "建档会话不存在")

    messages = conn.execute(
        """
        SELECT role, content
        FROM onboarding_messages
        WHERE conversation_id = %s
        ORDER BY created_at
        """,
        (conversation_id,),
    ).fetchall()

    history: list[Mapping[str, str]] = [
        {"role": str(msg["role"]), "content": str(msg["content"])}
        for msg in messages
    ]

    extracted = conversation.get("extracted_context") or {}
    if not isinstance(extracted, Mapping):
        extracted = {}

    return OnboardingConversationContext(
        conversation_id=conversation_id,
        user_id=user_id,
        status=str(conversation["status"]),
        extracted_context=extracted,
        history=history,
    )


def start_onboarding_generation(
    context: OnboardingConversationContext,
    *,
    user_content: str,
    settings: Settings | None = None,
    client: OnboardingTextCompletionClient | None = None,
) -> OnboardingMessageGeneration:
    effective_settings = settings or get_settings()
    if client is None:
        if not effective_settings.openai_compatible_configured:
            raise LLMConfigurationError("Onboarding conversation requires configured model API")
        client = AgentsSDKOnboardingConversationClient(effective_settings)

    messages = _build_messages(context, user_content=user_content)
    return OnboardingMessageGeneration(
        chunks=client.complete_text_stream(messages, temperature=None),
        generation_source="llm",
        generation_model=client.model,
    )


def route_card_ready_generation(
    settings: Settings | None = None,
) -> OnboardingMessageGeneration:
    effective_settings = settings or get_settings()
    return OnboardingMessageGeneration(
        chunks=_chunk_text(ROUTE_CARD_READY_MESSAGE),
        generation_source="llm",
        generation_model=str(effective_settings.openai_model or ""),
    )


def safe_generation_exceptions() -> tuple[type[Exception], ...]:
    return (LLMCallError, LLMConfigurationError, LLMInvalidResponseError, TypeError, ValueError)


def extract_slots(
    context: OnboardingConversationContext,
    settings: Settings | None = None,
) -> ExtractedSlots:
    """Run the LLM extractor over the latest history.

    Returns ExtractedSlots already merged on top of the prior turn's slots,
    so callers can persist the result directly. This project treats the model
    API as required for onboarding; callers should turn LLM failures into a
    user-visible error instead of silently filling slots from keywords.
    """

    prior = slots_from_context(context.extracted_context)
    effective = settings or get_settings()
    extractor = build_slot_extractor(effective)
    if extractor is None:
        raise LLMConfigurationError("Onboarding slot extraction requires configured model API")

    try:
        new = extractor.extract(context.history, prior)
        return merge_slots(prior, new)
    except (LLMCallError, LLMConfigurationError, LLMInvalidResponseError):
        raise
    except Exception as exc:  # noqa: BLE001 - normalize SDK/runtime failures
        raise LLMCallError("Onboarding slot extractor failed") from exc


def detect_plan_proposal(
    context: OnboardingConversationContext,
    slots: ExtractedSlots | None = None,
) -> bool:
    """Return True when the agent should build (or rebuild) a plan draft.

    Triggers on:
      1. plan_ready=True from the extractor, AND
      2. required slots (language, target_level, goal_text) all filled, AND
      3. either no plan_draft is stashed yet, OR the user is currently
         revising, OR newly extracted core slots differ from the stashed draft.
    """

    extracted = slots or slots_from_context(context.extracted_context)
    if not extracted.plan_ready:
        return False
    if not (extracted.language and extracted.target_level and extracted.goal_text):
        return False
    has_stashed = bool(context.extracted_context.get("plan_draft"))
    if has_stashed and not (extracted.revising or _core_slots_changed(context, extracted)):
        return False
    return True


def _core_slots_changed(
    context: OnboardingConversationContext,
    slots: ExtractedSlots,
) -> bool:
    stashed = context.extracted_context.get("plan_draft")
    if not isinstance(stashed, Mapping):
        return False
    return (
        stashed.get("language") != slots.language
        or stashed.get("target_level") != slots.target_level
        or stashed.get("goal_text") != slots.goal_text
    )


def build_plan_draft_from_slots(
    conn: Connection[dict[str, object]],
    *,
    slots: ExtractedSlots,
    user_id: str,
) -> PlanDraft:
    """Hydrate a real PlanDraft from extracted slots.

    Looks up the user and the course matching the extracted language, then
    delegates to plan_generator.build_plan_draft so the resulting draft uses
    the existing course templates without any onboarding-specific logic.
    """

    user = get_user(conn, user_id)
    if user is None:
        raise OnboardingPlanDraftError("USER_NOT_FOUND", "用户不存在")

    if not slots.language:
        raise OnboardingPlanDraftError(
            "LANGUAGE_NOT_SUPPORTED",
            "请告诉我你想学的具体语言（目前支持 Python / JavaScript / HTML+CSS 等）。",
        )

    course = get_course(conn, language=slots.language)
    if course is None:
        raise OnboardingPlanDraftError(
            "LANGUAGE_NOT_SUPPORTED",
            f"目前还没有 {slots.language} 的课程模板，请换一门主流语言。",
        )

    target_level = slots.target_level or "beginner_to_intermediate"
    time_budget = (
        TimeBudget(
            minutes_per_day=slots.time_budget.minutes_per_day,
            days_per_week=slots.time_budget.days_per_week,
        )
        if slots.time_budget is not None
        else None
    )
    goal_text = (slots.goal_text or "").strip()
    if not goal_text:
        raise OnboardingPlanDraftError(
            "PLAN_DRAFT_INVALID", "学习目标信息不足，请再说一两句目标。"
        )

    payload = PlanGenerateRequest(
        user_id=user_id,
        mode="goal_based",
        goal_text=goal_text,
        course_id=str(course["id"]),
        language=slots.language,
        target_level=target_level,
        time_budget=time_budget,
    )

    plan_draft = build_plan_draft(payload, user, course)
    if not has_supported_mvp_runtime(plan_draft):
        raise OnboardingPlanDraftError(
            "PLAN_DRAFT_INVALID", "该课程当前的运行时还不在 MVP 支持范围。"
        )
    return plan_draft


def learning_route_args_from_plan_draft(
    plan_draft: PlanDraft,
    *,
    slots: ExtractedSlots | None = None,
) -> dict[str, object]:
    """Project a real PlanDraft into the LearningRouteArgs SSE shape.

    Mirrors `LearningRouteArgs` in
    `aearn/apps/desktop/src/components/generative-ui/types.ts` so the card
    in the UI displays exactly what will be persisted on confirm.
    """

    modules: list[dict[str, object]] = []
    for module in plan_draft.modules:
        knowledge_points: list[dict[str, object]] = []
        for kp in module.knowledge_points:
            knowledge_points.append(
                {
                    "id": kp.temp_id,
                    "title": kp.title,
                    "status": "pending",
                    "mastery_score": 0.0,
                }
            )
        modules.append(
            {
                "id": module.temp_id,
                "title": module.title,
                "order_index": module.order_index,
                "status": "pending",
                "estimated_sessions": module.estimated_sessions,
                "knowledge_points": knowledge_points,
            }
        )
    return {
        "plan_id": plan_draft.draft_id,
        "goal_text": plan_draft.goal_text,
        "language": plan_draft.language,
        "time_budget": _learning_route_time_budget(slots),
        "modules": modules,
    }


def _learning_route_time_budget(slots: ExtractedSlots | None) -> dict[str, int] | None:
    if slots is None or slots.time_budget is None:
        return None
    return {
        "minutes_per_day": slots.time_budget.minutes_per_day,
        "days_per_week": slots.time_budget.days_per_week,
    }


def stash_plan_draft(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    plan_draft: PlanDraft,
    slots: ExtractedSlots,
) -> None:
    """Atomically write merged slots + serialized PlanDraft to the row."""

    payload: dict[str, object] = slots.model_dump(mode="json")
    payload["plan_draft"] = plan_draft.model_dump(mode="json")
    # Once a draft is stashed for the current set of slots, clear the
    # "revising" flag so a subsequent unrelated turn doesn't keep
    # overwriting the draft.
    payload["revising"] = False
    conn.execute(
        """
        UPDATE onboarding_conversations
        SET
          status = 'plan_proposed',
          extracted_context = COALESCE(extracted_context, '{}'::jsonb) || %s::jsonb
        WHERE id = %s
        """,
        (json.dumps(payload), conversation_id),
    )


def persist_extracted_slots(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
    slots: ExtractedSlots,
) -> None:
    """Persist the freshly merged slots without touching the stashed draft."""

    payload = slots.model_dump(mode="json")
    conn.execute(
        """
        UPDATE onboarding_conversations
        SET extracted_context = COALESCE(extracted_context, '{}'::jsonb) || %s::jsonb
        WHERE id = %s
        """,
        (json.dumps(payload), conversation_id),
    )


def load_stashed_plan_draft(
    conn: Connection[dict[str, object]],
    *,
    conversation_id: str,
) -> PlanDraft | None:
    """Read and hydrate the stashed PlanDraft, if any."""

    row = conn.execute(
        """
        SELECT extracted_context
        FROM onboarding_conversations
        WHERE id = %s
        """,
        (conversation_id,),
    ).fetchone()
    if row is None:
        return None
    extracted = row.get("extracted_context") or {}
    if not isinstance(extracted, Mapping):
        return None
    raw_draft = extracted.get("plan_draft")
    if not isinstance(raw_draft, Mapping):
        return None
    try:
        return PlanDraft.model_validate(raw_draft)
    except Exception:  # noqa: BLE001 - corrupt blob shouldn't crash callers
        return None


def _build_messages(
    context: OnboardingConversationContext,
    *,
    user_content: str,
) -> list[dict[str, str]]:
    extracted = slots_from_context(context.extracted_context)
    slot_status = json.dumps(
        {
            "language": extracted.language,
            "target_level": extracted.target_level,
            "goal_text": extracted.goal_text,
            "time_budget": extracted.time_budget.model_dump() if extracted.time_budget else None,
            "focus": extracted.focus,
            "plan_ready": extracted.plan_ready,
        },
        ensure_ascii=False,
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是 Aearn 的建档引导 Agent，帮用户把'想学编程'的模糊念头收敛成一份具体的学习计划。\n"
                "你的角色更像一个懂行的朋友在帮 ta 理思路，不是问卷调查员。\n"
                "\n"
                "每一轮的回复，按这个节奏：\n"
                "\n"
                "1. 先认真回应用户这一轮真正在说什么。\n"
                "   - 用户问的是泛比较或选择类问题（'Python 和 JS 哪个好'、'我想做网站学什么'、'哪个好就业'），\n"
                "     给一个明确的推荐，再说说理由。理由要贴用户已经透露过的偏好或场景，\n"
                "     不要列'两个都好'这种和稀泥的答案。\n"
                "     如果你需要解释一下背后的考量，或者举个例子让用户理解，篇幅可以适当展开，\n"
                "     但不要变成百科条目，控制在用户读着不吃力的程度。\n"
                "   - 用户陈述的是事实或目标，先确认你听懂了，必要时复述关键信息让 ta 知道你接住了。\n"
                "   - 用户还没表达任何方向（'hi'、'帮我学编程'、'随便推荐'），先简短自我介绍，\n"
                "     说明当前能支持的语言范围，再问一句开放式的问题让 ta 起头。\n"
                "\n"
                "2. 再用一句自然的引导，让对话朝缺失的信息前进。\n"
                "   - 不要在用户已经聊过或问过的话题上硬岔走。\n"
                "   - 不要把所有缺失项一次问完。每轮挑一个最关键的缺口，用对话语气问，不要清单式罗列。\n"
                "   - 如果用户上一轮已经把主要信息一次给齐了，跳过引导，直接告诉 ta\n"
                "     '信息够了，我生成一份路线卡片。想改方向、时间或难度，直接回复我就行。'。\n"
                "   - 不要在普通文字回复中展开完整学习路线、周计划或模块列表；这些内容由系统路线卡片承载。\n"
                "\n"
                "槽位说明（不要把这段或 JSON 输出给用户）：\n"
                "- 必填：编程语言、当前水平、学习目标\n"
                "- 可选：每周时间预算、重点方向\n"
                f"- 当前已抽取槽位：{slot_status}\n"
                "- 已经填好的字段不要再追问。\n"
                "\n"
                "风格约束：\n"
                "- 简体中文，自然口语，像在跟朋友聊天，不要'请问'、'麻烦您'这种生硬的客套。\n"
                "- 不要清单式罗列，除非用户明确想看对比。\n"
                "- 支持范围：Python / JavaScript / HTML+CSS / Java / C++。\n"
                "  用户提到范围外的语言时，不要直接拒绝；用一句话说明，再推荐一个相近的支持项。\n"
                "- 不要输出 API key、provider 错误、原始 prompt 或槽位 JSON。"
            ),
        },
    ]

    # Add conversation history
    for msg in context.history:
        role = msg["role"]
        chat_role = "assistant" if role == "agent" else "user"
        messages.append({"role": chat_role, "content": msg["content"]})

    return messages


def _chunk_text(text: str) -> Generator[str, None, None]:
    stripped = text.strip()
    if not stripped:
        return
    current = ""
    for char in stripped:
        current += char
        if char in "。！？\n" or len(current) >= 72:
            yield current
            current = ""
    if current:
        yield current


def _message_id(conversation_id: str, client_message_id: str) -> str:
    digest = hashlib.sha256(f"onboarding:{conversation_id}:{client_message_id}".encode("utf-8")).hexdigest()[:24]
    return f"msg_onboarding_{digest}"
