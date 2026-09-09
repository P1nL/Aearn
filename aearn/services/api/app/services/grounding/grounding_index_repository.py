from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast

from psycopg import Connection

from app.services.grounding.grounding_citations import AgentGroundingItem, grounding_results_for_agent
from app.services.grounding.grounding_processing import GroundingChunk
from app.services.grounding.grounding_provenance import provenance_from_metadata
from app.services.grounding.grounding_reindex import GroundingReindexReport, run_fixture_grounding_reindex
from app.services.grounding.grounding_retrieval import GroundingRetrievalQuery, GroundingRetrievalResult, retrieve_grounding_chunks
from app.services.grounding.grounding_sources import SourceContentType, SourceTrustTier, SourceVersionKind
from app.services.runners.language_capabilities import capabilities_for_public_course_language, get_language_capability


@dataclass(frozen=True, slots=True)
class PersistedGroundingReindex:
    run_id: str
    report: GroundingReindexReport
    chunks_persisted: int


def run_and_persist_fixture_grounding_reindex(
    conn: Connection[dict[str, object]],
) -> PersistedGroundingReindex:
    report = run_fixture_grounding_reindex()
    run_id = persist_grounding_reindex_report(conn, report, mode="fixture")
    chunks_persisted = replace_grounding_chunks(
        conn,
        report.chunks,
        source_ids=tuple(source.source_id for source in report.source_reports),
    )
    return PersistedGroundingReindex(run_id=run_id, report=report, chunks_persisted=chunks_persisted)


