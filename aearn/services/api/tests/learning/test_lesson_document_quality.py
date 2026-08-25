from __future__ import annotations

from dataclasses import replace

from app.services.learning.lesson_quality import validate_lesson_document
from tests.support.lesson_document_support import CITATION_ID, sample_lesson_document, sample_source_snapshot, with_script_content


def test_standard_lesson_quality_requires_registered_citations_and_full_coverage() -> None:
    document = sample_lesson_document()
    report = validate_lesson_document(document, (sample_source_snapshot(),))

    assert report.passed is True
    assert report.citation_coverage == 1.0
    assert report.covered_capabilities == ("python.variables",)
    assert report.gate_keys == ("python.variables.basic",)

    concept = document.blocks[2]
    broken = replace(document, blocks=(*document.blocks[:2], replace(concept, citation_ids=()), *document.blocks[3:]))
    failed = validate_lesson_document(broken, (sample_source_snapshot(),))
    assert failed.passed is False
    assert "LESSON_CITATION_REQUIRED" in {issue.code for issue in failed.issues}


def test_quality_rejects_unregistered_citation_script_and_registry_mismatch() -> None:
    document = sample_lesson_document()
    unknown = replace(document.blocks[2], citation_ids=("cite_ffffffffffffffff",))
    invalid = replace(document, blocks=(*document.blocks[:2], unknown, *document.blocks[3:]))
    report = validate_lesson_document(invalid, (sample_source_snapshot(),))
    assert "LESSON_CITATION_NOT_FOUND" in {issue.code for issue in report.issues}

    script_report = validate_lesson_document(with_script_content(document), (sample_source_snapshot(),))
    assert "LESSON_SENSITIVE_CONTENT_FORBIDDEN" in {issue.code for issue in script_report.issues}

    bad_source = replace(sample_source_snapshot(), source_version_label="invented-version")
    mismatch = validate_lesson_document(document, (bad_source,))
    assert "LESSON_SOURCE_REGISTRY_MISMATCH" in {issue.code for issue in mismatch.issues}


def test_personalized_lesson_preserves_standard_coverage_and_gate_contract() -> None:
    standard = sample_lesson_document()
    personalized = sample_lesson_document(personalized=True)
    report = validate_lesson_document(
        personalized,
        (sample_source_snapshot(),),
        document_kind="personalized",
        standard_document=standard,
    )
    assert report.passed is True

    changed_gate = replace(personalized.blocks[7], assessment_contract_version="lesson_gate_v2")
    changed = replace(personalized, blocks=(*personalized.blocks[:7], changed_gate, *personalized.blocks[8:]))
    failed = validate_lesson_document(
        changed,
        (sample_source_snapshot(),),
        document_kind="personalized",
        standard_document=standard,
    )
    assert "LESSON_PERSONALIZED_GATE_CHANGED" in {issue.code for issue in failed.issues}

    assert CITATION_ID in personalized.blocks[2].citation_ids
