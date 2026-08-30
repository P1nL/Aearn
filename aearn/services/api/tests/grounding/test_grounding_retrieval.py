from __future__ import annotations

from datetime import UTC, datetime

from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery, retrieve_grounding_chunks


def _chunk(
    chunk_id: str,
    language_id: str,
    title: str,
    text: str,
    *,
    topic_tags: tuple[str, ...] = (),
    trust_tier: str = "official",
) -> GroundingChunk:
    return GroundingChunk(
        chunk_id=chunk_id,
        source_id=f"{language_id}-source",
        language_id=language_id,
        title=title,
        section_path=(title,),
        canonical_url=f"https://docs.example/{chunk_id}",
        source_type="tutorial",
        source_trust_tier=trust_tier,  # type: ignore[arg-type]
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        content_hash=f"hash-{chunk_id}",
        text=text,
        topic_tags=topic_tags,
        source_version_label="python-3",
        source_version_kind="rolling",
        document_content_hash="d" * 64,
    )


def test_retrieval_filters_to_requested_language() -> None:
    chunks = (
        _chunk("py-functions", "python", "Functions", "Functions group reusable Python behavior."),
        _chunk("js-functions", "javascript", "Functions", "Functions group reusable JavaScript behavior."),
    )

    results = retrieve_grounding_chunks(chunks, GroundingRetrievalQuery(language_id_or_alias="python", query_text="functions"))

    assert [result.chunk.chunk_id for result in results] == ["py-functions"]


def test_query_and_topic_matches_improve_ranking() -> None:
    chunks = (
        _chunk("py-classes", "python", "Classes", "Classes model objects.", topic_tags=("classes",)),
        _chunk("py-functions", "python", "Functions", "Functions return reusable values.", topic_tags=("functions",)),
    )

    results = retrieve_grounding_chunks(
        chunks,
        GroundingRetrievalQuery(language_id_or_alias="py", query_text="reusable return", topic_tags=("functions",)),
    )

    assert [result.chunk.chunk_id for result in results] == ["py-functions", "py-classes"]
    assert "query_terms" in results[0].match_reasons
    assert "topic_tags" in results[0].match_reasons


def test_preferred_trust_tier_boosts_rank_without_hiding_fallbacks() -> None:
    chunks = (
        _chunk("trusted-cpp", "cpp", "Vector", "C++ vector reference.", trust_tier="trusted_de_facto"),
        _chunk("internal-cpp", "cpp", "Vector", "Internal vector note.", trust_tier="internal"),
    )

    results = retrieve_grounding_chunks(
        chunks,
        GroundingRetrievalQuery(
            language_id_or_alias="c++",
            query_text="vector",
            preferred_trust_tiers=("trusted_de_facto",),
        ),
    )

    assert [result.chunk.chunk_id for result in results] == ["trusted-cpp", "internal-cpp"]
    assert "trust_tier" in results[0].match_reasons


def test_unknown_language_returns_empty_results() -> None:
    chunks = (_chunk("py-functions", "python", "Functions", "Functions group reusable behavior."),)

    assert retrieve_grounding_chunks(chunks, GroundingRetrievalQuery("unknown", query_text="functions")) == ()


def test_empty_or_no_hit_query_falls_back_to_same_language_chunks() -> None:
    chunks = (
        _chunk("py-b", "python", "Beta", "Second topic."),
        _chunk("py-a", "python", "Alpha", "First topic."),
        _chunk("js-a", "javascript", "Alpha", "JavaScript topic."),
    )

    results = retrieve_grounding_chunks(chunks, GroundingRetrievalQuery("python", query_text="", top_k=1))

    assert [result.chunk.chunk_id for result in results] == ["py-a"]
    assert results[0].match_reasons == ("fallback",)

