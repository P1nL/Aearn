"""Exact learner-safe task evidence, separate from the compact teaching authority.

No scorer, private rubric, hint, or answer-explanation authority is consulted here.
The caller must authenticate the frozen Artifact/receipt lineage before calling.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from app.services.learning.item_bank.contracts import (
    LearningItemPublicV1,
    LearningItemKnowledgeCheckContentV1,
)

from app.services.learning.artifacts.contracts import (
    TutorArtifactCodeRangeResponse,
    TutorArtifactKnowledgeCheckPresentationV1,
    TutorArtifactMultiSelectResponse,
    TutorArtifactOrderingResponse,
    TutorArtifactResponseV1,
    TutorArtifactSingleSelectResponse,
    TutorArtifactTextResponse,
)

_RESPONSE: TypeAdapter[TutorArtifactResponseV1] = TypeAdapter(TutorArtifactResponseV1)
MAX_GROUNDING_SOURCE_CHARACTERS = 1200
MAX_GROUNDING_SOURCES = 8


class KnowledgeCheckGroundingError(ValueError):
    pass


def build_knowledge_check_candidate_grounding(
    *,
    handle: str,
    learning_item_version_id: str,
    public: LearningItemPublicV1,
) -> tuple[dict[str, object], ...]:
    """A published candidate is a frozen question, not a model-authored task."""
    if not isinstance(public.content, LearningItemKnowledgeCheckContentV1):
        raise KnowledgeCheckGroundingError("candidate question content is invalid")
    content = public.content
    return pack_knowledge_check_grounding(
        (
            {
                "kind": "knowledge_check_grounding",
                "component": "candidate_question",
                "source_handle": handle,
                "learning_item_version_id": learning_item_version_id,
                "content_role": "untrusted_task_data",
                "response_kind": content.response_kind,
                "prompt_markdown": content.prompt_markdown,
                "options": [
                    {"value": item.option_id, "label": item.label}
                    for item in content.options
                ],
            },
        )
    )


def build_knowledge_check_grounding(
    *,
    artifact_id: str,
    learning_item_version_id: str,
    receipt_id: str,
    presentation: Mapping[str, object],
    response: Mapping[str, object],
    outcome: str,
    assistance_kind: str,
    independent_mastery_eligible: bool,
) -> tuple[dict[str, object], ...]:
    """Use an explicit whitelist; learner submissions remain untrusted data."""
    try:
        for identity in (artifact_id, learning_item_version_id, receipt_id):
            UUID(identity)
        public = TutorArtifactKnowledgeCheckPresentationV1.model_validate(presentation)
        if (
            not public.answer_locked
            or public.response_receipt_id != receipt_id
            or public.outcome != outcome
            or public.assistance_kind != assistance_kind
            or type(independent_mastery_eligible) is not bool
            or independent_mastery_eligible
            != (outcome == "correct" and assistance_kind == "independent")
        ):
            raise KnowledgeCheckGroundingError(
                "knowledge-check result identity is inconsistent"
            )
        if assistance_kind == "direct_answer":
            if dict(response) != {"kind": "direct_answer"}:
                raise KnowledgeCheckGroundingError(
                    "direct-answer evidence is inconsistent"
                )
            submitted: dict[str, object] = {
                "kind": "direct_answer",
                "submitted_answer": False,
            }
        else:
            parsed = _RESPONSE.validate_python(response)
            if parsed.kind != public.response_kind:
                raise KnowledgeCheckGroundingError(
                    "knowledge-check response kind is inconsistent"
                )
            choices = {item.value for item in public.options}
            if (
                isinstance(parsed, TutorArtifactSingleSelectResponse)
                and parsed.value not in choices
            ):
                raise KnowledgeCheckGroundingError(
                    "knowledge-check selected option is unknown"
                )
            if isinstance(
                parsed,
                (TutorArtifactMultiSelectResponse, TutorArtifactOrderingResponse),
            ):
                if (
                    not set(parsed.values).issubset(choices)
                    or not public.minimum_selections
                    <= len(parsed.values)
                    <= public.maximum_selections
                ):
                    raise KnowledgeCheckGroundingError(
                        "knowledge-check selected options are inconsistent"
                    )
                if (
                    isinstance(parsed, TutorArtifactOrderingResponse)
                    and set(parsed.values) != choices
                ):
                    raise KnowledgeCheckGroundingError(
                        "knowledge-check ordering is incomplete"
                    )
            if (
                isinstance(parsed, TutorArtifactTextResponse)
                and len(parsed.text) > public.maximum_text_length
            ):
                raise KnowledgeCheckGroundingError(
                    "knowledge-check submitted text is oversized"
                )
            if (
                isinstance(parsed, TutorArtifactCodeRangeResponse)
                and parsed.end_line > 4000
            ):
                raise KnowledgeCheckGroundingError(
                    "knowledge-check submitted range is oversized"
                )
            submitted = parsed.model_dump(mode="json")
        source_handle = f"artifact:{artifact_id}"
        option_labels = {item.value: item.label for item in public.options}
        selected_values = (
            [submitted["value"]]
            if "value" in submitted
            else submitted.get("values", [])
        )
        selected_labels = (
            [
                option_labels[value]
                for value in selected_values
                if isinstance(value, str) and value in option_labels
            ]
            if isinstance(selected_values, list)
            else []
        )
        return pack_knowledge_check_grounding(
            (
                {
                    "kind": "knowledge_check_grounding",
                    "component": "question",
                    "source_handle": source_handle,
                    "learning_item_version_id": learning_item_version_id,
                    "content_role": "untrusted_task_data",
                    "response_kind": public.response_kind,
                    # Validation can normalize outer whitespace; the frozen
                    # task text itself must still be transmitted byte-for-byte.
                    "prompt_markdown": presentation["prompt_markdown"],
                    "options": [
                        {"value": item.value, "label": item.label}
                        for item in public.options
                    ],
                },
                {
                    "kind": "knowledge_check_grounding",
                    "component": "scored_submission",
                    "source_handle": source_handle,
                    "receipt_id": receipt_id,
                    "learner_submission_role": "untrusted_submission",
                    "learner_submission": submitted,
                    "selected_option_labels": selected_labels,
                    "outcome": outcome,
                    "assistance_kind": assistance_kind,
                    "independent_mastery_eligible": independent_mastery_eligible,
                },
            )
        )
    except (ValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, KnowledgeCheckGroundingError):
            raise
        raise KnowledgeCheckGroundingError(
            "knowledge-check grounding data is invalid"
        ) from None


def pack_knowledge_check_grounding(
    facts: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Keep complete JSON or complete ordered parts; never silently truncate.

    Every part remains REQUIRED_FACTS. The existing ContextBuilder also checks
    aggregate source count, serialization and the complete-request token budget.
    """
    packed: list[dict[str, object]] = []
    for fact in facts:
        serialized = _json(fact)
        if len(serialized) <= MAX_GROUNDING_SOURCE_CHARACTERS:
            packed.append(dict(fact))
            continue
        # Reserve metadata using the maximum possible one-digit part/count.
        base = {
            "kind": "knowledge_check_grounding_part",
            "component": fact["component"],
            "source_handle": fact["source_handle"],
            "content_role": "untrusted_task_data",
            "encoding": "ordered_json_parts",
            "part_index": 8,
            "part_count": 8,
        }
        pieces: list[str] = []
        remaining = serialized
        while remaining:
            low, high = 0, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if (
                    len(_json({**base, "data": remaining[:middle]}))
                    <= MAX_GROUNDING_SOURCE_CHARACTERS
                ):
                    low = middle
                else:
                    high = middle - 1
            if low == 0 or len(packed) + len(pieces) + 1 > MAX_GROUNDING_SOURCES:
                raise KnowledgeCheckGroundingError(
                    "knowledge-check grounding exceeds required-context capacity"
                )
            pieces.append(remaining[:low])
            remaining = remaining[low:]
        packed.extend(
            {**base, "part_index": index, "part_count": len(pieces), "data": piece}
            for index, piece in enumerate(pieces, 1)
        )
    if len(packed) > MAX_GROUNDING_SOURCES:
        raise KnowledgeCheckGroundingError(
            "knowledge-check grounding exceeds required-context capacity"
        )
    return tuple(cast(dict[str, object], fact) for fact in packed)


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
