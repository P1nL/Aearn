"""Feature-gated Learning Artifact facade and owner-delegation service."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from psycopg import Connection

from .contracts import (
    TutorArtifactActionRequest,
    TutorArtifactAttemptDetailV1,
    TutorArtifactCreate,
    TutorPublicArtifactItem,
)
from .conversation_events import (
    ArtifactConversationEventConflict,
    ArtifactConversationEventUnavailable,
    ArtifactConversationEventSink,
    PostgresTutorArtifactConversationEventSink,
)
from .owner_adapters import (
    ArtifactMutation,
    ArtifactOwnerActionInvalid,
    ArtifactOwnerAdapterError,
    ArtifactOwnerAdapterRegistry,
    ArtifactOwnerScopeConflict,
    ArtifactOwnerUnavailable,
    ArtifactOwnerVersionConflict,
)
from .repository import (
    ArtifactOwnerEventKind,
    LearningArtifactEventSinkUnavailable,
    LearningArtifactIdempotencyConflict,
    LearningArtifactNotFound,
    LearningArtifactProjectionError,
    LearningArtifactRepositoryError,
    LearningArtifactStateConflict,
    LearningArtifactVersionConflict,
    LearningArtifactWriteResult,
    PostgresLearningArtifactRepository,
)


class LearningArtifactServiceError(ValueError):
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


class LearningArtifactService:
    """Read history always; admit no Artifact mutation while the feature is off."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        repository: PostgresLearningArtifactRepository | None = None,
        conversation_events: ArtifactConversationEventSink | None = None,
        owner_adapters: ArtifactOwnerAdapterRegistry | None = None,
        enabled: Callable[[], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = conn
        if repository is None:
            sink = conversation_events or PostgresTutorArtifactConversationEventSink(
                conn
            )
            repository = PostgresLearningArtifactRepository(
                conn,
                conversation_events=sink,
            )
        self._repository = repository
        self._owner_adapters = owner_adapters or ArtifactOwnerAdapterRegistry()
        self._enabled = enabled or (lambda: False)
        self._clock = clock or (lambda: datetime.now(UTC))

    def read_artifact(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
    ) -> TutorPublicArtifactItem:
        try:
            return self._repository.read_artifact(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def list_conversation_artifacts(
        self,
        *,
        user_id: str,
        conversation_id: str,
        limit: int = 100,
    ) -> tuple[TutorPublicArtifactItem, ...]:
        try:
            return self._repository.list_conversation_artifacts(
                user_id=user_id,
                conversation_id=conversation_id,
                limit=limit,
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def read_attempt_detail(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        attempt_id: str,
    ) -> TutorArtifactAttemptDetailV1:
        try:
            return self._repository.read_attempt_detail(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                attempt_id=attempt_id,
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def create_artifact(
        self,
        request: TutorArtifactCreate,
        *,
        creation_key: str,
    ) -> LearningArtifactWriteResult:
        self._require_enabled()
        try:
            return self._repository.create_artifact(
                request,
                creation_key=creation_key,
                occurred_at=self._clock(),
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ArtifactConversationEventConflict as exc:
            raise _idempotency_error() from exc
        except ArtifactConversationEventUnavailable as exc:
            raise _event_unavailable_error() from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def act(
        self,
        *,
        artifact_id: str,
        request: TutorArtifactActionRequest,
        conversation_id: str | None = None,
    ) -> LearningArtifactWriteResult:
        self._require_enabled()

        def delegate(artifact: TutorPublicArtifactItem) -> ArtifactMutation:
            adapter = self._owner_adapters.require(artifact.owner_kind)
            return adapter.apply_action(
                conn=self._conn,
                artifact=artifact,
                request=request,
            )

        try:
            return self._repository.apply_action(
                artifact_id=artifact_id,
                request=request,
                owner_callback=delegate,
                conversation_id=conversation_id,
                occurred_at=self._clock(),
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ArtifactOwnerAdapterError as exc:
            raise _map_owner_error(exc) from exc
        except ArtifactConversationEventConflict as exc:
            raise _idempotency_error() from exc
        except ArtifactConversationEventUnavailable as exc:
            raise _event_unavailable_error() from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def apply_owner_update(
        self,
        *,
        artifact_id: str,
        user_id: str,
        conversation_id: str,
        learning_track_id: str,
        teaching_session_id: str,
        expected_artifact_version: int,
        event_key: str,
        event_kind: ArtifactOwnerEventKind,
        mutation: ArtifactMutation,
    ) -> LearningArtifactWriteResult:
        self._require_enabled()
        try:
            return self._repository.apply_owner_update(
                artifact_id=artifact_id,
                user_id=user_id,
                conversation_id=conversation_id,
                learning_track_id=learning_track_id,
                teaching_session_id=teaching_session_id,
                expected_artifact_version=expected_artifact_version,
                event_key=event_key,
                event_kind=event_kind,
                mutation=mutation,
                occurred_at=self._clock(),
            )
        except LearningArtifactRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        except ArtifactConversationEventConflict as exc:
            raise _idempotency_error() from exc
        except ArtifactConversationEventUnavailable as exc:
            raise _event_unavailable_error() from exc
        except ValueError as exc:
            raise _validation_error() from exc

    def _require_enabled(self) -> None:
        if not self._enabled():
            raise LearningArtifactServiceError(
                "LEARNING_ARTIFACT_DISABLED",
                "Learning Artifact 写入当前未启用；既有工件仍可只读访问。",
                status_code=409,
                recoverable=True,
            )


def _map_repository_error(
    error: LearningArtifactRepositoryError,
) -> LearningArtifactServiceError:
    if isinstance(error, LearningArtifactNotFound):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_NOT_FOUND",
            "Learning Artifact 不存在或不属于当前范围。",
            status_code=404,
            recoverable=False,
        )
    if isinstance(error, LearningArtifactVersionConflict):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_VERSION_CONFLICT",
            "Learning Artifact 或其 owner authority 已发生变化。",
            status_code=409,
            details={"reason": str(error)},
        )
    if isinstance(error, LearningArtifactIdempotencyConflict):
        return _idempotency_error()
    if isinstance(error, LearningArtifactStateConflict):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_STATE_CONFLICT",
            "Learning Artifact 当前状态不允许该操作。",
            status_code=409,
            details={"reason": str(error)},
        )
    if isinstance(error, LearningArtifactEventSinkUnavailable):
        return _event_unavailable_error()
    if isinstance(error, LearningArtifactProjectionError):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_PROJECTION_INVALID",
            "Learning Artifact 的安全投影无效。",
            status_code=500,
            recoverable=False,
        )
    return LearningArtifactServiceError(
        "LEARNING_ARTIFACT_CONFLICT",
        "Learning Artifact 请求未能安全完成。",
        status_code=409,
    )


def _map_owner_error(
    error: ArtifactOwnerAdapterError,
) -> LearningArtifactServiceError:
    if isinstance(error, ArtifactOwnerUnavailable):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_OWNER_UNAVAILABLE",
            "Learning Artifact owner adapter 当前不可用。",
            status_code=409,
        )
    if isinstance(error, ArtifactOwnerScopeConflict):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_NOT_FOUND",
            "Learning Artifact owner 不存在或不属于当前范围。",
            status_code=404,
            recoverable=False,
        )
    if isinstance(error, ArtifactOwnerVersionConflict):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_VERSION_CONFLICT",
            "Learning Artifact owner authority 已发生变化。",
            status_code=409,
        )
    if isinstance(error, ArtifactOwnerActionInvalid):
        return LearningArtifactServiceError(
            "LEARNING_ARTIFACT_ACTION_INVALID",
            "Learning Artifact owner 拒绝了该动作。",
            status_code=400,
            recoverable=False,
        )
    return LearningArtifactServiceError(
        "LEARNING_ARTIFACT_OWNER_FAILED",
        "Learning Artifact owner 未能安全完成该动作。",
        status_code=409,
    )


def _idempotency_error() -> LearningArtifactServiceError:
    return LearningArtifactServiceError(
        "IDEMPOTENCY_CONFLICT",
        "同一 Learning Artifact 幂等标识不能用于不同请求。",
        status_code=409,
        recoverable=False,
    )


def _validation_error() -> LearningArtifactServiceError:
    return LearningArtifactServiceError(
        "VALIDATION_ERROR",
        "Learning Artifact 请求字段不合法。",
        status_code=400,
        recoverable=False,
    )


def _event_unavailable_error() -> LearningArtifactServiceError:
    return LearningArtifactServiceError(
        "LEARNING_ARTIFACT_EVENT_UNAVAILABLE",
        "Learning Artifact 无法原子写入对话事件。",
        status_code=503,
        recoverable=True,
    )


__all__ = (
    "LearningArtifactService",
    "LearningArtifactServiceError",
)
