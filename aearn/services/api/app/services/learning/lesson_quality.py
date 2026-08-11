"""Deterministic publication quality gate for LessonDocument artifacts."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from app.services.grounding.grounding_sources import get_grounding_source
from app.services.learning.lesson_contracts import (
    AuthorityNoteBlock,
    CodeExampleBlock,
    ComparisonBlock,
    ConceptBlock,
    ExerciseGateBlock,
    HeadingBlock,
    LearningObjectivesBlock,
    LessonDocumentDraft,
    LessonSourceSnapshot,
    SummaryBlock,
    canonical_lesson_document_payload,
)
from app.services.runners.language_capabilities import capabilities_for_public_course_language, get_language_capability


FACTUAL_BLOCK_TYPES = (ConceptBlock, AuthorityNoteBlock, CodeExampleBlock, ComparisonBlock, SummaryBlock)
_BLOCKED_TEXT_MARKERS = (
    "dangerouslysetinnerhtml",
    "<script",
    "</script",
    "<style",
    "javascript:",
    "onerror=",
    "onclick=",
    "hidden_test",
    "hidden test",
    "private_rubric",
    "private rubric",
    "reference_answer",
    "reference answer",
    "solution_reference",
    "file://",
    "c:\\",
    "/home/",
    "/users/",
)


@dataclass(frozen=True, slots=True)
class LessonQualityIssue:
    code: str
    message: str
    block_id: str | None = None


@dataclass(frozen=True, slots=True)
class LessonQualityReport:
    passed: bool
    issues: tuple[LessonQualityIssue, ...]
    citation_coverage: float
    covered_capabilities: tuple[str, ...]
    gate_keys: tuple[str, ...]

    def safe_summary(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "issue_codes": sorted({issue.code for issue in self.issues}),
            "citation_coverage": self.citation_coverage,
            "covered_capabilities": list(self.covered_capabilities),
            "gate_keys": list(self.gate_keys),
        }


class LessonQualityError(ValueError):
    def __init__(self, report: LessonQualityReport) -> None:
        super().__init__("LessonDocument quality gate failed")
        self.report = report


def validate_lesson_document(
    document: LessonDocumentDraft,
    snapshots: tuple[LessonSourceSnapshot, ...],
    *,
    document_kind: Literal["standard", "personalized"] = "standard",
    standard_document: LessonDocumentDraft | None = None,
) -> LessonQualityReport:
    issues: list[LessonQualityIssue] = []
    snapshots_by_id = {snapshot.citation_id: snapshot for snapshot in snapshots}
    if len(snapshots_by_id) != len(snapshots):
        issues.append(LessonQualityIssue("LESSON_SOURCE_DUPLICATE", "来源引用标识不能重复。"))

    allowed_language_ids = _allowed_language_ids(document.language_id)
    for snapshot in snapshots:
        source = get_grounding_source(snapshot.source_id)
        if source is None:
            issues.append(LessonQualityIssue("LESSON_SOURCE_NOT_REGISTERED", "课程来源未注册。"))
            continue
        if source.language_id not in allowed_language_ids:
            issues.append(LessonQualityIssue("LESSON_SOURCE_LANGUAGE_MISMATCH", "课程来源语言与课程不一致。"))
        if (
            source.display_name != snapshot.display_name
            or source.provider != snapshot.provider
            or source.trust_tier != snapshot.trust_tier
            or source.content_type != snapshot.source_type
            or source.source_version_label != snapshot.source_version_label
            or source.source_version_kind != snapshot.source_version_kind
        ):
            issues.append(LessonQualityIssue("LESSON_SOURCE_REGISTRY_MISMATCH", "课程来源快照与注册表不一致。"))
        parsed = urlparse(snapshot.canonical_url)
        hostname = (parsed.hostname or "").lower()
        if not any(hostname == domain.lower() or hostname.endswith(f".{domain.lower()}") for domain in source.allowlisted_domains):
            issues.append(LessonQualityIssue("LESSON_SOURCE_URL_NOT_ALLOWLISTED", "课程来源 URL 不在允许列表内。"))
        if snapshot.document_content_hash == snapshot.chunk_content_hash:
            issues.append(LessonQualityIssue("LESSON_SOURCE_HASH_SEMANTICS_INVALID", "文档 hash 与 chunk hash 必须保留不同语义。"))

    factual_blocks = [block for block in document.blocks if isinstance(block, FACTUAL_BLOCK_TYPES)]
    cited_factual_blocks = 0
    covered_capabilities: set[str] = set()
    gate_keys: list[str] = []
    seen_gate_keys: set[str] = set()

    if not any(isinstance(block, HeadingBlock) for block in document.blocks):
        issues.append(LessonQualityIssue("LESSON_HEADING_REQUIRED", "课程必须包含标题块。"))
    if not any(isinstance(block, LearningObjectivesBlock) for block in document.blocks):
        issues.append(LessonQualityIssue("LESSON_OBJECTIVES_REQUIRED", "课程必须包含学习目标块。"))
    if not any(isinstance(block, ConceptBlock) for block in document.blocks):
        issues.append(LessonQualityIssue("LESSON_CONCEPT_REQUIRED", "课程必须包含概念块。"))
    if not any(isinstance(block, SummaryBlock) for block in document.blocks):
        issues.append(LessonQualityIssue("LESSON_SUMMARY_REQUIRED", "课程必须包含总结块。"))

    for block in document.blocks:
        unknown_citations = sorted(set(block.citation_ids) - set(snapshots_by_id))
        if unknown_citations:
            issues.append(LessonQualityIssue("LESSON_CITATION_NOT_FOUND", "课程块引用了不属于当前文档的来源。", block.block_id))
        if isinstance(block, FACTUAL_BLOCK_TYPES):
            if not block.citation_ids:
                issues.append(LessonQualityIssue("LESSON_CITATION_REQUIRED", "事实性课程块必须引用受信来源。", block.block_id))
            elif not unknown_citations:
                cited_factual_blocks += 1
        if isinstance(block, AuthorityNoteBlock):
            if not any(snapshots_by_id[citation].trust_tier == "official" for citation in block.citation_ids if citation in snapshots_by_id):
                issues.append(LessonQualityIssue("LESSON_AUTHORITY_SOURCE_REQUIRED", "权威说明必须至少引用一个官方来源。", block.block_id))
        if isinstance(block, (LearningObjectivesBlock, ConceptBlock, SummaryBlock)):
            covered_capabilities.update(block.coverage_keys)
        if isinstance(block, CodeExampleBlock):
            if block.language_id not in allowed_language_ids and block.language_id != document.language_id:
                issues.append(LessonQualityIssue("LESSON_CODE_LANGUAGE_MISMATCH", "代码示例语言与课程不一致。", block.block_id))
            if block.execution_claim != "not_run":
                issues.append(LessonQualityIssue("LESSON_EXECUTION_CLAIM_FORBIDDEN", "课程不得声称代码已经运行或验证。", block.block_id))
        if isinstance(block, ExerciseGateBlock):
            if block.gate_key in seen_gate_keys:
                issues.append(LessonQualityIssue("LESSON_GATE_DUPLICATE", "课程 Gate 标识不能重复。", block.block_id))
            seen_gate_keys.add(block.gate_key)
            gate_keys.append(block.gate_key)
            covered_capabilities.update(block.required_capabilities)

    missing_coverage = sorted(set(document.coverage_keys) - covered_capabilities)
    if missing_coverage:
        issues.append(LessonQualityIssue("LESSON_COVERAGE_INCOMPLETE", "课程未覆盖全部声明能力。"))

    serialized_text = json.dumps(canonical_lesson_document_payload(document), ensure_ascii=False).lower()
    if any(marker in serialized_text for marker in _BLOCKED_TEXT_MARKERS):
        issues.append(LessonQualityIssue("LESSON_SENSITIVE_CONTENT_FORBIDDEN", "课程包含被禁止的可执行或内部内容。"))

    if document_kind == "personalized":
        if standard_document is None:
            issues.append(LessonQualityIssue("LESSON_STANDARD_LINEAGE_REQUIRED", "个性化课程必须引用标准课程。"))
        else:
            _validate_personalized_preserves_standard(document, standard_document, issues)
    elif standard_document is not None:
        issues.append(LessonQualityIssue("LESSON_STANDARD_LINEAGE_INVALID", "标准课程不能声明 personalized lineage。"))

    coverage = 1.0 if not factual_blocks else round(cited_factual_blocks / len(factual_blocks), 4)
    return LessonQualityReport(
        passed=not issues,
        issues=tuple(issues),
        citation_coverage=coverage,
        covered_capabilities=tuple(sorted(covered_capabilities)),
        gate_keys=tuple(gate_keys),
    )


def require_lesson_quality(
    document: LessonDocumentDraft,
    snapshots: tuple[LessonSourceSnapshot, ...],
    *,
    document_kind: Literal["standard", "personalized"] = "standard",
    standard_document: LessonDocumentDraft | None = None,
) -> LessonQualityReport:
    report = validate_lesson_document(
        document,
        snapshots,
        document_kind=document_kind,
        standard_document=standard_document,
    )
    if not report.passed:
        raise LessonQualityError(report)
    return report


def _validate_personalized_preserves_standard(
    candidate: LessonDocumentDraft,
    standard: LessonDocumentDraft,
    issues: list[LessonQualityIssue],
) -> None:
    if candidate.language_id != standard.language_id or candidate.knowledge_key != standard.knowledge_key:
        issues.append(LessonQualityIssue("LESSON_PERSONALIZED_SCOPE_MISMATCH", "个性化课程必须保留标准课程 scope。"))
    if not set(standard.coverage_keys).issubset(candidate.coverage_keys):
        issues.append(LessonQualityIssue("LESSON_PERSONALIZED_COVERAGE_REDUCED", "个性化课程不能删除标准能力覆盖。"))
    standard_gates = {
        block.gate_key: (
            block.gate_kind,
            block.assessment_contract_version,
            block.required_capabilities,
            block.learner_prompt,
        )
        for block in standard.blocks
        if isinstance(block, ExerciseGateBlock)
    }
    candidate_gates = {
        block.gate_key: (
            block.gate_kind,
            block.assessment_contract_version,
            block.required_capabilities,
            block.learner_prompt,
        )
        for block in candidate.blocks
        if isinstance(block, ExerciseGateBlock)
    }
    if standard_gates != candidate_gates:
        issues.append(LessonQualityIssue("LESSON_PERSONALIZED_GATE_CHANGED", "个性化课程必须保留标准 Gate contract。"))


def _allowed_language_ids(language_id: str) -> set[str]:
    capability = get_language_capability(language_id)
    if capability is not None:
        return {capability.language_id}
    grouped = capabilities_for_public_course_language(language_id)
    if grouped:
        return {item.language_id for item in grouped}
    return {language_id}
