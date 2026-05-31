"""Teaching chunks repository — indexing and retrieval for RAG."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from psycopg import Connection


def index_knowledge_point_chunks(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
    knowledge_point: Mapping[str, object],
    exercises: Sequence[Mapping[str, object]] | None = None,
) -> int:
    """Index teaching materials for a knowledge point. Returns number of chunks created."""
    conn.execute(
        "DELETE FROM teaching_chunks WHERE knowledge_point_id = %s",
        (knowledge_point_id,),
    )

    chunks_created = 0

    lesson_outline = knowledge_point.get("lesson_outline_json")
    if isinstance(lesson_outline, list):
        for i, section in enumerate(lesson_outline):
            if not isinstance(section, Mapping):
                continue
            title = str(section.get("title", f"Section {i + 1}"))
            content_parts = []
            if section.get("summary"):
                content_parts.append(str(section["summary"]))
            subpoints = section.get("subpoints")
            if isinstance(subpoints, list):
                for sp in subpoints:
                    if isinstance(sp, Mapping):
                        content_parts.append(str(sp.get("text", "")))
                    elif isinstance(sp, str):
                        content_parts.append(sp)
            content = "\n".join(p for p in content_parts if p)
            if content:
                _insert_chunk(conn, knowledge_point_id, "outline", title, content)
                chunks_created += 1

    lesson_sources = knowledge_point.get("lesson_sources_json")
    if isinstance(lesson_sources, list):
        for source in lesson_sources:
            if isinstance(source, Mapping):
                url = str(source.get("url", ""))
                source_title = str(source.get("title", url))
                if url:
                    _insert_chunk(
                        conn, knowledge_point_id, "source_note",
                        source_title, f"Reference: {source_title}",
                        source_url=url,
                    )
                    chunks_created += 1
            elif isinstance(source, str) and source:
                _insert_chunk(
                    conn, knowledge_point_id, "source_note",
                    source, f"Reference: {source}",
                    source_url=source,
                )
                chunks_created += 1

    if exercises:
        for ex in exercises:
            if not isinstance(ex, Mapping):
                continue
            ex_title = str(ex.get("title", "Exercise"))
            prompt = str(ex.get("prompt_markdown", ""))
            content = prompt
            if content.strip():
                metadata: dict[str, object] = {"exercise_id": str(ex.get("id", ""))}
                _insert_chunk(conn, knowledge_point_id, "example", ex_title, content.strip(), metadata=metadata)
                chunks_created += 1

    kp_title = str(knowledge_point.get("title", ""))
    kp_desc = str(knowledge_point.get("description", ""))
    if kp_desc:
        _insert_chunk(
            conn, knowledge_point_id, "explanation",
            kp_title or "Knowledge Point",
            kp_desc,
        )
        chunks_created += 1

    return chunks_created


def index_current_knowledge_point_chunks(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
) -> int:
    """Rebuild teaching chunks from the currently persisted knowledge point and exercises."""
    knowledge_point = conn.execute(
        """
        SELECT *
        FROM knowledge_points
        WHERE id = %s
          AND archived_at IS NULL
          AND deleted_at IS NULL
        """,
        (knowledge_point_id,),
    ).fetchone()
    if knowledge_point is None:
        return 0

    exercises = conn.execute(
        """
        SELECT id, title, prompt_markdown, metadata_json
        FROM exercises
        WHERE knowledge_point_id = %s
          AND archived_at IS NULL
          AND deleted_at IS NULL
        ORDER BY created_at
        """,
        (knowledge_point_id,),
    ).fetchall()
    return index_knowledge_point_chunks(conn, knowledge_point_id, knowledge_point, exercises)


def ensure_current_knowledge_point_chunks(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
) -> int:
    """Backfill chunks for already-persisted lesson content when no index exists yet."""
    existing = conn.execute(
        "SELECT count(*)::int AS cnt FROM teaching_chunks WHERE knowledge_point_id = %s",
        (knowledge_point_id,),
    ).fetchone()
    if existing and _as_int(existing["cnt"], 0) > 0:
        return 0
    return index_current_knowledge_point_chunks(conn, knowledge_point_id)


def search_chunks(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
    query: str,
    *,
    top_k: int = 3,
) -> list[dict[str, object]]:
    """Search teaching chunks for a knowledge point using full-text search."""
    normalized_query = " ".join(word for word in query.split() if word.strip())
    if not normalized_query:
        return _fallback_chunks(conn, knowledge_point_id, top_k)

    rows = conn.execute(
        """
        SELECT id, chunk_type, title, content, source_url,
               ts_rank(search_vector, plainto_tsquery('simple', %s)) AS rank
        FROM teaching_chunks
        WHERE knowledge_point_id = %s
          AND search_vector @@ plainto_tsquery('simple', %s)
        ORDER BY rank DESC
        LIMIT %s
        """,
        (normalized_query, knowledge_point_id, normalized_query, top_k),
    ).fetchall()

    if not rows:
        return _fallback_chunks(conn, knowledge_point_id, top_k)

    return [_serialize_chunk(row) for row in rows]


def _fallback_chunks(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
    top_k: int,
) -> list[dict[str, object]]:
    """Return most recent chunks when search yields no results."""
    rows = conn.execute(
        """
        SELECT id, chunk_type, title, content, source_url, 0.0 AS rank
        FROM teaching_chunks
        WHERE knowledge_point_id = %s
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (knowledge_point_id, top_k),
    ).fetchall()
    return [_serialize_chunk(row) for row in rows]


def _insert_chunk(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
    chunk_type: str,
    title: str,
    content: str,
    *,
    source_url: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO teaching_chunks (knowledge_point_id, chunk_type, title, content, source_url, metadata_json)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            knowledge_point_id,
            chunk_type,
            title[:500],
            content[:4000],
            source_url,
            json.dumps(metadata or {}, ensure_ascii=False),
        ),
    )


def _serialize_chunk(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "chunk_id": str(row["id"]),
        "chunk_type": str(row["chunk_type"]),
        "title": str(row["title"]),
        "content": str(row["content"])[:2000],
        "source_url": row.get("source_url"),
        "relevance_rank": _as_float(row.get("rank"), 0.0),
    }


def _as_float(value: object, default: float) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default
