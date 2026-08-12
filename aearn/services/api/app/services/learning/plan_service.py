"""Use cases and learner-safe projections for conversational learning-plan sessions."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection

from app.services.learning.contracts import LearningScope, LearningScopeKind
from app.services.learning.plan_drafting import draft_artifact_from_row
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.learning.plan_repository import (
    LearningPlanSessionConflict,
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.learning.track_repository import (
    LearningScopeConflict,
    LearningTrackNotFound,
    PostgresLearningTrackRepository,
)
from app.services.learning.track_service import LearningTrackService
from app.services.runners.language_capabilities import (
    capabilities_for_public_course_language,
    get_language_capability,
)
from app.services.tutor.persistence import PostgresTutorRepository, TutorRunNotFound


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class LearningPlanSessionServiceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        recoverable: bool = True,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})


class LearningPlanSessionService:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._repository = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)
        self._track_repository = PostgresLearningTrackRepository(conn)
        self._tutor_repository = PostgresTutorRepository(conn)
        self._track_service = LearningTrackService(conn)

    def create_session(
        self,
        *,
        user_id: str,
        preferred_language_id: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        language_id = _optional_language(preferred_language_id)
        return self._mutate(
            user_id=normalized_user_id,
            operation="learning_plan_session.create",
            idempotency_key=idempotency_key,
            request_body={"preferred_language_id": language_id},
            action=lambda: self._create_session(
                user_id=normalized_user_id,
                preferred_language_id=language_id,
            ),
        )

    def current_session(self, *, user_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        self._assert_user(normalized_user_id)
        row = self._repository.read_current_session(user_id=normalized_user_id)
        return {"session": self._project_session(row) if row is not None else None}

    def read_session(self, *, user_id: str, session_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_session_id = _uuid(session_id, label="session_id")
        try:
            row = self._repository.read_session(user_id=normalized_user_id, session_id=normalized_session_id)
        except LearningPlanSessionNotFound as exc:
            raise _not_found(normalized_session_id) from exc
        return {"session": self._project_session(row)}

    def cancel_session(
        self,
        *,
        user_id: str,
        session_id: str,
        expected_session_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_session_id = _uuid(session_id, label="session_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation=f"learning_plan_session.cancel:{normalized_session_id}",
            idempotency_key=idempotency_key,
            request_body={
                "session_id": normalized_session_id,
                "expected_session_version": expected_session_version,
            },
            action=lambda: self._cancel_session(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                expected_session_version=expected_session_version,
            ),
        )

    def confirm_session(
        self,
        *,
        user_id: str,
        session_id: str,
        expected_session_version: int,
        draft_id: str,
        draft_version: int,
        content_hash: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_session_id = _uuid(session_id, label="session_id")
        normalized_draft_id = _uuid(draft_id, label="draft_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation=f"learning_plan_session.confirm:{normalized_session_id}",
            idempotency_key=idempotency_key,
            request_body={
                "session_id": normalized_session_id,
                "expected_session_version": expected_session_version,
                "draft_id": normalized_draft_id,
                "draft_version": draft_version,
                "content_hash": content_hash,
            },
            action=lambda: self._confirm_session(
                user_id=normalized_user_id,
                session_id=normalized_session_id,
                expected_session_version=expected_session_version,
                draft_id=normalized_draft_id,
                draft_version=draft_version,
                content_hash=content_hash,
            ),
        )

    def _create_session(self, *, user_id: str, preferred_language_id: str | None) -> dict[str, object]:
        self._conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext('learning-plan-session-active'))",
            (user_id,),
        )
        current = self._repository.read_current_session(user_id=user_id, for_update=True)
        if current is not None:
            return {"session": self._project_session(current), "resumed": True}
        try:
            conversation_id = self._tutor_repository.create_conversation(user_id=user_id)
            self._track_repository.bind_conversation_scope(
                user_id=user_id,
                conversation_id=conversation_id,
                scope=LearningScope(scope_kind=LearningScopeKind.PLAN_DRAFTING),
            )
            row = self._repository.create_session(
                user_id=user_id,
                conversation_id=conversation_id,
                preferred_language_id=preferred_language_id,
            )
        except (TutorRunNotFound, LearningTrackNotFound) as exc:
            raise LearningPlanSessionServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404) from exc
        except LearningScopeConflict as exc:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_SESSION_CONFLICT",
                "计划制定对话当前不可用，请刷新后重试。",
                status_code=409,
            ) from exc
        return {"session": self._project_session(row), "resumed": False}

    def _cancel_session(
        self,
        *,
        user_id: str,
        session_id: str,
        expected_session_version: int,
    ) -> dict[str, object]:
        try:
            self._repository.cancel_session(
                user_id=user_id,
                session_id=session_id,
                expected_version=expected_session_version,
            )
            row = self._repository.read_session(user_id=user_id, session_id=session_id)
        except LearningPlanSessionNotFound as exc:
            raise _not_found(session_id) from exc
        except LearningPlanSessionConflict as exc:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_SESSION_CONFLICT",
                "计划制定会话已发生变化，请刷新后重试。",
                status_code=409,
                details={"session_id": session_id},
            ) from exc
        return {"session": self._project_session(row)}

    def _confirm_session(
        self,
        *,
        user_id: str,
        session_id: str,
        expected_session_version: int,
        draft_id: str,
        draft_version: int,
        content_hash: str,
    ) -> dict[str, object]:
        try:
            session = self._repository.read_session(
                user_id=user_id,
                session_id=session_id,
                for_update=True,
            )
        except LearningPlanSessionNotFound as exc:
            raise _not_found(session_id) from exc
        status = str(session["status"])
        if status == "confirmed":
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_SESSION_ALREADY_CONFIRMED",
                "该计划制定会话已经确认。",
                status_code=409,
                recoverable=False,
                details={"session_id": session_id},
            )
        if status != "draft_ready" or session.get("current_draft_id") is None:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_DRAFT_NOT_READY",
                "当前还没有可确认的学习计划。",
                status_code=409,
                details={"session_id": session_id},
            )
        if (
            _int(session.get("version")) != expected_session_version
            or str(session.get("current_draft_id")) != draft_id
            or _int(session.get("draft_version")) != draft_version
            or str(session.get("content_hash")) != content_hash
        ):
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_DRAFT_STALE",
                "学习计划已经更新，请刷新后确认最新版本。",
                status_code=409,
                details={
                    "session_id": session_id,
                    "current_session_version": _int(session.get("version")),
                    "current_draft_id": str(session.get("current_draft_id")),
                    "current_draft_version": _int(session.get("draft_version")),
                },
            )
        stored_facts_fingerprint = session.get("facts_fingerprint")
        if stored_facts_fingerprint is not None:
            _values, current_fingerprint, current_revision, _missing = self._facts.profile_fact_state(
                user_id=user_id,
                session_id=session_id,
            )
            if (
                str(stored_facts_fingerprint) != current_fingerprint
                or _int(session.get("facts_revision")) != current_revision
            ):
                raise LearningPlanSessionServiceError(
                    "LEARNING_PLAN_DRAFT_STALE",
                    "学习事实已经更新，请重新生成并确认最新计划。",
                    status_code=409,
                    details={"session_id": session_id},
                )
        try:
            artifact = draft_artifact_from_row(session)
        except ValueError as exc:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_DRAFT_INVALID",
                "学习计划草案未通过结构校验。",
                status_code=422,
                recoverable=False,
            ) from exc
        try:
            track_id = self._track_repository.create_track(
                user_id=user_id,
                language_id=artifact.profile.language_id,
                goal_text=artifact.profile.goal_text,
                target_level=artifact.profile.target_level,
                plan=artifact.plan,
                conversation_id=str(session["conversation_id"]),
            )
            self._repository.mark_confirmed(
                user_id=user_id,
                session_id=session_id,
                expected_version=expected_session_version,
                draft_id=draft_id,
                track_id=track_id,
            )
            confirmed = self._repository.read_session(user_id=user_id, session_id=session_id)
        except LearningScopeConflict as exc:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_SESSION_CONFLICT",
                "计划制定对话仍有活动运行，请稍后重试。",
                status_code=409,
            ) from exc
        except LearningPlanSessionConflict as exc:
            raise LearningPlanSessionServiceError(
                "LEARNING_PLAN_DRAFT_STALE",
                "学习计划已经更新，请刷新后重试。",
                status_code=409,
                details={"session_id": session_id},
            ) from exc
        return {
            "session": self._project_session(confirmed),
            "track": self._track_service.read_track(user_id=user_id, track_id=track_id)["track"],
        }

    def _mutate(
        self,
        *,
        user_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, object],
        action: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        key = _idempotency_key(idempotency_key)
        request_hash = _request_hash(request_body)
        with self._conn.transaction():
            self._assert_user(user_id)
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                (user_id, f"{operation}:{key}"),
            )
            existing = self._conn.execute(
                """
                SELECT request_hash, response_json
                FROM tutor_api_idempotency_records
                WHERE user_id = %s AND operation = %s AND idempotency_key = %s
                FOR UPDATE
                """,
                (user_id, operation, key),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise LearningPlanSessionServiceError(
                        "IDEMPOTENCY_CONFLICT",
                        "同一幂等标识不能用于不同的计划制定请求。",
                        status_code=409,
                        recoverable=False,
                    )
                response = dict(existing["response_json"]) if isinstance(existing["response_json"], Mapping) else {}
                response["idempotent_replayed"] = True
                return response
            response = _json_mapping(action())
            response["idempotent_replayed"] = False
            self._conn.execute(
                """
                INSERT INTO tutor_api_idempotency_records (
                  user_id, operation, idempotency_key, request_hash, response_json
                ) VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (user_id, operation, key, request_hash, _json(response)),
            )
            return response

    def _assert_user(self, user_id: str) -> None:
        row = self._conn.execute(
            "SELECT id FROM users WHERE id = %s AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404)

    def _project_session(self, row: Mapping[str, object]) -> dict[str, object]:
        draft: dict[str, object] | None = None
        if row.get("current_draft_id") is not None:
            profile_raw = row.get("profile_json")
            plan_raw = row.get("plan_json")
            profile = dict(profile_raw) if isinstance(profile_raw, Mapping) else {}
            plan = dict(plan_raw) if isinstance(plan_raw, Mapping) else {}
            sources = row.get("source_summary_json")
            draft = {
                "draft_id": str(row["current_draft_id"]),
                "draft_version": _int(row.get("draft_version")),
                "content_hash": str(row.get("content_hash") or ""),
                "profile": profile,
                "plan": plan,
                "sources": [dict(item) for item in sources if isinstance(item, Mapping)]
                if isinstance(sources, list)
                else [],
                "generator_version": str(row.get("generator_version") or ""),
                "policy_version": str(row.get("policy_version") or ""),
                "facts_revision": _int(row.get("facts_revision")),
                "created_at": _iso(row.get("draft_created_at")),
            }
        planning_context = self._facts.public_projection(
            user_id=str(row["user_id"]),
            session_id=str(row["id"]),
        )
        return {
            "session_id": str(row["id"]),
            "conversation_id": str(row["conversation_id"]),
            "status": str(row["status"]),
            "preferred_language_id": _optional_str(row.get("preferred_language_id")),
            "version": _int(row.get("version")),
            "current_draft": draft,
            "planning_context": planning_context,
            "confirmed_track_id": _optional_str(row.get("confirmed_track_id")),
            "last_error": (
                {
                    "code": str(row["last_error_code"]),
                    "at": _iso(row.get("last_error_at")),
                }
                if row.get("last_error_code") is not None
                else None
            ),
            "created_at": _iso(row.get("created_at")),
            "updated_at": _iso(row.get("updated_at")),
            "confirmed_at": _iso(row.get("confirmed_at")),
            "cancelled_at": _iso(row.get("cancelled_at")),
        }


def _optional_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    direct = get_language_capability(normalized)
    if direct is not None:
        canonical = direct.language_id
        capability = direct
    else:
        public = capabilities_for_public_course_language(normalized)
        if not public:
            raise _language_not_selectable(value)
        canonical = normalized
        capability = public[0]
    if not capability.enabled_for_public_selection:
        raise _language_not_selectable(value)
    return canonical


def _language_not_selectable(value: str) -> LearningPlanSessionServiceError:
    return LearningPlanSessionServiceError(
        "LEARNING_LANGUAGE_NOT_SELECTABLE",
        "该编程语言当前不能创建新的学习主线。",
        status_code=422,
        recoverable=False,
        details={"language_id": value.strip().lower()},
    )


def _not_found(session_id: str) -> LearningPlanSessionServiceError:
    return LearningPlanSessionServiceError(
        "LEARNING_PLAN_SESSION_NOT_FOUND",
        "计划制定会话不存在或不属于当前用户。",
        status_code=404,
        details={"session_id": session_id},
    )


def _uuid(value: str, *, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise LearningPlanSessionServiceError(
            "VALIDATION_ERROR",
            f"{label} 必须是 UUID。",
            status_code=400,
            details={"field": label},
        ) from exc


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise LearningPlanSessionServiceError(
            "VALIDATION_ERROR",
            "Idempotency-Key 格式不合法。",
            status_code=400,
            details={"field": "Idempotency-Key"},
        )
    return normalized


def _request_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _json(value: object) -> str:
    return json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _json_mapping(value: Mapping[str, object]) -> dict[str, object]:
    normalized = _json_value(value)
    return dict(normalized) if isinstance(normalized, Mapping) else {}


def _json_value(value: object) -> object:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()
