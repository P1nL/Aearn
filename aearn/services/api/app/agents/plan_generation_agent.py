from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from agents import Runner

from app.agents.agent_runtime_context import limit_text, parse_fenced_json_object
from app.agents.guardrails import assert_safe_teaching_output, build_teaching_guardrails
from app.agents.sdk_runtime import (
    AgentsSDKRunner,
    build_agent,
    build_run_config,
    iter_streamed_text,
    split_chat_messages,
    stream_text_deltas,
)
from app.agents.tools_web import build_web_tools
from app.core.config import Settings, get_settings
from app.models.onboarding import (
    DraftKnowledgePoint,
    DraftModule,
    PlanGenerateRequest,
)
from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError


logger = logging.getLogger(__name__)

PLAN_GENERATION_AGENT_NAME = "Aearn Plan Generation"

AUTHORITATIVE_DOCS: dict[str, list[str]] = {
    "python": ["https://docs.python.org/3/tutorial/"],
    "javascript": ["https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide"],
    "html_css": [
        "https://developer.mozilla.org/en-US/docs/Learn/HTML",
        "https://developer.mozilla.org/en-US/docs/Learn/CSS",
    ],
    "typescript": ["https://www.typescriptlang.org/docs/handbook/"],
    "rust": ["https://doc.rust-lang.org/book/"],
    "go": ["https://go.dev/tour/", "https://go.dev/doc/effective_go"],
    "java": ["https://docs.oracle.com/javase/tutorial/"],
    "cpp": ["https://en.cppreference.com/w/cpp/language"],
}

_TEMP_ID_MODULE_RE = re.compile(r"^mod_draft_[a-z][a-z0-9_]*_[a-z][a-z0-9_]*$")
_TEMP_ID_KP_RE = re.compile(r"^kp_draft_[a-z][a-z0-9_]*_[a-z][a-z0-9_]*$")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")

_MIN_MODULES = 4
_MAX_MODULES = 8
_MIN_KPS = 2
_MAX_KPS = 4

SAFE_GENERATION_EXCEPTIONS = (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    TypeError,
    ValueError,
    TimeoutError,
)

_SYSTEM_PROMPT = """\
你是 Aearn 的学习路线规划师。你的任务是为中文用户生成编程学习模块。

## 工作流程

1. 如果提供了权威文档 URL，使用 fetch_doc_toc 获取文档目录结构
2. 如果没有提供 URL 或获取失败，使用 web_search 搜索该语言的权威教程文档
3. 基于文档目录结构和用户上下文，生成学习模块

## 输出要求

- 输出严格 JSON，不要包含任何其他文本
- title 和 description 必须为中文
- 每个路线 4-8 个模块，每个模块 2-4 个知识点
- 模块顺序应参考官方文档的教学顺序
- 根据用户水平调整深度：beginner 侧重基础语法，intermediate 加入进阶概念

## 输出 JSON Schema

```json
{
  "modules": [
    {
      "temp_id": "mod_draft_{language}_{english_slug}",
      "title": "中文模块标题",
      "description": "中文模块描述，说明学习内容和目标",
      "order_index": 0,
      "is_skippable": false,
      "estimated_sessions": 3,
      "knowledge_points": [
        {
          "temp_id": "kp_draft_{language}_{english_slug}",
          "title": "中文知识点标题",
          "description": "中文知识点描述",
          "skill_tags": ["tag1", "tag2"],
          "exercise_refs": []
        }
      ]
    }
  ],
  "source_urls": ["实际参考的文档 URL"],
  "generation_notes": "简要说明参考了哪些文档章节"
}
```

## 约束

- temp_id 中的 slug 部分使用英文小写和下划线
- is_skippable: 核心基础模块为 false，进阶可选模块为 true
- estimated_sessions: 根据内容量估算，通常 2-4
- skill_tags: 使用英文小写标签
- 不得承诺 Java/C++ 的完整编译运行沙箱
- 不得输出参考答案或隐藏测试内容
"""


@dataclass(frozen=True)
class PlanGenerationContext:
    language: str
    target_level: str
    goal_text: str
    mode: str
    time_budget: Mapping[str, object] | None
    profession: str
    doc_urls: list[str]


@dataclass(frozen=True)
class PlanGenerationJsonResponse:
    content: dict[str, object]
    model: str


@dataclass(frozen=True)
class PlanGenerationResult:
    modules: list[DraftModule]
    source_attribution: list[str]
    model: str


class PlanGenerationClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        context: PlanGenerationContext,
        *,
        temperature: float | None = None,
    ) -> PlanGenerationJsonResponse: ...


