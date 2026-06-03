from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.agents.runtime.agent_runtime_context import limit_text
from app.agents.runtime.guardrails import assert_safe_teaching_output
from app.agents.tooling.tools_web import fetch_doc_toc_text
from app.core.config import Settings, get_settings
from app.models.onboarding import (
    DraftKnowledgePoint,
    DraftModule,
    PlanGenerateRequest,
)
from app.services.llm.llm_client import (
    LLMCallError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMJsonResponse,
    OpenAICompatibleClient,
)


logger = logging.getLogger(__name__)

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
    "csharp": ["https://learn.microsoft.com/en-us/dotnet/csharp/"],
    "sql": [
        "https://www.postgresql.org/docs/current/tutorial.html",
        "https://www.sqlite.org/lang.html",
    ],
}

PUBLIC_SUPPORTED_PLAN_LANGUAGES = (
    "python",
    "javascript",
    "typescript",
    "html_css",
    "java",
    "go",
    "csharp",
    "sql",
)

_TEMP_ID_MODULE_RE = re.compile(r"^mod_draft_[a-z][a-z0-9_]*_[a-z][a-z0-9_]*$")
_TEMP_ID_KP_RE = re.compile(r"^kp_draft_[a-z][a-z0-9_]*_[a-z][a-z0-9_]*$")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_COVERAGE_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.]{1,}|[\u4e00-\u9fff]{2,}")

_MIN_MODULES = 4
_MAX_MODULES = 8
_MIN_KPS = 2
_MAX_KPS = 4
_MAX_DOC_TOCS = 6
_MAX_DOC_TOC_CHARS = 2000

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

1. 使用用户输入和后端提供的 authoritative_doc_tocs / authoritative_doc_urls
2. 基于权威文档目录结构和用户上下文，生成学习模块
3. 如果某个文档目录获取失败，仍可参考对应 authoritative_doc_urls，但不得编造非权威来源

## 输出要求

