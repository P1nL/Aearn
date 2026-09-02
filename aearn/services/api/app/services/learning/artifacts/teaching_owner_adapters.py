"""Learning Item and legacy teaching-practice Artifact owner adapters."""
from __future__ import annotations

from collections.abc import Mapping

from psycopg import Connection

from .contracts import (
    TutorArtifactActionRequest,
    TutorArtifactKind,
    TutorArtifactOwnerKind,
    TutorArtifactRequestDirectAnswerAction,
    TutorArtifactRequestHintAction,
    TutorArtifactRespondAction,
    TutorArtifactState,
    TutorPublicArtifactItem,
)
from .demonstrations import complete_demonstration
from .knowledge_checks import apply_knowledge_check_action
from .owner_adapters import (
    ArtifactMutation,
    ArtifactOwnerActionInvalid,
    ArtifactOwnerScopeConflict,
    ArtifactOwnerVersionConflict,
)


class _TeachingArtifactOwnerAdapter:
    """Delegate lifecycle authority without introducing score or mastery state.

    Child-specific Run, Hint, Review, response, and demonstration adapters must still
    delegate to their exact Gate/Review/Practice owner. This shared adapter owns only
    safe cancellation and rejects every unregistered action rather than fabricating a
    second evaluator or completion state.
    """

    owner_kind: TutorArtifactOwnerKind

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation:
        row = _locked_owner_row(
            conn,
            artifact=artifact,
            request=request,
            owner_kind=self.owner_kind,
        )
        if request.action.action != "cancel":
            raise ArtifactOwnerActionInvalid(
                "Artifact action requires an exact Gate, Review, Practice, or demonstration owner adapter"
            )
        _validate_cancel_authority(
            conn,
            row=row,
            artifact=artifact,
            owner_kind=self.owner_kind,
        )
        return ArtifactMutation(
            state=TutorArtifactState.CANCELLED,
            owner_version=artifact.owner_version,
            owner_context_version=_positive_int(
                row.get("owner_context_version"),
                "owner_context_version",
            ),
            presentation=artifact.presentation,
            allowed_actions=(),
            active_attempt=artifact.active_attempt,
            safe_event_payload={
                "reason": "learner_cancelled",
                "owner_kind": self.owner_kind.value,
            },
        )


class LearningItemArtifactOwnerAdapter(_TeachingArtifactOwnerAdapter):
    owner_kind = TutorArtifactOwnerKind.LEARNING_ITEM

    def apply_action(
        self,
        *,
        conn: Connection[dict[str, object]],
        artifact: TutorPublicArtifactItem,
        request: TutorArtifactActionRequest,
    ) -> ArtifactMutation:
        if (
            artifact.artifact_kind is TutorArtifactKind.KNOWLEDGE_CHECK
            and isinstance(
                request.action,
                (
                    TutorArtifactRequestHintAction,
                    TutorArtifactRequestDirectAnswerAction,
                    TutorArtifactRespondAction,
                ),
            )
        ):
            row = _locked_owner_row(
                conn,
                artifact=artifact,
                request=request,
                owner_kind=self.owner_kind,
            )
            _validate_cancel_authority(
                conn,
                row=row,
                artifact=artifact,
                owner_kind=self.owner_kind,
            )
            return apply_knowledge_check_action(
                conn,
                artifact=artifact,
                action=request.action,
                owner_context_version=_positive_int(
                    row.get("owner_context_version"),
                    "owner_context_version",
                ),
            )
        if (
            artifact.artifact_kind is TutorArtifactKind.DEMONSTRATION
            and request.action.action == "complete_demo"
        ):
            row = _locked_owner_row(
                conn,
                artifact=artifact,
                request=request,
                owner_kind=self.owner_kind,
            )
            _validate_cancel_authority(
                conn,
                row=row,
                artifact=artifact,
                owner_kind=self.owner_kind,
            )
            receipt = complete_demonstration(
                conn,
                artifact=artifact,
                request=request,
            )
            return ArtifactMutation(
                state=TutorArtifactState.COMPLETED,
                owner_version=artifact.owner_version,
                owner_context_version=_positive_int(
                    row.get("owner_context_version"),
                    "owner_context_version",
                ),
                presentation=artifact.presentation,
                allowed_actions=(),
                active_attempt=None,
                safe_event_payload={
                    "completion_receipt_id": receipt.receipt_id,
                    "completion_kind": receipt.completion_kind,
                    "descriptor_hash": receipt.descriptor_hash,
                },
            )
        return super().apply_action(conn=conn, artifact=artifact, request=request)


