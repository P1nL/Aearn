from __future__ import annotations

from collections.abc import Generator, Mapping
from datetime import date, datetime
from decimal import Decimal

from psycopg import Connection

from app.services.llm_client import LLMCallError, LLMConfigurationError, LLMInvalidResponseError, OpenAICompatibleClient
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
    chunks: list[str] = []
    for delta in generate_agent_draft_stream(
        conn,
        note,
        style=style,
        focus=focus,
        session_id=session_id,
        attempt_id=attempt_id,
    ):
        chunks.append(delta)
    return "".join(chunks).strip()


def generate_agent_draft_stream(
    conn: Connection[dict[str, object]],
    note: Mapping[str, object],
    *,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> Generator[str, None, str]:
    prompt = _build_agent_draft_prompt(
        conn,
        note,
        style=style,
        focus=focus,
        session_id=session_id,
        attempt_id=attempt_id,
    )
    messages = [
        {
            "role": "system",
            "content": "你是 Aearn 的编程学习笔记助手，只补充当前知识点的可插入笔记片段，不替用户重写整篇笔记。",
        },
        {"role": "user", "content": prompt},
    ]
    try:
        full_text = ""
        for delta in OpenAICompatibleClient().complete_text_stream(messages, temperature=0.3):
            full_text += delta
            yield delta
        if full_text.strip():
            return full_text.strip()
    except (LLMConfigurationError, LLMCallError, LLMInvalidResponseError):
        pass

    for chunk in _chunk_deterministic_draft(prompt):
        yield chunk
    return prompt


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


def _build_agent_draft_prompt(
    conn: Connection[dict[str, object]],
    note: Mapping[str, object],
    *,
    style: str,
    focus: str,
    session_id: str | None,
    attempt_id: str | None,
) -> str:
    context_lines = [f"围绕知识点“{note['knowledge_point_title']}”补全当前笔记，不要重写整篇内容。"]
    content = str(note.get("content_markdown") or "").strip()
    if content:
        context_lines.append(f"现有笔记重点：{content[:120]}")

    if focus == "mistake_summary":
        context_lines.append("重点补充：真实易错点、触发条件和最小反例。")
    else:
        context_lines.append("重点补充：下一次遇到同类代码时的检查顺序。")

    if attempt_id:
        latest_attempt = conn.execute(
            """
            SELECT error_cause, runtime_status, test_pass_rate, explanation_text
            FROM attempts
            WHERE id::text = %s
              AND user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (attempt_id, note["user_id"]),
        ).fetchone()
    else:
        latest_attempt = conn.execute(
            """
            SELECT error_cause, runtime_status, test_pass_rate, explanation_text
            FROM attempts
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (note["user_id"],),
        ).fetchone()
    if latest_attempt is not None:
        context_lines.append(
            f"最近一次尝试状态：{latest_attempt['runtime_status']}，通过率 {_float_or_zero(latest_attempt.get('test_pass_rate')):.2f}。"
        )
        if latest_attempt.get("error_cause"):
            context_lines.append(f"建议补充的错因标签：{latest_attempt['error_cause']}。")
        if latest_attempt.get("explanation_text"):
            context_lines.append(f"可以把你的解释压缩成一条规则：{str(latest_attempt['explanation_text'])[:80]}")

    if session_id:
        context_lines.append(f"来源会话：{session_id}。只整理当前知识点，不展开到独立草稿流程。")

    if style == "concise":
        context_lines.append("建议结构：1. 触发条件 2. 正确写法 3. 一个最小反例。")
    else:
        context_lines.append("建议结构：1. 背景 2. 错因 3. 修正方式 4. 复查清单。")
    return "\n".join(context_lines)


def _chunk_deterministic_draft(content: str) -> Generator[str, None, None]:
    lines = content.splitlines(keepends=True)
    if not lines:
        yield content
        return
    for line in lines:
        yield line


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
