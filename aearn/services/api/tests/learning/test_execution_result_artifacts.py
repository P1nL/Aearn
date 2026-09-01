from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
import pytest
from pydantic import ValidationError

from aearn_shared.execution import (
    SafeExecutionLocationV1,
    SafeExecutionPresentationNoneV1,
    SafeExecutionResultV1,
    SafeExecutionResultV2,
    SafeExecutionStatus,
    SafeTableResultPresentationV1,
    SafeTestFeedbackV2,
)
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.artifacts.contracts import (
    TutorArtifactAttemptDetailV1,
    TutorArtifactAttemptDetailV2,
    TutorArtifactAttemptResultV2,
)
from app.services.learning.artifacts.execution_results import (
    ExecutionResultArtifactProjector,
    build_execution_result_summary,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactProjectionError,
    PostgresLearningArtifactRepository,
)
from app.services.learning.practice.policies import score_execution_result
from app.services.tutor.execution import (
    ExecutionIntentRepository,
    ExecutionSubmissionError,
)
from app.services.repositories.local_user_data_repository import reset_user_data
from tests.support.teaching_session_support import database_available
from tests.tutor.test_tutor_learning_artifact_routes import (
    _seed_artifact_route_fixture,
)


_NOW = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)


def _table_result() -> SafeExecutionResultV2:
    return SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=SafeExecutionStatus.SUCCESS,
        stdout="2 rows",
        test_feedback=(
            SafeTestFeedbackV2(
                case_id="visible-query",
                passed=True,
                visible=True,
                message="查询结果正确。",
            ),
        ),
        passed_test_count=1,
        total_test_count=1,
        diagnostic_code="query_complete",
        presentation=SafeTableResultPresentationV1(
            columns=("name", "score"),
            rows=(("Ada", 1), ("Lin", 2)),
        ),
    )


def _failed_result() -> SafeExecutionResultV2:
    return SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=SafeExecutionStatus.SUCCESS,
        test_feedback=(
            SafeTestFeedbackV2(
                case_id="visible-output",
                passed=False,
                visible=True,
                message="输出值不正确。",
                location=SafeExecutionLocationV1(line=7, column=3),
            ),
            SafeTestFeedbackV2(
                case_id="non-visible-1",
                passed=True,
                visible=False,
                message="A non-visible scenario passed.",
            ),
        ),
        passed_test_count=2,
        total_test_count=3,
        diagnostic_code="tests_complete",
        presentation=SafeExecutionPresentationNoneV1(),
    )


def test_scoring_persists_the_exact_strict_v2_execution_result() -> None:
    execution = _table_result()

    scored = score_execution_result(
        execution,
        required_capabilities=("sql.query",),
    )

    assert scored.safe_feedback == execution.model_dump(mode="json")
    assert scored.safe_feedback["schema_version"] == "safe-execution-result-v2"
    assert scored.safe_feedback["presentation"] == {
        "kind": "table_result_v1",
        "columns": ["name", "score"],
        "rows": [["Ada", 1], ["Lin", 2]],
    }
    assert "tests" not in scored.safe_feedback


class _SafeResultConnection:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def execute(self, *_args: object, **_kwargs: object) -> "_SafeResultConnection":
        return self

    def fetchone(self) -> dict[str, object]:
        return {"result_json": self._payload}


@pytest.mark.parametrize("version", ("v1", "v2"))
def test_execution_readers_parse_v1_and_v2_as_strict_v2(version: str) -> None:
    v1 = SafeExecutionResultV1(
        status=SafeExecutionStatus.SUCCESS,
        passed_test_count=1,
        total_test_count=1,
        diagnostic_code="completed",
    )
    payload = (
        v1.model_dump(mode="json")
        if version == "v1"
        else SafeExecutionResultV2.from_v1(v1).model_dump(mode="json")
    )
    repository = ExecutionIntentRepository(_SafeResultConnection(payload))  # type: ignore[arg-type]

    result = repository.read_safe_result(
        user_id="user-1",
        run_id="run-1",
        job_id="job-1",
    )

    assert result == SafeExecutionResultV2.from_v1(v1)
    assert result.schema_version == "safe-execution-result-v2"


def test_execution_reader_rejects_unknown_stored_result_version() -> None:
    repository = ExecutionIntentRepository(
        _SafeResultConnection(
            {
                "schema_version": "safe-execution-result-v3",
                "status": "success",
                "presentation": {"kind": "none"},
            }
        )
    )  # type: ignore[arg-type]

    with pytest.raises(ExecutionSubmissionError, match="stored_result_invalid"):
        repository.read_safe_result(
            user_id="user-1",
            run_id="run-1",
            job_id="job-1",
        )


