from __future__ import annotations

from collections.abc import Mapping

from app.agents.onboarding.plan_generation_agent import (
    PlanGenerationContext,
    PlanGenerationJsonResponse,
    build_plan_generation_client,
    build_plan_generation_context,
    build_sdk_plan_generation_response,
)
from app.agents.tooling.tools_web import build_web_tools
from app.core.config import Settings
from app.models.onboarding import PlanGenerateRequest


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


def _context(language: str) -> PlanGenerationContext:
    payload = PlanGenerateRequest(
        user_id="user_1",
        mode="goal_based",
        goal_text="我想学习 Python 数据分析。",
        language="python",
        target_level="beginner",
    )
    return build_plan_generation_context(payload, {"language": language})


def _valid_payload(language: str, *, source_urls: list[str] | None = None) -> dict[str, object]:
    return {
        "modules": [_module(language, index) for index in range(4)],
        "source_urls": source_urls if source_urls is not None else ["https://docs.python.org/3/tutorial/"],
        "generation_notes": "参考官方教程目录生成基础路线。",
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
