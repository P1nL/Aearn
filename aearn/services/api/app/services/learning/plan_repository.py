"""PostgreSQL repository for persistent conversational learning-plan sessions."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import canonical_plan_payload
from app.services.learning.plan_drafting import LearningPlanDraftArtifact


class LearningPlanSessionRepositoryError(ValueError):
    pass


class LearningPlanSessionNotFound(LearningPlanSessionRepositoryError):
    pass


class LearningPlanSessionConflict(LearningPlanSessionRepositoryError):
    pass


class LearningPlanDraftConflict(LearningPlanSessionRepositoryError):
    pass


_SAFE_ERROR_CODES = frozenset(
    {
        "LEARNING_PLAN_DRAFT_INVALID",
        "LEARNING_PLAN_DRAFT_QUALITY_BLOCKED",
        "LEARNING_LANGUAGE_NOT_SELECTABLE",
        "LEARNING_PLAN_CAPABILITY_UNAVAILABLE",
    }
)


class PostgresLearningPlanSessionRepository:
    """Transaction-bound adapter; callers own commit and rollback."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def create_session(
        self,
        *,
        user_id: str,
        conversation_id: str,
        preferred_language_id: str | None,
    ) -> dict[str, object]:
        row = self._conn.execute(
            """
            INSERT INTO tutor_learning_plan_sessions (
              user_id, conversation_id, preferred_language_id, status, version
            )
            VALUES (%s, %s, %s, 'collecting', 1)
            RETURNING *
            """,
            (user_id, conversation_id, preferred_language_id),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionConflict("learning plan session was not created")
        return dict(row)

    def read_current_session(self, *, user_id: str, for_update: bool = False) -> dict[str, object] | None:
        lock = " FOR UPDATE OF sessions" if for_update else ""
        row = self._conn.execute(
            self._SESSION_READ_SQL
            + " WHERE sessions.user_id = %s AND sessions.status IN ('collecting', 'draft_ready')"
            + " ORDER BY sessions.updated_at DESC, sessions.id DESC LIMIT 1"
            + lock,
            (user_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def read_session(
        self,
        *,
        user_id: str,
        session_id: str,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF sessions" if for_update else ""
        row = self._conn.execute(
            self._SESSION_READ_SQL + " WHERE sessions.id = %s AND sessions.user_id = %s" + lock,
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionNotFound("learning plan session not found")
        return dict(row)

    def active_session_for_run(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF sessions" if for_update else ""
        row = self._conn.execute(
            self._SESSION_READ_SQL
            + """
              JOIN tutor_runs AS runs
                ON runs.conversation_id = sessions.conversation_id
               AND runs.user_id = sessions.user_id
              JOIN tutor_run_learning_scopes AS scopes
                ON scopes.run_id = runs.id
               AND scopes.user_id = runs.user_id
               AND scopes.conversation_id = runs.conversation_id
              WHERE sessions.user_id = %s
                AND runs.id = %s
                AND runs.origin = 'interactive'
                AND runs.input_revision = %s
                AND runs.terminal_outcome IS NULL
                AND runs.cancelled_at IS NULL
                AND runs.superseded_by_run_id IS NULL
                AND sessions.status IN ('collecting', 'draft_ready')
                AND scopes.scope_kind = 'plan_drafting'
                AND scopes.task_kind = 'plan_drafting'
            """
            + lock,
            (user_id, run_id, input_revision),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionNotFound("active learning plan session not found for run")
        return dict(row)

    def draft_for_source(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            self._DRAFT_READ_SQL
            + " WHERE drafts.user_id = %s AND drafts.source_run_id = %s AND drafts.source_input_revision = %s",
            (user_id, run_id, input_revision),
        ).fetchone()
        return dict(row) if row is not None else None

    def append_draft(
        self,
        *,
        user_id: str,
        run_id: str,
        input_revision: int,
        artifact: LearningPlanDraftArtifact,
        facts_fingerprint: str,
        facts_revision: int,
    ) -> tuple[dict[str, object], bool]:
        replay = self._conn.execute(
            self._DRAFT_READ_SQL
            + " WHERE drafts.source_run_id = %s AND drafts.source_input_revision = %s",
            (run_id, input_revision),
        ).fetchone()
        if replay is not None:
            if (
                str(replay["user_id"]) != user_id
                or str(replay["content_hash"]) != artifact.content_hash
                or str(replay.get("facts_fingerprint") or "") != facts_fingerprint
                or _int(replay.get("facts_revision")) != facts_revision
            ):
                raise LearningPlanDraftConflict("draft replay conflicts with stored artifact")
            return dict(replay), True

        session = self.active_session_for_run(
            user_id=user_id,
            run_id=run_id,
            input_revision=input_revision,
            for_update=True,
        )
        prior_id = _optional_str(session.get("current_draft_id"))
        prior_version = _int(session.get("draft_version"))
        draft_id = str(uuid4())
        draft_version = prior_version + 1
        profile_json = artifact.profile.model_dump(mode="json")
        plan_json = canonical_plan_payload(artifact.plan)
        source_json = [source.as_dict() for source in artifact.sources]
        row = self._conn.execute(
            """
            INSERT INTO tutor_learning_plan_drafts (
              id, session_id, user_id, draft_version, predecessor_draft_id,
              language_id, goal_text, target_level, weekly_minutes, experience_level,
              teaching_preferences_json, pace_summary, profile_json, plan_json,
              source_summary_json, content_hash, generator_version, policy_version,
              change_reason, source_run_id, source_input_revision,
              facts_fingerprint, facts_revision
            ) VALUES (
              %s, %s, %s, %s, %s,
              %s, %s, %s, %s, %s,
              %s::jsonb, %s, %s::jsonb, %s::jsonb,
              %s::jsonb, %s, %s, %s,
              %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                draft_id,
                session["id"],
                user_id,
                draft_version,
                prior_id,
                artifact.profile.language_id,
                artifact.profile.goal_text,
                artifact.profile.target_level,
                artifact.profile.weekly_minutes,
                artifact.profile.experience_level.value,
                _json(artifact.profile.teaching_preferences),
                artifact.profile.pace_summary,
                _json(profile_json),
                _json(plan_json),
                _json(source_json),
                artifact.content_hash,
                artifact.plan.generator_version,
                artifact.plan.policy_version,
                artifact.plan.change_reason,
                run_id,
                input_revision,
                facts_fingerprint,
                facts_revision,
            ),
        ).fetchone()
        if row is None:
            raise LearningPlanDraftConflict("learning plan draft was not appended")
        updated = self._conn.execute(
            """
            UPDATE tutor_learning_plan_sessions
            SET status = 'draft_ready', current_draft_id = %s, version = version + 1,
                last_error_code = NULL, last_error_at = NULL
            WHERE id = %s AND user_id = %s AND version = %s
              AND status IN ('collecting', 'draft_ready')
            RETURNING version
            """,
            (draft_id, session["id"], user_id, session["version"]),
        ).fetchone()
        if updated is None:
            raise LearningPlanSessionConflict("learning plan session changed while appending draft")
        result = dict(row)
        result["session_version"] = _int(updated["version"])
        return result, False

    def cancel_session(self, *, user_id: str, session_id: str, expected_version: int) -> dict[str, object]:
        now = datetime.now(UTC)
        row = self._conn.execute(
            """
            UPDATE tutor_learning_plan_sessions
            SET status = 'cancelled', cancelled_at = %s, version = version + 1
            WHERE id = %s AND user_id = %s AND version = %s
              AND status IN ('collecting', 'draft_ready')
            RETURNING *
            """,
            (now, session_id, user_id, expected_version),
        ).fetchone()
        if row is None:
            current = self.read_session(user_id=user_id, session_id=session_id)
            if str(current["status"]) == "confirmed":
                raise LearningPlanSessionConflict("confirmed learning plan session cannot be cancelled")
            raise LearningPlanSessionConflict("learning plan session version changed")
        return dict(row)

    def mark_confirmed(
        self,
        *,
        user_id: str,
        session_id: str,
        expected_version: int,
        draft_id: str,
        track_id: str,
    ) -> dict[str, object]:
        now = datetime.now(UTC)
        row = self._conn.execute(
            """
            UPDATE tutor_learning_plan_sessions
            SET status = 'confirmed', confirmed_track_id = %s, confirmed_at = %s,
                version = version + 1, last_error_code = NULL, last_error_at = NULL
            WHERE id = %s AND user_id = %s AND version = %s
              AND status = 'draft_ready' AND current_draft_id = %s
            RETURNING *
            """,
            (track_id, now, session_id, user_id, expected_version, draft_id),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionConflict("learning plan session changed before confirmation")
        return dict(row)

    def record_safe_error(self, *, user_id: str, session_id: str, code: str) -> None:
        if code not in _SAFE_ERROR_CODES:
            raise ValueError("learning plan error code is not allowlisted")
        self._conn.execute(
            """
            UPDATE tutor_learning_plan_sessions
            SET last_error_code = %s, last_error_at = %s
            WHERE id = %s AND user_id = %s AND status IN ('collecting', 'draft_ready')
            """,
            (code, datetime.now(UTC), session_id, user_id),
        )

    def draft_for_session(self, *, user_id: str, session_id: str, draft_id: str) -> dict[str, object]:
        row = self._conn.execute(
            self._DRAFT_READ_SQL
            + " WHERE drafts.id = %s AND drafts.session_id = %s AND drafts.user_id = %s",
            (draft_id, session_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningPlanSessionNotFound("learning plan draft not found")
        return dict(row)

    _SESSION_READ_SQL = """
        SELECT sessions.*,
               drafts.draft_version, drafts.content_hash, drafts.language_id AS draft_language_id,
               drafts.goal_text AS draft_goal_text, drafts.target_level AS draft_target_level,
               drafts.weekly_minutes, drafts.experience_level, drafts.teaching_preferences_json,
               drafts.pace_summary, drafts.profile_json, drafts.plan_json, drafts.source_summary_json,
               drafts.generator_version, drafts.policy_version, drafts.change_reason,
               drafts.source_run_id, drafts.source_input_revision, drafts.facts_fingerprint,
               drafts.facts_revision, drafts.created_at AS draft_created_at
        FROM tutor_learning_plan_sessions AS sessions
        LEFT JOIN tutor_learning_plan_drafts AS drafts
          ON drafts.id = sessions.current_draft_id
         AND drafts.session_id = sessions.id
         AND drafts.user_id = sessions.user_id
    """

    _DRAFT_READ_SQL = """
        SELECT drafts.*
        FROM tutor_learning_plan_drafts AS drafts
    """


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
