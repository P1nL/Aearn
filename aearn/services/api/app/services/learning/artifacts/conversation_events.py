"""Atomic Tutor conversation item-reference sink for Learning Artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from psycopg import Connection

from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorIdempotencyConflict,
    TutorRunNotFound,
)


ArtifactConversationItemEventKind = Literal["item_added", "item_updated"]


class ArtifactConversationEventError(ValueError):
    pass


class ArtifactConversationEventConflict(ArtifactConversationEventError):
    pass


class ArtifactConversationEventUnavailable(ArtifactConversationEventError):
    pass


class ArtifactConversationEventSink(Protocol):
    """Append one safe item reference before the caller's transaction exits."""

    def append_item_reference(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        artifact_version: int,
        turn_id: str | None,
        kind: ArtifactConversationItemEventKind,
        occurred_at: datetime,
    ) -> object: ...


class PostgresTutorArtifactConversationEventSink:
    """Reuse Tutor's ordered event authority on the same psycopg connection."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._repository = PostgresTutorRepository(conn)

    def append_item_reference(
        self,
        *,
        user_id: str,
        conversation_id: str,
        artifact_id: str,
        artifact_version: int,
        turn_id: str | None,
        kind: ArtifactConversationItemEventKind,
        occurred_at: datetime,
    ) -> object:
        if artifact_version < 1:
            raise ValueError("artifact event version must be positive")
        try:
            return self._repository.append_artifact_item_reference(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=artifact_id,
                artifact_version=artifact_version,
                turn_id=turn_id,
                kind=kind,
                occurred_at=occurred_at,
            )
        except TutorIdempotencyConflict as exc:
            raise ArtifactConversationEventConflict(
                "artifact conversation item reference conflicts with durable evidence"
            ) from exc
        except TutorRunNotFound as exc:
            raise ArtifactConversationEventUnavailable(
                "artifact conversation authority is unavailable"
            ) from exc


__all__ = (
    "ArtifactConversationEventConflict",
    "ArtifactConversationEventError",
    "ArtifactConversationEventSink",
    "ArtifactConversationEventUnavailable",
    "ArtifactConversationItemEventKind",
    "PostgresTutorArtifactConversationEventSink",
)
