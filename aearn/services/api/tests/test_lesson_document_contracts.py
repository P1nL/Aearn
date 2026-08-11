from __future__ import annotations

from dataclasses import replace

import pytest

from app.services.learning.lesson_contracts import (
    ExerciseGateBlock,
    calculate_lesson_impact,
    canonical_lesson_document_payload,
    parse_lesson_document_candidate,
)
from lesson_document_support import sample_lesson_document


def test_registered_block_union_round_trips_and_hash_is_canonical() -> None:
    document = sample_lesson_document()
    payload = canonical_lesson_document_payload(document)
    parsed = parse_lesson_document_candidate(payload)

    assert parsed == document
    assert parsed.content_hash == document.content_hash
    assert len(document.content_hash) == 64
    assert [block.type for block in document.blocks] == [
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
    ]


def test_candidate_parser_rejects_unknown_fields_types_and_arbitrary_html_blocks() -> None:
    payload = canonical_lesson_document_payload(sample_lesson_document())
    payload["unknown"] = True
    with pytest.raises(ValueError, match="fields are invalid"):
        parse_lesson_document_candidate(payload)

    payload = canonical_lesson_document_payload(sample_lesson_document())
    blocks = payload["blocks"]
    assert isinstance(blocks, list)
    blocks[0]["type"] = "html"
    with pytest.raises(ValueError, match="unregistered"):
        parse_lesson_document_candidate(payload)

    payload = canonical_lesson_document_payload(sample_lesson_document())
    blocks = payload["blocks"]
    assert isinstance(blocks, list)
    blocks[2]["dangerouslySetInnerHTML"] = {"__html": "<script />"}
    with pytest.raises(ValueError, match="fields are invalid"):
        parse_lesson_document_candidate(payload)


def test_document_rejects_duplicate_ids_non_contiguous_order_and_gate_execution_claims() -> None:
    document = sample_lesson_document()
    blocks = list(document.blocks)
    blocks[1] = replace(blocks[1], block_id="heading")
    with pytest.raises(ValueError, match="block_id"):
        replace(document, blocks=tuple(blocks))

    blocks = list(document.blocks)
    blocks[1] = replace(blocks[1], order_index=8)
    with pytest.raises(ValueError, match="continuous"):
        replace(document, blocks=tuple(blocks))

    gate = next(block for block in document.blocks if isinstance(block, ExerciseGateBlock))
    assert gate.assessment_contract_version == "lesson_gate_v1"
    with pytest.raises(TypeError):
        ExerciseGateBlock(
            block_id="bad-gate",
            order_index=0,
            citation_ids=(),
            gate_key="python.variables.bad",
            gate_kind="knowledge_check",
            assessment_contract_version="lesson_gate_v1",
            required_capabilities=("python.variables",),
            learner_prompt="Prompt",
            hidden_tests=("secret",),  # type: ignore[call-arg]
        )


def test_lesson_impact_reports_source_block_example_and_gate_changes() -> None:
    current = sample_lesson_document()
    blocks = list(sample_lesson_document(title="Python 变量更新").blocks)
    blocks[4] = replace(blocks[4], code="count = 4\nprint(count)")
    blocks[7] = replace(blocks[7], assessment_contract_version="lesson_gate_v2")
    candidate = replace(sample_lesson_document(), blocks=tuple(blocks))

    impact = calculate_lesson_impact(
        current,
        candidate,
        current_source_ids=("python-tutorial",),
        candidate_source_ids=("python-library-reference",),
    )

    assert impact.examples_changed == ("example",)
    assert impact.gates_changed == ("gate",)
    assert impact.source_changes == ("python-library-reference", "python-tutorial")
    assert impact.has_changes is True