def test_attempt_detail_v1_remains_available_for_historical_payloads() -> None:
    detail = TutorArtifactAttemptDetailV1(
        artifact_id="artifact-legacy",
        artifact_version=1,
        conversation_id="conversation-legacy",
        learning_track_id="track-legacy",
        knowledge_key="python.variables",
        teaching_session_id="session-legacy",
        attempt_id="attempt-legacy",
        attempt_type="run",
        exercise_version_id="exercise-legacy",
        submission_hash="a" * 64,
        independence="independent",
        assistance_kind="independent",
        status="terminal",
        accepted_at=_NOW.isoformat(),
        result={
            "outcome": "failed",
            "score": 0.5,
            "safe_feedback": {"message": "Legacy learner-safe feedback."},
            "capability_scores": {"python.variables": 0.5},
            "policy_version": "lesson_gate_pass_v1",
            "result_hash": "b" * 64,
            "terminal_at": _NOW.isoformat(),
        },
    )

    assert detail.schema_version == "tutor_learning_artifact_attempt_v1"
    assert detail.result is not None
    assert detail.result.safe_feedback == {"message": "Legacy learner-safe feedback."}


def test_attempt_detail_v2_has_only_the_typed_execution_result_seam() -> None:
    execution = _table_result()
    payload = {
        "artifact_id": "artifact-1",
        "artifact_version": 2,
        "conversation_id": "conversation-1",
        "learning_track_id": "track-1",
        "knowledge_key": "sql.select",
        "teaching_session_id": "session-1",
        "attempt_id": "attempt-1",
        "attempt_type": "run",
        "exercise_version_id": "exercise-1",
        "submission_hash": "a" * 64,
        "independence": "independent",
        "assistance_kind": "independent",
        "status": "terminal",
        "accepted_at": _NOW.isoformat(),
        "result": {
            "outcome": "passed",
            "score": 1.0,
            "execution_result": execution.model_dump(mode="json"),
            "capability_scores": {"sql.query": 1.0},
            "policy_version": "lesson_gate_pass_v1",
            "result_hash": "b" * 64,
            "terminal_at": _NOW.isoformat(),
        },
    }

    detail = TutorArtifactAttemptDetailV2.model_validate(payload)

    public = detail.model_dump(mode="json")
    assert public["schema_version"] == "tutor_learning_artifact_attempt_v2"
    assert public["result"]["execution_result"] == execution.model_dump(mode="json")
    assert "safe_feedback" not in public["result"]
    invalid_result = payload["result"]
    assert isinstance(invalid_result, dict)
    with pytest.raises(ValidationError):
        TutorArtifactAttemptResultV2.model_validate(
            invalid_result | {"safe_feedback": {"path": "/work/private.py"}}
        )


def test_result_summary_prioritizes_failures_and_uses_numeric_locations_only() -> None:
    summary = build_execution_result_summary(
        outcome="failed",
        execution_result=_failed_result(),
    )

    assert summary.splitlines() == [
        "**未通过**：请修改原工件后再次运行。",
        "- 输出值不正确。（第 7 行，第 3 列）",
        "- 其他 2 项通过。",
    ]
    assert "/work" not in summary
    assert "container" not in summary.casefold()


@pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)
def test_postgres_projector_is_atomic_idempotent_and_keeps_run_history() -> None:
    bootstrap_database()
    with connect() as conn:
        fixture = _seed_artifact_route_fixture(conn)
        _replace_attempt_result(
            conn,
            user_id=fixture.user_id,
            attempt_id=fixture.attempt_id,
            execution_result=_failed_result(),
            terminal_at=_NOW,
        )
        projector = ExecutionResultArtifactProjector(
            conn,
            enabled=lambda: True,
            clock=lambda: _NOW,
        )

        first = projector.project(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            source_artifact_id=fixture.artifact_id,
            attempt_id=fixture.attempt_id,
        )
        replay = projector.project(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            source_artifact_id=fixture.artifact_id,
            attempt_id=fixture.attempt_id,
        )

        assert first.source_artifact.artifact.state.value == "active"
        assert first.source_artifact.artifact.allowed_actions
        assert first.result_artifact.artifact.state.value == "completed"
        assert first.result_artifact.artifact.blocking is False
        assert replay.source_artifact.idempotent_replayed is True
        assert replay.result_artifact.idempotent_replayed is True
        detail = PostgresLearningArtifactRepository(conn).read_attempt_detail(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            artifact_id=fixture.artifact_id,
            attempt_id=fixture.attempt_id,
        )
        assert detail.schema_version == "tutor_learning_artifact_attempt_v2"
        assert detail.result is not None
        assert detail.result.execution_result == _failed_result()
        assert "safe_feedback" not in detail.model_dump(mode="json")["result"]

        second_attempt_id = _seed_second_terminal_attempt(
            conn,
            fixture=fixture,
            terminal_at=_NOW + timedelta(minutes=1),
        )
        second = projector.project(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            source_artifact_id=fixture.artifact_id,
            attempt_id=second_attempt_id,
        )
        older_replay = projector.project(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            source_artifact_id=fixture.artifact_id,
            attempt_id=fixture.attempt_id,
        )
        assert second.source_artifact.artifact.state.value == "completed"
        assert second.source_artifact.artifact.active_attempt is not None
        assert (
            second.source_artifact.artifact.active_attempt.attempt_id
            == second_attempt_id
        )
        assert older_replay.source_artifact.artifact.active_attempt is not None
        assert (
            older_replay.source_artifact.artifact.active_attempt.attempt_id
            == second_attempt_id
        )
        assert (
            older_replay.source_artifact.artifact.version
            == older_replay.source_artifact.artifact_event_sequence
        )
        result_rows = conn.execute(
            """
            SELECT active_attempt_id::text AS attempt_id
            FROM tutor_learning_artifacts
            WHERE user_id = %s AND artifact_kind = 'test_result'
            ORDER BY created_at, id
            """,
            (fixture.user_id,),
        ).fetchall()
        assert {str(row["attempt_id"]) for row in result_rows} == {
            fixture.attempt_id,
            second_attempt_id,
        }
        conn.commit()

    with connect() as cleanup:
        reset_user_data(cleanup, fixture.user_id)
        cleanup.commit()


@pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)
def test_postgres_projector_rejects_partial_source_only_persistence() -> None:
    bootstrap_database()
    with connect() as conn:
        fixture = _seed_artifact_route_fixture(conn)
        _replace_attempt_result(
            conn,
            user_id=fixture.user_id,
            attempt_id=fixture.attempt_id,
            execution_result=_failed_result(),
            terminal_at=_NOW,
        )
        projector = ExecutionResultArtifactProjector(
            conn,
            enabled=lambda: True,
            clock=lambda: _NOW,
        )
        projected = projector.project(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            source_artifact_id=fixture.artifact_id,
            attempt_id=fixture.attempt_id,
        )
        result_id = projected.result_artifact.artifact.id
        conn.execute(
            "SELECT set_config('aearn.learning_track_purge_user_id', %s, true)",
            (fixture.user_id,),
        )
        conn.execute(
            "DELETE FROM tutor_learning_artifact_references WHERE artifact_id = %s",
            (result_id,),
        )
        conn.execute(
            "DELETE FROM tutor_learning_artifact_attempt_links WHERE artifact_id = %s",
            (result_id,),
        )
        conn.execute(
            "DELETE FROM tutor_learning_artifact_events WHERE artifact_id = %s",
            (result_id,),
        )
        conn.execute(
            "DELETE FROM tutor_learning_artifacts WHERE id = %s",
            (result_id,),
        )

        with pytest.raises(
            LearningArtifactProjectionError,
            match="only partially persisted",
        ):
            projector.project(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                source_artifact_id=fixture.artifact_id,
                attempt_id=fixture.attempt_id,
            )
        conn.rollback()

    with connect() as cleanup:
        reset_user_data(cleanup, fixture.user_id)
        cleanup.commit()


def _replace_attempt_result(
    conn,  # type: ignore[no-untyped-def]
    *,
    user_id: str,
    attempt_id: str,
    execution_result: SafeExecutionResultV2,
    terminal_at: datetime,
) -> None:
    scored = score_execution_result(
        execution_result,
        required_capabilities=("python.variables",),
    )
    scored = type(scored)(
        outcome=scored.outcome,
        score=scored.score,
        safe_feedback=scored.safe_feedback,
        capability_scores=scored.capability_scores,
        policy_version=scored.policy_version,
        terminal_at=terminal_at,
        execution_receipt_hash=scored.execution_receipt_hash,
    )
    conn.execute(
        "SELECT set_config('aearn.learning_track_purge_user_id', %s, true)",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_exercise_attempt_results WHERE attempt_id = %s AND user_id = %s",
        (attempt_id, user_id),
    )
    conn.execute(
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
            scored.outcome.value,
            scored.score,
            json.dumps(scored.safe_feedback),
            json.dumps(scored.capability_scores),
            scored.execution_receipt_hash,
            scored.policy_version,
            scored.result_hash,
            terminal_at,
        ),
    )


