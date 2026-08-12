"""Transaction use cases and learner-safe projections for LearningTrack."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from psycopg import Connection

from app.core.config import Settings, get_settings
from app.services.learning.contracts import (
    ExecutionComposition,
    LearningPlan,
)
from app.services.learning.execution_tiers import (
    ExecutionTierInputs,
    ExecutionTierResolver,
    ExecutorAvailabilityPort,
)
from app.services.learning.track_repository import (
    LearningIdempotencyConflict,
    LearningPlanActivationInvalid,
    LearningPlanVersionConflict,
    LearningScopeConflict,
    LearningTrackNotFound,
    PostgresLearningTrackRepository,
)
from app.services.runners.language_capabilities import (
    LanguageCapability,
    capabilities_for_public_course_language,
    get_language_capability,
)
from app.services.tutor.execution import ExecutionIntentRepository, default_runtime_registry


_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")
_LANGUAGE_CATALOG: tuple[tuple[str, str], ...] = (
    ("python", "core"),
    ("javascript", "core"),
    ("typescript", "core"),
    ("sql", "core"),
    ("java", "extended"),
    ("html_css", "extended"),
    ("go", "degraded"),
    ("csharp", "degraded"),
    ("rust", "degraded"),
    ("cpp", "degraded"),
)
T = TypeVar("T")


class LearningTrackServiceError(ValueError):
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


class _ExecutorAvailabilityAdapter(ExecutorAvailabilityPort):
    def __init__(self, repository: ExecutionIntentRepository) -> None:
        self._repository = repository

    def is_runtime_available(self, runtime_id: str) -> bool:
        return self._repository.availability_for_runtime(runtime_id).available


class LearningTrackService:
    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings | None = None,
        tier_resolver: ExecutionTierResolver | None = None,
        local_runner_available: Callable[[LanguageCapability], bool] | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._repository = PostgresLearningTrackRepository(conn)
        self._tier_resolver = tier_resolver or ExecutionTierResolver()
        self._local_runner_available = local_runner_available or _default_local_runner_available

    def create_track(
        self,
        *,
        user_id: str,
        language_id: str,
        goal_text: str,
        target_level: str,
        plan: LearningPlan,
        conversation_id: str | None,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_conversation_id = _uuid(conversation_id, label="conversation_id") if conversation_id else None
        normalized_goal_text = _bounded_text(goal_text, label="goal_text", maximum=2000)
        normalized_target_level = _bounded_text(target_level, label="target_level", maximum=120)
        if normalized_target_level != plan.target_level:
            raise LearningTrackServiceError(
                "LEARNING_PLAN_INVALID",
                "LearningTrack target_level 必须与初始计划一致。",
                status_code=422,
                recoverable=False,
                details={"field": "target_level"},
            )
        canonical_language_id, _capability = _language(language_id)
        return self._mutate(
            user_id=normalized_user_id,
            operation="learning_track.create",
            idempotency_key=idempotency_key,
            request_body={
                "language_id": canonical_language_id,
                "goal_text": normalized_goal_text,
                "target_level": normalized_target_level,
                "plan_hash": plan.content_hash,
                "plan_generator_version": plan.generator_version,
                "plan_policy_version": plan.policy_version,
                "plan_change_reason": plan.change_reason,
                "conversation_id": normalized_conversation_id,
            },
            action=lambda: self._create_track(
                user_id=normalized_user_id,
                language_id=canonical_language_id,
                goal_text=normalized_goal_text,
                target_level=normalized_target_level,
                plan=plan,
                conversation_id=normalized_conversation_id,
            ),
        )

    def list_tracks(self, *, user_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        self._assert_user(normalized_user_id)
        return {"items": [self._project_track(row) for row in self._repository.list_tracks(user_id=normalized_user_id)]}

    def list_language_catalog(self, *, user_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        self._assert_user(normalized_user_id)
        return {
            "items": [
                self._project_language_catalog(language_id=language_id, selection_tier=selection_tier)
                for language_id, selection_tier in _LANGUAGE_CATALOG
            ]
        }

    def read_track(self, *, user_id: str, track_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_track_id = _uuid(track_id, label="track_id")
        try:
            return {"track": self._project_track(self._repository.read_track(user_id=normalized_user_id, track_id=normalized_track_id), detail=True)}
        except LearningTrackNotFound as exc:
            raise _not_found(normalized_track_id) from exc

    def read_roadmap(self, *, user_id: str, track_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_track_id = _uuid(track_id, label="track_id")
        try:
            return {"roadmap": self._repository.read_roadmap(user_id=normalized_user_id, track_id=normalized_track_id)}
        except LearningTrackNotFound as exc:
            raise _not_found(normalized_track_id) from exc

    def list_revisions(self, *, user_id: str, track_id: str) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_track_id = _uuid(track_id, label="track_id")
        try:
            rows = self._repository.list_revisions(user_id=normalized_user_id, track_id=normalized_track_id)
        except LearningTrackNotFound as exc:
            raise _not_found(normalized_track_id) from exc
        return {"items": [_revision_projection(row) for row in rows]}

    def propose_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        expected_track_version: int,
        plan: LearningPlan,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_track_id = _uuid(track_id, label="track_id")
        request_body = {
            "track_id": normalized_track_id,
            "expected_track_version": expected_track_version,
            "plan_hash": plan.content_hash,
            "plan_generator_version": plan.generator_version,
            "plan_policy_version": plan.policy_version,
            "plan_change_reason": plan.change_reason,
        }
        request_hash = _request_hash(request_body)
        return self._mutate(
            user_id=normalized_user_id,
            operation=f"learning_track.plan.propose:{normalized_track_id}",
            idempotency_key=idempotency_key,
            request_body=request_body,
            action=lambda: self._propose_revision(
                user_id=normalized_user_id,
                track_id=normalized_track_id,
                expected_track_version=expected_track_version,
                plan=plan,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
            ),
        )

    def activate_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        revision_id: str,
        expected_track_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        normalized_user_id = _uuid(user_id, label="user_id")
        normalized_track_id = _uuid(track_id, label="track_id")
        normalized_revision_id = _uuid(revision_id, label="revision_id")
        return self._mutate(
            user_id=normalized_user_id,
            operation=f"learning_track.plan.activate:{normalized_track_id}",
            idempotency_key=idempotency_key,
            request_body={
                "track_id": normalized_track_id,
                "revision_id": normalized_revision_id,
                "expected_track_version": expected_track_version,
            },
            action=lambda: self._activate_revision(
                user_id=normalized_user_id,
                track_id=normalized_track_id,
                revision_id=normalized_revision_id,
                expected_track_version=expected_track_version,
            ),
        )

    def _create_track(
        self,
        *,
        user_id: str,
        language_id: str,
        goal_text: str,
        target_level: str,
        plan: LearningPlan,
        conversation_id: str | None,
    ) -> dict[str, object]:
        try:
            track_id = self._repository.create_track(
                user_id=user_id,
                language_id=language_id,
                goal_text=goal_text,
                target_level=target_level,
                plan=plan,
                conversation_id=conversation_id,
            )
            row = self._repository.read_track(user_id=user_id, track_id=track_id)
        except LearningTrackNotFound as exc:
            if "learner" in str(exc):
                raise LearningTrackServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404) from exc
            raise LearningTrackServiceError(
                "LEARNING_SCOPE_CONFLICT",
                "指定的 Tutor conversation 不属于当前用户。",
                status_code=409,
            ) from exc
        except LearningScopeConflict as exc:
            raise _scope_conflict() from exc
        return {"track": self._project_track(row, detail=True)}

    def _propose_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        expected_track_version: int,
        plan: LearningPlan,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object]:
        try:
            revision_id, impact, track_version = self._repository.propose_revision(
                user_id=user_id,
                track_id=track_id,
                expected_track_version=expected_track_version,
                plan=plan,
                idempotency_key=_idempotency_key(idempotency_key),
                request_hash=request_hash,
            )
        except LearningTrackNotFound as exc:
            raise _not_found(track_id) from exc
        except LearningPlanVersionConflict as exc:
            raise _version_conflict(track_id) from exc
        except LearningPlanActivationInvalid as exc:
            raise LearningTrackServiceError(
                "LEARNING_PLAN_ACTIVATION_INVALID",
                "当前学习主线不能创建该计划版本。",
                status_code=409,
                recoverable=False,
            ) from exc
        return {
            "revision_id": revision_id,
            "track_id": track_id,
            "track_version": track_version,
            "status": "proposed",
            "impact": impact.as_dict(),
        }

    def _activate_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        revision_id: str,
        expected_track_version: int,
    ) -> dict[str, object]:
        try:
            track_version = self._repository.activate_revision(
                user_id=user_id,
                track_id=track_id,
                revision_id=revision_id,
                expected_track_version=expected_track_version,
            )
            track = self._repository.read_track(user_id=user_id, track_id=track_id)
        except LearningTrackNotFound as exc:
            raise _not_found(track_id) from exc
        except LearningPlanVersionConflict as exc:
            raise _version_conflict(track_id) from exc
        except LearningPlanActivationInvalid as exc:
            raise LearningTrackServiceError(
                "LEARNING_PLAN_ACTIVATION_INVALID",
                "计划版本不是当前 active revision 的可确认直接后继。",
                status_code=409,
                recoverable=False,
                details={"track_id": track_id, "revision_id": revision_id},
            ) from exc
        return {
            "track_version": track_version,
            "active_revision_id": revision_id,
            "track": self._project_track(track, detail=True),
        }

    def _project_track(self, row: Mapping[str, object], *, detail: bool = False) -> dict[str, object]:
        language_id = str(row["language_id"])
        _canonical, capability = _language(language_id)
        tier = self._execution_tier(capability)
        total = _int(row.get("progress_total"))
        completed = _int(row.get("progress_completed"))
        result: dict[str, object] = {
            "track_id": str(row["id"]),
            "language_id": language_id,
            "language_display_name": "HTML/CSS" if language_id == "html_css" else capability.display_name,
            "goal_text": str(row["goal_text"]),
            "target_level": str(row["target_level"]),
            "status": str(row["status"]),
            "version": _int(row["version"]),
            "active_revision_id": str(row["active_revision_id"]),
            "active_plan_title": str(row["active_plan_title"]),
            "current_knowledge_key": _optional_str(row.get("current_knowledge_key")),
            "current_knowledge_title": _optional_str(row.get("current_knowledge_title")),
            "progress": {
                "total": total,
                "completed": completed,
                "in_progress": _int(row.get("progress_in_progress")),
                "review_due": _int(row.get("progress_review_due")),
                "percent": round(0.0 if total == 0 else completed * 100 / total, 2),
            },
            "review_due_count": _int(row.get("review_due_count")),
            "execution_tier": tier.tier.value,
            "execution_disclosure": tier.disclosure,
            "last_learned_at": _iso(row.get("last_learned_at")),
            "updated_at": _iso(row.get("updated_at")),
        }
        if detail:
            result["created_at"] = _iso(row.get("created_at"))
            result["archived_at"] = _iso(row.get("archived_at"))
        return result

    def _project_language_catalog(self, *, language_id: str, selection_tier: str) -> dict[str, object]:
        canonical, capability = _language(language_id)
        grouped = capabilities_for_public_course_language(canonical)
        capabilities = grouped or (capability,)
        tier = self._execution_tier(capability)
        return {
            "language_id": canonical,
            "display_name": "HTML/CSS" if canonical == "html_css" else capability.display_name,
            "selection_tier": selection_tier,
            "selectable": all(item.enabled_for_public_selection for item in capabilities),
            "lesson_generation_state": capability.lesson_generation,
            "execution_tier": tier.tier.value,
            "execution_disclosure": tier.disclosure,
            "source_trust_policy": capability.source_trust_policy,
        }

    def _execution_tier(self, capability: LanguageCapability):
        composition = (
            ExecutionComposition.DEVELOPMENT
            if self._settings.app_env.strip().lower() == "development"
            else ExecutionComposition.PUBLIC
        )
        availability = _ExecutorAvailabilityAdapter(
            ExecutionIntentRepository(
                self._conn,
                registry=default_runtime_registry(),
                executor_enabled=lambda: self._settings.tutor_executor_enabled,
            )
        )
        return self._tier_resolver.resolve(
            language=capability,
            inputs=ExecutionTierInputs(
                composition=composition,
                local_runner_available=self._local_runner_available(capability),
                runtime_registry=default_runtime_registry(),
                executor_availability=availability,
            ),
        )

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
        try:
            with self._conn.transaction():
                self._assert_user(user_id)
                self._conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (user_id, f"{operation}:{key}"),
                )
                existing = self._conn.execute(
                    """
                    SELECT request_hash, response_json FROM tutor_api_idempotency_records
                    WHERE user_id = %s AND operation = %s AND idempotency_key = %s FOR UPDATE
                    """,
                    (user_id, operation, key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_hash"]) != request_hash:
                        raise LearningIdempotencyConflict("idempotency key conflicts with the stored request")
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
        except LearningIdempotencyConflict as exc:
            raise LearningTrackServiceError(
                "IDEMPOTENCY_CONFLICT",
                "同一幂等标识不能用于不同的 LearningTrack 请求。",
                status_code=409,
                recoverable=False,
            ) from exc

    def _assert_user(self, user_id: str) -> None:
        row = self._conn.execute("SELECT id FROM users WHERE id = %s AND deleted_at IS NULL", (user_id,)).fetchone()
        if row is None:
            raise LearningTrackServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404)


def _language(value: str) -> tuple[str, LanguageCapability]:
    normalized = str(value or "").strip().lower()
    direct = get_language_capability(normalized)
    if direct is not None:
        return direct.language_id, direct
    public = capabilities_for_public_course_language(normalized)
    if public:
        return normalized, public[0]
    raise LearningTrackServiceError(
        "LEARNING_PLAN_INVALID",
        "学习计划使用了未注册的编程语言。",
        status_code=422,
        recoverable=False,
        details={"field": "language_id"},
    )


def _default_local_runner_available(capability: LanguageCapability) -> bool:
    if not capability.supports_execution:
        return False
    if capability.runner_key in {"python", "browser", "sql"}:
        return True
    if capability.runner_key == "node":
        return shutil.which("node") is not None and (shutil.which("tsc") is not None or shutil.which("tsc.cmd") is not None)
    if capability.language_id == "java":
        return shutil.which("javac") is not None and shutil.which("java") is not None
    if capability.language_id == "go":
        return shutil.which("go") is not None
    if capability.language_id == "csharp":
        return shutil.which("dotnet") is not None
    return False


def _revision_projection(row: Mapping[str, object]) -> dict[str, object]:
    impact = row.get("impact_json")
    return {
        "revision_id": str(row["revision_id"]),
        "predecessor_revision_id": _optional_str(row.get("predecessor_revision_id")),
        "status": str(row["status"]),
        "title": str(row["title"]),
        "target_level": str(row["target_level"]),
        "generator_version": str(row["generator_version"]),
        "policy_version": str(row["policy_version"]),
        "change_reason": str(row["change_reason"]),
        "content_hash": str(row["content_hash"]),
        "impact": _impact_projection(impact),
        "created_at": _iso(row.get("created_at")),
        "activated_at": _iso(row.get("activated_at")),
    }


def _impact_projection(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    allowed = ("added", "removed", "reordered", "prerequisite_changed", "retained_progress")
    return {
        key: [str(item) for item in raw]
        for key in allowed
        if isinstance((raw := value.get(key)), list | tuple)
    }


def _not_found(track_id: str) -> LearningTrackServiceError:
    return LearningTrackServiceError(
        "LEARNING_TRACK_NOT_FOUND",
        "LearningTrack 不存在或不属于当前用户。",
        status_code=404,
        details={"track_id": track_id},
    )


def _version_conflict(track_id: str) -> LearningTrackServiceError:
    return LearningTrackServiceError(
        "LEARNING_PLAN_VERSION_CONFLICT",
        "LearningTrack 已发生变化，请刷新后重试。",
        status_code=409,
        details={"track_id": track_id},
    )


def _scope_conflict() -> LearningTrackServiceError:
    return LearningTrackServiceError(
        "LEARNING_SCOPE_CONFLICT",
        "Tutor conversation 当前有活动中的前台运行，不能改变学习作用域。",
        status_code=409,
    )


def _bounded_text(value: str, *, label: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise LearningTrackServiceError(
            "LEARNING_PLAN_INVALID",
            f"{label} 必须包含 1..{maximum} 个字符。",
            status_code=422,
            recoverable=False,
            details={"field": label},
        )
    return normalized


def _uuid(value: str, *, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError) as exc:
        raise LearningTrackServiceError(
            "VALIDATION_ERROR",
            f"{label} 必须是 UUID。",
            status_code=400,
            details={"field": label},
        ) from exc


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise LearningTrackServiceError(
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
    if isinstance(value, float | str | bytes | bytearray):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _iso(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat()
