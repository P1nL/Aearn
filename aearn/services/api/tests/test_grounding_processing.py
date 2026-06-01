from __future__ import annotations

from datetime import UTC, datetime

from app.services.grounding_fetcher import GroundingFetchDocument
from app.services.grounding_processing import clean_and_chunk_document


def _document(raw_content: str) -> GroundingFetchDocument:
    return GroundingFetchDocument(
        source_id="python-tutorial",
        language_id="python",
        canonical_url="https://docs.python.org/3/tutorial/index.html",
        final_url="https://docs.python.org/3/tutorial/index.html",
        content_type="text/html",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
        raw_content=raw_content,
        content_hash="raw-hash",
    )


def test_clean_and_chunk_document_extracts_sections_and_filters_noise() -> None:
    chunks = clean_and_chunk_document(
        _document(
            """
            <html>
              <head><title>ignored title</title></head>
              <body>
                <nav>navigation should not leak</nav>
                <script>alert('x')</script>
                <h1>Python Tutorial</h1>
                <p>Python is an approachable programming language.</p>
                <h2>Control Flow</h2>
                <p>Use if statements and loops to branch and repeat work.</p>
                <ul><li>for loops iterate over items.</li></ul>
              </body>
            </html>
            """,
        ),
    )

    assert [chunk.title for chunk in chunks] == ["Python Tutorial", "Control Flow"]
    assert chunks[0].section_path == ("Python Tutorial",)
    assert chunks[1].section_path == ("Python Tutorial", "Control Flow")
    assert "navigation" not in " ".join(chunk.text for chunk in chunks)
    assert "alert" not in " ".join(chunk.text for chunk in chunks)
    assert "for loops iterate over items" in chunks[1].text


def test_chunks_include_source_metadata_and_stable_hashes() -> None:
    document = _document("<h1>Python Tutorial</h1><p>Functions group reusable behavior.</p>")

    first = clean_and_chunk_document(document)
    second = clean_and_chunk_document(document)

    assert len(first) == 1
    assert first == second
    chunk = first[0]
    assert chunk.source_id == "python-tutorial"
    assert chunk.language_id == "python"
    assert chunk.canonical_url == document.canonical_url
    assert chunk.source_type == "tutorial"
    assert chunk.source_trust_tier == "official"
    assert chunk.fetched_at == document.fetched_at
    assert len(chunk.chunk_id) == 24
    assert len(chunk.content_hash) == 64
    assert "functions" in chunk.topic_tags


def test_clean_and_chunk_document_returns_empty_tuple_for_unreadable_content() -> None:
    assert clean_and_chunk_document(_document("<script>onlyNoise()</script><style>.x{}</style>")) == ()


def test_clean_and_chunk_document_splits_large_sections_deterministically() -> None:
    long_text = " ".join(f"word{i}" for i in range(80))

    chunks = clean_and_chunk_document(_document(f"<h1>Large Section</h1><p>{long_text}</p>"), max_chars=120)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 120 for chunk in chunks)
    assert len({chunk.chunk_id for chunk in chunks}) == len(chunks)

