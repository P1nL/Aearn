from __future__ import annotations

from collections.abc import Generator, Mapping
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg import Connection

from app.agents.note_assist_agent import (
    NoteAssistContext,
    assert_note_assist_judgement_ready,
    assert_safe_note_draft_output,
    build_note_assist_client,
)
from app.services.llm_client import LLMConfigurationError, LLMInvalidResponseError
from app.services.user_repository import get_user


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_notes(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str | None,
    limit: int,
) -> dict[str, object]:
    _ensure_user_exists(conn, user_id)
    if knowledge_point_id is not None:
        _load_knowledge_point_context(conn, user_id=user_id, knowledge_point_id=knowledge_point_id)

    params: dict[str, object] = {
        "user_id": user_id,
        "limit": limit,
    }
    conditions = [
        "notes.user_id = %(user_id)s",
        "notes.deleted_at IS NULL",
        "knowledge_points.deleted_at IS NULL",
        "plan_modules.deleted_at IS NULL",
        "learning_plans.deleted_at IS NULL",
    ]
    if knowledge_point_id is not None:
        conditions.append("notes.knowledge_point_id::text = %(knowledge_point_id)s")
        params["knowledge_point_id"] = knowledge_point_id

    rows = conn.execute(
        f"""
        SELECT
          notes.*,
          knowledge_points.title AS knowledge_point_title,
          knowledge_points.description AS knowledge_point_description,
          plan_modules.id AS module_id,
          plan_modules.title AS module_title,
          learning_plans.id AS plan_id,
          learning_plans.language AS plan_language,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM notes
        JOIN knowledge_points ON knowledge_points.id = notes.knowledge_point_id
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        WHERE {" AND ".join(conditions)}
        ORDER BY notes.updated_at DESC, notes.created_at DESC
        LIMIT %(limit)s
        """,
        params,
    ).fetchall()

    return {
        "items": [serialize_note(row) for row in rows],
        "page_info": {
            "limit": limit,
            "next_cursor": None,
            "has_more": False,
        },
    }