- 输出严格 JSON，不要包含任何其他文本
- title 和 description 必须为中文
- 每个路线 4-8 个模块，每个模块 2-4 个知识点
- 模块顺序应参考官方文档的教学顺序
- 根据用户水平调整深度：beginner 侧重基础语法，intermediate 加入进阶概念
- generation_notes 必须说明 goal_text、target_level、profession/time_budget（如果提供）和权威文档如何影响路线

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
  "generation_notes": "简要说明用户目标、水平、时间/职业背景和参考文档如何影响路线"
}
```

## 约束

- temp_id 中的 slug 部分使用英文小写和下划线
- is_skippable: 核心基础模块为 false，进阶可选模块为 true
- estimated_sessions: 根据内容量估算，通常 2-4
- skill_tags: 使用英文小写标签
- 不得承诺 Java/C++ 的完整编译运行沙箱
- 不得输出参考答案或隐藏测试内容
- 不得输出没有覆盖用户目标、水平、时间/职业背景或权威来源的泛化路线
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


class LLMJsonPlanClient(Protocol):
    @property
    def model(self) -> str: ...

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
    ) -> LLMJsonResponse: ...


DocTocProvider = Callable[[str], str]


class DirectPlanGenerationClient:
    def __init__(
        self,
        settings: Settings,
        *,
        json_client: LLMJsonPlanClient | None = None,
        doc_toc_provider: DocTocProvider = fetch_doc_toc_text,
        runner: object | None = None,
    ) -> None:
        del runner
        self._settings = settings
        self._json_client = json_client or OpenAICompatibleClient(settings)
        self._doc_toc_provider = doc_toc_provider

    @property
    def model(self) -> str:
        return str(self._json_client.model or self._settings.llm_model or "")

    def complete_json(
        self,
        context: PlanGenerationContext,
        *,
        temperature: float | None = None,
    ) -> PlanGenerationJsonResponse:
        doc_tocs = _prefetch_authoritative_doc_tocs(
            context.doc_urls,
            doc_toc_provider=self._doc_toc_provider,
        )
        result = self._json_client.complete_json(
            _build_messages(context, authoritative_doc_tocs=doc_tocs),
            temperature=temperature,
        )
        return PlanGenerationJsonResponse(content=result.content, model=result.model or self.model)


AgentsSDKPlanGenerationClient = DirectPlanGenerationClient


def build_plan_generation_client(
    settings: Settings | None = None,
    *,
    runner: object | None = None,
) -> PlanGenerationClient | None:
    effective_settings = settings or get_settings()
    if not effective_settings.openai_compatible_configured:
        return None
    if not effective_settings.plan_generation_enabled:
        return None
    if not effective_settings.exa_api_key:
        return None
    try:
        return DirectPlanGenerationClient(effective_settings, runner=runner)
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
            return _validate_and_parse(result.content, context, result.model)
        except SAFE_GENERATION_EXCEPTIONS as exc:
            if attempt == 0:
                logger.warning("Plan generation attempt 1 failed, retrying: %s", exc)
                continue
            logger.warning("Plan generation attempt 2 failed: %s", exc)
            return None

    return None


def _build_messages(
    context: PlanGenerationContext,
    *,
    authoritative_doc_tocs: Sequence[Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
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
        if authoritative_doc_tocs:
            evidence["authoritative_doc_tocs"] = list(authoritative_doc_tocs)
        evidence["instruction"] = (
            "后端已经预取 authoritative_doc_tocs；请基于这些目录结构和用户目标生成学习模块。"
            "source_urls 必须包含 authoritative_doc_urls 中实际参考的权威文档。"
        )
    else:
        evidence["instruction"] = (
            f"缺少 {context.language} 的 authoritative_doc_urls；不要编造非权威来源。"
        )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))},
    ]


def _prefetch_authoritative_doc_tocs(
    doc_urls: Sequence[str],
    *,
    doc_toc_provider: DocTocProvider,
) -> list[dict[str, str]]:
    doc_tocs: list[dict[str, str]] = []
    for url in doc_urls[:_MAX_DOC_TOCS]:
        try:
            toc = doc_toc_provider(url)
        except Exception as exc:
            logger.warning("authoritative doc toc prefetch failed for %s: %s", url, exc)
            toc = f"无法获取页面内容: {url}"
        doc_tocs.append({"url": url, "toc": limit_text(str(toc or ""), _MAX_DOC_TOC_CHARS)})
    return doc_tocs


def _validate_and_parse(
    payload: Mapping[str, object],
    context: PlanGenerationContext,
    model: str,
) -> PlanGenerationResult:
    modules_raw = payload.get("modules")
    if not isinstance(modules_raw, list):
        raise LLMInvalidResponseError("输出缺少 modules 数组")
    if not (_MIN_MODULES <= len(modules_raw) <= _MAX_MODULES):
        raise LLMInvalidResponseError(f"模块数量必须在 {_MIN_MODULES}-{_MAX_MODULES} 之间，实际: {len(modules_raw)}")

    modules: list[DraftModule] = []
    for i, mod_raw in enumerate(modules_raw):
        if not isinstance(mod_raw, Mapping):
            raise LLMInvalidResponseError(f"模块 {i} 不是对象")
        module = _parse_module(mod_raw, i, context.language)
        if module.order_index != i:
            raise LLMInvalidResponseError("模块 order_index 必须从 0 开始连续递增")
        modules.append(module)

    source_urls = _validate_source_urls(payload.get("source_urls"), context.language)
    generation_notes = _validate_generation_notes(payload.get("generation_notes"))
    _validate_user_need_coverage(context, modules, generation_notes)
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


def _validate_source_urls(value: object, language: str) -> list[str]:
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
    authoritative = AUTHORITATIVE_DOCS.get(language, [])
    if authoritative and not any(
        _matches_authoritative_url(url, authoritative_url)
        for url in urls
        for authoritative_url in authoritative
    ):
        raise LLMInvalidResponseError(f"source_urls must include authoritative docs for {language}")
    return urls


def _validate_generation_notes(value: object) -> str:
    if value is None:
        raise LLMInvalidResponseError("generation_notes is required")
    note = limit_text(value, 260)
    if not note:
        raise LLMInvalidResponseError("generation_notes is empty")
    _assert_chinese(note, "generation_notes")
    assert_safe_teaching_output(note)
    return note


def _matches_authoritative_url(url: str, authoritative_url: str) -> bool:
    normalized_url = url.rstrip("/")
    normalized_authoritative = authoritative_url.rstrip("/")
    return normalized_url == normalized_authoritative or normalized_url.startswith(
        f"{normalized_authoritative}/"
    )


def _validate_user_need_coverage(
    context: PlanGenerationContext,
    modules: list[DraftModule],
    generation_notes: str,
) -> None:
    coverage_text = _coverage_text(context, modules, generation_notes)
    if context.goal_text and not _has_any_coverage_term(context.goal_text, coverage_text):
        raise LLMInvalidResponseError("生成路线未覆盖用户目标")
    if not _target_level_covered(context.target_level, coverage_text):
        raise LLMInvalidResponseError("生成路线未覆盖用户水平")
    if context.profession and not _has_any_coverage_term(context.profession, coverage_text):
        raise LLMInvalidResponseError("生成路线未覆盖用户方向或职业背景")
    if context.time_budget is not None:
        _assert_time_budget_covered(context.time_budget, coverage_text)


def _coverage_text(
    context: PlanGenerationContext,
    modules: list[DraftModule],
    generation_notes: str,
) -> str:
    parts: list[str] = [generation_notes]
    for module in modules:
        parts.extend([module.title, module.description or ""])
        for kp in module.knowledge_points:
            parts.extend([kp.title, kp.description or ""])
    return _normalize_coverage_text(" ".join(parts))


def _normalize_coverage_text(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _has_any_coverage_term(source_text: str, coverage_text: str) -> bool:
    for term in _coverage_terms(source_text):
        if _normalize_coverage_text(term) in coverage_text:
            return True
    return False


def _coverage_terms(source_text: str) -> list[str]:
    generic_terms = {
        "learn",
        "learning",
        "study",
        "programming",
        "我想学习",
        "学习",
        "目标",
        "路线",
    }
    terms: list[str] = []
    for match in _COVERAGE_TOKEN_RE.finditer(source_text):
        term = match.group(0).strip()
        normalized = _normalize_coverage_text(term)
        if len(normalized) < 2 or normalized in generic_terms:
            continue
        terms.append(term)
    return terms


def _target_level_covered(target_level: str, coverage_text: str) -> bool:
    markers = {
        "beginner": ("beginner", "入门", "零基础", "基础"),
        "intermediate": ("intermediate", "进阶", "中级"),
        "advanced": ("advanced", "高级", "深入"),
        "beginner_to_intermediate": ("beginner_to_intermediate", "入门", "进阶", "基础"),
    }.get(target_level, (target_level,))
    return any(_normalize_coverage_text(marker) in coverage_text for marker in markers)


def _assert_time_budget_covered(time_budget: Mapping[str, object], coverage_text: str) -> None:
    required_values = [
        str(value)
        for key in ("minutes_per_day", "days_per_week", "deadline")
        if (value := time_budget.get(key)) is not None
    ]
    if required_values and not all(value in coverage_text for value in required_values):
        raise LLMInvalidResponseError("生成路线未覆盖用户时间安排")


def _int_or_default(value: object, default: int) -> int:
    if value is None:
        return default
    return int(cast(Any, value))