class AgentsSDKPlanGenerationClient:
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
        return str(self._settings.llm_model or "")

    def complete_json(
        self,
        context: PlanGenerationContext,
        *,
        temperature: float | None = None,
    ) -> PlanGenerationJsonResponse:
        messages = _build_messages(context)
        instructions, input_text = split_chat_messages(messages)
        input_guardrails, output_guardrails = build_teaching_guardrails()
        tools = build_web_tools(self._settings)
        agent = build_agent(
            name=PLAN_GENERATION_AGENT_NAME,
            instructions=instructions,
            model=self.model,
            temperature=temperature,
            tools=tools,
            input_guardrails=input_guardrails,
            output_guardrails=output_guardrails,
        )
        runner = self._runner
        if runner is None:
            runner = cast(AgentsSDKRunner, Runner)

        chunks = iter_streamed_text(
            lambda: stream_text_deltas(
                runner=runner,
                agent=agent,
                input_text=input_text,
                run_config=self._run_config,
                max_turns=6,
            )
        )
        content = "".join(chunks).strip()
        return PlanGenerationJsonResponse(content=_parse_json_object(content), model=self.model)


def build_plan_generation_client(
    settings: Settings | None = None,
    *,
    runner: AgentsSDKRunner | None = None,
) -> PlanGenerationClient | None:
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    if not effective_settings.plan_generation_enabled:
        return None
    if not effective_settings.exa_api_key:
        return None
    try:
        return AgentsSDKPlanGenerationClient(effective_settings, runner=runner)
    except LLMConfigurationError:
        return None


def build_plan_generation_context(
    payload: PlanGenerateRequest,
    course: Mapping[str, object],
) -> PlanGenerationContext:
    language = str(course.get("language") or payload.language or "")
    doc_urls = AUTHORITATIVE_DOCS.get(language, [])
    goal_text = limit_text((payload.goal_text or "").strip(), 600)
    if not goal_text and payload.materials:
        titles = [m.title for m in payload.materials if m.title]
        goal_text = limit_text(f"学习提供的材料: {', '.join(titles)}" if titles else "学习编程材料", 600)

    time_budget = payload.time_budget.model_dump(mode="json") if payload.time_budget else None

    return PlanGenerationContext(
        language=language,
        target_level=payload.target_level,
        goal_text=goal_text,
        mode=payload.mode,
        time_budget=time_budget,
        profession=limit_text(payload.profession or "", 120),
        doc_urls=doc_urls,
    )


def build_sdk_plan_generation_response(
    context: PlanGenerationContext,
    *,
    settings: Settings | None = None,
    client: PlanGenerationClient | None = None,
) -> PlanGenerationResult | None:
    resolved_client = client
    if resolved_client is None:
        resolved_client = build_plan_generation_client(settings)
    if resolved_client is None:
        return None

    for attempt in range(2):
        try:
            result = resolved_client.complete_json(context, temperature=None)
            return _validate_and_parse(result.content, context.language, result.model)
        except SAFE_GENERATION_EXCEPTIONS as exc:
            if attempt == 0:
                logger.warning("Plan generation attempt 1 failed, retrying: %s", exc)
                continue
            logger.warning("Plan generation attempt 2 failed, falling back: %s", exc)
            return None

    return None


def _build_messages(context: PlanGenerationContext) -> list[dict[str, str]]:
    evidence: dict[str, object] = {
        "task": "generate_learning_plan",
        "language": context.language,
        "target_level": context.target_level,
        "goal_text": context.goal_text,
        "mode": context.mode,
        "profession": context.profession,
    }
    if context.time_budget:
        evidence["time_budget"] = context.time_budget
    if context.doc_urls:
        evidence["authoritative_doc_urls"] = context.doc_urls
        evidence["instruction"] = "请先使用 fetch_doc_toc 获取这些文档的目录结构，然后基于目录结构生成学习模块。"
    else:
        evidence["instruction"] = f"请使用 web_search 搜索 '{context.language} official tutorial documentation'，找到权威文档后用 fetch_doc_toc 获取目录结构，然后生成学习模块。"

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))},
    ]


def _validate_and_parse(payload: Mapping[str, object], language: str, model: str) -> PlanGenerationResult:
    modules_raw = payload.get("modules")
    if not isinstance(modules_raw, list):
        raise LLMInvalidResponseError("输出缺少 modules 数组")
    if not (_MIN_MODULES <= len(modules_raw) <= _MAX_MODULES):
        raise LLMInvalidResponseError(f"模块数量必须在 {_MIN_MODULES}-{_MAX_MODULES} 之间，实际: {len(modules_raw)}")

    modules: list[DraftModule] = []
    for i, mod_raw in enumerate(modules_raw):
        if not isinstance(mod_raw, Mapping):
            raise LLMInvalidResponseError(f"模块 {i} 不是对象")
        module = _parse_module(mod_raw, i, language)
        modules.append(module)

    source_urls = _validate_source_urls(payload.get("source_urls"))
    generation_notes = _validate_generation_notes(payload.get("generation_notes"))
    source_attribution = ["Dynamic generation: agent_generated"]
    source_attribution.extend(f"Dynamic source: {url}" for url in source_urls)
    if generation_notes:
        source_attribution.append(f"Dynamic notes: {generation_notes}")

    return PlanGenerationResult(modules=modules, source_attribution=source_attribution, model=model)