def persist_grounding_reindex_report(
    conn: Connection[dict[str, object]],
    report: GroundingReindexReport,
    *,
    mode: str,
) -> str:
    row = conn.execute(
        """
        INSERT INTO grounding_reindex_runs (
          mode, status, total_sources, total_documents, total_chunks,
          total_failures, source_reports_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
        RETURNING id
        """,
        (
            mode,
            report.status,
            report.total_sources,
            report.total_documents,
            report.total_chunks,
            report.total_failures,
            json.dumps(_serialize_source_reports(report), ensure_ascii=False),
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("grounding reindex run insert did not return an id")
    return str(row["id"])


def replace_grounding_chunks(
    conn: Connection[dict[str, object]],
    chunks: Sequence[GroundingChunk],
    *,
    source_ids: Sequence[str] | None = None,
) -> int:
    source_id_set = tuple(sorted({source_id for source_id in (source_ids or ()) if source_id.strip()}))
    if not source_id_set:
        source_id_set = tuple(sorted({chunk.source_id for chunk in chunks}))
    for source_id in source_id_set:
        conn.execute("DELETE FROM grounding_chunks WHERE source_id = %s", (source_id,))

    for chunk in chunks:
        conn.execute(
            """
            INSERT INTO grounding_chunks (
              chunk_id, source_id, language_id, title, section_path_json,
              canonical_url, source_type, source_trust_tier, fetched_at,
              source_version_label, source_version_kind, document_content_hash,
              content_hash, content, topic_tags_json, metadata_json
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (chunk_id) DO UPDATE SET
              source_id = EXCLUDED.source_id,
              language_id = EXCLUDED.language_id,
              title = EXCLUDED.title,
              section_path_json = EXCLUDED.section_path_json,
              canonical_url = EXCLUDED.canonical_url,
              source_type = EXCLUDED.source_type,
              source_trust_tier = EXCLUDED.source_trust_tier,
              fetched_at = EXCLUDED.fetched_at,
              source_version_label = EXCLUDED.source_version_label,
              source_version_kind = EXCLUDED.source_version_kind,
              document_content_hash = EXCLUDED.document_content_hash,
              content_hash = EXCLUDED.content_hash,
              content = EXCLUDED.content,
              topic_tags_json = EXCLUDED.topic_tags_json,
              metadata_json = EXCLUDED.metadata_json
            """,
            (
                chunk.chunk_id,
                chunk.source_id,
                chunk.language_id,
                chunk.title[:500],
                json.dumps(list(chunk.section_path), ensure_ascii=False),
                chunk.canonical_url,
                chunk.source_type,
                chunk.source_trust_tier,
                chunk.fetched_at,
                chunk.source_version_label,
                chunk.source_version_kind,
                chunk.document_content_hash,
                chunk.content_hash,
                chunk.text[:4000],
                json.dumps(list(chunk.topic_tags), ensure_ascii=False),
                json.dumps({"provenance": chunk.provenance.payload()}, ensure_ascii=False),
            ),
        )
    return len(chunks)


def search_persisted_grounding_chunks(
    conn: Connection[dict[str, object]],
    query: GroundingRetrievalQuery,
    *,
    admission_filter: Callable[[GroundingChunk], bool] | None = None,
) -> tuple[GroundingRetrievalResult, ...]:
    language_ids = grounding_language_ids(query.language_id_or_alias)
    if not language_ids:
        return ()
    chunks = _load_grounding_chunks_for_languages(conn, language_ids)
    if admission_filter is not None:
        chunks = tuple(chunk for chunk in chunks if admission_filter(chunk))
    if not chunks:
        return ()

    results: list[GroundingRetrievalResult] = []
    per_language_top_k = max(query.top_k, 1)
    for language_id in language_ids:
        language_query = replace(query, language_id_or_alias=language_id, top_k=per_language_top_k)
        results.extend(retrieve_grounding_chunks(chunks, language_query))
    return tuple(sorted(results, key=lambda result: (-result.relevance_score, result.chunk.chunk_id))[: query.top_k])


def build_official_docs_grounding_context(
    conn: Connection[dict[str, object]],
    *,
    language_id_or_alias: str,
    query_text: str,
    topic_tags: Sequence[str] = (),
    knowledge_point_id: str | None = None,
    knowledge_point_title: str | None = None,
    top_k: int = 4,
) -> dict[str, object]:
    language_ids = grounding_language_ids(language_id_or_alias)
    base: dict[str, object] = {
        "status": "empty",
        "source_mode": "persisted_index",
        "language_id": language_id_or_alias,
        "language_ids": list(language_ids),
        "query": _limit_text(query_text, 500),
        "retrieved_chunk_count": 0,
        "citation_count": 0,
        "fallback_reason": None,
        "source_ids": [],
        "items": [],
        "citations": [],
    }
    if not language_ids:
        base["fallback_reason"] = "unsupported_language"
        return base

    try:
        results = search_persisted_grounding_chunks(
            conn,
            GroundingRetrievalQuery(
                language_id_or_alias=language_id_or_alias,
                query_text=query_text,
                topic_tags=tuple(topic_tags),
                preferred_trust_tiers=("official", "trusted_de_facto"),
                knowledge_point_id=knowledge_point_id,
                knowledge_point_title=knowledge_point_title,
                top_k=top_k,
            ),
        )
        items = grounding_results_for_agent(results, max_items=top_k)
    except Exception:
        base["status"] = "failed"
        base["fallback_reason"] = "repository_error"
        return base

    if not items:
        base["fallback_reason"] = "no_persisted_grounding"
        return base

    serialized_items = [_serialize_agent_grounding_item(item) for item in items]
    citations = [_serialize_citation_metadata(item) for item in items]
    base.update(
        {
            "status": "used",
            "retrieved_chunk_count": len(results),
            "citation_count": len(citations),
            "source_ids": sorted({str(item["source_id"]) for item in citations}),
            "items": serialized_items,
            "citations": citations,
        }
    )
    return base


def grounding_response_metadata(rag_context: Mapping[str, object]) -> dict[str, object]:
    docs_context = rag_context.get("official_docs_grounding")
    if not isinstance(docs_context, Mapping):
        return {}
    citations = docs_context.get("citations")
    safe_citations = [dict(item) for item in citations if isinstance(item, Mapping)] if isinstance(citations, Sequence) else []
    return {
        "status": str(docs_context.get("status") or "empty"),
        "source_mode": str(docs_context.get("source_mode") or "persisted_index"),
        "language_id": str(docs_context.get("language_id") or ""),
        "language_ids": _string_list(docs_context.get("language_ids")),
        "retrieved_chunk_count": _as_int(docs_context.get("retrieved_chunk_count")),
        "citation_count": _as_int(docs_context.get("citation_count")),
        "fallback_reason": docs_context.get("fallback_reason"),
        "source_ids": _string_list(docs_context.get("source_ids")),
        "citations": safe_citations[:4],
    }


def grounding_language_ids(language_id_or_alias: str) -> tuple[str, ...]:
    capability = get_language_capability(language_id_or_alias)
    if capability is not None:
        return (capability.language_id,)
    course_capabilities = capabilities_for_public_course_language(language_id_or_alias)
    return tuple(capability.language_id for capability in course_capabilities)


def _load_grounding_chunks_for_languages(
    conn: Connection[dict[str, object]],
    language_ids: Sequence[str],
) -> tuple[GroundingChunk, ...]:
    rows: list[Mapping[str, object]] = []
    for language_id in language_ids:
        rows.extend(
            conn.execute(
                """
                SELECT *
                FROM grounding_chunks
                WHERE language_id = %s
                ORDER BY source_trust_tier, source_id, chunk_id
                """,
                (language_id,),
            ).fetchall()
        )
    return tuple(_chunk_from_row(row) for row in rows)


def _chunk_from_row(row: Mapping[str, object]) -> GroundingChunk:
    section_path = row.get("section_path_json")
    topic_tags = row.get("topic_tags_json")
    fetched_at = row.get("fetched_at")
    return GroundingChunk(
        chunk_id=str(row["chunk_id"]),
        source_id=str(row["source_id"]),
        language_id=str(row["language_id"]),
        title=str(row["title"]),
        section_path=tuple(str(item) for item in section_path) if isinstance(section_path, list | tuple) else (),
        canonical_url=str(row["canonical_url"]),
        source_type=cast(SourceContentType, str(row["source_type"])),
        source_trust_tier=cast(SourceTrustTier, str(row["source_trust_tier"])),
        fetched_at=fetched_at if isinstance(fetched_at, datetime) else datetime.fromisoformat(str(fetched_at)),
        content_hash=str(row["content_hash"]),
        text=str(row["content"]),
        topic_tags=tuple(str(item) for item in topic_tags) if isinstance(topic_tags, list | tuple) else (),
        source_version_label=str(row.get("source_version_label") or "unversioned"),
        source_version_kind=cast(SourceVersionKind, str(row.get("source_version_kind") or "rolling")),
        document_content_hash=str(row.get("document_content_hash") or "0" * 64),
        provenance=provenance_from_metadata(row.get("metadata_json")),
    )


def _serialize_agent_grounding_item(item: AgentGroundingItem) -> dict[str, object]:
    return {
        "content": _limit_text(item.content, 800),
        "citation": _serialize_citation(item),
        "relevance_score": item.relevance_score,
        "match_reasons": list(item.match_reasons),
    }


def _serialize_citation_metadata(item: AgentGroundingItem) -> dict[str, object]:
    citation = item.citation
    return {
        "citation_id": citation.citation_id,
        "source_id": citation.source_id,
        "title": citation.title,
        "section_path": list(citation.section_path),
        "canonical_url": citation.canonical_url,
        "source_type": citation.source_type,
        "source_trust_tier": citation.source_trust_tier,
        "source_version_label": citation.source_version_label,
        "source_version_kind": citation.source_version_kind,
        "document_content_hash": citation.document_content_hash,
        "content_hash": citation.content_hash,
        "fetched_at": citation.fetched_at.isoformat(),
        "relevance_score": item.relevance_score,
        "match_reasons": list(item.match_reasons),
    }


def _serialize_citation(item: AgentGroundingItem) -> dict[str, object]:
    metadata = _serialize_citation_metadata(item)
    metadata.pop("relevance_score", None)
    metadata.pop("match_reasons", None)
    return metadata


def _serialize_source_reports(report: GroundingReindexReport) -> list[dict[str, object]]:
    return [
        {
            "source_id": item.source_id,
            "language_id": item.language_id,
            "status": item.status,
            "fetched_documents": item.fetched_documents,
            "chunks_created": item.chunks_created,
            "failure_count": item.failure_count,
            "error_codes": list(item.error_codes),
        }
        for item in report.source_reports
    ]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _limit_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    if max_length <= 3:
        return "." * max_length
    return value[: max_length - 3].rstrip() + "..."
