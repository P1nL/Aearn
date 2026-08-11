from __future__ import annotations

from datetime import UTC, datetime

from app.services.grounding.grounding_citations import grounding_results_for_agent
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_retrieval import GroundingRetrievalResult


def _result(text: str = "Functions group reusable behavior for clear programs.") -> GroundingRetrievalResult:
    chunk = GroundingChunk(
        chunk_id="py-functions",
        source_id="python-tutorial",
        language_id="python",
        title="Functions",
        section_path=("Python Tutorial", "Functions"),
        canonical_url="https://docs.python.org/3/tutorial/controlflow.html#functions",
        source_type="tutorial",
        source_trust_tier="official",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash="abc123",
        text=text,
        topic_tags=("functions",),
        source_version_label="python-3",
        source_version_kind="rolling",
        document_content_hash="d" * 64,
    )
    return GroundingRetrievalResult(chunk=chunk, relevance_score=7.5, match_reasons=("query_terms", "topic_tags"))


def test_grounding_results_for_agent_exposes_citation_metadata() -> None:
    item = grounding_results_for_agent((_result(),))[0]

    assert item.content == "Functions group reusable behavior for clear programs."
    assert item.relevance_score == 7.5
    assert item.match_reasons == ("query_terms", "topic_tags")
    assert item.citation.source_id == "python-tutorial"
    assert item.citation.title == "Functions"
    assert item.citation.section_path == ("Python Tutorial", "Functions")
    assert item.citation.canonical_url == "https://docs.python.org/3/tutorial/controlflow.html#functions"
    assert item.citation.source_type == "tutorial"
    assert item.citation.source_trust_tier == "official"
    assert item.citation.source_version_label == "python-3"
    assert item.citation.source_version_kind == "rolling"
    assert item.citation.document_content_hash == "d" * 64
    assert item.citation.content_hash == "abc123"
    assert item.citation.fetched_at == datetime(2026, 1, 1, tzinfo=UTC)


def test_citation_id_is_deterministic() -> None:
    first = grounding_results_for_agent((_result(),))[0].citation.citation_id
    second = grounding_results_for_agent((_result(),))[0].citation.citation_id

    assert first == second
    assert len(first) == 24


def test_agent_grounding_content_is_bounded() -> None:
    item = grounding_results_for_agent((_result("word " * 30),), max_content_chars=24)[0]

    assert len(item.content) <= 24
    assert item.content.endswith("...")


def test_grounding_results_for_agent_respects_max_items_and_empty_input() -> None:
    results = (_result("first"), _result("second"))

    assert len(grounding_results_for_agent(results, max_items=1)) == 1
    assert grounding_results_for_agent(()) == ()