def _parse_module(raw: Mapping[str, object], index: int, language: str) -> DraftModule:
    temp_id = str(raw.get("temp_id", ""))
    if not _TEMP_ID_MODULE_RE.match(temp_id):
        raise LLMInvalidResponseError(f"模块 temp_id 格式无效: {temp_id}")
    if not temp_id.startswith(f"mod_draft_{language}_"):
        raise LLMInvalidResponseError(f"模块 temp_id 必须以 mod_draft_{language}_ 开头")

    title = str(raw.get("title", ""))
    description = str(raw.get("description", ""))
    _assert_chinese(title, f"模块 {index} title")
    _assert_chinese(description, f"模块 {index} description")
    assert_safe_teaching_output(title)
    assert_safe_teaching_output(description)

    kps_raw = raw.get("knowledge_points")
    if not isinstance(kps_raw, list):
        raise LLMInvalidResponseError(f"模块 {index} 缺少 knowledge_points")
    if not (_MIN_KPS <= len(kps_raw) <= _MAX_KPS):
        raise LLMInvalidResponseError(f"模块 {index} 知识点数量必须在 {_MIN_KPS}-{_MAX_KPS} 之间")

    knowledge_points: list[DraftKnowledgePoint] = []
    for kp_raw in kps_raw:
        if not isinstance(kp_raw, Mapping):
            raise LLMInvalidResponseError(f"模块 {index} 知识点不是对象")
        knowledge_points.append(_parse_knowledge_point(kp_raw, index, language))

    return DraftModule(
        temp_id=temp_id,
        title=title,
        description=description,
        order_index=_int_or_default(raw.get("order_index"), index),
        is_skippable=bool(raw.get("is_skippable", True)),
        is_adjustable=True,
        estimated_sessions=_int_or_default(raw.get("estimated_sessions"), 3),
        source="agent_generated",
        knowledge_points=knowledge_points,
    )


def _parse_knowledge_point(raw: Mapping[str, object], module_index: int, language: str) -> DraftKnowledgePoint:
    temp_id = str(raw.get("temp_id", ""))
    if not _TEMP_ID_KP_RE.match(temp_id):
        raise LLMInvalidResponseError(f"知识点 temp_id 格式无效: {temp_id}")
    if not temp_id.startswith(f"kp_draft_{language}_"):
        raise LLMInvalidResponseError(f"知识点 temp_id 必须以 kp_draft_{language}_ 开头")

    title = str(raw.get("title", ""))
    description = str(raw.get("description", ""))
    _assert_chinese(title, f"模块 {module_index} 知识点 title")
    _assert_chinese(description, f"模块 {module_index} 知识点 description")
    assert_safe_teaching_output(title)
    assert_safe_teaching_output(description)

    skill_tags = raw.get("skill_tags", [])
    if not isinstance(skill_tags, list):
        skill_tags = []
    skill_tags = [str(tag) for tag in skill_tags[:8]]

    exercise_refs = raw.get("exercise_refs", [])
    if not isinstance(exercise_refs, list):
        exercise_refs = []
    exercise_refs = [str(ref) for ref in exercise_refs[:8]]

    return DraftKnowledgePoint(
        temp_id=temp_id,
        title=title,
        description=description,
        skill_tags=skill_tags,
        source="agent_generated",
        exercise_refs=exercise_refs,
    )


def _assert_chinese(text: str, field_name: str) -> None:
    if not _CJK_RE.search(text):
        raise LLMInvalidResponseError(f"{field_name} 必须包含中文字符")


def _validate_source_urls(value: object) -> list[str]:
    if not isinstance(value, list) or not value:
        raise LLMInvalidResponseError("Plan generation output must include source_urls")
    urls: list[str] = []
    for item in value[:8]:
        url = str(item or "").strip()
        if not url:
            continue
        if not url.startswith(("https://", "http://")):
            raise LLMInvalidResponseError(f"source_urls contains invalid URL: {url}")
        urls.append(url)
    if not urls:
        raise LLMInvalidResponseError("Plan generation output source_urls is empty")
    return urls


def _validate_generation_notes(value: object) -> str | None:
    if value is None:
        return None
    note = limit_text(value, 260)
    if not note:
        return None
    _assert_chinese(note, "generation_notes")
    assert_safe_teaching_output(note)
    return note


def _int_or_default(value: object, default: int) -> int:
    if value is None:
        return default
    return int(cast(Any, value))


def _parse_json_object(content: str) -> dict[str, object]:
    return parse_fenced_json_object(
        content,
        invalid_message="Plan generation output is not valid JSON",
        object_message="Plan generation output must be a JSON object",
    )
