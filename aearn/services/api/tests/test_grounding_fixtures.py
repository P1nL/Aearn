from __future__ import annotations

from app.services.grounding.grounding_citations import grounding_results_for_agent
from app.services.grounding.grounding_fixtures import fixture_documents_for_language, mainstream_grounding_fixture_documents
from app.services.grounding.grounding_processing import clean_and_chunk_document
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery, retrieve_grounding_chunks
from app.services.grounding.grounding_sources import get_grounding_source
from app.services.runners.language_capabilities import all_language_capabilities, require_language_capability


def test_mainstream_fixtures_cover_all_language_capabilities() -> None:
    fixture_language_ids = {document.language_id for document in mainstream_grounding_fixture_documents()}
    expected_language_ids = {capability.language_id for capability in all_language_capabilities()}

    assert fixture_language_ids == expected_language_ids


def test_fixture_documents_reference_registered_sources_and_seed_urls() -> None:
    for document in mainstream_grounding_fixture_documents():
        source = get_grounding_source(document.source_id)

        assert source is not None
        assert document.canonical_url in source.seed_urls
        assert document.final_url == document.canonical_url
        assert len(document.content_hash) == 64


def test_each_fixture_runs_through_chunk_retrieve_and_citation_smoke() -> None:
    for document in mainstream_grounding_fixture_documents():
        chunks = clean_and_chunk_document(document)
        query = GroundingRetrievalQuery(document.language_id, query_text=document.language_id, top_k=1)
        retrieval_results = retrieve_grounding_chunks(chunks, query)
        agent_items = grounding_results_for_agent(retrieval_results)

        assert chunks
        assert retrieval_results
        assert agent_items
        assert agent_items[0].citation.canonical_url == document.canonical_url


def test_fixture_documents_for_language_supports_aliases_and_unknowns() -> None:
    assert fixture_documents_for_language("JS")[0].language_id == "javascript"
    assert fixture_documents_for_language("c++")[0].language_id == "cpp"
    assert fixture_documents_for_language("unknown") == ()


def test_fixture_documents_preserve_current_public_language_capabilities() -> None:
    expected_capabilities = {
        "typescript": (True, True),
        "go": (True, True),
        "csharp": (True, True),
        "rust": (False, False),
        "sql": (True, True),
    }

    for language_id, (enabled_for_public_selection, supports_execution) in expected_capabilities.items():
        capability = require_language_capability(language_id)

        assert fixture_documents_for_language(language_id)
        assert capability.enabled_for_public_selection is enabled_for_public_selection
        assert capability.supports_execution is supports_execution
