from __future__ import annotations

from collections.abc import Mapping, Sequence
import json

from app.core.config import Settings
from app.services.learning.lesson_authoring import (
    LessonAuthoringEvidence,
    LessonAuthoringRequest,
    _author_messages,
    _parse_author_candidate,
)
from app.services.learning.lesson_contracts import (
    LESSON_CONTENT_STANDARD_VERSION,
    LESSON_DOCUMENT_SCHEMA_VERSION,
    canonical_lesson_author_example,
    lesson_author_block_examples,
    lesson_author_output_schema,
)
from app.services.llm.llm_client import LLMJsonResponse
from app.services.llm.llm_explain_error import (
    build_llm_error_explanation,
    llm_error_explanation_output_schema,
)


def _lesson_author_prompt(*trust_tiers: str) -> tuple[str, dict[str, object], dict[str, object]]:
    evidence = tuple(
        LessonAuthoringEvidence(
            handle=f"S{index}",
            display_name=f"Source {index}",
            provider="Offline prompt test",
            trust_tier=trust_tier,
            source_version_label="test-only",
            source_version_kind="rolling",
            section_path=("Queries",),
            evidence_excerpt="SELECT rows with a bounded condition.",
        )
        for index, trust_tier in enumerate(trust_tiers, 1)
    )
    request = LessonAuthoringRequest(
        document_kind="standard",
        language_id="sql",
        knowledge_key="sql.queries",
        title="SQL queries",
        goal_text="Learn bounded SQL query behavior.",
        target_level="beginner",
        required_capabilities=("sql.queries",),
        mastery_level="unseen",
        mastery_confidence=0.0,
        evidence=evidence,
    )
    system, user = _author_messages(request)
    examples = json.loads(
        system["content"].rsplit("Exact field examples for the allowed block types: ", 1)[1]
    )
    return system["content"], json.loads(user["content"]), examples


def test_lesson_author_prompt_forbids_authority_note_without_official_evidence() -> None:
    system, payload, examples = _lesson_author_prompt("trusted_de_facto")

    allowed_types = system.split("Allowed block types for this request are ", 1)[1].split(
        ". They are not all mandatory.", 1
    )[0]
    assert "authority_note" not in allowed_types.split(", ")
    assert "authority_note" not in examples
    assert "authority_note may cite only official evidence handles: []" in system
    assert "When that list is empty, do not emit authority_note" in system
    assert [item["trust_tier"] for item in payload["evidence"]] == ["trusted_de_facto"]


def test_lesson_author_prompt_uses_only_later_official_handle_for_authority_example() -> None:
    system, payload, examples = _lesson_author_prompt("trusted_de_facto", "official")

    assert examples["authority_note"]["citation_ids"] == ["S2"]
    assert "authority_note may cite only official evidence handles: [\"S2\"]" in system
    assert [item["trust_tier"] for item in payload["evidence"]] == ["trusted_de_facto", "official"]


def test_lesson_author_prompt_preserves_authority_example_for_official_evidence() -> None:
    system, payload, examples = _lesson_author_prompt("official")

    assert examples["authority_note"]["citation_ids"] == ["S1"]
    assert "authority_note" in system.split("Allowed block types for this request are ", 1)[1].split(
        ". They are not all mandatory.", 1
    )[0].split(", ")
    assert [item["trust_tier"] for item in payload["evidence"]] == ["official"]


