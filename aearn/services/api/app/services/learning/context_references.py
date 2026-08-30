"""Validated, append-only learner-safe context references for Tutor inputs."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import StrEnum
from typing import cast

from psycopg import Connection

from app.core.teaching_safety import sanitize_summary_text
from app.services.learning.contracts import LearningScopeKind, LearningTaskKind
from app.services.learning.track_repository import ScopeSnapshot


CONTEXT_REFERENCE_SCHEMA_VERSION = "tutor_context_reference_v1"
MAX_CONTEXT_REFERENCES = 6
MAX_REFERENCE_EXCERPT = 800
_STABLE_KEY = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContextReferenceKind(StrEnum):
    LESSON_SELECTION = "lesson_selection"
    EXERCISE_FEEDBACK = "exercise_feedback"
    EXECUTION_RESULT = "execution_result"
    REVIEW_FEEDBACK = "review_feedback"
    TEACHING_SESSION_MESSAGE = "teaching_session_message"


class ContextReferenceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable


class PostgresTutorContextReferenceRepository:
    """Validate source artifacts and snapshot only bounded learner-safe fields."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def record_for_input(
        self,
        *,
        user_id: str,
        scope: ScopeSnapshot,
        message_id: str,
        input_revision: int,
        references: Sequence[Mapping[str, object]],
    ) -> tuple[dict[str, object], ...]:
        if not references:
            return ()
        if len(references) > MAX_CONTEXT_REFERENCES:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_INVALID",
                f"每条消息最多包含 {MAX_CONTEXT_REFERENCES} 个结构化引用。",
                status_code=422,
                recoverable=False,
            )
        if scope.scope_kind is not LearningScopeKind.LEARNING_TRACK or scope.learning_track_id is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_SCOPE_CONFLICT",
                "结构化学习引用只能用于已绑定 LearningTrack 的 Tutor 输入。",
            )

        projected: list[dict[str, object]] = []
        seen: set[str] = set()
        for index, raw in enumerate(references):
            reference = self._project_reference(user_id=user_id, scope=scope, raw=raw)
            identity = _reference_identity(reference)
            if identity in seen:
                raise ContextReferenceError(
                    "CONTEXT_REFERENCE_INVALID",
                    "同一条消息不能重复附加相同引用。",
                    status_code=422,
                    recoverable=False,
                )
            seen.add(identity)
            safe_hash = _sha256_json(reference)
            row = self._conn.execute(
                """
                INSERT INTO tutor_message_context_references (
                  user_id, conversation_id, run_id, message_id, input_revision,
                  reference_index, reference_kind, track_id, knowledge_key,
                  document_id, attempt_id, review_session_id, exercise_version_id,
                  source_version, source_hash, safe_payload_json, safe_payload_hash
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s::jsonb, %s
                )
                RETURNING id::text AS id, created_at
                """,
                (
                    user_id,
                    scope.conversation_id,
                    scope.run_id,
                    message_id,
                    input_revision,
                    index,
                    reference["kind"],
                    scope.learning_track_id,
                    reference["knowledge_key"],
                    reference.get("document_id"),
                    reference.get("attempt_id"),
                    reference.get("review_session_id"),
                    reference.get("exercise_version_id"),
                    reference["source_version"],
                    reference["source_hash"],
                    _json(reference),
                    safe_hash,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Tutor context reference insert failed")
            projected.append(
                {
                    "reference_id": str(row["id"]),
                    **reference,
                    "safe_payload_hash": safe_hash,
                    "created_at": _iso(row.get("created_at")),
                }
            )
        return tuple(projected)

    def read_for_input(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
    ) -> tuple[dict[str, object], ...]:
        rows = self._conn.execute(
            """
            SELECT id::text AS reference_id, safe_payload_json, safe_payload_hash, created_at
            FROM tutor_message_context_references
            WHERE user_id = %s AND run_id = %s AND input_revision = %s
            ORDER BY reference_index
            """,
            (user_id, run_id, input_revision),
        ).fetchall()
        return tuple(_public_row(row) for row in rows)

    def read_for_context(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
    ) -> tuple[dict[str, object], ...]:
        public_references = self.read_for_input(
            user_id=user_id,
            run_id=run_id,
            input_revision=input_revision,
        )
        resolved: list[dict[str, object]] = []
        for reference in public_references:
            if reference.get("kind") != ContextReferenceKind.TEACHING_SESSION_MESSAGE.value:
                resolved.append(reference)
                continue
            row = self._conn.execute(
                """
                SELECT messages.content
                FROM tutor_runs AS destination_run
                JOIN tutor_teaching_sessions AS sessions
                  ON sessions.id = %s
                 AND sessions.user_id = destination_run.user_id
                 AND sessions.conversation_id = destination_run.conversation_id
                 AND sessions.track_id = %s
                 AND sessions.knowledge_key = %s
                JOIN tutor_messages AS messages
                  ON messages.id = %s AND messages.conversation_id = sessions.conversation_id
                LEFT JOIN tutor_run_input_events AS input_events
                  ON input_events.message_id = messages.id
                LEFT JOIN tutor_run_public_processes AS tutor_process
                  ON tutor_process.tutor_message_id = messages.id
                JOIN tutor_run_teaching_scopes AS teaching_scopes
                  ON teaching_scopes.run_id = COALESCE(input_events.run_id, tutor_process.run_id)
                 AND teaching_scopes.teaching_session_id = sessions.id
                 AND teaching_scopes.user_id = sessions.user_id
                 AND teaching_scopes.conversation_id = sessions.conversation_id
                WHERE destination_run.id = %s AND destination_run.user_id = %s
                """,
                (
                    reference["teaching_session_id"],
                    reference["learning_track_id"],
                    reference["knowledge_key"],
                    reference["message_id"],
                    run_id,
                    user_id,
                ),
            ).fetchone()
            if row is None:
                raise ContextReferenceError(
                    "CONTEXT_REFERENCE_STALE",
                    "历史教学消息引用的 authority 已变化。",
                )
            resolved.append({**reference, "message_content": str(row.get("content") or "")})
        return tuple(resolved)

    def read_for_messages(
        self,
        *,
        user_id: str,
        conversation_id: str,
        message_ids: Sequence[str],
    ) -> dict[str, tuple[dict[str, object], ...]]:
        if not message_ids:
            return {}
        rows = self._conn.execute(
            """
            SELECT message_id::text AS message_id, id::text AS reference_id,
                   safe_payload_json, safe_payload_hash, created_at
            FROM tutor_message_context_references
            WHERE user_id = %s AND conversation_id = %s
              AND message_id = ANY(%s::uuid[])
            ORDER BY message_id, reference_index
            """,
            (user_id, conversation_id, list(message_ids)),
        ).fetchall()
        result: dict[str, list[dict[str, object]]] = {}
        for row in rows:
            result.setdefault(str(row["message_id"]), []).append(_public_row(row))
        return {key: tuple(value) for key, value in result.items()}

    def _project_reference(
        self,
        *,
        user_id: str,
        scope: ScopeSnapshot,
        raw: Mapping[str, object],
    ) -> dict[str, object]:
        try:
            kind = ContextReferenceKind(str(raw.get("kind") or ""))
        except ValueError as exc:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_INVALID",
                "结构化引用类型不受支持。",
                status_code=422,
                recoverable=False,
            ) from exc
        track_id = str(raw.get("learning_track_id") or "")
        knowledge_key = _stable_key(raw.get("knowledge_key"), "knowledge_key")
        if track_id != scope.learning_track_id:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_SCOPE_CONFLICT",
                "引用不属于当前 Tutor Conversation 的 LearningTrack。",
            )
        if (
            kind is not ContextReferenceKind.TEACHING_SESSION_MESSAGE
            and scope.knowledge_key is not None
            and knowledge_key != scope.knowledge_key
        ):
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_SCOPE_CONFLICT",
                "引用不属于当前 TurnRun 的知识点。",
            )
        allowed_tasks = {
            ContextReferenceKind.LESSON_SELECTION: {
                LearningTaskKind.LESSON_TEACHING,
                LearningTaskKind.REMEDIATION,
            },
            ContextReferenceKind.EXERCISE_FEEDBACK: {
                LearningTaskKind.EXERCISE_FEEDBACK,
                LearningTaskKind.MODEL_CODE_REVIEW,
                LearningTaskKind.REMEDIATION,
            },
            ContextReferenceKind.EXECUTION_RESULT: {
                LearningTaskKind.EXERCISE_FEEDBACK,
                LearningTaskKind.MODEL_CODE_REVIEW,
                LearningTaskKind.REMEDIATION,
            },
            ContextReferenceKind.REVIEW_FEEDBACK: {
                LearningTaskKind.REVIEW_COACHING,
                LearningTaskKind.REMEDIATION,
            },
            ContextReferenceKind.TEACHING_SESSION_MESSAGE: {
                LearningTaskKind.LESSON_TEACHING,
                LearningTaskKind.REMEDIATION,
            },
        }
        if scope.task_kind not in allowed_tasks[kind]:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_SCOPE_CONFLICT",
                "引用类型与当前 TurnRun 教学任务不一致。",
            )
        if kind is ContextReferenceKind.LESSON_SELECTION:
            return self._lesson_selection(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key, raw=raw)
        if kind is ContextReferenceKind.TEACHING_SESSION_MESSAGE:
            return self._teaching_session_message(
                user_id=user_id,
                track_id=track_id,
                conversation_id=scope.conversation_id,
                knowledge_key=knowledge_key,
                raw=raw,
            )
        if kind is ContextReferenceKind.REVIEW_FEEDBACK:
            return self._review_feedback(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key, raw=raw)
        return self._exercise_feedback(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            raw=raw,
            execution_required=kind is ContextReferenceKind.EXECUTION_RESULT,
        )

    def _lesson_selection(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        raw: Mapping[str, object],
    ) -> dict[str, object]:
        document_id = str(raw.get("document_id") or "")
        expected_hash = str(raw.get("document_content_hash") or "").lower()
        block_id = _stable_key(raw.get("block_id"), "block_id")
        excerpt = _normalize_selection(raw.get("excerpt"))
        start_offset = _bounded_offset(raw.get("start_offset"), "start_offset")
        end_offset = _bounded_offset(raw.get("end_offset"), "end_offset")
        if (
            not document_id
            or not _SHA256.fullmatch(expected_hash)
            or not excerpt
            or len(excerpt) > MAX_REFERENCE_EXCERPT
            or end_offset <= start_offset
            or end_offset - start_offset != len(excerpt)
        ):
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_INVALID",
                "课程选择引用缺少有效 document、hash、block 或 excerpt。",
                status_code=422,
                recoverable=False,
            )
        row = self._conn.execute(
            """
            SELECT documents.id, documents.content_hash, documents.content_standard_version,
                   documents.blocks_json, assignments.assignment_version
            FROM tutor_lesson_assignments AS assignments
            JOIN tutor_lesson_documents AS documents
              ON (documents.id, documents.user_id, documents.track_id, documents.knowledge_key) =
                 (assignments.document_id, assignments.user_id, assignments.track_id, assignments.knowledge_key)
            WHERE assignments.user_id = %s AND assignments.track_id = %s
              AND assignments.knowledge_key = %s AND assignments.status = 'active'
              AND assignments.document_id = %s
            """,
            (user_id, track_id, knowledge_key, document_id),
        ).fetchone()
        if row is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_STALE",
                "课程引用对应的 active frozen document 已变化，请重新选择。",
            )
        content_hash = str(row["content_hash"])
        if content_hash != expected_hash:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_STALE",
                "课程引用的 document hash 已过期，请重新选择。",
            )
        raw_blocks = row.get("blocks_json")
        blocks: Sequence[object] = raw_blocks if isinstance(raw_blocks, list | tuple) else ()
        block = next(
            (item for item in blocks if isinstance(item, Mapping) and str(item.get("block_id")) == block_id),
            None,
        )
        if block is None:
            raise ContextReferenceError("CONTEXT_REFERENCE_STALE", "课程引用的 block 已不存在，请重新选择。")
        canonical = _normalize_selection(_lesson_block_public_text(block))
        if end_offset > len(canonical) or canonical[start_offset:end_offset] != excerpt:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_STALE",
                "所选文本范围不属于当前 frozen LessonDocument，请重新选择。",
            )
        return {
            "schema_version": CONTEXT_REFERENCE_SCHEMA_VERSION,
            "kind": ContextReferenceKind.LESSON_SELECTION.value,
            "learning_track_id": track_id,
            "knowledge_key": knowledge_key,
            "document_id": document_id,
            "document_content_hash": content_hash,
            "content_standard_version": str(row["content_standard_version"]),
            "assignment_version": _int(row.get("assignment_version")),
            "block_id": block_id,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "safe_excerpt": excerpt,
            "source_version": str(row["content_standard_version"]),
            "source_hash": content_hash,
        }

    def _teaching_session_message(
        self,
        *,
        user_id: str,
        track_id: str,
        conversation_id: str,
        knowledge_key: str,
        raw: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = str(raw.get("teaching_session_id") or "")
        message_id = str(raw.get("message_id") or "")
        if not session_id or not message_id:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_INVALID",
                "历史教学消息引用缺少 exact session/message identity。",
                status_code=422,
                recoverable=False,
            )
        row = self._conn.execute(
            """
            SELECT sessions.id::text AS teaching_session_id,
                   sessions.version AS session_version,
                   messages.id::text AS message_id,
                   messages.role,
                   messages.content,
                   messages.created_at,
                   COALESCE(input_events.run_id, tutor_process.run_id)::text AS turn_id
            FROM tutor_teaching_sessions AS sessions
            JOIN tutor_messages AS messages
              ON messages.id = %s AND messages.conversation_id = sessions.conversation_id
            LEFT JOIN tutor_run_input_events AS input_events
              ON input_events.message_id = messages.id
            LEFT JOIN tutor_run_public_processes AS tutor_process
              ON tutor_process.tutor_message_id = messages.id
            JOIN tutor_run_teaching_scopes AS teaching_scopes
              ON teaching_scopes.run_id = COALESCE(input_events.run_id, tutor_process.run_id)
             AND teaching_scopes.teaching_session_id = sessions.id
             AND teaching_scopes.user_id = sessions.user_id
             AND teaching_scopes.conversation_id = sessions.conversation_id
            WHERE sessions.id = %s AND sessions.user_id = %s
              AND sessions.track_id = %s AND sessions.conversation_id = %s
              AND sessions.knowledge_key = %s
            """,
            (message_id, session_id, user_id, track_id, conversation_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_NOT_FOUND",
                "历史教学消息不存在或不属于指定 session、conversation 与 LearningTrack。",
                status_code=404,
            )
        role = str(row["role"])
        content = str(row.get("content") or "")
        summary = f"历史{'提问' if role == 'learner' else '讲解'}（exact session/message reference）"
        source_version = f"teaching-session:{_int(row.get('session_version'))}"
        source_hash = _sha256_json({
            "teaching_session_id": session_id,
            "message_id": message_id,
            "turn_id": str(row["turn_id"]),
            "role": role,
            "content": content,
        })
        return {
            "schema_version": CONTEXT_REFERENCE_SCHEMA_VERSION,
            "kind": ContextReferenceKind.TEACHING_SESSION_MESSAGE.value,
            "learning_track_id": track_id,
            "knowledge_key": knowledge_key,
            "teaching_session_id": session_id,
            "message_id": message_id,
            "turn_id": str(row["turn_id"]),
            "role": role,
            "message_summary": summary,
            "message_created_at": _iso(row.get("created_at")),
            "source_version": source_version,
            "source_hash": source_hash,
        }

    def _exercise_feedback(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        raw: Mapping[str, object],
        execution_required: bool,
    ) -> dict[str, object]:
        attempt_id = str(raw.get("attempt_id") or "")
        row = self._conn.execute(
            """
            SELECT attempts.id, attempts.attempt_type, attempts.exercise_version_id,
                   attempts.assistance_kind, results.outcome, results.score,
                   results.safe_feedback_json, results.capability_scores_json,
                   results.result_hash, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE attempts.id = %s AND attempts.user_id = %s AND attempts.track_id = %s
              AND attempts.knowledge_key = %s AND attempts.attempt_type IN ('run', 'submit')
            """,
            (attempt_id, user_id, track_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_NOT_FOUND",
                "练习结果不存在、尚未完成或不属于当前学习范围。",
                status_code=404,
            )
        if execution_required and row.get("execution_job_id") is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_NOT_READY",
                "该 Attempt 没有可引用的受控执行结果。",
            )
        kind = ContextReferenceKind.EXECUTION_RESULT if execution_required else ContextReferenceKind.EXERCISE_FEEDBACK
        result_hash = str(row["result_hash"])
        payload: dict[str, object] = {
            "schema_version": CONTEXT_REFERENCE_SCHEMA_VERSION,
            "kind": kind.value,
            "learning_track_id": track_id,
            "knowledge_key": knowledge_key,
            "attempt_id": attempt_id,
            "attempt_type": str(row["attempt_type"]),
            "exercise_version_id": str(row["exercise_version_id"]),
            "outcome": str(row["outcome"]),
            "score": _score(row.get("score")),
            "assistance_kind": str(row.get("assistance_kind") or "independent"),
            "feedback_summary": _feedback_summary(row.get("safe_feedback_json")),
            "capability_scores": _capability_scores(row.get("capability_scores_json")),
            "terminal_at": _iso(row.get("terminal_at")),
            "source_version": str(row["exercise_version_id"]),
            "source_hash": result_hash,
        }
        if execution_required:
            payload["execution_job_id"] = str(row["execution_job_id"])
            payload["execution_job_state"] = str(row.get("execution_job_state") or "unavailable")
        return payload

    def _review_feedback(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        raw: Mapping[str, object],
    ) -> dict[str, object]:
        session_id = str(raw.get("review_session_id") or "")
        attempt_id = str(raw.get("attempt_id") or "")
        row = self._conn.execute(
            """
            SELECT attempts.id, attempts.exercise_version_id, attempts.assistance_kind,
                   attempts.review_item_id, sessions.version AS session_version,
                   results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json, results.result_hash, results.terminal_at
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_review_sessions AS sessions
              ON (sessions.id, sessions.user_id, sessions.track_id) =
                 (attempts.review_session_id, attempts.user_id, attempts.track_id)
            JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE attempts.id = %s AND attempts.user_id = %s AND attempts.track_id = %s
              AND attempts.knowledge_key = %s AND attempts.review_session_id = %s
              AND attempts.attempt_type = 'review_submit'
            """,
            (attempt_id, user_id, track_id, knowledge_key, session_id),
        ).fetchone()
        if row is None:
            raise ContextReferenceError(
                "CONTEXT_REFERENCE_NOT_FOUND",
                "复习反馈不存在、尚未完成或不属于当前学习范围。",
                status_code=404,
            )
        result_hash = str(row["result_hash"])
        return {
            "schema_version": CONTEXT_REFERENCE_SCHEMA_VERSION,
            "kind": ContextReferenceKind.REVIEW_FEEDBACK.value,
            "learning_track_id": track_id,
            "knowledge_key": knowledge_key,
            "review_session_id": session_id,
            "review_item_id": str(row["review_item_id"]),
            "attempt_id": attempt_id,
            "exercise_version_id": str(row["exercise_version_id"]),
            "session_version": _int(row.get("session_version")),
            "outcome": str(row["outcome"]),
            "score": _score(row.get("score")),
            "assistance_kind": str(row.get("assistance_kind") or "independent"),
            "feedback_summary": _feedback_summary(row.get("safe_feedback_json")),
            "capability_scores": _capability_scores(row.get("capability_scores_json")),
            "terminal_at": _iso(row.get("terminal_at")),
            "source_version": str(row["exercise_version_id"]),
            "source_hash": result_hash,
        }


def _public_row(row: Mapping[str, object]) -> dict[str, object]:
    payload = row.get("safe_payload_json")
    if not isinstance(payload, Mapping):
        raise ContextReferenceError(
            "CONTEXT_REFERENCE_INVALID",
            "已保存的结构化引用无法安全读取。",
            status_code=500,
            recoverable=False,
        )
    safe_hash = str(row.get("safe_payload_hash") or "")
    if not _SHA256.fullmatch(safe_hash) or _sha256_json(payload) != safe_hash:
        raise ContextReferenceError(
            "CONTEXT_REFERENCE_INVALID",
            "已保存的结构化引用完整性校验失败。",
            status_code=500,
            recoverable=False,
        )
    return {
        "reference_id": str(row["reference_id"]),
        **{str(key): _safe_json_value(value) for key, value in payload.items()},
        "safe_payload_hash": safe_hash,
        "created_at": _iso(row.get("created_at")),
    }


def _lesson_block_public_text(block: Mapping[str, object]) -> str:
    block_type = str(block.get("type") or "")
    keys_by_type = {
        "heading": ("title", "subtitle"),
        "learning_objectives": ("items",),
        "concept": ("title", "paragraphs"),
        "authority_note": ("title", "statement"),
        "code_example": ("title", "code", "explanation"),
        "comparison": ("title", "columns", "rows", "conclusion"),
        "hint": ("title", "steps"),
        "exercise_gate": ("learner_prompt",),
        "summary": ("points",),
        "next_steps": ("items",),
    }
    values = [_flatten_text(block.get(key)) for key in keys_by_type.get(block_type, ())]
    return "\n".join(value for value in values if value)


def _flatten_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return "\n".join(item for child in value if (item := _flatten_text(child)))
    return ""


def _normalize_selection(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).replace("\r\n", "\n").replace("\r", "\n")
    return " ".join(text.split())


def _feedback_summary(value: object) -> str:
    if not isinstance(value, Mapping):
        return "服务器已记录 learner-safe 结果。"
    for key in ("message", "summary", "text"):
        candidate = sanitize_summary_text(value.get(key), max_length=600)
        if candidate:
            return candidate
    return "服务器已记录 learner-safe 结果。"


def _capability_scores(value: object) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, float] = {}
    for raw_key, raw_value in list(value.items())[:16]:
        key = str(raw_key or "").strip().lower()
        if not _STABLE_KEY.fullmatch(key):
            continue
        if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
            continue
        score = float(raw_value)
        if 0 <= score <= 1:
            result[key] = round(score, 4)
    return result


def _reference_identity(reference: Mapping[str, object]) -> str:
    return _sha256_json(
        {
            key: reference.get(key)
            for key in (
                "kind", "learning_track_id", "knowledge_key", "document_id", "block_id",
                "start_offset", "end_offset", "attempt_id", "review_session_id",
                "teaching_session_id", "message_id",
            )
        }
    )


def _stable_key(value: object, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _STABLE_KEY.fullmatch(normalized):
        raise ContextReferenceError(
            "CONTEXT_REFERENCE_INVALID",
            f"{label} 不是有效 stable key。",
            status_code=422,
            recoverable=False,
        )
    return normalized


def _bounded_offset(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 48_000:
        raise ContextReferenceError(
            "CONTEXT_REFERENCE_INVALID",
            f"{label} 不是有效课程选择范围。",
            status_code=422,
            recoverable=False,
        )
    return value


def _score(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return round(max(0.0, min(1.0, float(value))), 4)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(cast(int | float | str, value))
    except (TypeError, ValueError):
        return 0


def _safe_json_value(value: object) -> object:
    if value is None or isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _safe_json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_safe_json_value(item) for item in value]
    return str(value)


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _sha256_json(value: object) -> str:
    canonical = json.dumps(_safe_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(_safe_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
