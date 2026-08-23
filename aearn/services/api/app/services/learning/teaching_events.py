"""Fail-closed adapters from durable learning events to teaching Turn stimuli."""
from __future__ import annotations

from psycopg import Connection

from app.services.learning.teaching_contracts import (
    DomainEventStimulus,
    TeachingDomainEventKind,
    TeachingSessionMode,
    stable,
)
from app.services.learning.teaching_sessions import (
    TeachingSessionConflict,
    TeachingSessionNotFound,
    TeachingSessionRepository,
)


class TeachingDomainEventAdapter:
    """Admit at most one bounded teaching Turn for one durable source identity."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._teaching = TeachingSessionRepository(conn)

    def admit_gate_terminal(self, *, user_id: str, attempt_id: str) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT attempts.track_id::text AS track_id, attempts.knowledge_key,
                   progress.status AS progress_status, progress.version AS progress_version
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            JOIN tutor_track_node_progress AS progress
              ON progress.track_id = attempts.track_id
             AND progress.user_id = attempts.user_id
             AND progress.knowledge_key = attempts.knowledge_key
            WHERE attempts.id = %s AND attempts.user_id = %s
              AND attempts.attempt_type IN ('run', 'submit')
            """,
            (attempt_id, user_id),
        ).fetchone()
        if row is None:
            return _ignored("domain_event_source_not_found")
        knowledge_key = str(row["knowledge_key"])
        gate_handle = f"gate:{attempt_id}"
        if str(row["progress_status"]) == "completed":
            return self.admit_progress_changed(
                user_id=user_id,
                track_id=str(row["track_id"]),
                knowledge_key=knowledge_key,
                source_version=_int(row["progress_version"]),
                extra_safe_handles=(gate_handle,),
            )
        return self._admit(
            event_kind=TeachingDomainEventKind.GATE_TERMINAL,
            source_id=attempt_id,
            source_version=1,
            user_id=user_id,
            track_id=str(row["track_id"]),
            knowledge_key=knowledge_key,
            safe_handles=(gate_handle, f"knowledge:{knowledge_key}"),
        )

    def admit_review_terminal(self, *, user_id: str, finalization_id: str) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT track_id::text AS track_id, knowledge_key
            FROM tutor_review_finalizations
            WHERE id = %s AND user_id = %s
            """,
            (finalization_id, user_id),
        ).fetchone()
        if row is None:
            return _ignored("domain_event_source_not_found")
        knowledge_key = str(row["knowledge_key"])
        return self._admit(
            event_kind=TeachingDomainEventKind.REVIEW_TERMINAL,
            source_id=finalization_id,
            source_version=1,
            user_id=user_id,
            track_id=str(row["track_id"]),
            knowledge_key=knowledge_key,
            safe_handles=(f"review:{finalization_id}", f"knowledge:{knowledge_key}"),
        )

    def admit_progress_changed(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        source_version: int,
        extra_safe_handles: tuple[str, ...] = (),
    ) -> dict[str, object]:
        key = stable(knowledge_key, "knowledge_key")
        row = self._conn.execute(
            """
            SELECT status, version
            FROM tutor_track_node_progress
            WHERE track_id = %s AND user_id = %s AND knowledge_key = %s
            """,
            (track_id, user_id, key),
        ).fetchone()
        if row is None or _int(row["version"]) != source_version:
            return _ignored("domain_event_stale")
        return self._admit(
            event_kind=TeachingDomainEventKind.PROGRESS_CHANGED,
            source_id=f"progress:{key}",
            source_version=source_version,
            user_id=user_id,
            track_id=track_id,
            knowledge_key=key,
            safe_handles=(*extra_safe_handles, f"progress:{key}", f"knowledge:{key}"),
        )

    def admit_assignment_changed(self, *, user_id: str, assignment_id: str) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT track_id::text AS track_id, knowledge_key, assignment_version, status
            FROM tutor_lesson_assignments
            WHERE id = %s AND user_id = %s
            """,
            (assignment_id, user_id),
        ).fetchone()
        if row is None or str(row["status"]) != "active":
            return _ignored("domain_event_stale")
        knowledge_key = str(row["knowledge_key"])
        return self._admit(
            event_kind=TeachingDomainEventKind.ASSIGNMENT_CHANGED,
            source_id=assignment_id,
            source_version=_int(row["assignment_version"]),
            user_id=user_id,
            track_id=str(row["track_id"]),
            knowledge_key=knowledge_key,
            safe_handles=(f"assignment:{assignment_id}", f"knowledge:{knowledge_key}"),
        )

    def _admit(
        self,
        *,
        event_kind: TeachingDomainEventKind,
        source_id: str,
        source_version: int,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        safe_handles: tuple[str, ...],
    ) -> dict[str, object]:
        stimulus = DomainEventStimulus(
            event_kind=event_kind,
            source_id=source_id,
            source_version=source_version,
            safe_handles=tuple(dict.fromkeys(safe_handles)),
        )
        replay = self._teaching.find_domain_event_admission(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            stimulus=stimulus,
        )
        if replay is not None:
            return {**replay, "event_status": "replayed", "idempotent_replayed": True}
        try:
            current = self._teaching.read_current(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                for_update=True,
            )
        except TeachingSessionNotFound:
            return _ignored("teaching_session_not_open")
        if str(current["status"]) == "completed":
            return _ignored("teaching_session_completed")
        try:
            authority = self._teaching.resolve_authority(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                conversation_id=str(current["conversation_id"]),
                for_update=True,
            )
            session, refreshed = self._teaching.open_or_resume(
                authority=authority,
                mode=TeachingSessionMode(str(current["mode"])),
            )
            admitted = self._teaching.admit_domain_event_run(
                authority=authority,
                session=session,
                stimulus=stimulus,
            )
        except (TeachingSessionConflict, TeachingSessionNotFound):
            return _ignored("teaching_authority_conflict")
        return {
            **admitted,
            "event_status": "admitted",
            "authority_refreshed": refreshed,
            "idempotent_replayed": False,
        }


def _ignored(code: str) -> dict[str, object]:
    return {"event_status": "ignored", "code": code, "idempotent_replayed": False}


def _int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("stored integer is invalid")
    return int(str(value))


__all__ = ["TeachingDomainEventAdapter"]