def _seed_second_terminal_attempt(
    conn,  # type: ignore[no-untyped-def]
    *,
    fixture,  # type: ignore[no-untyped-def]
    terminal_at: datetime,
) -> str:
    source_attempt = conn.execute(
        """
        SELECT attempts.*, submissions.submission_kind
        FROM tutor_exercise_attempts AS attempts
        JOIN tutor_exercise_attempt_submissions AS submissions
          ON submissions.attempt_id = attempts.id
        WHERE attempts.id = %s AND attempts.user_id = %s
        """,
        (fixture.attempt_id, fixture.user_id),
    ).fetchone()
    assert source_attempt is not None
    attempt = conn.execute(
        """
        INSERT INTO tutor_exercise_attempts (
          attempt_type, user_id, track_id, plan_revision_id, expected_track_version,
          expected_progress_version, knowledge_key, lesson_assignment_id, document_id,
          gate_binding_id, exercise_version_id, submission_hash, hint_state_hash,
          independence, idempotency_key, request_hash, accepted_at
        ) VALUES (
          'run', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, 'independent', %s, %s, %s
        ) RETURNING id
        """,
        (
            fixture.user_id,
            source_attempt["track_id"],
            source_attempt["plan_revision_id"],
            source_attempt["expected_track_version"],
            source_attempt["expected_progress_version"],
            source_attempt["knowledge_key"],
            source_attempt["lesson_assignment_id"],
            source_attempt["document_id"],
            source_attempt["gate_binding_id"],
            source_attempt["exercise_version_id"],
            "c" * 64,
            "d" * 64,
            f"execution-result-second:{fixture.attempt_id}",
            "e" * 64,
            terminal_at,
        ),
    ).fetchone()
    assert attempt is not None
    attempt_id = str(attempt["id"])
    conn.execute(
        """
        INSERT INTO tutor_exercise_attempt_submissions (
          attempt_id, user_id, exercise_version_id, submission_kind,
          content_text, content_hash
        ) VALUES (%s, %s, %s, %s, 'print(2)', %s)
        """,
        (
            attempt_id,
            fixture.user_id,
            source_attempt["exercise_version_id"],
            source_attempt["submission_kind"],
            "c" * 64,
        ),
    )
    passed = SafeExecutionResultV2(
        schema_version="safe-execution-result-v2",
        status=SafeExecutionStatus.SUCCESS,
        test_feedback=(
            SafeTestFeedbackV2(
                case_id="visible-output",
                passed=True,
                visible=True,
                message="输出正确。",
            ),
        ),
        passed_test_count=1,
        total_test_count=1,
        diagnostic_code="tests_complete",
        presentation=SafeExecutionPresentationNoneV1(),
    )
    scored = score_execution_result(
        passed,
        required_capabilities=("python.variables",),
    )
    scored = type(scored)(
        outcome=scored.outcome,
        score=scored.score,
        safe_feedback=scored.safe_feedback,
        capability_scores=scored.capability_scores,
        policy_version=scored.policy_version,
        terminal_at=terminal_at,
        execution_receipt_hash=scored.execution_receipt_hash,
    )
    conn.execute(
        """
        INSERT INTO tutor_exercise_attempt_results (
          attempt_id, user_id, outcome, score, safe_feedback_json,
          capability_scores_json, execution_receipt_hash, policy_version,
          result_hash, terminal_at
        ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
        """,
        (
            attempt_id,
            fixture.user_id,
            scored.outcome.value,
            scored.score,
            json.dumps(scored.safe_feedback),
            json.dumps(scored.capability_scores),
            scored.execution_receipt_hash,
            scored.policy_version,
            scored.result_hash,
            terminal_at,
        ),
    )
    conn.execute(
        """
        INSERT INTO tutor_learning_artifact_attempt_links (
          artifact_id, user_id, conversation_id, teaching_session_id,
          learning_track_id, attempt_id, artifact_version, created_at
        )
        SELECT id, user_id, conversation_id, teaching_session_id,
               learning_track_id, %s, version, %s
        FROM tutor_learning_artifacts
        WHERE id = %s
        """,
        (attempt_id, terminal_at, fixture.artifact_id),
    )
    return attempt_id