def test_lesson_author_schema_and_examples_cover_every_registered_block() -> None:
    schema = lesson_author_output_schema()
    examples = lesson_author_block_examples(language_id="python", citation_handle="S1")
    expected_types = {
        "heading",
        "learning_objectives",
        "concept",
        "authority_note",
        "code_example",
        "comparison",
        "hint",
        "exercise_gate",
        "summary",
        "next_steps",
    }

    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "schema_version",
        "title",
        "language_id",
        "knowledge_key",
        "content_standard_version",
        "coverage_keys",
        "blocks",
    ]
    variants = schema["properties"]["blocks"]["items"]["oneOf"]
    assert {item["properties"]["type"]["const"] for item in variants} == expected_types
    assert set(examples) == expected_types

    blocks: list[dict[str, object]] = []
    for order_index, block in enumerate(examples.values()):
        blocks.append({**block, "order_index": order_index})
    payload = {
        "schema_version": LESSON_DOCUMENT_SCHEMA_VERSION,
        "title": "Python 核心概念",
        "language_id": "python",
        "knowledge_key": "python.core",
        "content_standard_version": LESSON_CONTENT_STANDARD_VERSION,
        "coverage_keys": ["core.behavior"],
        "blocks": blocks,
    }

    document = _parse_author_candidate(payload, {"S1": "cite_0123456789abcdef"})
    assert {block.type for block in document.blocks} == expected_types

    compact = canonical_lesson_author_example(
        language_id="python",
        knowledge_key="python.core",
        title="Python 核心概念",
        citation_handle="S1",
    )
    assert _parse_author_candidate(compact, {"S1": "cite_0123456789abcdef"}).schema_version == LESSON_DOCUMENT_SCHEMA_VERSION


class _ErrorExplanationClient:
    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = dict(payload)
        self.messages: tuple[dict[str, str], ...] = ()
        self.output_schema: Mapping[str, object] | None = None
        self.schema_name: str | None = None

    @property
    def model(self) -> str:
        return "fake-error-explainer"

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.2,
        output_schema: Mapping[str, object] | None = None,
        schema_name: str | None = None,
    ) -> LLMJsonResponse:
        del temperature
        self.messages = tuple(dict(item) for item in messages)
        self.output_schema = output_schema
        self.schema_name = schema_name
        return LLMJsonResponse(content=self.payload, model=self.model)


def _build_error(client: _ErrorExplanationClient) -> dict[str, object] | None:
    return build_llm_error_explanation(
        {"title": "边界练习", "exercise_type": "code", "prompt_markdown": "修复边界判断。"},
        error_message="assertion failed",
        stderr="",
        failed_tests=[
            {"case_type": "visible", "case_id": "visible-zero", "message": "zero failed"},
            {"case_type": "hidden", "case_id": "hidden-boundary-42", "message": "hidden failed"},
        ],
        current_code="def value_at(items, index):\n    return items[index]",
        related_knowledge_points=[{"id": "kp.boundary", "title": "边界条件"}],
        settings=Settings(llm_type="disabled"),
        client=client,
    )


def test_error_explanation_uses_strict_schema_grounded_knowledge_points_and_example() -> None:
    client = _ErrorExplanationClient(
        {
            "error_cause": "boundary_condition_error",
            "explanation": "索引边界判断遗漏了空列表情况。",
            "fix_suggestion": "先补充边界分支，再运行同一组测试。",
            "related_knowledge_points": [{"id": "kp.boundary", "title": "边界条件"}],
            "next_action": "retry_same",
        }
    )

    result = _build_error(client)

    assert result is not None
    assert result["generation_source"] == "llm"
    assert result["related_knowledge_points"] == [{"id": "kp.boundary", "title": "边界条件"}]
    assert client.output_schema == llm_error_explanation_output_schema()
    assert client.schema_name == "llm_error_explanation_v1"
    assert "合法输出示例" in client.messages[0]["content"]


def test_error_explanation_rejects_extra_fields_ungrounded_knowledge_and_hidden_id_leaks() -> None:
    base = {
        "error_cause": "boundary_condition_error",
        "explanation": "索引边界判断有误。",
        "fix_suggestion": "调整边界条件后重试。",
        "related_knowledge_points": [{"id": "kp.boundary", "title": "边界条件"}],
        "next_action": "retry_same",
    }
    invalid_payloads = (
        {**base, "private_test": "leak"},
        {**base, "related_knowledge_points": [{"id": "kp.unknown", "title": "未知"}]},
        {**base, "explanation": "失败来自 hidden-boundary-42。"},
    )

    for payload in invalid_payloads:
        assert _build_error(_ErrorExplanationClient(payload)) is None