def create_note(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    title: str | None,
    content_markdown: str,
) -> tuple[dict[str, object], bool]:
    context = _load_knowledge_point_context(conn, user_id=user_id, knowledge_point_id=knowledge_point_id)
    existing = _load_note_row_by_user_and_knowledge_point(
        conn,
        user_id=user_id,
        knowledge_point_id=knowledge_point_id,
    )
    if existing is not None:
        return serialize_note(existing), True

    created = conn.execute(
        """
        INSERT INTO notes (
          user_id, knowledge_point_id, title, content_markdown, is_user_edited
        )
        VALUES (%s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            user_id,
            knowledge_point_id,
            title or context["title"],
            content_markdown,
            True,
        ),
    ).fetchone()
    if created is None:
        raise RuntimeError("note insert returned no row")
    note = _reload_note(conn, str(created["id"]))
    if note is None:
        raise RuntimeError("created note could not be reloaded")
    return serialize_note(note), False


def update_note(
    conn: Connection[dict[str, object]],
    *,
    note_id: str,
    title: str | None,
    content_markdown: str | None,
    is_user_edited: bool,
) -> dict[str, object]:
    current = _load_note_row_by_id(conn, note_id)
    if current is None:
        raise EntityNotFoundError("NOTE_NOT_FOUND", "笔记不存在")

    next_title = title if title is not None else str(current["title"] or "")
    next_content = content_markdown if content_markdown is not None else str(current["content_markdown"] or "")
    updated = conn.execute(
        """
        UPDATE notes
        SET title = %s,
            content_markdown = %s,
            is_user_edited = %s
        WHERE id = %s
          AND deleted_at IS NULL
        RETURNING *
        """,
        (
            next_title,
            next_content,
            is_user_edited,
            note_id,
        ),
    ).fetchone()
    if updated is None:
        raise EntityNotFoundError("NOTE_NOT_FOUND", "笔记不存在")
    note = _reload_note(conn, note_id)
    if note is None:
        raise RuntimeError("updated note could not be reloaded")
    return serialize_note(note)


def update_agent_draft(
    conn: Connection[dict[str, object]],
    *,
    note_id: str,
    user_id: str,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> dict[str, object]:
    current = load_note_for_agent_draft(conn, note_id=note_id, user_id=user_id)
    draft = generate_agent_draft(
        conn,
        current,
        style=style,
        focus=focus,
        session_id=session_id,
        attempt_id=attempt_id,
    )
    return update_agent_draft_content(conn, note_id=note_id, draft=draft)


def load_note_for_agent_draft(
    conn: Connection[dict[str, object]],
    *,
    note_id: str,
    user_id: str,
) -> Mapping[str, object]:
    _ensure_user_exists(conn, user_id)
    current = _load_note_row_by_id(conn, note_id)
    if current is None:
        raise EntityNotFoundError("NOTE_NOT_FOUND", "笔记不存在")
    if str(current["user_id"]) != user_id:
        raise EntityNotFoundError("NOTE_NOT_FOUND", "笔记不存在")
    return current


def update_agent_draft_content(
    conn: Connection[dict[str, object]],
    *,
    note_id: str,
    draft: str,
) -> dict[str, object]:
    updated = conn.execute(
        """
        UPDATE notes
        SET agent_draft_content = %s
        WHERE id = %s
          AND deleted_at IS NULL
        RETURNING *
        """,
        (draft, note_id),
    ).fetchone()
    if updated is None:
        raise EntityNotFoundError("NOTE_NOT_FOUND", "笔记不存在")
    note = _reload_note(conn, note_id)
    if note is None:
        raise RuntimeError("agent draft note could not be reloaded")
    return serialize_note(note)


def generate_agent_draft(
    conn: Connection[dict[str, object]],
    note: Mapping[str, object],
    *,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> str:
    context = _build_note_assist_context(
        conn,
        note,
        style=style,
        focus=focus,
        session_id=session_id,
        attempt_id=attempt_id,
    )
    client = build_note_assist_client()
    if client is None:
        raise LLMConfigurationError("Note Assist requires configured model API")
    draft = client.complete_text(context, temperature=0.3)
    if draft:
        draft = draft.strip()
        if draft:
            assert_note_assist_judgement_ready(draft, context)
            assert_safe_note_draft_output(draft)
            return draft
    raise LLMInvalidResponseError("Note Assist model produced no draft")


def generate_agent_draft_stream(
    conn: Connection[dict[str, object]],
    note: Mapping[str, object],
    *,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> Generator[str, None, str]:
    context = _build_note_assist_context(
        conn,
        note,
        style=style,
        focus=focus,
        session_id=session_id,
        attempt_id=attempt_id,
    )
    client = build_note_assist_client()
    if client is None:
        raise LLMConfigurationError("Note Assist requires configured model API")
    full_text = ""
    for delta in client.complete_text_stream(context, temperature=0.3):
        if not delta:
            continue
        assert_safe_note_draft_output(delta)
        full_text += delta
        yield delta
    full_text = full_text.strip()
    if not full_text:
        raise LLMInvalidResponseError("Note Assist model produced no draft")
    assert_note_assist_judgement_ready(full_text, context)
    assert_safe_note_draft_output(full_text)
    return full_text


def _ensure_user_exists(conn: Connection[dict[str, object]], user_id: str) -> None:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")


def _load_knowledge_point_context(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
) -> Mapping[str, object]:
    _ensure_user_exists(conn, user_id)
    row = conn.execute(
        """
        SELECT
          knowledge_points.*,
          plan_modules.id AS module_id,
          plan_modules.title AS module_title,
          learning_plans.id AS plan_id,
          learning_plans.language AS plan_language,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        WHERE knowledge_points.id = %s
          AND learning_plans.user_id = %s
          AND knowledge_points.deleted_at IS NULL
          AND plan_modules.deleted_at IS NULL
          AND learning_plans.deleted_at IS NULL
        LIMIT 1
        """,
        (knowledge_point_id, user_id),
    ).fetchone()
    if row is None:
        raise EntityNotFoundError("KNOWLEDGE_POINT_NOT_FOUND", "知识点不存在")
    return row


def _load_note_row_by_user_and_knowledge_point(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT
          notes.*,
          knowledge_points.title AS knowledge_point_title,
          knowledge_points.description AS knowledge_point_description,
          plan_modules.id AS module_id,
          plan_modules.title AS module_title,
          learning_plans.id AS plan_id,
          learning_plans.language AS plan_language,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM notes
        JOIN knowledge_points ON knowledge_points.id = notes.knowledge_point_id
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        WHERE notes.user_id = %s
          AND notes.knowledge_point_id = %s
          AND notes.deleted_at IS NULL
        LIMIT 1
        """,
        (user_id, knowledge_point_id),
    ).fetchone()