class TeachingPracticeArtifactOwnerAdapter(_TeachingArtifactOwnerAdapter):
    owner_kind = TutorArtifactOwnerKind.TEACHING_PRACTICE


def _locked_owner_row(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    request: TutorArtifactActionRequest,
    owner_kind: TutorArtifactOwnerKind,
) -> Mapping[str, object]:
    row = conn.execute(
        """
        SELECT artifacts.owner_kind, artifacts.owner_id, artifacts.owner_version,
               artifacts.owner_context_version, artifacts.checkpoint_id,
               sessions.current_checkpoint_id, sessions.version AS session_version,
               sessions.status AS session_status
        FROM tutor_learning_artifacts AS artifacts
        JOIN tutor_teaching_sessions AS sessions
          ON sessions.id = artifacts.teaching_session_id
         AND sessions.user_id = artifacts.user_id
         AND sessions.conversation_id = artifacts.conversation_id
         AND sessions.track_id = artifacts.learning_track_id
         AND sessions.knowledge_key = artifacts.knowledge_key
        WHERE artifacts.id = %s
          AND artifacts.user_id = %s
          AND artifacts.conversation_id = %s
          AND artifacts.learning_track_id = %s
          AND artifacts.teaching_session_id = %s
        FOR UPDATE OF sessions
        """,
        (
            artifact.id,
            request.user_id,
            artifact.conversation_id,
            request.learning_track_id,
            request.teaching_session_id,
        ),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerScopeConflict(
            "teaching Artifact owner scope was not found"
        )
    if (
        str(row.get("owner_kind") or "") != owner_kind.value
        or str(row.get("owner_id") or "") != artifact.owner_id
        or _positive_int(row.get("owner_version"), "owner_version")
        != artifact.owner_version
        or str(row.get("checkpoint_id") or "") != artifact.checkpoint_id
    ):
        raise ArtifactOwnerVersionConflict(
            "teaching Artifact owner identity changed before action"
        )
    if (
        str(row.get("current_checkpoint_id") or "") != artifact.checkpoint_id
        or _positive_int(row.get("session_version"), "session_version")
        != _positive_int(row.get("owner_context_version"), "owner_context_version")
        or str(row.get("session_status") or "") not in {"active", "paused"}
    ):
        raise ArtifactOwnerVersionConflict(
            "teaching Artifact session authority is stale"
        )
    return row


def _validate_cancel_authority(
    conn: Connection[dict[str, object]],
    *,
    row: Mapping[str, object],
    artifact: TutorPublicArtifactItem,
    owner_kind: TutorArtifactOwnerKind,
) -> None:
    if owner_kind is TutorArtifactOwnerKind.TEACHING_PRACTICE:
        if (
            artifact.owner_id != artifact.checkpoint_id
            or artifact.owner_version
            != _positive_int(row.get("session_version"), "session_version")
        ):
            raise ArtifactOwnerVersionConflict(
                "legacy teaching-practice owner is stale"
            )
        return
    item = conn.execute(
        """
        SELECT versions.id
        FROM tutor_learning_item_versions AS versions
        JOIN tutor_learning_item_publication_events AS publication
          ON publication.version_id = versions.id
         AND publication.state_version = %s
         AND publication.state = 'published'
        WHERE versions.id = %s
          AND versions.knowledge_key = %s
        """,
        (artifact.owner_version, artifact.owner_id, artifact.knowledge_key),
    ).fetchone()
    if item is None:
        raise ArtifactOwnerVersionConflict(
            "Learning Item owner publication identity is stale"
        )


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ArtifactOwnerVersionConflict(f"{label} is invalid")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ArtifactOwnerVersionConflict(f"{label} is invalid") from exc
    if parsed < 1:
        raise ArtifactOwnerVersionConflict(f"{label} is invalid")
    return parsed


__all__ = (
    "LearningItemArtifactOwnerAdapter",
    "TeachingPracticeArtifactOwnerAdapter",
)
