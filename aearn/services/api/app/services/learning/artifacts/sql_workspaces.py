"""Bounded SQL Learning Item Run admission and post-commit execution."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from psycopg import Connection
from pydantic import ValidationError

from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactAttemptSummaryV1,
    TutorArtifactRunAction,
    TutorArtifactSqlWorkspacePresentationV2,
    TutorArtifactState,
    TutorPublicArtifactItem,
    canonical_hash,
)
from app.services.learning.artifacts.owner_adapters import (
    ArtifactMutation,
    ArtifactOwnerActionInvalid,
    ArtifactOwnerVersionConflict,
)
from app.services.learning.item_bank.contracts import (
    LearningItemPrivateV1,
    LearningItemPublicV1,
    LearningItemSqlContentV2,
    LearningItemSqlPrivateV2,
)
from app.services.learning.practice.contracts import canonical_submission_hash
from app.services.learning.practice.policies import score_execution_result
from app.services.learning.practice.repository import (
    PostgresExerciseGateRepository,
    PracticeRepositoryError,
)
from app.services.runners.sql_query_runner import (
    execute_sql_workspace_query,
    sql_execution_result_to_safe_result,
)


SQL_WORKSPACE_RUN_POLICY_VERSION = "sql_workspace_run_v1"


@dataclass(frozen=True, slots=True)
class _SqlWorkspaceAuthority:
    user_id: str
    plan_revision_id: str
    lesson_assignment_id: str
    document_id: str
    track_version: int
    progress_version: int
    assignment_version: int
    exercise_version_id: str
    public: LearningItemPublicV1
    private: LearningItemSqlPrivateV2


def admit_sql_workspace_run(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
    request: TutorArtifactActionRequest,
    owner_context_version: int,
) -> ArtifactMutation:
    """Persist one private pending Attempt; execution occurs after this transaction commits."""

    if not isinstance(request.action, TutorArtifactRunAction):
        raise ArtifactOwnerActionInvalid("SQL workspace accepts only an exact Run action")
    presentation = artifact.presentation
    if not isinstance(presentation, TutorArtifactSqlWorkspacePresentationV2):
        raise ArtifactOwnerActionInvalid("SQL workspace Run requires presentation v2")
    if artifact.active_attempt is not None and artifact.active_attempt.status == "pending":
        raise ArtifactOwnerActionInvalid("SQL workspace already has a pending Run")
    authority = _load_authority(conn, artifact=artifact)
    query = request.action.submission.replace("\r\n", "\n").replace("\r", "\n")
    submission_hash = canonical_submission_hash(query)
    idempotency_key = _attempt_idempotency_key(artifact.id, request.client_action_id)
    request_identity = canonical_hash(
        {
            "artifact_id": artifact.id,
            "artifact_version": artifact.version,
            "learning_item_version_id": artifact.owner_id,
            "exercise_version_id": authority.exercise_version_id,
            "submission_hash": submission_hash,
            "client_action_id": request.client_action_id,
        }
    )
    existing = conn.execute(
        """
        SELECT id,request_hash,accepted_at
        FROM tutor_exercise_attempts
        WHERE user_id=%s AND attempt_type='run' AND idempotency_key=%s
        """,
        (authority.user_id, idempotency_key),
    ).fetchone()
    if existing is not None:
        if str(existing["request_hash"]) != request_identity:
            raise ArtifactOwnerVersionConflict("SQL Run idempotency identity conflicts")
        attempt_id = str(existing["id"])
        accepted_at = _iso(existing["accepted_at"])
    else:
        attempt_id = str(uuid4())
        accepted_at_value = datetime.now(UTC)
        conn.execute(
            """
            INSERT INTO tutor_exercise_attempts (
              id,attempt_type,user_id,track_id,plan_revision_id,
              expected_track_version,expected_progress_version,knowledge_key,
              lesson_assignment_id,document_id,gate_binding_id,
              diagnostic_session_id,diagnostic_item_id,review_session_id,review_item_id,
              expected_review_session_version,expected_review_item_version,
              exercise_version_id,learning_item_version_id,submission_hash,hint_state_hash,
              independence,assistance_kind,idempotency_key,request_hash,accepted_at
            ) VALUES (
              %s,'run',%s,%s,%s,%s,%s,%s,%s,%s,NULL,
              NULL,NULL,NULL,NULL,NULL,NULL,%s,%s,%s,%s,
              'independent','independent',%s,%s,%s
            )
            """,
            (
                attempt_id,
                authority.user_id,
                artifact.learning_track_id,
                authority.plan_revision_id,
                authority.track_version,
                authority.progress_version,
                artifact.knowledge_key,
                authority.lesson_assignment_id,
                authority.document_id,
                authority.exercise_version_id,
                artifact.owner_id,
                submission_hash,
                canonical_hash(
                    {
                        "artifact_id": artifact.id,
                        "assistance_kind": "independent",
                        "policy_version": SQL_WORKSPACE_RUN_POLICY_VERSION,
                    }
                ),
                idempotency_key,
                request_identity,
                accepted_at_value,
            ),
        )
        conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_submissions (
              attempt_id,user_id,exercise_version_id,submission_kind,content_text,content_hash
            ) VALUES (%s,%s,%s,'sql',%s,%s)
            """,
            (
                attempt_id,
                authority.user_id,
                authority.exercise_version_id,
                query,
                submission_hash,
            ),
        )
        accepted_at = accepted_at_value.isoformat()
    pending = TutorArtifactAttemptSummaryV1(
        attempt_id=attempt_id,
        attempt_type="run",
        status="pending",
        accepted_at=accepted_at,
    )
    return ArtifactMutation(
        state=TutorArtifactState.RUNNING,
        owner_version=artifact.owner_version,
        owner_context_version=owner_context_version,
        presentation=presentation,
        allowed_actions=artifact.allowed_actions,
        active_attempt=pending,
        safe_event_payload={
            "attempt_id": attempt_id,
            "attempt_status": "pending",
            "query_hash": submission_hash,
            "execution_tier": presentation.execution_tier,
        },
    )


