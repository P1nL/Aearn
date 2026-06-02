from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.services.grounding.grounding_fetcher import GroundingFetchDocument
from app.services.grounding.grounding_sources import sources_for_language
from app.services.runners.language_capabilities import all_language_capabilities, get_language_capability


DEFAULT_FIXTURE_FETCHED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def mainstream_grounding_fixture_documents(
    *,
    fetched_at: datetime | None = None,
) -> tuple[GroundingFetchDocument, ...]:
    documents: list[GroundingFetchDocument] = []
    for capability in all_language_capabilities():
        documents.extend(fixture_documents_for_language(capability.language_id, fetched_at=fetched_at))
    return tuple(documents)


def fixture_documents_for_language(
    language_id_or_alias: str,
    *,
    fetched_at: datetime | None = None,
) -> tuple[GroundingFetchDocument, ...]:
    capability = get_language_capability(language_id_or_alias)
    if capability is None:
        return ()
    sources = sources_for_language(capability.language_id)
    if not sources:
        return ()

    source = sources[0]
    seed_url = source.seed_urls[0]
    raw_content = _fixture_html(capability.display_name, capability.language_id, source.topic_tags)
    return (
        GroundingFetchDocument(
            source_id=source.source_id,
            language_id=capability.language_id,
            canonical_url=seed_url,
            final_url=seed_url,
            content_type="text/html; charset=utf-8",
            fetched_at=fetched_at or DEFAULT_FIXTURE_FETCHED_AT,
            raw_content=raw_content,
            content_hash=_sha256(raw_content),
        ),
    )


def _fixture_html(display_name: str, language_id: str, topic_tags: tuple[str, ...]) -> str:
    topic_text = ", ".join(topic_tags[:4]) or language_id
    return (
        "<html><body>"
        f"<h1>{display_name} grounding fixture</h1>"
        f"<p>{language_id} documentation fixture covering {topic_text} for language-aware grounding smoke tests.</p>"
        "</body></html>"
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
