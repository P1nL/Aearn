from __future__ import annotations

import json
from collections.abc import Mapping

from app.agents.onboarding.plan_generation_agent import (
    AUTHORITATIVE_DOCS,
    DirectPlanGenerationClient,
    PUBLIC_SUPPORTED_PLAN_LANGUAGES,
    PlanGenerationContext,
    PlanGenerationJsonResponse,
    build_plan_generation_client,
    build_plan_generation_context,
    build_sdk_plan_generation_response,
)
from app.agents.tooling.tools_web import build_web_tools
from app.core.config import Settings
from app.models.onboarding import PlanGenerateRequest
from app.services.llm.llm_client import LLMJsonResponse


class FakePlanGenerationClient:
    def __init__(self, *outputs: Mapping[str, object]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    @property
    def model(self) -> str:
        return "fake-plan-model"

    def complete_json(
        self,
        context: PlanGenerationContext,
        *,
        temperature: float | None = None,
    ) -> PlanGenerationJsonResponse:
        del context, temperature
        self.calls += 1
        return PlanGenerationJsonResponse(content=dict(self.outputs.pop(0)), model=self.model)


class FakeJsonPlanClient:
    def __init__(self, output: Mapping[str, object]) -> None:
        self.output = dict(output)
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []
        self.temperatures: list[float | None] = []

    @property
    def model(self) -> str:
        return "fake-json-plan-model"

    def complete_json(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
    ) -> LLMJsonResponse:
        self.calls += 1
        self.messages.append([dict(message) for message in messages])
        self.temperatures.append(temperature)
        return LLMJsonResponse(content=dict(self.output), model=self.model)


def test_plan_generation_client_requires_exa_key_for_web_tools() -> None:
    settings = Settings(
        llm_type="openai",
        openai_api_key="test-key",
        openai_base_url="https://llm.example",
        openai_model="test-model",
        exa_api_key=None,
    )

    assert build_plan_generation_client(settings) is None
    assert build_web_tools(settings) == []


def test_direct_plan_generation_client_prefetches_docs_without_tool_calls() -> None:
    captured_urls: list[str] = []
    json_client = FakeJsonPlanClient(_valid_payload("python"))

    def doc_toc_provider(url: str) -> str:
        captured_urls.append(url)
        return "- Tutorial\n  - Data Structures\n  - Modules"

    client = DirectPlanGenerationClient(
        Settings(
            llm_type="deepseek",
            deepseek_api_key="test-key",
            deepseek_base_url="https://api.deepseek.com",
            deepseek_model="test-model",
            exa_api_key="test-exa-key",
        ),
        json_client=json_client,
        doc_toc_provider=doc_toc_provider,
    )

    result = build_sdk_plan_generation_response(_context("python"), client=client)

    assert result is not None
    assert captured_urls == ["https://docs.python.org/3/tutorial/"]
    assert json_client.calls == 1
    assert json_client.temperatures == [None]
    messages = json_client.messages[0]
    assert [message["role"] for message in messages] == ["system", "user"]
    user_payload = json.loads(messages[1]["content"])
    assert user_payload["authoritative_doc_urls"] == ["https://docs.python.org/3/tutorial/"]
    assert user_payload["authoritative_doc_tocs"] == [
        {
            "url": "https://docs.python.org/3/tutorial/",
            "toc": "- Tutorial\n  - Data Structures\n  - Modules",
        }
    ]
    assert "后端已经预取 authoritative_doc_tocs" in user_payload["instruction"]
    assert "fetch_doc_toc" not in user_payload["instruction"]


def test_authoritative_docs_cover_public_supported_languages() -> None:
    assert set(PUBLIC_SUPPORTED_PLAN_LANGUAGES).issubset(AUTHORITATIVE_DOCS)
    assert AUTHORITATIVE_DOCS["sql"]
    assert AUTHORITATIVE_DOCS["csharp"]


def test_dynamic_plan_response_parses_modules_and_source_attribution() -> None:
    client = FakePlanGenerationClient(_valid_payload("python"))
    context = _context("python")

    result = build_sdk_plan_generation_response(context, client=client)

    assert result is not None
    assert client.calls == 1
    assert len(result.modules) == 4
    assert result.modules[0].source == "agent_generated"
    assert result.modules[0].knowledge_points[0].source == "agent_generated"
    assert "Dynamic generation: agent_generated" in result.source_attribution
    assert "Dynamic source: https://docs.python.org/3/tutorial/" in result.source_attribution
    assert any(item.startswith("Dynamic notes:") for item in result.source_attribution)


def test_dynamic_plan_generation_retries_once_after_invalid_output() -> None:
    client = FakePlanGenerationClient({"modules": []}, _valid_payload("python"))

    result = build_sdk_plan_generation_response(_context("python"), client=client)

    assert result is not None
    assert client.calls == 2


def test_dynamic_plan_generation_falls_back_after_invalid_outputs() -> None:
    client = FakePlanGenerationClient(
        {"modules": []},
        _valid_payload("python", source_urls=[]),
    )

    assert build_sdk_plan_generation_response(_context("python"), client=client) is None
    assert client.calls == 2


def test_dynamic_plan_generation_rejects_missing_user_need_coverage() -> None:
    payload = _valid_payload(
        "python",
        generation_notes="参考官方教程目录生成通用路线。",
    )
    client = FakePlanGenerationClient(payload, payload)

    assert build_sdk_plan_generation_response(_context("python"), client=client) is None
    assert client.calls == 2


def test_dynamic_plan_generation_requires_authoritative_source_coverage() -> None:
    client = FakePlanGenerationClient(
        _valid_payload("python", source_urls=["https://example.com/python"]),
        _valid_payload("python", source_urls=["https://example.com/python"]),
    )

    assert build_sdk_plan_generation_response(_context("python"), client=client) is None
    assert client.calls == 2


def test_dynamic_plan_generation_rejects_missing_time_budget_coverage() -> None:
    context = _context(
        "python",
        time_budget={"minutes_per_day": 60, "days_per_week": 5},
    )
    payload = _valid_payload(
        "python",
        generation_notes="根据 beginner 水平和 Python 数据分析目标生成路线。",
    )
    client = FakePlanGenerationClient(payload, payload)

    assert build_sdk_plan_generation_response(context, client=client) is None
    assert client.calls == 2


def test_dynamic_plan_generation_rejects_missing_profession_coverage() -> None:
    context = _context("python", profession="数据分析师")
    payload = _valid_payload(
        "python",
        generation_notes="根据 beginner 水平和 Python 基础目标生成路线。",
    )
    client = FakePlanGenerationClient(payload, payload)

    assert build_sdk_plan_generation_response(context, client=client) is None
    assert client.calls == 2


def test_dynamic_plan_rejects_temp_ids_for_wrong_language() -> None:
    client = FakePlanGenerationClient(_valid_payload("javascript"), _valid_payload("javascript"))

    assert build_sdk_plan_generation_response(_context("python"), client=client) is None


def test_plan_generation_context_uses_authoritative_docs_and_bounds_user_text() -> None:
    long_goal = "我想学习 Python 数据分析。" * 80
    payload = PlanGenerateRequest(
        user_id="user_1",
        mode="goal_based",
        goal_text=long_goal,
        language="python",
        target_level="beginner",
        profession="数据分析师" * 80,
    )

    context = build_plan_generation_context(payload, {"language": "python"})

    assert context.doc_urls == ["https://docs.python.org/3/tutorial/"]
    assert len(context.goal_text) <= 603
    assert len(context.profession) <= 123


def _context(
    language: str,
    *,
    goal_text: str = "我想学习 Python 数据分析。",
    target_level: str = "beginner",
    profession: str | None = None,
    time_budget: dict[str, int] | None = None,
) -> PlanGenerationContext:
    payload = PlanGenerateRequest(
        user_id="user_1",
        mode="goal_based",
        goal_text=goal_text,
        language="python",
        target_level=target_level,
        profession=profession,
        time_budget=time_budget,
    )
    return build_plan_generation_context(payload, {"language": language})


def _valid_payload(
    language: str,
    *,
    source_urls: list[str] | None = None,
    generation_notes: str | None = None,
) -> dict[str, object]:
    return {
        "modules": [_module(language, index) for index in range(4)],
        "source_urls": source_urls if source_urls is not None else ["https://docs.python.org/3/tutorial/"],
        "generation_notes": generation_notes
        or "根据 beginner 水平、Python 数据分析目标和官方教程目录生成基础路线。",
    }


def _module(language: str, index: int) -> dict[str, object]:
    return {
        "temp_id": f"mod_draft_{language}_module_{index}",
        "title": f"模块{index + 1}",
        "description": f"这是第{index + 1}个中文模块说明。",
        "order_index": index,
        "is_skippable": index >= 3,
        "estimated_sessions": 3,
        "knowledge_points": [
            {
                "temp_id": f"kp_draft_{language}_point_{index}_{point}",
                "title": f"知识点{index + 1}-{point + 1}",
                "description": f"这是第{index + 1}个模块的中文知识点说明。",
                "skill_tags": ["syntax", "practice"],
                "exercise_refs": [],
            }
            for point in range(2)
        ],
    }
