"""Atomic projection of terminal execution Attempts into learner-safe Artifacts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from psycopg import Connection

from app.core.config import get_settings
from app.services.learning.artifacts.contracts import (
    TutorArtifactAttemptSummaryV1,
    TutorArtifactCreate,
    TutorArtifactKind,
    TutorArtifactPurpose,
    TutorArtifactSourceReferenceV1,
    TutorArtifactState,
    TutorArtifactTestResultPresentationV1,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.owner_adapters import ArtifactMutation
from app.services.learning.artifacts.repository import (
    ArtifactOwnerEventKind,
    ExecutionResultProjectionSource,
    LearningArtifactProjectionError,
    LearningArtifactStateConflict,
    LearningArtifactWriteResult,
    PostgresLearningArtifactRepository,
)
from app.services.learning.artifacts.service import LearningArtifactService
from aearn_shared.execution import SafeExecutionLocationV1, SafeExecutionResultV2


_RESULT_CREATION_KEY_PREFIX = "execution-result"
_RESULT_EVENT_KEY_PREFIX = "execution-result"
_MAX_SUMMARY_FAILURES = 8


@dataclass(frozen=True, slots=True)
class ExecutionResultArtifactProjection:
    source_artifact: LearningArtifactWriteResult
    result_artifact: LearningArtifactWriteResult


class ExecutionResultArtifactProjector:
    """Project exactly one terminal Attempt without owning scoring or progress."""

    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        repository: PostgresLearningArtifactRepository | None = None,
        enabled: Callable[[], bool] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = conn
        self._clock = clock or (lambda: datetime.now(UTC))
        if repository is None:
            repository = PostgresLearningArtifactRepository(
                conn,
                conversation_events=PostgresTutorArtifactConversationEventSink(conn),
            )
        self._repository = repository
        self._artifacts = LearningArtifactService(
            conn,
            repository=repository,
            enabled=enabled
            or (lambda: get_settings().tutor_learning_artifacts_enabled),
            clock=self._clock,
        )

    def project(
        self,
        *,
        user_id: str,
        conversation_id: str,
        source_artifact_id: str,
        attempt_id: str,
    ) -> ExecutionResultArtifactProjection:
        """Update the source Artifact and create one immutable result Artifact.

        Nested ``Connection.transaction()`` calls are savepoints when the caller
        already owns a transaction, so both writes remain part of that caller-owned
        commit and roll back together.
        """

        event_key = f"{_RESULT_EVENT_KEY_PREFIX}:{attempt_id}"
        with self._conn.transaction():
            source = self._repository.read_execution_result_projection_source(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=source_artifact_id,
                attempt_id=attempt_id,
            )
            if source.artifact.artifact_kind is TutorArtifactKind.TEST_RESULT:
                raise LearningArtifactStateConflict(
                    "a test-result Artifact cannot be its own execution source"
                )
            attempt_result = source.attempt.result
            if attempt_result is None:  # Defensive after the repository terminal gate.
                raise LearningArtifactStateConflict(
                    "execution result projection requires a terminal Attempt"
                )
            terminal_pass = attempt_result.outcome == "passed"
            attempt_summary = _attempt_summary(source)
            current_attempt = source.artifact.active_attempt
            projects_latest_attempt = (
                current_attempt is None
                or current_attempt.attempt_id == attempt_summary.attempt_id
                or _attempt_is_newer(attempt_summary, current_attempt)
            )
            projected_state = (
                TutorArtifactState.COMPLETED
                if projects_latest_attempt and terminal_pass
                else TutorArtifactState.ACTIVE
                if projects_latest_attempt
                else source.artifact.state
            )
            projected_attempt = (
                attempt_summary if projects_latest_attempt else current_attempt
            )
            if projected_attempt is None:
                raise LearningArtifactProjectionError(
                    "execution result projection lost the current Attempt authority"
                )
            event_kind: ArtifactOwnerEventKind = (
                "terminal"
                if terminal_pass and projects_latest_attempt
                else "attempt_linked"
            )
            owner_result = {
                "attempt_id": source.attempt.attempt_id,
                "outcome": attempt_result.outcome,
                "score": attempt_result.score,
                "result_hash": attempt_result.result_hash,
            }
            existing_source = self._repository.read_owner_update_result(
                user_id=user_id,
                conversation_id=conversation_id,
                artifact_id=source_artifact_id,
                event_key=event_key,
                event_kind=event_kind,
                expected_owner_result=owner_result,
            )
            existing_result = self._repository.read_result_artifact_for_attempt(
                user_id=user_id,
                conversation_id=conversation_id,
                source_artifact_id=source_artifact_id,
                attempt_id=attempt_id,
                result_hash=attempt_result.result_hash,
            )
            if (existing_source is None) != (existing_result is None):
                raise LearningArtifactProjectionError(
                    "execution result Artifact projection is only partially persisted"
                )
            if existing_source is not None and existing_result is not None:
                source_reference = next(
                    (
                        reference
                        for reference in existing_result.artifact.source_references
                        if reference.kind == "artifact"
                        and reference.reference_id == source.artifact.id
                    ),
                    None,
                )
                if (
                    source_reference is None
                    or source_reference.reference_version
                    != existing_source.artifact_event_sequence
                ):
                    raise LearningArtifactProjectionError(
                        "result Artifact source version differs from its source event"
                    )
                response_source = existing_source
                if (
                    response_source.artifact.version
                    != response_source.artifact_event_sequence
                ):
                    response_source = self._repository.read_current_artifact_write(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        artifact_id=source_artifact_id,
                    )
                return ExecutionResultArtifactProjection(
                    source_artifact=response_source,
                    result_artifact=existing_result,
                )

            if not projects_latest_attempt and source.artifact.state.terminal:
                raise LearningArtifactProjectionError(
                    "an older unprojected Attempt cannot mutate a terminal source Artifact"
                )
            source_write = self._artifacts.apply_owner_update(
                artifact_id=source.artifact.id,
                user_id=user_id,
                conversation_id=conversation_id,
                learning_track_id=source.artifact.learning_track_id,
                teaching_session_id=source.artifact.teaching_session_id,
                expected_artifact_version=source.artifact.version,
                event_key=event_key,
                event_kind=event_kind,
                mutation=ArtifactMutation(
                    state=projected_state,
                    owner_version=source.artifact.owner_version,
                    owner_context_version=source.owner_context_version,
                    presentation=source.artifact.presentation,
                    allowed_actions=(
                        ()
                        if projects_latest_attempt and terminal_pass
                        else source.artifact.allowed_actions
                    ),
                    active_attempt=projected_attempt,
                    safe_event_payload=owner_result,
                ),
            )
            summary = build_execution_result_summary(
                outcome=attempt_result.outcome,
                execution_result=attempt_result.execution_result,
            )
            execution_result = attempt_result.execution_result
            result_write = self._artifacts.create_artifact(
                TutorArtifactCreate(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    turn_id=None,
                    learning_track_id=source.artifact.learning_track_id,
                    knowledge_key=source.artifact.knowledge_key,
                    teaching_session_id=source.artifact.teaching_session_id,
                    checkpoint_id=source.artifact.checkpoint_id,
                    track_version=source.track_version,
                    progress_version=source.progress_version,
                    assignment_version=source.assignment_version,
                    owner_kind=source.artifact.owner_kind,
                    owner_id=source.artifact.owner_id,
                    owner_version=source.artifact.owner_version,
                    owner_context_version=source.owner_context_version,
                    artifact_kind=TutorArtifactKind.TEST_RESULT,
                    purpose=TutorArtifactPurpose.RESULT,
                    state=TutorArtifactState.COMPLETED,
                    blocking=False,
                    title="测试结果",
                    instruction_markdown=summary,
                    difficulty=source.artifact.difficulty,
                    presentation=TutorArtifactTestResultPresentationV1(
                        attempt_id=source.attempt.attempt_id,
                        status="terminal",
                        outcome=attempt_result.outcome,
                        passed_count=(
                            execution_result.passed_test_count
                            if execution_result is not None
                            else 0
                        ),
                        total_count=(
                            execution_result.total_test_count
                            if execution_result is not None
                            else 0
                        ),
                        summary_markdown=summary,
                        result_hash=attempt_result.result_hash,
                    ),
                    allowed_actions=(),
                    source_references=(
                        TutorArtifactSourceReferenceV1(
                            kind="artifact",
                            reference_id=source.artifact.id,
                            reference_version=source_write.artifact.version,
                            label="Source Artifact",
                        ),
                        TutorArtifactSourceReferenceV1(
                            kind="attempt_result",
                            reference_id=source.attempt.attempt_id,
                            content_hash=attempt_result.result_hash,
                            label="Authoritative Attempt result",
                        ),
                    ),
                    active_attempt=attempt_summary,
                ),
                creation_key=f"{_RESULT_CREATION_KEY_PREFIX}:{attempt_id}",
                publish_item=False,
            )
            return ExecutionResultArtifactProjection(
                source_artifact=source_write,
                result_artifact=result_write,
            )


def build_execution_result_summary(
    *,
    outcome: str,
    execution_result: SafeExecutionResultV2 | None,
) -> str:
    """Build bounded deterministic Markdown with failures before pass aggregation."""

    if outcome == "passed":
        if execution_result is None or execution_result.total_test_count == 0:
            return "**通过**：本次运行已完成。"
        return (
            f"**通过**：{execution_result.passed_test_count}/"
            f"{execution_result.total_test_count} 项测试通过。"
        )

    heading = {
        "failed": "**未通过**：请修改原工件后再次运行。",
        "timed_out": "**运行超时**：请修改原工件后再次运行。",
        "cancelled": "**运行已取消**：原工件仍可继续修改。",
        "unavailable": "**运行暂不可用**：结果已保留，可稍后重试。",
        "invalid": "**结果无效**：请返回原工件检查输入。",
    }.get(outcome, "**未通过**：请返回原工件继续修改。")
    if execution_result is None:
        return heading

    failed = [item for item in execution_result.test_feedback if not item.passed]
    lines = [heading]
    for item in failed[:_MAX_SUMMARY_FAILURES]:
        message = item.message or "测试未通过。"
        location = _location_markdown(item.location)
        lines.append(f"- {message}{location}")
    omitted_failures = len(failed) - _MAX_SUMMARY_FAILURES
    if omitted_failures > 0:
        lines.append(f"- 另有 {omitted_failures} 项未通过。")
    if execution_result.passed_test_count > 0:
        lines.append(f"- 其他 {execution_result.passed_test_count} 项通过。")
    return "\n".join(lines)


def _attempt_summary(
    source: ExecutionResultProjectionSource,
) -> TutorArtifactAttemptSummaryV1:
    result = source.attempt.result
    if result is None:
        raise LearningArtifactStateConflict(
            "execution result projection requires a terminal Attempt"
        )
    return TutorArtifactAttemptSummaryV1(
        attempt_id=source.attempt.attempt_id,
        attempt_type=source.attempt.attempt_type,
        status="terminal",
        outcome=result.outcome,
        score=result.score,
        result_hash=result.result_hash,
        accepted_at=source.attempt.accepted_at,
        terminal_at=result.terminal_at,
    )


def _attempt_is_newer(
    candidate: TutorArtifactAttemptSummaryV1,
    current: TutorArtifactAttemptSummaryV1,
) -> bool:
    """Order multiple Runs by server acceptance time with a stable identity tie-break."""

    try:
        candidate_at = datetime.fromisoformat(candidate.accepted_at.replace("Z", "+00:00"))
        current_at = datetime.fromisoformat(current.accepted_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LearningArtifactProjectionError(
            "execution Attempt acceptance time is invalid"
        ) from exc
    candidate_at = (
        candidate_at.replace(tzinfo=UTC)
        if candidate_at.tzinfo is None
        else candidate_at.astimezone(UTC)
    )
    current_at = (
        current_at.replace(tzinfo=UTC)
        if current_at.tzinfo is None
        else current_at.astimezone(UTC)
    )
    return (candidate_at, candidate.attempt_id) > (current_at, current.attempt_id)


def _location_markdown(location: SafeExecutionLocationV1 | None) -> str:
    if location is None:
        return ""
    if location.column is None:
        return f"（第 {location.line} 行）"
    return f"（第 {location.line} 行，第 {location.column} 列）"


__all__ = (
    "ExecutionResultArtifactProjection",
    "ExecutionResultArtifactProjector",
    "build_execution_result_summary",
)
