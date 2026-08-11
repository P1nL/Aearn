from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.services.grounding.grounding_sources import get_grounding_source
from app.services.learning.lesson_contracts import (
    AuthorityNoteBlock,
    CodeExampleBlock,
    ComparisonBlock,
    ConceptBlock,
    ExerciseGateBlock,
    HeadingBlock,
    HintBlock,
    LearningObjectivesBlock,
    LessonDocumentDraft,
    LessonSourceSnapshot,
    NextStepsBlock,
    SummaryBlock,
)


CITATION_ID = "cite_0123456789abcdef"


def sample_source_snapshot(*, citation_id: str = CITATION_ID) -> LessonSourceSnapshot:
    source = get_grounding_source("python-tutorial")
    assert source is not None
    return LessonSourceSnapshot(
        citation_id=citation_id,
        source_id=source.source_id,
        display_name=source.display_name,
        provider=source.provider,
        trust_tier=source.trust_tier,
        source_type=source.content_type,
        source_version_label=source.source_version_label,
        source_version_kind=source.source_version_kind,
        canonical_url=source.seed_urls[0],
        section_path=("Python Tutorial", "Variables"),
        grounding_chunk_id="chunk-python-variables",
        document_content_hash="a" * 64,
        chunk_content_hash="b" * 64,
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        snapshotted_at=datetime(2026, 8, 11, tzinfo=UTC),
        evidence_excerpt="Names refer to values, and assignment binds a name to a value.",
    )


def sample_lesson_document(*, title: str = "Python 变量", personalized: bool = False) -> LessonDocumentDraft:
    citation_ids = (CITATION_ID,)
    depth = "结合你的自动化目标理解变量。" if personalized else "理解名称如何绑定并引用值。"
    return LessonDocumentDraft(
        title=title,
        language_id="python",
        knowledge_key="python.variables",
        content_standard_version="programming_language_lesson_v1",
        coverage_keys=("python.variables",),
        blocks=(
            HeadingBlock(block_id="heading", order_index=0, citation_ids=(), title=title, subtitle="稳定、可引用的课程文档"),
            LearningObjectivesBlock(block_id="objectives", order_index=1, citation_ids=(), items=("解释变量绑定。",), coverage_keys=("python.variables",)),
            ConceptBlock(block_id="concept", order_index=2, citation_ids=citation_ids, title="变量绑定", paragraphs=(depth,), coverage_keys=("python.variables",)),
            AuthorityNoteBlock(block_id="authority", order_index=3, citation_ids=citation_ids, title="权威说明", statement="赋值语句把名称与值关联。"),
            CodeExampleBlock(block_id="example", order_index=4, citation_ids=citation_ids, title="建立并读取变量", language_id="python", code="count = 3\nprint(count)", explanation=("示例仅作为静态教学文本展示。",)),
            ComparisonBlock(block_id="comparison", order_index=5, citation_ids=citation_ids, title="名称和值", columns=("名称", "值"), rows=(("count", "3"),), conclusion="名称用于在后续表达式中引用值。"),
            HintBlock(block_id="hint", order_index=6, citation_ids=(), title="阅读提示", steps=("先找赋值符号左侧的名称。",)),
            ExerciseGateBlock(block_id="gate", order_index=7, citation_ids=(), gate_key="python.variables.basic", gate_kind="knowledge_check", assessment_contract_version="lesson_gate_v1", required_capabilities=("python.variables",), learner_prompt="稍后用一个变量保存数量。"),
            SummaryBlock(block_id="summary", order_index=8, citation_ids=citation_ids, points=("变量让名称引用值。",), coverage_keys=("python.variables",)),
            NextStepsBlock(block_id="next", order_index=9, citation_ids=(), items=("开始课程后再进入练习 Gate。",)),
        ),
    )


def with_script_content(document: LessonDocumentDraft) -> LessonDocumentDraft:
    blocks = list(document.blocks)
    concept = blocks[2]
    assert isinstance(concept, ConceptBlock)
    blocks[2] = replace(concept, paragraphs=("<script>alert('x')</script>",))
    return replace(document, blocks=tuple(blocks))


def author_candidate_payload(*, personalized: bool = False, title: str | None = None) -> dict[str, object]:
    from app.services.learning.lesson_contracts import canonical_lesson_document_payload

    document = sample_lesson_document(
        title=title or ("Python 变量：个性化" if personalized else "Python 变量"),
        personalized=personalized,
    )
    payload = canonical_lesson_document_payload(document)
    blocks = payload["blocks"]
    assert isinstance(blocks, list)
    for block in blocks:
        assert isinstance(block, dict)
        citations = block.get("citation_ids")
        if isinstance(citations, list) and citations:
            block["citation_ids"] = ["S1"]
    return payload
