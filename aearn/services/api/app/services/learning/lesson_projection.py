"""Shared learner-safe LessonDocument projection helpers."""
from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence

from app.services.learning.lesson_contracts import (
    LessonBlock,
    LessonDocumentDraft,
    LessonSourceSnapshot,
    lesson_block_payload,
)


def project_lesson_document(document: LessonDocumentDraft) -> dict[str, object]:
    return {
        "schema_version": document.schema_version,
        "title": document.title,
        "language_id": document.language_id,
        "knowledge_key": document.knowledge_key,
        "content_standard_version": document.content_standard_version,
        "coverage_keys": list(document.coverage_keys),
        "blocks": [lesson_block_payload(block) for block in document.blocks],
        "content_hash": document.content_hash,
    }


def project_lesson_source(snapshot: LessonSourceSnapshot) -> dict[str, object]:
    return {
        "citation_id": snapshot.citation_id,
        "source_id": snapshot.source_id,
        "display_name": snapshot.display_name,
        "provider": snapshot.provider,
        "trust_tier": snapshot.trust_tier,
        "source_type": snapshot.source_type,
        "source_version_label": snapshot.source_version_label,
        "source_version_kind": snapshot.source_version_kind,
        "canonical_url": snapshot.canonical_url,
        "section_path": list(snapshot.section_path),
        "fetched_at": snapshot.fetched_at.isoformat(),
        "snapshotted_at": snapshot.snapshotted_at.isoformat(),
        "evidence_excerpt": snapshot.evidence_excerpt,
    }


def lesson_block_public_text(block: LessonBlock | Mapping[str, object]) -> str:
    payload = lesson_block_payload(block) if not isinstance(block, Mapping) else block
    block_type = str(payload.get("type") or "")
    keys_by_type = {
        "heading": ("title", "subtitle"),
        "learning_objectives": ("items",),
        "concept": ("title", "paragraphs"),
        "authority_note": ("title", "statement"),
        "code_example": ("title", "code", "explanation"),
        "comparison": ("title", "columns", "rows", "conclusion"),
        "hint": ("title", "steps"),
        "exercise_gate": ("learner_prompt",),
        "summary": ("points",),
        "next_steps": ("items",),
    }
    values = [_flatten_text(payload.get(key)) for key in keys_by_type.get(block_type, ())]
    return "\n".join(value for value in values if value)


def normalize_lesson_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text.split())


def _flatten_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "\n".join(item for child in value if (item := _flatten_text(child)))
    return ""


__all__ = (
    "lesson_block_public_text",
    "normalize_lesson_text",
    "project_lesson_document",
    "project_lesson_source",
)