def observe_sql_workspace_attempt(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    conversation_id: str,
    artifact_id: str,
    attempt_id: str,
) -> None:
    """Run a committed pending SQL Attempt without holding the Artifact row lock."""

    row = conn.execute(
        """
        SELECT attempts.id,attempts.user_id,results.result_hash,
               submissions.content_text,
               artifacts.owner_id,artifacts.owner_version,artifacts.presentation_json,
               versions.public_hash,versions.private_hash,versions.content_hash,versions.handle,
               public.public_json,private.private_json,
               materializations.exercise_version_id,
               publication.state AS publication_state,
               publication.state_version AS publication_state_version
        FROM tutor_learning_artifact_attempt_links AS links
        JOIN tutor_learning_artifacts AS artifacts
          ON artifacts.id=links.artifact_id
         AND artifacts.user_id=links.user_id
         AND artifacts.conversation_id=links.conversation_id
         AND artifacts.learning_track_id=links.learning_track_id
         AND artifacts.teaching_session_id=links.teaching_session_id
        JOIN tutor_exercise_attempts AS attempts
          ON attempts.id=links.attempt_id
         AND attempts.user_id=links.user_id
         AND attempts.track_id=links.learning_track_id
         AND attempts.knowledge_key=artifacts.knowledge_key
        JOIN tutor_exercise_attempt_submissions AS submissions
          ON submissions.attempt_id=attempts.id
         AND submissions.user_id=attempts.user_id
         AND submissions.exercise_version_id=attempts.exercise_version_id
        LEFT JOIN tutor_exercise_attempt_results AS results
          ON results.attempt_id=attempts.id
         AND results.user_id=attempts.user_id
        JOIN tutor_learning_item_versions AS versions
          ON versions.id=attempts.learning_item_version_id
         AND versions.id=artifacts.owner_id
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN tutor_learning_item_private_contents AS private ON private.version_id=versions.id
        JOIN tutor_learning_item_practice_materializations AS materializations
          ON materializations.version_id=versions.id
         AND materializations.exercise_version_id=attempts.exercise_version_id
        JOIN LATERAL (
          SELECT state,state_version
          FROM tutor_learning_item_publication_events AS events
          WHERE events.version_id=versions.id
          ORDER BY state_version DESC LIMIT 1
        ) AS publication ON true
        WHERE links.artifact_id=%s AND links.attempt_id=%s
          AND links.user_id=%s AND links.conversation_id=%s
          AND attempts.attempt_type='run'
          AND attempts.gate_binding_id IS NULL
          AND attempts.learning_item_version_id=artifacts.owner_id
          AND tutor_learning_artifact_attempt_owner_matches(
            artifacts.user_id,artifacts.conversation_id,artifacts.learning_track_id,
            artifacts.knowledge_key,artifacts.teaching_session_id,
            artifacts.owner_kind,artifacts.owner_id,attempts.id
          )
        """,
        (artifact_id, attempt_id, user_id, conversation_id),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("SQL workspace Attempt scope is unavailable")
    if row.get("result_hash") is not None:
        conn.rollback()
        return
    try:
        presentation = TutorArtifactSqlWorkspacePresentationV2.model_validate(
            row["presentation_json"]
        )
        public = LearningItemPublicV1.model_validate(row["public_json"])
        private = LearningItemPrivateV1.model_validate(row["private_json"])
        if not isinstance(public.content, LearningItemSqlContentV2):
            raise TypeError("SQL public content is not v2")
        if not isinstance(private.content, LearningItemSqlPrivateV2):
            raise TypeError("SQL private content is not v2")
        if (
            str(row["publication_state"]) != "published"
            or _positive_int(row.get("publication_state_version"))
            != _positive_int(row.get("owner_version"))
            or public.public_hash != str(row["public_hash"])
            or private.private_hash != str(row["private_hash"])
            or presentation.exercise_version_id != str(row["exercise_version_id"])
            or presentation.tables != public.content.tables
            or presentation.max_rows != public.content.max_rows
        ):
            raise TypeError("SQL workspace authority identity is stale")
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        conn.rollback()
        raise ArtifactOwnerVersionConflict(
            "stored SQL workspace authority is invalid"
        ) from exc
    query = str(row["content_text"])
    cases = [
        {
            "id": item.id,
            "case_type": item.case_type,
            "dataset": item.dataset.model_dump(mode="json"),
            "expected_output": item.expected_output.model_dump(mode="json"),
            "weight": item.weight,
            "is_critical": item.is_critical,
            "order_index": item.order_index,
        }
        for item in private.content.tests
    ]
    conn.rollback()
    run_result = execute_sql_workspace_query(
        query,
        cases,
        schema=[item.model_dump(mode="json") for item in public.content.tables],
        public_dataset=public.content.public_dataset.model_dump(mode="json"),
        comparison=public.content.comparison,
        max_rows=public.content.max_rows,
    )
    safe_result = sql_execution_result_to_safe_result(run_result)
    with conn.transaction():
        locked = conn.execute(
            """
            SELECT results.result_hash
            FROM tutor_exercise_attempts AS attempts
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id=attempts.id
            WHERE attempts.id=%s AND attempts.user_id=%s
            FOR UPDATE OF attempts
            """,
            (attempt_id, user_id),
        ).fetchone()
        if locked is None:
            raise ArtifactOwnerVersionConflict("SQL workspace Attempt disappeared")
        if locked.get("result_hash") is not None:
            return
        # The immutable ExerciseVersion is the canonical capability authority.
        capability_row = conn.execute(
            """
            SELECT required_capabilities_json
            FROM tutor_exercise_versions WHERE id=%s AND validation_status='ready'
            """,
            (presentation.exercise_version_id,),
        ).fetchone()
        raw_capabilities = (
            capability_row.get("required_capabilities_json")
            if capability_row is not None
            else None
        )
        if not isinstance(raw_capabilities, list):
            raise ArtifactOwnerVersionConflict(
                "SQL workspace ExerciseVersion capabilities are unavailable"
            )
        scored = score_execution_result(
            safe_result,
            required_capabilities=tuple(str(item) for item in raw_capabilities),
            now=datetime.now(UTC),
        )
        try:
            PostgresExerciseGateRepository(conn).finalize_gate_attempt(
                user_id=user_id,
                attempt_id=attempt_id,
                result=scored,
                now=scored.terminal_at,
            )
        except PracticeRepositoryError as exc:
            raise ArtifactOwnerVersionConflict(
                "SQL workspace Attempt could not be finalized"
            ) from exc


def _load_authority(
    conn: Connection[dict[str, object]],
    *,
    artifact: TutorPublicArtifactItem,
) -> _SqlWorkspaceAuthority:
    row = conn.execute(
        """
        SELECT artifacts.user_id,artifacts.track_version,artifacts.progress_version,
               artifacts.assignment_version,
               sessions.lesson_assignment_id,
               assignments.document_id,
               active_plan.revision_id AS plan_revision_id,
               versions.public_hash,versions.private_hash,versions.content_hash,versions.handle,
               public.public_json,private.private_json,
               materializations.exercise_version_id,materializations.item_handle,
               materializations.content_hash AS materialization_content_hash,
               publication.state AS publication_state,
               publication.state_version AS publication_state_version
        FROM tutor_learning_artifacts AS artifacts
        JOIN tutor_teaching_sessions AS sessions
          ON sessions.id=artifacts.teaching_session_id
         AND sessions.user_id=artifacts.user_id
         AND sessions.conversation_id=artifacts.conversation_id
         AND sessions.track_id=artifacts.learning_track_id
         AND sessions.knowledge_key=artifacts.knowledge_key
        JOIN tutor_lesson_assignments AS assignments
          ON assignments.id=sessions.lesson_assignment_id
         AND assignments.user_id=artifacts.user_id
         AND assignments.track_id=artifacts.learning_track_id
         AND assignments.knowledge_key=artifacts.knowledge_key
        JOIN tutor_track_active_plans AS active_plan
          ON active_plan.track_id=artifacts.learning_track_id
         AND active_plan.user_id=artifacts.user_id
        JOIN tutor_learning_item_versions AS versions ON versions.id=artifacts.owner_id
        JOIN tutor_learning_item_public_contents AS public ON public.version_id=versions.id
        JOIN tutor_learning_item_private_contents AS private ON private.version_id=versions.id
        JOIN tutor_learning_item_practice_materializations AS materializations
          ON materializations.version_id=versions.id
        JOIN LATERAL (
          SELECT state,state_version
          FROM tutor_learning_item_publication_events AS events
          WHERE events.version_id=versions.id
          ORDER BY state_version DESC LIMIT 1
        ) AS publication ON true
        WHERE artifacts.id=%s AND artifacts.owner_kind='learning_item'
          AND artifacts.owner_id=%s AND artifacts.artifact_kind='sql_workspace'
        """,
        (artifact.id, artifact.owner_id),
    ).fetchone()
    if row is None:
        raise ArtifactOwnerVersionConflict("SQL workspace Learning Item authority is stale")
    try:
        public = LearningItemPublicV1.model_validate(row["public_json"])
        private = LearningItemPrivateV1.model_validate(row["private_json"])
        presentation = artifact.presentation
        if not isinstance(public.content, LearningItemSqlContentV2):
            raise TypeError("SQL public content is not v2")
        if not isinstance(private.content, LearningItemSqlPrivateV2):
            raise TypeError("SQL private content is not v2")
        if not isinstance(presentation, TutorArtifactSqlWorkspacePresentationV2):
            raise TypeError("SQL Artifact presentation is not v2")
        exercise_version_id = str(row["exercise_version_id"])
        if (
            str(row["publication_state"]) != "published"
            or _positive_int(row.get("publication_state_version"))
            != artifact.owner_version
            or public.public_hash != str(row["public_hash"])
            or private.private_hash != str(row["private_hash"])
            or str(row["item_handle"]) != str(row["handle"])
            or str(row["materialization_content_hash"]) != str(row["content_hash"])
            or presentation.exercise_version_id != exercise_version_id
            or presentation.tables != public.content.tables
            or presentation.max_rows != public.content.max_rows
        ):
            raise TypeError("SQL workspace authority identity is stale")
        return _SqlWorkspaceAuthority(
            user_id=str(row["user_id"]),
            plan_revision_id=str(row["plan_revision_id"]),
            lesson_assignment_id=str(row["lesson_assignment_id"]),
            document_id=str(row["document_id"]),
            track_version=_positive_int(row.get("track_version")),
            progress_version=_positive_int(row.get("progress_version")),
            assignment_version=_positive_int(row.get("assignment_version")),
            exercise_version_id=exercise_version_id,
            public=public,
            private=private.content,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ArtifactOwnerVersionConflict(
            "stored SQL workspace authority is invalid"
        ) from exc


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("expected a positive integer")
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("expected a positive integer") from exc
    if parsed < 1:
        raise ValueError("expected a positive integer")
    return parsed


def _attempt_idempotency_key(artifact_id: str, client_action_id: str) -> str:
    return f"sql-run:{artifact_id}:{canonical_hash(client_action_id)[:32]}"


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return normalized.isoformat()
    return str(value)


__all__ = (
    "SQL_WORKSPACE_RUN_POLICY_VERSION",
    "admit_sql_workspace_run",
    "observe_sql_workspace_attempt",
)
