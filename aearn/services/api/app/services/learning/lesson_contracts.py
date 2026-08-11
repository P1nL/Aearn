"""Strict immutable contracts for LessonDocument authoring and rendering."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import ClassVar, Literal, TypeAlias, cast
from urllib.parse import urlparse

from app.services.learning.contracts import bounded_text, stable_key


LESSON_DOCUMENT_SCHEMA_VERSION: Literal["lesson_document_v1"] = "lesson_document_v1"
LESSON_CONTENT_STANDARD_VERSION = "programming_language_lesson_v1"
LESSON_GENERATOR_VERSION = "lesson_author_v1"
LESSON_POLICY_VERSION = "lesson_quality_v1"
MAX_LESSON_BLOCKS = 64
MAX_DOCUMENT_TEXT_CHARS = 48_000

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CITATION_ID = re.compile(r"^cite_[0-9a-f]{16}$")
_BLOCK_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")

DocumentKind: TypeAlias = Literal["standard", "personalized"]
SourceVersionKind: TypeAlias = Literal["fixed", "rolling"]
LessonGateKind: TypeAlias = Literal["knowledge_check", "guided_practice", "independent_practice"]
LessonAssignmentStatus: TypeAlias = Literal["active", "proposed", "superseded"]
LessonAuthoringState: TypeAlias = Literal["pending", "claimed", "running", "completed", "failed", "cancelled"]


def _bounded_tuple(
    values: Sequence[str],
    *,
    label: str,
    item_maximum: int,
    maximum_items: int,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    items = tuple(str(item or "").strip() for item in values)
    if (not allow_empty and not items) or len(items) > maximum_items:
        minimum = 0 if allow_empty else 1
        raise ValueError(f"{label} must contain {minimum}..{maximum_items} items")
    if any(not item or len(item) > item_maximum for item in items):
        raise ValueError(f"{label} items must contain 1..{item_maximum} characters")
    return items


def _stable_tuple(values: Sequence[str], *, label: str, maximum_items: int, allow_empty: bool = False) -> tuple[str, ...]:
    items = tuple(stable_key(item, label=label) for item in values)
    if (not allow_empty and not items) or len(items) > maximum_items:
        minimum = 0 if allow_empty else 1
        raise ValueError(f"{label} must contain {minimum}..{maximum_items} items")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} must be unique")
    return items


def _citation_tuple(values: Sequence[str]) -> tuple[str, ...]:
    items = tuple(str(item or "").strip() for item in values)
    if len(items) > 16 or len(items) != len(set(items)):
        raise ValueError("citation_ids must be unique and contain at most 16 items")
    if any(not _CITATION_ID.fullmatch(item) for item in items):
        raise ValueError("citation_ids must use the registered citation identity")
    return items


@dataclass(frozen=True, slots=True)
class LessonBlockBase:
    block_id: str
    order_index: int
    citation_ids: tuple[str, ...]
    type: ClassVar[str]

    def __post_init__(self) -> None:
        normalized_id = str(self.block_id or "").strip().lower()
        if not _BLOCK_ID.fullmatch(normalized_id):
            raise ValueError("block_id must use a stable lowercase identifier")
        if isinstance(self.order_index, bool) or self.order_index < 0:
            raise ValueError("block order_index must be non-negative")
        object.__setattr__(self, "block_id", normalized_id)
        object.__setattr__(self, "citation_ids", _citation_tuple(self.citation_ids))


@dataclass(frozen=True, slots=True)
class HeadingBlock(LessonBlockBase):
    type: ClassVar[Literal["heading"]] = "heading"
    title: str
    subtitle: str = ""

    def __post_init__(self) -> None:
        super(HeadingBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="heading title", maximum=240))
        subtitle = str(self.subtitle or "").strip()
        if len(subtitle) > 500:
            raise ValueError("heading subtitle must contain at most 500 characters")
        object.__setattr__(self, "subtitle", subtitle)


@dataclass(frozen=True, slots=True)
class LearningObjectivesBlock(LessonBlockBase):
    type: ClassVar[Literal["learning_objectives"]] = "learning_objectives"
    items: tuple[str, ...]
    coverage_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        super(LearningObjectivesBlock, self).__post_init__()
        object.__setattr__(self, "items", _bounded_tuple(self.items, label="learning objectives", item_maximum=500, maximum_items=16))
        object.__setattr__(self, "coverage_keys", _stable_tuple(self.coverage_keys, label="coverage key", maximum_items=32))


@dataclass(frozen=True, slots=True)
class ConceptBlock(LessonBlockBase):
    type: ClassVar[Literal["concept"]] = "concept"
    title: str
    paragraphs: tuple[str, ...]
    coverage_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        super(ConceptBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="concept title", maximum=240))
        object.__setattr__(self, "paragraphs", _bounded_tuple(self.paragraphs, label="concept paragraphs", item_maximum=2400, maximum_items=12))
        object.__setattr__(self, "coverage_keys", _stable_tuple(self.coverage_keys, label="coverage key", maximum_items=32))


@dataclass(frozen=True, slots=True)
class AuthorityNoteBlock(LessonBlockBase):
    type: ClassVar[Literal["authority_note"]] = "authority_note"
    title: str
    statement: str

    def __post_init__(self) -> None:
        super(AuthorityNoteBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="authority note title", maximum=240))
        object.__setattr__(self, "statement", bounded_text(self.statement, label="authority statement", maximum=2400))


@dataclass(frozen=True, slots=True)
class CodeExampleBlock(LessonBlockBase):
    type: ClassVar[Literal["code_example"]] = "code_example"
    title: str
    language_id: str
    code: str
    explanation: tuple[str, ...]
    execution_claim: Literal["not_run"] = "not_run"

    def __post_init__(self) -> None:
        super(CodeExampleBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="code example title", maximum=240))
        object.__setattr__(self, "language_id", stable_key(self.language_id, label="language_id"))
        code = str(self.code or "").rstrip()
        if not code or len(code) > 12_000:
            raise ValueError("code example must contain 1..12000 characters")
        if self.execution_claim != "not_run":
            raise ValueError("code example execution_claim must remain not_run")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "explanation", _bounded_tuple(self.explanation, label="code explanation", item_maximum=1200, maximum_items=12))


@dataclass(frozen=True, slots=True)
class ComparisonBlock(LessonBlockBase):
    type: ClassVar[Literal["comparison"]] = "comparison"
    title: str
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    conclusion: str

    def __post_init__(self) -> None:
        super(ComparisonBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="comparison title", maximum=240))
        columns = _bounded_tuple(self.columns, label="comparison columns", item_maximum=160, maximum_items=6)
        rows = tuple(tuple(str(cell or "").strip() for cell in row) for row in self.rows)
        if not rows or len(rows) > 16 or any(len(row) != len(columns) for row in rows):
            raise ValueError("comparison rows must align with columns and contain 1..16 rows")
        if any(not cell or len(cell) > 800 for row in rows for cell in row):
            raise ValueError("comparison cells must contain 1..800 characters")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "conclusion", bounded_text(self.conclusion, label="comparison conclusion", maximum=1600))


@dataclass(frozen=True, slots=True)
class HintBlock(LessonBlockBase):
    type: ClassVar[Literal["hint"]] = "hint"
    title: str
    steps: tuple[str, ...]

    def __post_init__(self) -> None:
        super(HintBlock, self).__post_init__()
        object.__setattr__(self, "title", bounded_text(self.title, label="hint title", maximum=240))
        object.__setattr__(self, "steps", _bounded_tuple(self.steps, label="hint steps", item_maximum=1000, maximum_items=12))


@dataclass(frozen=True, slots=True)
class ExerciseGateBlock(LessonBlockBase):
    type: ClassVar[Literal["exercise_gate"]] = "exercise_gate"
    gate_key: str
    gate_kind: LessonGateKind
    assessment_contract_version: str
    required_capabilities: tuple[str, ...]
    learner_prompt: str

    def __post_init__(self) -> None:
        super(ExerciseGateBlock, self).__post_init__()
        object.__setattr__(self, "gate_key", stable_key(self.gate_key, label="gate_key"))
        if self.gate_kind not in {"knowledge_check", "guided_practice", "independent_practice"}:
            raise ValueError("gate_kind is not registered")
        object.__setattr__(self, "assessment_contract_version", stable_key(self.assessment_contract_version, label="assessment contract version"))
        object.__setattr__(self, "required_capabilities", _stable_tuple(self.required_capabilities, label="required capability", maximum_items=16))
        object.__setattr__(self, "learner_prompt", bounded_text(self.learner_prompt, label="learner prompt", maximum=1200))


@dataclass(frozen=True, slots=True)
class SummaryBlock(LessonBlockBase):
    type: ClassVar[Literal["summary"]] = "summary"
    points: tuple[str, ...]
    coverage_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        super(SummaryBlock, self).__post_init__()
        object.__setattr__(self, "points", _bounded_tuple(self.points, label="summary points", item_maximum=800, maximum_items=16))
        object.__setattr__(self, "coverage_keys", _stable_tuple(self.coverage_keys, label="coverage key", maximum_items=32))


@dataclass(frozen=True, slots=True)
class NextStepsBlock(LessonBlockBase):
    type: ClassVar[Literal["next_steps"]] = "next_steps"
    items: tuple[str, ...]

    def __post_init__(self) -> None:
        super(NextStepsBlock, self).__post_init__()
        object.__setattr__(self, "items", _bounded_tuple(self.items, label="next steps", item_maximum=800, maximum_items=12))


LessonBlock: TypeAlias = (
    HeadingBlock
    | LearningObjectivesBlock
    | ConceptBlock
    | AuthorityNoteBlock
    | CodeExampleBlock
    | ComparisonBlock
    | HintBlock
    | ExerciseGateBlock
    | SummaryBlock
    | NextStepsBlock
)


@dataclass(frozen=True, slots=True)
class LessonSourceSnapshot:
    citation_id: str
    source_id: str
    display_name: str
    provider: str
    trust_tier: Literal["official", "trusted_de_facto", "internal"]
    source_type: Literal["tutorial", "reference", "spec", "platform_docs", "vendor_docs"]
    source_version_label: str
    source_version_kind: SourceVersionKind
    canonical_url: str
    section_path: tuple[str, ...]
    grounding_chunk_id: str
    document_content_hash: str
    chunk_content_hash: str
    fetched_at: datetime
    snapshotted_at: datetime
    evidence_excerpt: str

    def __post_init__(self) -> None:
        if not _CITATION_ID.fullmatch(self.citation_id):
            raise ValueError("citation_id is invalid")
        object.__setattr__(self, "source_id", stable_key(self.source_id, label="source_id"))
        object.__setattr__(self, "display_name", bounded_text(self.display_name, label="source display name", maximum=240))
        object.__setattr__(self, "provider", bounded_text(self.provider, label="source provider", maximum=240))
        object.__setattr__(self, "source_version_label", bounded_text(self.source_version_label, label="source version", maximum=160))
        if self.source_version_kind not in {"fixed", "rolling"}:
            raise ValueError("source_version_kind is invalid")
        parsed = urlparse(self.canonical_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("canonical_url must be an absolute credential-free HTTP URL")
        object.__setattr__(self, "section_path", _bounded_tuple(self.section_path, label="section path", item_maximum=240, maximum_items=16, allow_empty=True))
        object.__setattr__(self, "grounding_chunk_id", bounded_text(self.grounding_chunk_id, label="grounding chunk id", maximum=160))
        if not _SHA256.fullmatch(self.document_content_hash) or not _SHA256.fullmatch(self.chunk_content_hash):
            raise ValueError("source snapshot hashes must be SHA-256")
        object.__setattr__(self, "evidence_excerpt", bounded_text(self.evidence_excerpt, label="evidence excerpt", maximum=1200))


@dataclass(frozen=True, slots=True)
class LessonDocumentDraft:
    title: str
    language_id: str
    knowledge_key: str
    content_standard_version: str
    coverage_keys: tuple[str, ...]
    blocks: tuple[LessonBlock, ...]
    schema_version: Literal["lesson_document_v1"] = LESSON_DOCUMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != LESSON_DOCUMENT_SCHEMA_VERSION:
            raise ValueError("unsupported LessonDocument schema_version")
        object.__setattr__(self, "title", bounded_text(self.title, label="lesson title", maximum=240))
        object.__setattr__(self, "language_id", stable_key(self.language_id, label="language_id"))
        object.__setattr__(self, "knowledge_key", stable_key(self.knowledge_key, label="knowledge_key"))
        object.__setattr__(self, "content_standard_version", stable_key(self.content_standard_version, label="content standard version"))
        object.__setattr__(self, "coverage_keys", _stable_tuple(self.coverage_keys, label="coverage key", maximum_items=64))
        blocks = tuple(self.blocks)
        if not blocks or len(blocks) > MAX_LESSON_BLOCKS:
            raise ValueError(f"LessonDocument must contain 1..{MAX_LESSON_BLOCKS} blocks")
        block_ids = tuple(block.block_id for block in blocks)
        orders = tuple(block.order_index for block in blocks)
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("LessonDocument block_id values must be unique")
        if orders != tuple(range(len(blocks))):
            raise ValueError("LessonDocument block order_index values must be continuous from zero")
        object.__setattr__(self, "blocks", blocks)
        if _document_text_size(self) > MAX_DOCUMENT_TEXT_CHARS:
            raise ValueError("LessonDocument exceeds the total text limit")

    @property
    def content_hash(self) -> str:
        return canonical_lesson_document_hash(self)


@dataclass(frozen=True, slots=True)
class LessonImpact:
    source_changes: tuple[str, ...]
    blocks_added: tuple[str, ...]
    blocks_removed: tuple[str, ...]
    blocks_reordered: tuple[str, ...]
    examples_changed: tuple[str, ...]
    gates_changed: tuple[str, ...]
    retained_blocks: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return any((self.source_changes, self.blocks_added, self.blocks_removed, self.blocks_reordered, self.examples_changed, self.gates_changed))

    def as_dict(self) -> dict[str, object]:
        return {
            "source_changes": list(self.source_changes),
            "blocks_added": list(self.blocks_added),
            "blocks_removed": list(self.blocks_removed),
            "blocks_reordered": list(self.blocks_reordered),
            "examples_changed": list(self.examples_changed),
            "gates_changed": list(self.gates_changed),
            "retained_blocks": list(self.retained_blocks),
        }


def lesson_block_payload(block: LessonBlock) -> dict[str, object]:
    common: dict[str, object] = {
        "block_id": block.block_id,
        "type": block.type,
        "order_index": block.order_index,
        "citation_ids": list(block.citation_ids),
    }
    if isinstance(block, HeadingBlock):
        common.update(title=block.title, subtitle=block.subtitle)
    elif isinstance(block, LearningObjectivesBlock):
        common.update(items=list(block.items), coverage_keys=list(block.coverage_keys))
    elif isinstance(block, ConceptBlock):
        common.update(title=block.title, paragraphs=list(block.paragraphs), coverage_keys=list(block.coverage_keys))
    elif isinstance(block, AuthorityNoteBlock):
        common.update(title=block.title, statement=block.statement)
    elif isinstance(block, CodeExampleBlock):
        common.update(title=block.title, language_id=block.language_id, code=block.code, explanation=list(block.explanation), execution_claim=block.execution_claim)
    elif isinstance(block, ComparisonBlock):
        common.update(title=block.title, columns=list(block.columns), rows=[list(row) for row in block.rows], conclusion=block.conclusion)
    elif isinstance(block, HintBlock):
        common.update(title=block.title, steps=list(block.steps))
    elif isinstance(block, ExerciseGateBlock):
        common.update(gate_key=block.gate_key, gate_kind=block.gate_kind, assessment_contract_version=block.assessment_contract_version, required_capabilities=list(block.required_capabilities), learner_prompt=block.learner_prompt)
    elif isinstance(block, SummaryBlock):
        common.update(points=list(block.points), coverage_keys=list(block.coverage_keys))
    elif isinstance(block, NextStepsBlock):
        common.update(items=list(block.items))
    else:  # pragma: no cover - defensive exhaustiveness guard
        raise TypeError(f"unsupported Lesson block: {type(block).__name__}")
    return common


def canonical_lesson_document_payload(document: LessonDocumentDraft) -> dict[str, object]:
    return {
        "schema_version": document.schema_version,
        "title": document.title,
        "language_id": document.language_id,
        "knowledge_key": document.knowledge_key,
        "content_standard_version": document.content_standard_version,
        "coverage_keys": list(document.coverage_keys),
        "blocks": [lesson_block_payload(block) for block in document.blocks],
    }


def canonical_lesson_document_hash(document: LessonDocumentDraft) -> str:
    encoded = json.dumps(canonical_lesson_document_payload(document), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_source_set_hash(snapshots: Sequence[LessonSourceSnapshot]) -> str:
    payload = [
        {
            "citation_id": item.citation_id,
            "source_id": item.source_id,
            "source_version_label": item.source_version_label,
            "source_version_kind": item.source_version_kind,
            "canonical_url": item.canonical_url,
            "section_path": list(item.section_path),
            "grounding_chunk_id": item.grounding_chunk_id,
            "document_content_hash": item.document_content_hash,
            "chunk_content_hash": item.chunk_content_hash,
        }
        for item in sorted(snapshots, key=lambda snapshot: snapshot.citation_id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def calculate_lesson_impact(
    current: LessonDocumentDraft,
    candidate: LessonDocumentDraft,
    *,
    current_source_ids: Sequence[str] = (),
    candidate_source_ids: Sequence[str] = (),
) -> LessonImpact:
    current_blocks = {block.block_id: block for block in current.blocks}
    candidate_blocks = {block.block_id: block for block in candidate.blocks}
    retained = set(current_blocks) & set(candidate_blocks)
    current_order = {block.block_id: block.order_index for block in current.blocks}
    candidate_order = {block.block_id: block.order_index for block in candidate.blocks}
    example_changes = tuple(
        sorted(
            block_id
            for block_id in retained
            if isinstance(current_blocks[block_id], CodeExampleBlock)
            and isinstance(candidate_blocks[block_id], CodeExampleBlock)
            and lesson_block_payload(current_blocks[block_id]) != lesson_block_payload(candidate_blocks[block_id])
        )
    )
    gate_changes = tuple(
        sorted(
            block_id
            for block_id in retained
            if isinstance(current_blocks[block_id], ExerciseGateBlock)
            and isinstance(candidate_blocks[block_id], ExerciseGateBlock)
            and _gate_signature(current_blocks[block_id]) != _gate_signature(candidate_blocks[block_id])
        )
    )
    source_delta = sorted(set(current_source_ids) ^ set(candidate_source_ids))
    return LessonImpact(
        source_changes=tuple(source_delta),
        blocks_added=tuple(sorted(set(candidate_blocks) - set(current_blocks))),
        blocks_removed=tuple(sorted(set(current_blocks) - set(candidate_blocks))),
        blocks_reordered=tuple(sorted(block_id for block_id in retained if current_order[block_id] != candidate_order[block_id])),
        examples_changed=example_changes,
        gates_changed=gate_changes,
        retained_blocks=tuple(sorted(retained)),
    )


def parse_lesson_document_candidate(payload: Mapping[str, object]) -> LessonDocumentDraft:
    _require_exact_keys(payload, {"schema_version", "title", "language_id", "knowledge_key", "content_standard_version", "coverage_keys", "blocks"}, label="LessonDocument")
    blocks_value = payload.get("blocks")
    if not isinstance(blocks_value, Sequence) or isinstance(blocks_value, (str, bytes)):
        raise ValueError("LessonDocument blocks must be an array")
    blocks = tuple(_parse_block(item) for item in blocks_value)
    schema_version = _string(payload.get("schema_version"), "schema_version")
    if schema_version != LESSON_DOCUMENT_SCHEMA_VERSION:
        raise ValueError("LessonDocument schema_version is unsupported")
    return LessonDocumentDraft(
        schema_version=LESSON_DOCUMENT_SCHEMA_VERSION,
        title=_string(payload.get("title"), "title"),
        language_id=_string(payload.get("language_id"), "language_id"),
        knowledge_key=_string(payload.get("knowledge_key"), "knowledge_key"),
        content_standard_version=_string(payload.get("content_standard_version"), "content_standard_version"),
        coverage_keys=_string_sequence(payload.get("coverage_keys"), "coverage_keys"),
        blocks=blocks,
    )


def _parse_block(value: object) -> LessonBlock:
    if not isinstance(value, Mapping):
        raise ValueError("LessonDocument block must be an object")
    block_type = _string(value.get("type"), "block type")
    block_id = _string(value.get("block_id"), "block_id")
    order_index = _integer(value.get("order_index"), "order_index")
    citation_ids = _string_sequence(value.get("citation_ids"), "citation_ids", allow_empty=True)
    if block_type == "heading":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "subtitle"}, label="heading block")
        return HeadingBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string(value.get("subtitle"), "subtitle", allow_empty=True))
    if block_type == "learning_objectives":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "items", "coverage_keys"}, label="learning_objectives block")
        return LearningObjectivesBlock(block_id, order_index, citation_ids, _string_sequence(value.get("items"), "items"), _string_sequence(value.get("coverage_keys"), "coverage_keys"))
    if block_type == "concept":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "paragraphs", "coverage_keys"}, label="concept block")
        return ConceptBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string_sequence(value.get("paragraphs"), "paragraphs"), _string_sequence(value.get("coverage_keys"), "coverage_keys"))
    if block_type == "authority_note":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "statement"}, label="authority_note block")
        return AuthorityNoteBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string(value.get("statement"), "statement"))
    if block_type == "code_example":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "language_id", "code", "explanation", "execution_claim"}, label="code_example block")
        return CodeExampleBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string(value.get("language_id"), "language_id"), _string(value.get("code"), "code"), _string_sequence(value.get("explanation"), "explanation"), cast(Literal["not_run"], _string(value.get("execution_claim"), "execution_claim")))
    if block_type == "comparison":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "columns", "rows", "conclusion"}, label="comparison block")
        rows_value = value.get("rows")
        if not isinstance(rows_value, Sequence) or isinstance(rows_value, (str, bytes)):
            raise ValueError("comparison rows must be an array")
        return ComparisonBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string_sequence(value.get("columns"), "columns"), tuple(_string_sequence(row, "comparison row") for row in rows_value), _string(value.get("conclusion"), "conclusion"))
    if block_type == "hint":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "title", "steps"}, label="hint block")
        return HintBlock(block_id, order_index, citation_ids, _string(value.get("title"), "title"), _string_sequence(value.get("steps"), "steps"))
    if block_type == "exercise_gate":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "gate_key", "gate_kind", "assessment_contract_version", "required_capabilities", "learner_prompt"}, label="exercise_gate block")
        return ExerciseGateBlock(block_id, order_index, citation_ids, _string(value.get("gate_key"), "gate_key"), cast(LessonGateKind, _string(value.get("gate_kind"), "gate_kind")), _string(value.get("assessment_contract_version"), "assessment_contract_version"), _string_sequence(value.get("required_capabilities"), "required_capabilities"), _string(value.get("learner_prompt"), "learner_prompt"))
    if block_type == "summary":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "points", "coverage_keys"}, label="summary block")
        return SummaryBlock(block_id, order_index, citation_ids, _string_sequence(value.get("points"), "points"), _string_sequence(value.get("coverage_keys"), "coverage_keys"))
    if block_type == "next_steps":
        _require_exact_keys(value, {"block_id", "type", "order_index", "citation_ids", "items"}, label="next_steps block")
        return NextStepsBlock(block_id, order_index, citation_ids, _string_sequence(value.get("items"), "items"))
    raise ValueError(f"unregistered LessonDocument block type: {block_type}")

def citation_id_for_chunk(chunk_id: str, chunk_hash: str) -> str:
    digest = hashlib.sha256(f"{chunk_id}:{chunk_hash}".encode("utf-8")).hexdigest()
    return f"cite_{digest[:16]}"


def _require_exact_keys(value: Mapping[str, object], expected: set[str], *, label: str) -> None:
    keys = {str(key) for key in value}
    if keys != expected:
        unexpected = sorted(keys - expected)
        missing = sorted(expected - keys)
        raise ValueError(f"{label} fields are invalid; unexpected={unexpected}, missing={missing}")


def _string(value: object, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _string_sequence(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an array")
    items = tuple(_string(item, label) for item in value)
    if not allow_empty and not items:
        raise ValueError(f"{label} must not be empty")
    return items


def _document_text_size(document: LessonDocumentDraft) -> int:
    payload = canonical_lesson_document_payload(document)
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def _gate_signature(block: LessonBlock) -> tuple[object, ...] | None:
    if not isinstance(block, ExerciseGateBlock):
        return None
    return (block.gate_key, block.gate_kind, block.assessment_contract_version, block.required_capabilities, block.learner_prompt)
