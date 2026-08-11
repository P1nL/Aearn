"""Verified LessonDocument use cases and learner-safe projections."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection

from app.services.learning.contracts import stable_key
from app.services.learning.lesson_contracts import LessonDocumentDraft, LessonSourceSnapshot, lesson_block_payload
from app.services.learning.lesson_repository import (
    LessonAssignmentConflict,
    LessonAuthoringRunRecord,
    LessonIdempotencyConflict,
    LessonNotFound,
    LessonScopeRecord,
    LessonVersionConflict,
    PostgresLessonDocumentRepository,
)


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class LessonDocumentServiceError(ValueError):
    def __init__(
        self, code: str, message: str, *, status_code: int,
        recoverable: bool = True, details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})


class LessonDocumentService:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._repository = PostgresLessonDocumentRepository(conn)

    def read(self, *, user_id: str, track_id: str, knowledge_key: str) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        try:
            state = self._repository.read_lesson_state(user_id=user, track_id=track, knowledge_key=key)
        except LessonNotFound as exc:
            raise _not_found(track, key) from exc
        return self._project_state(state)

    def prepare(
        self, *, user_id: str, track_id: str, knowledge_key: str,
        expected_track_version: int, expected_progress_version: int,
        idempotency_key: str, run_kind: str = "prepare",
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        action_key = _idempotency_key(idempotency_key)
        with self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (user, f"lesson.{run_kind}:{track}:{key}:{action_key}"))
            try:
                current = self._repository.read_lesson_state(user_id=user, track_id=track, knowledge_key=key)
                scope = current["scope"]
                assert isinstance(scope, LessonScopeRecord)
                if run_kind == "prepare" and current.get("assignment") is not None:
                    response = self._project_state(current)
                    response.update(should_dispatch=False, idempotent_replayed=True)
                    return response
                self._assert_prepare_scope(scope, expected_track_version, expected_progress_version)
                profile_hash = self._profile_hash(scope)
                request_hash = _hash_json({
                    "user_id": user, "track_id": track, "knowledge_key": key,
                    "run_kind": run_kind, "expected_track_version": expected_track_version,
                    "expected_progress_version": expected_progress_version, "profile_hash": profile_hash,
                })
                run, replayed = self._repository.create_or_replay_authoring_run(
                    scope=scope, run_kind=run_kind, idempotency_key=action_key,
                    request_hash=request_hash, profile_hash=profile_hash,
                )
            except LessonNotFound as exc:
                raise _not_found(track, key) from exc
            except LessonIdempotencyConflict as exc:
                raise LessonDocumentServiceError(
                    "IDEMPOTENCY_CONFLICT", "同一幂等标识不能用于不同的课程请求。",
                    status_code=409, recoverable=False,
                ) from exc
        return {
            "status": _run_public_status(run), "track_id": track, "knowledge_key": key,
            "authoring_run": _project_run(run), "should_dispatch": not replayed and run.state == "pending",
            "idempotent_replayed": replayed,
        }

    def start(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int, expected_progress_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        assignment = _uuid(assignment_id, "assignment_id")
        return self._mutate(
            user_id=user, operation=f"lesson.start:{track}:{key}", idempotency_key=idempotency_key,
            request_body={"track_id": track, "knowledge_key": key, "assignment_id": assignment,
                          "expected_assignment_version": expected_assignment_version,
                          "expected_progress_version": expected_progress_version},
            action=lambda: self._start(
                user_id=user, track_id=track, knowledge_key=key, assignment_id=assignment,
                expected_assignment_version=expected_assignment_version,
                expected_progress_version=expected_progress_version,
            ),
        )

    def activate_migration(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int, idempotency_key: str,
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        assignment = _uuid(assignment_id, "assignment_id")
        return self._mutate(
            user_id=user, operation=f"lesson.migrate:{track}:{key}", idempotency_key=idempotency_key,
            request_body={"track_id": track, "knowledge_key": key, "assignment_id": assignment,
                          "expected_assignment_version": expected_assignment_version},
            action=lambda: self._activate(
                user_id=user, track_id=track, knowledge_key=key, assignment_id=assignment,
                expected_assignment_version=expected_assignment_version,
            ),
        )

    def _start(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int, expected_progress_version: int,
    ) -> dict[str, object]:
        try:
            row = self._repository.start_assignment(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                assignment_id=assignment_id,
                expected_assignment_version=expected_assignment_version,
                expected_progress_version=expected_progress_version,
                now=datetime.now(UTC),
            )
        except LessonNotFound as exc:
            raise _not_found(track_id, knowledge_key) from exc
        except LessonAssignmentConflict as exc:
            raise _assignment_conflict() from exc
        except LessonVersionConflict as exc:
            raise _version_conflict() from exc
        return {"assignment": _project_assignment(row), "started": True}

    def _activate(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int,
    ) -> dict[str, object]:
        try:
            row = self._repository.activate_proposed_assignment(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                assignment_id=assignment_id,
                expected_assignment_version=expected_assignment_version,
                now=datetime.now(UTC),
            )
        except LessonNotFound as exc:
            raise _not_found(track_id, knowledge_key) from exc
        except LessonAssignmentConflict as exc:
            raise _assignment_conflict() from exc
        return {"assignment": _project_assignment(row), "migrated": True}

    def _assert_prepare_scope(self, scope: LessonScopeRecord, expected_track_version: int, expected_progress_version: int) -> None:
        if scope.progress_status == "locked":
            raise LessonDocumentServiceError(
                "LESSON_DOCUMENT_NOT_READY", "该知识点尚未解锁，不能准备课程。",
                status_code=409, recoverable=False,
            )
        if scope.track_version != expected_track_version or scope.progress_version != expected_progress_version:
            raise _version_conflict()

    def _profile_hash(self, scope: LessonScopeRecord) -> str:
        user = self._conn.execute(
            "SELECT learning_style, teaching_preference, encouragement_preference FROM users WHERE id = %s AND deleted_at IS NULL",
            (scope.user_id,),
        ).fetchone()
        if user is None:
            raise LessonDocumentServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404)
        return _hash_json({
            "goal_text": scope.goal_text[:1200], "target_level": scope.target_level,
            "mastery_level": scope.mastery_level, "mastery_confidence": round(scope.mastery_confidence, 4),
            "learning_style": _bounded_optional(user.get("learning_style"), 240),
            "teaching_preference": _bounded_optional(user.get("teaching_preference"), 240),
            "encouragement_preference": _bounded_optional(user.get("encouragement_preference"), 240),
        })

    def _mutate(
        self, *, user_id: str, operation: str, idempotency_key: str,
        request_body: Mapping[str, object], action: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        key = _idempotency_key(idempotency_key)
        request_hash = _hash_json(request_body)
        with self._conn.transaction():
            self._conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))", (user_id, f"{operation}:{key}"))
            existing = self._conn.execute(
                "SELECT request_hash, response_json FROM tutor_api_idempotency_records WHERE user_id = %s AND operation = %s AND idempotency_key = %s FOR UPDATE",
                (user_id, operation, key),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise LessonDocumentServiceError("IDEMPOTENCY_CONFLICT", "同一幂等标识不能用于不同的课程请求。", status_code=409, recoverable=False)
                response = dict(existing["response_json"]) if isinstance(existing["response_json"], Mapping) else {}
                response["idempotent_replayed"] = True
                return response
            response = action()
            response["idempotent_replayed"] = False
            self._conn.execute(
                "INSERT INTO tutor_api_idempotency_records (user_id, operation, idempotency_key, request_hash, response_json) VALUES (%s, %s, %s, %s, %s::jsonb)",
                (user_id, operation, key, request_hash, json.dumps(response, ensure_ascii=False, default=str)),
            )
            return response

    def _project_state(self, state: Mapping[str, object]) -> dict[str, object]:
        scope = state["scope"]
        assert isinstance(scope, LessonScopeRecord)
        assignment = state.get("assignment")
        document = state.get("document")
        latest_run = state.get("latest_run")
        base: dict[str, object] = {
            "track_id": scope.track_id, "knowledge_key": scope.knowledge_key,
            "track_version": scope.track_version, "progress_version": scope.progress_version,
            "progress_status": scope.progress_status,
        }
        if isinstance(assignment, Mapping) and isinstance(document, LessonDocumentDraft):
            sources = state.get("sources")
            safe_sources = tuple(item for item in sources if isinstance(item, LessonSourceSnapshot)) if isinstance(sources, tuple | list) else ()
            base.update(
                status="ready", assignment=_project_assignment(assignment),
                document={
                    "schema_version": document.schema_version, "title": document.title,
                    "language_id": document.language_id, "knowledge_key": document.knowledge_key,
                    "content_standard_version": document.content_standard_version,
                    "coverage_keys": list(document.coverage_keys),
                    "blocks": [lesson_block_payload(block) for block in document.blocks],
                    "content_hash": document.content_hash,
                },
                sources=[_project_source(item) for item in safe_sources],
                update=_project_proposal(state.get("proposed_assignment")),
            )
            return base
        if isinstance(latest_run, LessonAuthoringRunRecord):
            base.update(status=_run_public_status(latest_run), authoring_run=_project_run(latest_run))
            return base
        base["status"] = "missing"
        return base


def _project_assignment(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "assignment_id": str(row["id"]), "document_id": str(row["document_id"]),
        "assignment_version": _int(row["assignment_version"]), "status": str(row["status"]),
        "content_hash": str(row["content_hash"]),
        "started_at": _iso(row.get("started_at")), "activated_at": _iso(row.get("activated_at")),
        "progress_status": row.get("progress_status"), "progress_version": row.get("progress_version"),
    }


def _project_proposal(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    impact = value.get("impact_json")
    return {
        "assignment_id": str(value["id"]), "assignment_version": _int(value["assignment_version"]),
        "document_id": str(value["document_id"]), "status": str(value["status"]),
        "impact": dict(impact) if isinstance(impact, Mapping) else {},
    }


def _project_source(snapshot: LessonSourceSnapshot) -> dict[str, object]:
    return {
        "citation_id": snapshot.citation_id, "source_id": snapshot.source_id,
        "display_name": snapshot.display_name, "provider": snapshot.provider,
        "trust_tier": snapshot.trust_tier, "source_type": snapshot.source_type,
        "source_version_label": snapshot.source_version_label,
        "source_version_kind": snapshot.source_version_kind,
        "canonical_url": snapshot.canonical_url, "section_path": list(snapshot.section_path),
        "fetched_at": snapshot.fetched_at.isoformat(), "snapshotted_at": snapshot.snapshotted_at.isoformat(),
        "evidence_excerpt": snapshot.evidence_excerpt,
    }


def _project_run(run: LessonAuthoringRunRecord) -> dict[str, object]:
    return {
        "run_id": run.run_id, "state": run.state, "run_kind": run.run_kind,
        "attempt_count": run.attempt_count, "failure_code": run.failure_code,
        "failure_message": run.failure_message, "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(), "terminal_at": _iso(run.terminal_at),
    }


def _run_public_status(run: LessonAuthoringRunRecord) -> str:
    if run.state in {"pending", "claimed", "running"}:
        return "preparing"
    if run.state == "failed":
        return "failed"
    if run.state == "completed":
        return "ready"
    return "missing"


def _scope_ids(user_id: str, track_id: str, knowledge_key: str) -> tuple[str, str, str]:
    return _uuid(user_id, "user_id"), _uuid(track_id, "track_id"), stable_key(knowledge_key, label="knowledge_key")


def _uuid(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise LessonDocumentServiceError("VALIDATION_ERROR", f"{label} 必须是 UUID。", status_code=400, recoverable=False) from exc


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise LessonDocumentServiceError("VALIDATION_ERROR", "client_action_id 格式不合法。", status_code=400, recoverable=False)
    return normalized


def _hash_json(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_optional(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:maximum] if text else None


def _not_found(track_id: str, knowledge_key: str) -> LessonDocumentServiceError:
    return LessonDocumentServiceError(
        "LESSON_DOCUMENT_NOT_FOUND", "课程或知识点不存在。", status_code=404,
        recoverable=False, details={"track_id": track_id, "knowledge_key": knowledge_key},
    )


def _version_conflict() -> LessonDocumentServiceError:
    return LessonDocumentServiceError(
        "LESSON_DOCUMENT_VERSION_CONFLICT", "学习路线、进度或课程来源已经更新，请刷新后重试。",
        status_code=409,
    )


def _assignment_conflict() -> LessonDocumentServiceError:
    return LessonDocumentServiceError(
        "LESSON_ASSIGNMENT_CONFLICT", "课程 assignment 已更新，请刷新后重试。", status_code=409,
    )


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value or 0))
