"""PostgreSQL authority for finite ReviewSession batches and review-owned Attempts."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.practice.contracts import (
    ExerciseAttemptOutcome,
    ExerciseAttemptResult,
    ExerciseAttemptType,
    canonical_submission_hash,
)
from app.services.learning.reviews.context_snapshot import build_review_context_snapshot, snapshot_payload
from app.services.learning.reviews.contracts import REVIEW_POLICY_VERSION, ReviewAggregate, ReviewAttemptSummary, ReviewCandidate
from app.services.learning.reviews.persistence import (
    ReviewIdempotencyConflict,
    ReviewNotFound,
    ReviewNotReady,
    ReviewRepositoryError,
    ReviewVersionConflict,
    as_float,
    as_int,
    as_mapping,
    content_hash,
    json_text,
    string_list,
)
from app.services.learning.reviews.schedule_repository import (
    PostgresReviewScheduleRepository,
    schedule_from_row,
    schedule_payload,
)
from app.services.learning.reviews.scheduler import advance_schedule
from app.services.learning.track_repository import PostgresLearningTrackRepository


class PostgresReviewSessionRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn
        self._schedules = PostgresReviewScheduleRepository(conn)

    def candidate_rows(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        limit: int = 12,
    ) -> tuple[dict[str, object], ...]:
        scope = self._active_scope(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key)
        capabilities = string_list(scope.get("required_capabilities_json")) or [knowledge_key]
        rows = self._conn.execute(
            """
            SELECT versions.*
            FROM tutor_exercise_versions AS versions
            WHERE versions.language_id = %s AND versions.validation_status = 'ready'
              AND versions.required_capabilities_json ?| %s
              AND (
                versions.source_kind <> 'registered_author'
                OR EXISTS (
                  SELECT 1
                  FROM tutor_model_review_publications AS publications
                  WHERE publications.user_id = %s
                    AND publications.track_id = %s
                    AND publications.knowledge_key = %s
                    AND publications.exercise_version_id = versions.id
                )
              )
            ORDER BY
              CASE versions.exercise_type
                WHEN 'model_code_review' THEN 0
                WHEN 'static_code_reasoning' THEN 1
                ELSE 2
              END,
              versions.published_at DESC, versions.id DESC
            LIMIT %s
            """,
            (
                scope["language_id"],
                capabilities,
                user_id,
                track_id,
                knowledge_key,
                limit,
            ),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def create_or_retry_session(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        expected_track_version: int,
        expected_schedule_version: int,
        max_items: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
        candidates: Sequence[ReviewCandidate],
    ) -> dict[str, object]:
        existing = self._conn.execute(
            """SELECT * FROM tutor_review_sessions
            WHERE user_id = %s AND track_id = %s AND idempotency_key = %s FOR UPDATE""",
            (user_id, track_id, idempotency_key),
        ).fetchone()
        selected = tuple(candidates[:max_items])
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise ReviewIdempotencyConflict("review session idempotency conflict")
            if str(existing["state"]) == "blocked" and selected:
                scope = self._active_scope(
                    user_id=user_id,
                    track_id=track_id,
                    knowledge_key=knowledge_key,
                    for_update=True,
                )
                schedule_row = self._schedules.read(
                    user_id=user_id,
                    track_id=track_id,
                    knowledge_key=knowledge_key,
                    for_update=True,
                )
                due_at = schedule_row.get("due_at")
                if (
                    as_int(scope["track_version"]) != expected_track_version
                    or as_int(schedule_row["version"]) != expected_schedule_version
                    or str(scope["plan_revision_id"]) != str(existing["plan_revision_id"])
                    or str(schedule_row["status"]) != "active"
                    or not isinstance(due_at, datetime)
                    or (
                        due_at > now
                        and str(schedule_row.get("risk_level") or "") != "critical"
                    )
                ):
                    raise ReviewVersionConflict("blocked review session scope changed")
                self._insert_items(
                    session_id=str(existing["id"]),
                    user_id=user_id,
                    track_id=track_id,
                    plan_revision_id=str(existing["plan_revision_id"]),
                    knowledge_key=knowledge_key,
                    candidates=selected,
                )
                self._conn.execute(
                    """UPDATE tutor_review_sessions
                    SET state = 'active', failure_code = NULL, version = version + 1
                    WHERE id = %s""",
                    (existing["id"],),
                )
                return self.read_session(
                    user_id=user_id,
                    track_id=track_id,
                    session_id=str(existing["id"]),
                    replayed=True,
                )
            return self.read_session(
                user_id=user_id,
                track_id=track_id,
                session_id=str(existing["id"]),
                replayed=True,
            )
        scope = self._active_scope(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            for_update=True,
        )
        schedule_row = self._schedules.read(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            for_update=True,
        )
        if str(schedule_row["status"]) != "active":
            raise ReviewNotReady("review schedule is unavailable")
        due_at = schedule_row.get("due_at")
        if not isinstance(due_at, datetime) or (
            due_at > now and str(schedule_row.get("risk_level") or "") != "critical"
        ):
            raise ReviewNotReady("review schedule is not due or critical")
        if (
            as_int(scope["track_version"]) != expected_track_version
            or as_int(schedule_row["version"]) != expected_schedule_version
        ):
            raise ReviewVersionConflict("review session scope changed")
        session_id = str(uuid4())
        snapshot = build_review_context_snapshot(
            self._conn,
            session_id=session_id,
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            scope=scope,
            schedule_row=schedule_row,
        )
        blocked = not selected
        self._conn.execute(
            """
            INSERT INTO tutor_review_sessions (
              id, user_id, track_id, plan_revision_id, knowledge_key,
              expected_track_version, expected_schedule_version, state, stage,
              failure_code, context_snapshot_json, context_snapshot_hash,
              idempotency_key, request_hash, version, started_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'warmup', %s,
                      %s::jsonb, %s, %s, %s, 1, %s)
            """,
            (
                session_id,
                user_id,
                track_id,
                scope["plan_revision_id"],
                knowledge_key,
                expected_track_version,
                expected_schedule_version,
                "blocked" if blocked else "active",
                "REVIEW_CANDIDATE_UNAVAILABLE" if blocked else None,
                json_text(snapshot_payload(snapshot)),
                snapshot.snapshot_hash,
                idempotency_key,
                request_hash,
                now,
            ),
        )
        if selected:
            self._insert_items(
                session_id=session_id,
                user_id=user_id,
                track_id=track_id,
                plan_revision_id=str(scope["plan_revision_id"]),
                knowledge_key=knowledge_key,
                candidates=selected,
            )
        return self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)

    def read_session(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        replayed: bool = False,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF sessions" if for_update else ""
        row = self._conn.execute(
            """
            SELECT sessions.*, finalizations.rating, finalizations.aggregate_json,
                   finalizations.result_hash AS finalization_result_hash
            FROM tutor_review_sessions AS sessions
            LEFT JOIN tutor_review_finalizations AS finalizations ON finalizations.session_id = sessions.id
            WHERE sessions.id = %s AND sessions.user_id = %s AND sessions.track_id = %s
            """ + lock,
            (session_id, user_id, track_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("review session was not found")
        items = self._conn.execute(
            """
            SELECT items.*, versions.language_id, versions.exercise_type, versions.title,
                   versions.learner_prompt_json, versions.starter_artifact_json,
                   versions.required_capabilities_json, versions.runtime_profile_key,
                   versions.execution_required, versions.content_hash,
                   attempts.id AS attempt_id, attempts.independence, attempts.assistance_kind,
                   results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state
            FROM tutor_review_items AS items
            JOIN tutor_exercise_versions AS versions ON versions.id = items.exercise_version_id
            LEFT JOIN tutor_exercise_attempts AS attempts
              ON attempts.review_item_id = items.id AND attempts.attempt_type = 'review_submit'
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE items.session_id = %s AND items.user_id = %s AND items.track_id = %s
            ORDER BY items.order_index
            """,
            (session_id, user_id, track_id),
        ).fetchall()
        result = dict(row)
        result["items"] = [dict(item) for item in items]
        result["idempotent_replayed"] = replayed
        return result

    def _insert_items(
        self,
        *,
        session_id: str,
        user_id: str,
        track_id: str,
        plan_revision_id: str,
        knowledge_key: str,
        candidates: Sequence[ReviewCandidate],
    ) -> None:
        for index, candidate in enumerate(candidates):
            selection = {
                "policy_version": REVIEW_POLICY_VERSION,
                "knowledge_key": knowledge_key,
                "required_capabilities": list(candidate.required_capabilities),
                "content_hash": candidate.content_hash,
            }
            self._conn.execute(
                """
                INSERT INTO tutor_review_items (
                  session_id, user_id, track_id, plan_revision_id, knowledge_key,
                  exercise_version_id, order_index, selection_reason_json, item_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    session_id,
                    user_id,
                    track_id,
                    plan_revision_id,
                    knowledge_key,
                    candidate.exercise_version_id,
                    index,
                    json_text(selection),
                    content_hash(selection),
                ),
            )


    def record_warmup(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        response_kind: str,
        response_summary: Mapping[str, object],
        expected_session_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object]:
        session = self.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            for_update=True,
        )
        existing = self._conn.execute(
            "SELECT * FROM tutor_review_warmup_receipts WHERE session_id = %s FOR UPDATE",
            (session_id,),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise ReviewIdempotencyConflict("review warmup idempotency conflict")
            return self.read_session(
                user_id=user_id,
                track_id=track_id,
                session_id=session_id,
                replayed=True,
            )
        if str(session["state"]) != "active" or str(session["stage"]) != "warmup":
            raise ReviewNotReady("review warmup is not available")
        if as_int(session["version"]) != expected_session_version:
            raise ReviewVersionConflict("review session changed")
        self._conn.execute(
            """
            INSERT INTO tutor_review_warmup_receipts (
              session_id, user_id, track_id, response_kind, response_summary_json,
              idempotency_key, request_hash
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                session_id,
                user_id,
                track_id,
                response_kind,
                json_text(response_summary),
                idempotency_key,
                request_hash,
            ),
        )
        self._conn.execute(
            "UPDATE tutor_review_sessions SET stage = 'practice', version = version + 1 WHERE id = %s",
            (session_id,),
        )
        return self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)

    def record_hint(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        item_id: str,
        hint_level: int,
        expected_session_version: int,
        expected_item_version: int,
        safe_hint: Mapping[str, object],
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object]:
        session = self.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            for_update=True,
        )
        if str(session["state"]) != "active" or str(session["stage"]) != "practice":
            raise ReviewNotReady("review hint is not available")
        if as_int(session["version"]) != expected_session_version:
            raise ReviewVersionConflict("review session changed")
        item = self._item_scope(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=item_id,
        )
        if as_int(item["version"]) != expected_item_version:
            raise ReviewVersionConflict("review item changed")
        attempted = self._conn.execute(
            "SELECT 1 FROM tutor_exercise_attempts WHERE review_item_id = %s",
            (item_id,),
        ).fetchone()
        if attempted is not None:
            raise ReviewNotReady("submitted review item does not accept new hints")
        row = self._conn.execute(
            """
            INSERT INTO tutor_review_hint_receipts (
              session_id, item_id, user_id, track_id, knowledge_key, exercise_version_id,
              hint_level, hint_policy_version, safe_hint_json, idempotency_key, request_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'review_hint_v1', %s::jsonb, %s, %s)
            ON CONFLICT (user_id, item_id, idempotency_key) DO NOTHING RETURNING *
            """,
            (
                session_id,
                item_id,
                user_id,
                track_id,
                item["knowledge_key"],
                item["exercise_version_id"],
                hint_level,
                json_text(safe_hint),
                idempotency_key,
                request_hash,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                """SELECT * FROM tutor_review_hint_receipts
                WHERE user_id = %s AND item_id = %s AND idempotency_key = %s""",
                (user_id, item_id, idempotency_key),
            ).fetchone()
            if row is None or str(row["request_hash"]) != request_hash:
                raise ReviewIdempotencyConflict("review hint idempotency conflict")
        return dict(row)

    def create_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        item_id: str,
        submission: str,
        expected_session_version: int,
        expected_item_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        session = self.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            for_update=True,
        )
        normalized = str(submission).replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip() or len(normalized) > 48_000:
            raise ReviewRepositoryError("submission must contain 1..48000 characters")
        existing = self._conn.execute(
            """
            SELECT attempts.*, submissions.id AS submission_id
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = attempts.id
            WHERE attempts.user_id = %s AND attempts.attempt_type = 'review_submit'
              AND attempts.idempotency_key = %s FOR UPDATE OF attempts
            """,
            (user_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise ReviewIdempotencyConflict("review attempt idempotency conflict")
            replay = dict(existing)
            replay["idempotent_replayed"] = True
            return replay
        if str(session["state"]) != "active" or str(session["stage"]) != "practice":
            raise ReviewNotReady("review item submission is not available")
        if as_int(session["version"]) != expected_session_version:
            raise ReviewVersionConflict("review session changed")
        item = self._item_scope(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            item_id=item_id,
        )
        if as_int(item["version"]) != expected_item_version:
            raise ReviewVersionConflict("review item changed")
        prior = self._conn.execute(
            """SELECT id FROM tutor_exercise_attempts
            WHERE review_item_id = %s AND attempt_type = 'review_submit'""",
            (item_id,),
        ).fetchone()
        if prior is not None:
            raise ReviewNotReady("review item already has an Attempt")
        hints = self._conn.execute(
            """SELECT count(*)::int AS count FROM tutor_review_hint_receipts
            WHERE user_id = %s AND item_id = %s""",
            (user_id, item_id),
        ).fetchone()
        hint_count = as_int(hints["count"] if hints else 0)
        attempt_id = str(uuid4())
        submission_id = str(uuid4())
        submission_hash = canonical_submission_hash(normalized)
        independence = "hinted" if hint_count else "independent"
        hint_hash = content_hash({"hint_count": hint_count, "policy_version": "review_hint_v1"})
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempts (
              id, attempt_type, user_id, track_id, plan_revision_id,
              expected_track_version, expected_progress_version, knowledge_key,
              lesson_assignment_id, document_id, gate_binding_id,
              diagnostic_session_id, diagnostic_item_id,
              review_session_id, review_item_id, expected_review_session_version,
              expected_review_item_version, exercise_version_id, submission_hash,
              hint_state_hash, independence, assistance_kind, idempotency_key,
              request_hash, accepted_at
            ) VALUES (%s, 'review_submit', %s, %s, %s, %s, NULL, %s,
                      NULL, NULL, NULL, NULL, NULL, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s)
            """,
            (
                attempt_id,
                user_id,
                track_id,
                session["plan_revision_id"],
                session["expected_track_version"],
                session["knowledge_key"],
                session_id,
                item_id,
                expected_session_version,
                expected_item_version,
                item["exercise_version_id"],
                submission_hash,
                hint_hash,
                independence,
                independence,
                idempotency_key,
                request_hash,
                now,
            ),
        )
        self._conn.execute(
            "UPDATE tutor_review_sessions SET version = version + 1 WHERE id = %s",
            (session_id,),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_submissions (
              id, attempt_id, user_id, exercise_version_id,
              submission_kind, content_text, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                submission_id,
                attempt_id,
                user_id,
                item["exercise_version_id"],
                _submission_kind(str(item["exercise_type"])),
                normalized,
                submission_hash,
            ),
        )
        return {
            **dict(item),
            "id": attempt_id,
            "attempt_type": ExerciseAttemptType.REVIEW_SUBMIT.value,
            "user_id": user_id,
            "track_id": track_id,
            "review_session_id": session_id,
            "review_item_id": item_id,
            "knowledge_key": str(item["knowledge_key"]),
            "submission_id": submission_id,
            "submission_hash": submission_hash,
            "independence": independence,
            "assistance_kind": independence,
            "accepted_at": now,
            "review_session_version": expected_session_version + 1,
            "idempotent_replayed": False,
        }


    def read_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        attempt_id: str,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF attempts" if for_update else ""
        row = self._conn.execute(
            """
            SELECT attempts.*, submissions.id AS submission_id,
                   sessions.version AS review_session_version,
                   versions.language_id, versions.exercise_type, versions.title, versions.learner_prompt_json,
                   versions.starter_artifact_json, versions.required_capabilities_json,
                   versions.runtime_profile_key, versions.execution_required, versions.content_hash,
                   results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json, results.policy_version AS result_policy_version,
                   results.result_hash, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = attempts.id
            JOIN tutor_review_sessions AS sessions ON sessions.id = attempts.review_session_id
            JOIN tutor_exercise_versions AS versions ON versions.id = attempts.exercise_version_id
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE attempts.id = %s AND attempts.user_id = %s AND attempts.track_id = %s
              AND attempts.review_session_id = %s AND attempts.attempt_type = 'review_submit'
            """ + lock,
            (attempt_id, user_id, track_id, session_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("review Attempt was not found")
        return dict(row)

    def finalize_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        attempt_id: str,
        result: ExerciseAttemptResult,
    ) -> dict[str, object]:
        attempt = self.read_attempt(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            attempt_id=attempt_id,
            for_update=True,
        )
        if attempt.get("result_hash") is not None:
            if str(attempt["result_hash"]) != result.result_hash:
                raise ReviewIdempotencyConflict("review Attempt result conflict")
            attempt["idempotent_replayed"] = True
            return attempt
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_results (
              attempt_id, user_id, outcome, score, safe_feedback_json,
              capability_scores_json, execution_receipt_hash, policy_version,
              result_hash, terminal_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                attempt_id,
                user_id,
                result.outcome.value,
                result.score,
                json_text(result.safe_feedback),
                json_text(result.capability_scores),
                result.execution_receipt_hash,
                result.policy_version,
                result.result_hash,
                result.terminal_at,
            ),
        )
        counts = self._conn.execute(
            """
            SELECT count(items.id)::int AS total, count(results.id)::int AS completed
            FROM tutor_review_items AS items
            LEFT JOIN tutor_exercise_attempts AS attempts
              ON attempts.review_item_id = items.id AND attempts.attempt_type = 'review_submit'
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE items.session_id = %s AND items.user_id = %s
            """,
            (session_id, user_id),
        ).fetchone()
        ready = (
            counts is not None
            and as_int(counts["total"]) > 0
            and as_int(counts["total"]) == as_int(counts["completed"])
        )
        session = self._conn.execute(
            "SELECT state FROM tutor_review_sessions WHERE id = %s FOR UPDATE",
            (session_id,),
        ).fetchone()
        if session is None:
            raise ReviewNotFound("review session was not found")
        target = "ready_to_finalize" if ready else "active"
        if str(session["state"]) != target:
            self._conn.execute(
                "UPDATE tutor_review_sessions SET state = %s, version = version + 1 WHERE id = %s",
                (target, session_id),
            )
        return self.read_attempt(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            attempt_id=attempt_id,
        )

    def finalize_session(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        expected_session_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        existing = self._conn.execute(
            """SELECT * FROM tutor_review_finalizations
            WHERE session_id = %s AND user_id = %s FOR UPDATE""",
            (session_id, user_id),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise ReviewIdempotencyConflict("review finalization idempotency conflict")
            return self.read_session(
                user_id=user_id,
                track_id=track_id,
                session_id=session_id,
                replayed=True,
            )
        session = self.read_session(
            user_id=user_id,
            track_id=track_id,
            session_id=session_id,
            for_update=True,
        )
        if str(session["state"]) != "ready_to_finalize":
            raise ReviewNotReady("review session is not ready to finalize")
        if as_int(session["version"]) != expected_session_version:
            raise ReviewVersionConflict("review session changed")
        track = self._track_scope(user_id=user_id, track_id=track_id)
        if (
            as_int(track["version"]) != as_int(session["expected_track_version"])
            or str(track["plan_revision_id"]) != str(session["plan_revision_id"])
        ):
            raise ReviewVersionConflict("LearningTrack changed during ReviewSession")
        schedule_row = self._schedules.read(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=str(session["knowledge_key"]),
            for_update=True,
        )
        if as_int(schedule_row["version"]) != as_int(session["expected_schedule_version"]):
            raise ReviewVersionConflict("review schedule changed")
        rows = self._conn.execute(
            """
            SELECT attempts.independence, results.outcome, results.score,
                   results.capability_scores_json, versions.required_capabilities_json
            FROM tutor_review_items AS items
            JOIN tutor_exercise_attempts AS attempts
              ON attempts.review_item_id = items.id AND attempts.attempt_type = 'review_submit'
            JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            JOIN tutor_exercise_versions AS versions ON versions.id = items.exercise_version_id
            WHERE items.session_id = %s AND items.user_id = %s
            ORDER BY items.order_index
            """,
            (session_id, user_id),
        ).fetchall()
        raw_items = session.get("items")
        item_count = len(raw_items) if isinstance(raw_items, list | tuple) else 0
        if not rows or len(rows) != item_count:
            raise ReviewNotReady("review session has incomplete items")
        attempts = tuple(
            ReviewAttemptSummary(
                outcome=ExerciseAttemptOutcome(str(row["outcome"])),
                score=as_float(row["score"]),
                independence=MasteryIndependence(str(row["independence"])),
                capability_scores={
                    str(key): as_float(value)
                    for key, value in as_mapping(row.get("capability_scores_json")).items()
                },
            )
            for row in rows
        )
        capabilities = tuple(
            dict.fromkeys(
                capability
                for row in rows
                for capability in string_list(row.get("required_capabilities_json"))
            )
        )
        aggregate = ReviewAggregate(attempts=attempts, critical_capabilities=capabilities)
        prerequisite = str(session["knowledge_key"]) in self._schedules.current_prerequisites(
            user_id=user_id,
            track_id=track_id,
            revision_id=str(session["plan_revision_id"]),
            current_key=str(track.get("current_knowledge_key") or ""),
        )
        previous = schedule_from_row(schedule_row)
        decision = advance_schedule(
            previous=previous,
            aggregate=aggregate,
            now=now,
            prerequisite_for_current=prerequisite,
        )
        finalization_id = str(uuid4())
        updated_schedule = self._schedules.update_after_review(
            schedule_row=schedule_row,
            next_schedule=decision.next_schedule,
            now=now,
        )
        event_id = self._schedules.insert_event(
            schedule_row=updated_schedule,
            source_kind="session_finalization",
            source_receipt_id=finalization_id,
            reason_codes=decision.reason_codes,
            previous=schedule_payload(previous),
            next_state=schedule_payload(decision.next_schedule),
            now=now,
        )
        aggregate_payload = {
            "schema_version": "review_aggregate_v1",
            "attempt_count": len(attempts),
            "average_score": aggregate.average_score,
            "hint_count": aggregate.hint_count,
            "independence": aggregate.independence.value,
            "rating": decision.rating.value,
            "critical_failure": aggregate.critical_failure,
            "critical_prerequisite_gate": decision.critical_prerequisite_gate,
            "reason_codes": list(decision.reason_codes),
        }
        final_hash = content_hash(
            {
                "session_id": session_id,
                "aggregate": aggregate_payload,
                "schedule_event_id": event_id,
                "policy_version": REVIEW_POLICY_VERSION,
            }
        )
        evidence = MasteryEvidence(
            evidence_id=str(uuid4()),
            knowledge_key=str(session["knowledge_key"]),
            evidence_kind=MasteryEvidenceKind.REVIEW,
            source_receipt_id=finalization_id,
            source_receipt_hash=final_hash,
            independence=aggregate.independence,
            score=aggregate.average_score,
            hint_count=aggregate.hint_count,
            attempt_count=len(attempts),
            summary={
                "strengths": list(capabilities) if aggregate.all_passed else [],
                "weaknesses": list(capabilities) if not aggregate.all_passed else [],
                "rating": decision.rating.value,
            },
            created_at=now,
        )
        evidence_id, _mastery, _replayed = PostgresLearningTrackRepository(
            self._conn
        ).append_mastery_evidence(user_id=user_id, track_id=track_id, evidence=evidence)
        self._conn.execute(
            """
            INSERT INTO tutor_review_finalizations (
              id, session_id, user_id, track_id, knowledge_key, mastery_evidence_id,
              schedule_event_id, rating, aggregate_json, result_hash,
              idempotency_key, request_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (
                finalization_id,
                session_id,
                user_id,
                track_id,
                session["knowledge_key"],
                evidence_id,
                event_id,
                decision.rating.value,
                json_text(aggregate_payload),
                final_hash,
                idempotency_key,
                request_hash,
            ),
        )
        self._conn.execute(
            """UPDATE tutor_review_sessions
            SET state = 'finalized', stage = 'final_summary', terminal_at = %s,
                version = version + 1 WHERE id = %s""",
            (now, session_id),
        )
        return self.read_session(user_id=user_id, track_id=track_id, session_id=session_id)

    def _active_scope(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF tracks, progress" if for_update else ""
        row = self._conn.execute(
            """
            SELECT tracks.language_id, tracks.goal_text, tracks.target_level,
                   tracks.current_knowledge_key, tracks.version AS track_version,
                   active.revision_id AS plan_revision_id,
                   nodes.title, nodes.required_capabilities_json,
                   progress.status AS progress_status, progress.version AS progress_version,
                   mastery.confidence, mastery.mastery_level, mastery.version AS mastery_version
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
                 (active.revision_id, tracks.id, tracks.user_id)
             AND nodes.knowledge_key = %s
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (tracks.id, tracks.user_id, nodes.knowledge_key)
            LEFT JOIN tutor_mastery_states AS mastery
              ON (mastery.track_id, mastery.user_id, mastery.knowledge_key) =
                 (tracks.id, tracks.user_id, nodes.knowledge_key)
            WHERE tracks.id = %s AND tracks.user_id = %s
            """ + lock,
            (knowledge_key, track_id, user_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("active review knowledge node was not found")
        return dict(row)

    def _item_scope(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        item_id: str,
    ) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT items.*, versions.language_id, versions.exercise_type, versions.title,
                   versions.learner_prompt_json, versions.starter_artifact_json,
                   versions.required_capabilities_json, versions.runtime_profile_key,
                   versions.execution_required, versions.content_hash
            FROM tutor_review_items AS items
            JOIN tutor_exercise_versions AS versions ON versions.id = items.exercise_version_id
            WHERE items.id = %s AND items.session_id = %s
              AND items.user_id = %s AND items.track_id = %s
            """,
            (item_id, session_id, user_id, track_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("review item was not found")
        return dict(row)

    def _track_scope(self, *, user_id: str, track_id: str) -> dict[str, object]:
        row = self._conn.execute(
            """SELECT tracks.*, active.revision_id AS plan_revision_id
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            WHERE tracks.id = %s AND tracks.user_id = %s""",
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("LearningTrack was not found")
        return dict(row)


def _submission_kind(exercise_type: str) -> str:
    if exercise_type == "sql_query":
        return "sql"
    if exercise_type in {"static_code_reasoning", "model_code_review"}:
        return "structured_answer"
    return "code"