def _load_note_row_by_id(
    conn: Connection[dict[str, object]],
    note_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT
          notes.*,
          knowledge_points.title AS knowledge_point_title,
          knowledge_points.description AS knowledge_point_description,
          plan_modules.id AS module_id,
          plan_modules.title AS module_title,
          learning_plans.id AS plan_id,
          learning_plans.language AS plan_language,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM notes
        JOIN knowledge_points ON knowledge_points.id = notes.knowledge_point_id
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        WHERE notes.id = %s
          AND notes.deleted_at IS NULL
        LIMIT 1
        """,
        (note_id,),
    ).fetchone()


def _reload_note(conn: Connection[dict[str, object]], note_id: str) -> Mapping[str, object] | None:
    return _load_note_row_by_id(conn, note_id)


def _build_note_assist_context(
    conn: Connection[dict[str, object]],
    note: Mapping[str, object],
    *,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> NoteAssistContext:
    latest_attempt = _load_latest_note_attempt_summary(
        conn,
        user_id=str(note["user_id"]),
        knowledge_point_id=str(note["knowledge_point_id"]),
        session_id=session_id,
        attempt_id=attempt_id,
    )
    session_summary = _load_note_session_summary(
        conn,
        user_id=str(note["user_id"]),
        plan_id=str(note["plan_id"]),
        session_id=session_id,
    )
    return NoteAssistContext(
        note_id=str(note["id"]),
        note_title=str(note["title"] or note["knowledge_point_title"]),
        knowledge_point_title=str(note["knowledge_point_title"]),
        module_title=str(note["module_title"]),
        language=str(note["plan_language"]),
        note_excerpt=_bounded_excerpt(str(note.get("content_markdown") or ""), 180),
        style=style,
        focus=focus,
        session_id=session_id,
        session_summary=session_summary,
        latest_attempt=latest_attempt,
    )


def _load_note_session_summary(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    session_id: str | None,
) -> str | None:
    normalized_session_id = _valid_uuid_text(session_id)
    if normalized_session_id is None:
        return None
    row = conn.execute(
        """
        SELECT summary_text
        FROM learning_sessions
        WHERE id = %s
          AND user_id = %s
          AND plan_id = %s
        LIMIT 1
        """,
        (normalized_session_id, user_id, plan_id),
    ).fetchone()
    if row is None:
        return None
    summary = str(row.get("summary_text") or "").strip()
    if not summary:
        return None
    return _bounded_excerpt(summary, 240)


def _load_latest_note_attempt_summary(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    session_id: str | None,
    attempt_id: str | None,
) -> dict[str, object] | None:
    normalized_attempt_id = _valid_uuid_text(attempt_id)
    normalized_session_id = _valid_uuid_text(session_id)

    if normalized_attempt_id is not None:
        row = _fetch_note_attempt_summary(
            conn,
            where_clause=(
                "attempts.id = %s AND attempts.user_id = %s AND exercises.knowledge_point_id = %s"
                + (" AND attempts.session_id = %s" if normalized_session_id else "")
            ),
            params=(
                normalized_attempt_id,
                user_id,
                knowledge_point_id,
                normalized_session_id,
            )
            if normalized_session_id
            else (
                normalized_attempt_id,
                user_id,
                knowledge_point_id,
            ),
        )
        if row is not None:
            return _serialize_note_attempt_summary(row)

    if normalized_session_id is not None:
        row = _fetch_note_attempt_summary(
            conn,
            where_clause=(
                "attempts.user_id = %s AND attempts.session_id = %s AND exercises.knowledge_point_id = %s"
            ),
            params=(user_id, normalized_session_id, knowledge_point_id),
        )
        if row is not None:
            return _serialize_note_attempt_summary(row)

    row = _fetch_note_attempt_summary(
        conn,
        where_clause="attempts.user_id = %s AND exercises.knowledge_point_id = %s",
        params=(user_id, knowledge_point_id),
    )
    if row is None:
        return None
    return _serialize_note_attempt_summary(row)


def _valid_uuid_text(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        return str(UUID(candidate))
    except (ValueError, AttributeError, TypeError):
        return None


def _fetch_note_attempt_summary(
    conn: Connection[dict[str, object]],
    *,
    where_clause: str,
    params: tuple[object, ...],
) -> Mapping[str, object] | None:
    return conn.execute(
        f"""
        SELECT
          attempts.id,
          attempts.session_id,
          attempts.attempt_type,
          attempts.runtime_status,
          attempts.test_pass_rate,
          attempts.passed_test_count,
          attempts.total_test_count,
          attempts.error_message,
          attempts.error_cause,
          attempts.explanation_text,
          attempts.hint_usage_count,
          attempts.error_count
        FROM attempts
        JOIN exercises ON exercises.id = attempts.exercise_id
        WHERE {where_clause}
        ORDER BY attempts.created_at DESC
        LIMIT 1
        """,
        params,
    ).fetchone()


def _serialize_note_attempt_summary(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "available": True,
        "attempt_id": str(row["id"]),
        "session_id": str(row["session_id"]),
        "attempt_type": row["attempt_type"],
        "runtime_status": row["runtime_status"],
        "test_pass_rate": _float_or_zero(row.get("test_pass_rate")),
        "passed_test_count": row["passed_test_count"],
        "total_test_count": row["total_test_count"],
        "error_message": row["error_message"],
        "error_cause": row["error_cause"],
        "explanation_text": row["explanation_text"],
        "hint_usage_count": row["hint_usage_count"],
        "error_count": row["error_count"],
    }


def _bounded_excerpt(text: str, max_length: int) -> str:
    stripped = text.strip()
    if len(stripped) <= max_length:
        return stripped
    return f"{stripped[:max_length]}..."


def serialize_note(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "knowledge_point_id": str(row["knowledge_point_id"]),
        "title": row["title"],
        "content_markdown": row["content_markdown"],
        "agent_draft_content": row["agent_draft_content"],
        "is_user_edited": row["is_user_edited"],
        "updated_at": _isoformat(row["updated_at"]),
        "language": row["plan_language"],
        "plan_id": str(row["plan_id"]),
        "course": {
            "id": str(row["course_id"]),
            "title": row["course_title"],
        },
        "module": {
            "id": str(row["module_id"]),
            "title": row["module_title"],
        },
        "knowledge_point": {
            "id": str(row["knowledge_point_id"]),
            "title": row["knowledge_point_title"],
            "description": row["knowledge_point_description"],
        },
    }


def _float_or_zero(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _isoformat(value: object) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)
