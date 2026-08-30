"""Verified-only orchestration for track-scoped ReviewSession."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection

from aearn_shared.execution import ExecutionAction, SafeExecutionResultV1
from app.services.learning.contracts import ExecutionComposition, ExecutionTier
from app.services.learning.execution_tiers import ExecutionTierInputs, ExecutionTierResolver
from app.services.learning.teaching_events import TeachingDomainEventAdapter
from app.services.learning.practice.contracts import ExerciseAttemptType, ExerciseType
from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV1,
    ModelReviewAssistanceKind,
    ModelReviewRubricV1,
    parse_model_review_submission,
)
from app.services.learning.practice.model_review_scoring import evaluate_model_code_review
from app.services.learning.practice.policies import evaluate_static_reasoning, score_execution_result
from app.services.learning.reviews.contracts import ReviewCandidate
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
    iso,
    string_list,
)
from app.services.learning.reviews.schedule_repository import PostgresReviewScheduleRepository
from app.services.learning.reviews.session_repository import PostgresReviewSessionRepository
from app.services.runners.language_capabilities import require_language_capability
from app.services.tutor.execution import (
    ExecutionIntentRepository,
    ExecutionSubmissionError,
    default_runtime_registry,
)


LocalExerciseRunner = Callable[[Mapping[str, object], str], SafeExecutionResultV1]
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class ReviewServiceError(ValueError):
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


class _ExecutorAvailability:
    def __init__(self, repository: ExecutionIntentRepository) -> None:
        self._repository = repository

    def is_runtime_available(self, runtime_id: str) -> bool:
        return self._repository.availability_for_runtime(runtime_id).available


class ReviewService:
    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        composition: ExecutionComposition = ExecutionComposition.PUBLIC,
        local_runner_available: bool = False,
        local_runner: LocalExerciseRunner | None = None,
        execution_repository: ExecutionIntentRepository | None = None,
    ) -> None:
        self._conn = conn
        self._schedules = PostgresReviewScheduleRepository(conn)
        self._sessions = PostgresReviewSessionRepository(conn)
        self._execution = execution_repository or ExecutionIntentRepository(conn)
        self._composition = composition
        self._local_runner_available = local_runner_available
        self._local_runner = local_runner
        self._tier_resolver = ExecutionTierResolver()
        self._teaching_events = TeachingDomainEventAdapter(conn)

    def read_queue(self, *, user_id: str, track_id: str) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        try:
            return self._project_queue(
                self._schedules.read_queue(user_id=user, track_id=track, now=datetime.now(UTC))
            )
        except ReviewRepositoryError as exc:
            raise _map_error(exc) from exc

    def create_session(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        expected_track_version: int,
        expected_schedule_version: int,
        max_items: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        key = _stable_key(knowledge_key, "knowledge_key")
        request = {
            "track_id": track,
            "knowledge_key": key,
            "expected_track_version": expected_track_version,
            "expected_schedule_version": expected_schedule_version,
            "max_items": max_items,
        }
        try:
            with self._conn.transaction():
                candidates = self._candidates(user_id=user, track_id=track, knowledge_key=key)
                row = self._sessions.create_or_retry_session(
                    user_id=user,
                    track_id=track,
                    knowledge_key=key,
                    expected_track_version=expected_track_version,
                    expected_schedule_version=expected_schedule_version,
                    max_items=max_items,
                    idempotency_key=_idempotency(idempotency_key),
                    request_hash=content_hash(request),
                    now=datetime.now(UTC),
                    candidates=candidates,
                )
                return self._project_session(row)
        except (ReviewRepositoryError, ExecutionSubmissionError) as exc:
            raise _map_error(exc) from exc

    def read_session(self, *, user_id: str, track_id: str, session_id: str) -> dict[str, object]:
        try:
            row = self._sessions.read_session(
                user_id=_uuid(user_id, "user_id"),
                track_id=_uuid(track_id, "track_id"),
                session_id=_uuid(session_id, "session_id"),
            )
            return self._project_session(row)
        except ReviewRepositoryError as exc:
            raise _map_error(exc) from exc

    def warmup(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        response_kind: str,
        confidence: str | None,
        expected_session_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, session = _ids(user_id, track_id, session_id)
        if response_kind not in {"answered", "skipped"}:
            raise ReviewServiceError("VALIDATION_ERROR", "response_kind 必须是 answered 或 skipped。", status_code=422)
        if response_kind == "answered" and confidence not in {"low", "medium", "high"}:
            raise ReviewServiceError("VALIDATION_ERROR", "answered warmup 需要有效 confidence。", status_code=422)
        summary = {"confidence": confidence} if response_kind == "answered" else {"skipped": True}
        request = {
            "session_id": session,
            "response_kind": response_kind,
            "response_summary": summary,
            "expected_session_version": expected_session_version,
        }
        try:
            with self._conn.transaction():
                row = self._sessions.record_warmup(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                    response_kind=response_kind,
                    response_summary=summary,
                    expected_session_version=expected_session_version,
                    idempotency_key=_idempotency(idempotency_key),
                    request_hash=content_hash(request),
                )
                return self._project_session(row)
        except ReviewRepositoryError as exc:
            raise _map_error(exc) from exc

    def hint(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        item_id: str,
        hint_level: int,
        expected_session_version: int,
        expected_item_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, session = _ids(user_id, track_id, session_id)
        item = _uuid(item_id, "item_id")
        safe_hint = {
            "hint_level": hint_level,
            "message": {
                1: "先回忆这个知识点的最小规则，并写出一个反例。",
                2: "把题目拆成输入、约束和预期输出，逐项核对。",
                3: "先给出最小可验证答案，再解释为何满足核心能力。",
            }[hint_level],
            "reveals_answer": False,
        }
        request = {
            "session_id": session,
            "item_id": item,
            "hint_level": hint_level,
            "expected_session_version": expected_session_version,
            "expected_item_version": expected_item_version,
        }
        try:
            with self._conn.transaction():
                row = self._sessions.record_hint(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                    item_id=item,
                    hint_level=hint_level,
                    expected_session_version=expected_session_version,
                    expected_item_version=expected_item_version,
                    safe_hint=safe_hint,
                    idempotency_key=_idempotency(idempotency_key),
                    request_hash=content_hash(request),
                )
                return {
                    "hint_id": str(row["id"]),
                    "hint_level": as_int(row["hint_level"]),
                    "safe_hint": as_mapping(row.get("safe_hint_json")),
                    "created_at": iso(row.get("created_at")),
                }
        except (KeyError, ReviewRepositoryError) as exc:
            if isinstance(exc, KeyError):
                raise ReviewServiceError("VALIDATION_ERROR", "hint_level 必须在 1..3。", status_code=422) from exc
            raise _map_error(exc) from exc


    def attempt_item(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        item_id: str,
        submission: str | None,
        review_submission: Mapping[str, object] | None,
        expected_session_version: int,
        expected_item_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, session = _ids(user_id, track_id, session_id)
        item = _uuid(item_id, "item_id")
        try:
            with self._conn.transaction():
                session_row = self._sessions.read_session(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                )
                item_row = _find_item(session_row, item)
                exercise_type = str(item_row["exercise_type"])
                if exercise_type == ExerciseType.MODEL_CODE_REVIEW.value:
                    if submission is not None or review_submission is None:
                        raise ReviewServiceError(
                            "MODEL_REVIEW_SUBMISSION_INVALID",
                            "模型代码审核必须且只能提交结构化 review_submission。",
                            status_code=422,
                            recoverable=False,
                        )
                    artifact = ModelReviewArtifactV1.model_validate(
                        as_mapping(item_row.get("starter_artifact_json"))
                    )
                    parsed = parse_model_review_submission(review_submission)
                    parsed.validate_line_count(artifact.line_count)
                    normalized = parsed.canonical_json()
                else:
                    if submission is None or review_submission is not None:
                        raise ReviewServiceError(
                            "VALIDATION_ERROR",
                            "普通复习练习必须且只能提交 submission。",
                            status_code=422,
                            recoverable=False,
                        )
                    normalized = submission
                tier = self._execution_tier(item_row)
                if tier["execution_tier"] == ExecutionTier.STATIC_ONLY.value and bool(
                    item_row.get("execution_required")
                ):
                    raise ReviewServiceError(
                        "EXECUTION_UNAVAILABLE",
                        str(tier["execution_disclosure"]),
                        status_code=503,
                    )
                request = {
                    "session_id": session,
                    "item_id": item,
                    "submission_hash": content_hash(normalized),
                    "expected_session_version": expected_session_version,
                    "expected_item_version": expected_item_version,
                }
                attempt = self._sessions.create_attempt(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                    item_id=item,
                    submission=normalized,
                    expected_session_version=expected_session_version,
                    expected_item_version=expected_item_version,
                    idempotency_key=_idempotency(idempotency_key),
                    request_hash=content_hash(request),
                    now=datetime.now(UTC),
                )
                projected = self._dispatch_attempt(
                    attempt=attempt,
                    submission=normalized,
                    tier=tier,
                )
                projected["execution_tier"] = tier["execution_tier"]
                projected["execution_disclosure"] = tier["execution_disclosure"]
                return projected
        except ReviewServiceError:
            raise
        except (TypeError, ValueError) as exc:
            if isinstance(exc, ReviewRepositoryError):
                raise _map_error(exc) from exc
            raise ReviewServiceError(
                "MODEL_REVIEW_SUBMISSION_INVALID",
                "结构化代码审核不符合当前题目 contract。",
                status_code=422,
                recoverable=False,
            ) from exc
        except ExecutionSubmissionError as exc:
            raise _map_error(exc) from exc

    def read_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        user, track, session = _ids(user_id, track_id, session_id)
        attempt = _uuid(attempt_id, "attempt_id")
        try:
            with self._conn.transaction():
                row = self._sessions.read_attempt(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                    attempt_id=attempt,
                )
                if row.get("result_hash") is None and row.get("execution_job_id") is not None:
                    safe_result = self._execution.read_exercise_safe_result(
                        user_id=user,
                        attempt_id=attempt,
                    )
                    if safe_result is not None:
                        result = score_execution_result(
                            safe_result,
                            required_capabilities=string_list(
                                row.get("required_capabilities_json")
                            ),
                        )
                        row = self._sessions.finalize_attempt(
                            user_id=user,
                            track_id=track,
                            session_id=session,
                            attempt_id=attempt,
                            result=result,
                        )
                return self._project_attempt(row)
        except (ReviewRepositoryError, ExecutionSubmissionError) as exc:
            raise _map_error(exc) from exc

    def finalize_session(
        self,
        *,
        user_id: str,
        track_id: str,
        session_id: str,
        expected_session_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, session = _ids(user_id, track_id, session_id)
        request = {
            "session_id": session,
            "expected_session_version": expected_session_version,
        }
        try:
            with self._conn.transaction():
                row = self._sessions.finalize_session(
                    user_id=user,
                    track_id=track,
                    session_id=session,
                    expected_session_version=expected_session_version,
                    idempotency_key=_idempotency(idempotency_key),
                    request_hash=content_hash(request),
                    now=datetime.now(UTC),
                )
                finalization_id = row.get("finalization_id")
                if finalization_id is not None:
                    self._teaching_events.admit_review_terminal(
                        user_id=user, finalization_id=str(finalization_id),
                    )
                return self._project_session(row)
        except ReviewRepositoryError as exc:
            raise _map_error(exc) from exc

    def _candidates(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
    ) -> tuple[ReviewCandidate, ...]:
        selected: list[ReviewCandidate] = []
        for row in self._sessions.candidate_rows(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
        ):
            if str(row.get("source_kind")) == "registered_author":
                publication = self._conn.execute(
                    """SELECT 1 FROM tutor_model_review_publications
                    WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
                      AND exercise_version_id = %s""",
                    (user_id, track_id, knowledge_key, row["id"]),
                ).fetchone()
                if publication is None:
                    continue
            tier = self._execution_tier(row)
            if bool(row.get("execution_required")) and tier["execution_tier"] not in {
                ExecutionTier.CONTAINER_VERIFIED.value,
                ExecutionTier.TEACHING_LOCAL.value,
            }:
                continue
            if not bool(row.get("execution_required")) and tier["execution_tier"] == ExecutionTier.UNAVAILABLE.value:
                continue
            selected.append(
                ReviewCandidate(
                    exercise_version_id=str(row["id"]),
                    exercise_type=str(row["exercise_type"]),
                    title=str(row["title"]),
                    learner_prompt=as_mapping(row.get("learner_prompt_json")),
                    starter_artifact=as_mapping(row.get("starter_artifact_json")),
                    required_capabilities=tuple(
                        string_list(row.get("required_capabilities_json"))
                    ),
                    runtime_profile_key=str(row["runtime_profile_key"])
                    if row.get("runtime_profile_key")
                    else None,
                    execution_required=bool(row.get("execution_required")),
                    content_hash=str(row["content_hash"]),
                )
            )
        return tuple(selected)

    def _dispatch_attempt(
        self,
        *,
        attempt: Mapping[str, object],
        submission: str,
        tier: Mapping[str, object],
    ) -> dict[str, object]:
        if bool(attempt.get("idempotent_replayed")):
            stored = self._sessions.read_attempt(
                user_id=str(attempt["user_id"]),
                track_id=str(attempt["track_id"]),
                session_id=str(attempt["review_session_id"]),
                attempt_id=str(attempt["id"]),
            )
            if stored.get("result_hash") is not None or stored.get("execution_job_id") is not None:
                return self._project_attempt(stored)
        if tier["execution_tier"] == ExecutionTier.STATIC_ONLY.value:
            result = self._static_result(attempt=attempt, submission=submission)
            return self._project_attempt(
                self._sessions.finalize_attempt(
                    user_id=str(attempt["user_id"]),
                    track_id=str(attempt["track_id"]),
                    session_id=str(attempt["review_session_id"]),
                    attempt_id=str(attempt["id"]),
                    result=result,
                )
            )
        if tier["execution_tier"] == ExecutionTier.CONTAINER_VERIFIED.value:
            job = self._execution.create_or_replay_exercise_job(
                user_id=str(attempt["user_id"]),
                attempt_id=str(attempt["id"]),
                submission_id=str(attempt["submission_id"]),
                exercise_version_id=str(attempt["exercise_version_id"]),
                action=ExecutionAction.TEST,
            )
            response = self._project_attempt(attempt)
            response.update(
                status="pending",
                execution_job_id=job.job_id,
                execution_job_state=job.state.value,
            )
            return response
        if self._local_runner is None:
            raise ReviewServiceError(
                "EXECUTION_UNAVAILABLE",
                "教学本地执行器未配置，未运行任何代码。",
                status_code=503,
            )
        safe_result = self._local_runner(attempt, submission)
        result = score_execution_result(
            safe_result,
            required_capabilities=string_list(attempt.get("required_capabilities_json")),
        )
        return self._project_attempt(
            self._sessions.finalize_attempt(
                user_id=str(attempt["user_id"]),
                track_id=str(attempt["track_id"]),
                session_id=str(attempt["review_session_id"]),
                attempt_id=str(attempt["id"]),
                result=result,
            )
        )


    def _static_result(
        self,
        *,
        attempt: Mapping[str, object],
        submission: str,
    ):
        row = self._conn.execute(
            """SELECT versions.starter_artifact_json, rubrics.reference_answer_json,
                      rubrics.score_policy_json
            FROM tutor_exercise_versions AS versions
            JOIN tutor_exercise_private_rubrics AS rubrics
              ON rubrics.exercise_version_id = versions.id
            WHERE versions.id = %s AND versions.validation_status = 'ready'""",
            (attempt["exercise_version_id"],),
        ).fetchone()
        if row is None:
            raise ReviewServiceError(
                "REVIEW_CANDIDATE_INVALID",
                "复习练习缺少可验证评分 contract。",
                status_code=409,
            )
        if str(attempt.get("exercise_type")) == ExerciseType.MODEL_CODE_REVIEW.value:
            artifact = ModelReviewArtifactV1.model_validate(
                as_mapping(row.get("starter_artifact_json"))
            )
            rubric = ModelReviewRubricV1.model_validate(
                as_mapping(row.get("reference_answer_json"))
            )
            parsed = parse_model_review_submission(submission)
            parsed.validate_line_count(artifact.line_count)
            policy = as_mapping(row.get("score_policy_json"))
            return evaluate_model_code_review(
                submission=parsed,
                rubric=rubric,
                line_count=artifact.line_count,
                required_capabilities=tuple(
                    string_list(attempt.get("required_capabilities_json"))
                ),
                assistance_kind=ModelReviewAssistanceKind(
                    str(attempt.get("assistance_kind") or "independent")
                ),
                threshold=as_float(policy.get("threshold") or 0.8),
                now=datetime.now(UTC),
            )
        reference = as_mapping(row.get("reference_answer_json"))
        raw_answers = reference.get("accepted_answers")
        accepted = (
            tuple(
                str(item)
                for item in raw_answers
                if isinstance(item, str) and item.strip()
            )
            if isinstance(raw_answers, list | tuple)
            else ()
        )
        if not accepted:
            fallback = reference.get("content") or reference.get("answer")
            accepted = (
                (str(fallback),)
                if isinstance(fallback, str) and fallback.strip()
                else ()
            )
        if not accepted:
            raise ReviewServiceError(
                "REVIEW_CANDIDATE_INVALID",
                "静态复习练习缺少可验证评分 contract。",
                status_code=409,
            )
        return evaluate_static_reasoning(
            answer=submission,
            accepted_answers=accepted,
            required_capabilities=string_list(attempt.get("required_capabilities_json")),
            threshold=as_float(as_mapping(row.get("score_policy_json")).get("threshold") or 0.8),
            now=datetime.now(UTC),
        )

    def _execution_tier(self, row: Mapping[str, object]) -> dict[str, object]:
        language = require_language_capability(str(row["language_id"]))
        projection = self._tier_resolver.resolve(
            language=language,
            inputs=ExecutionTierInputs(
                composition=self._composition,
                local_runner_available=self._local_runner_available,
                runtime_registry=default_runtime_registry(),
                executor_availability=_ExecutorAvailability(self._execution),
            ),
        )
        if bool(row.get("execution_required")) and projection.tier is ExecutionTier.STATIC_ONLY:
            return {
                "execution_tier": ExecutionTier.UNAVAILABLE.value,
                "execution_disclosure": (
                    "该复习题依赖真实执行，但当前没有 reviewed container lock 与兼容 executor；"
                    "系统没有回退到本机运行。"
                ),
                "runtime_id": None,
            }
        return {
            "execution_tier": projection.tier.value,
            "execution_disclosure": projection.disclosure,
            "runtime_id": projection.runtime_id,
        }

    def _project_queue(self, row: Mapping[str, object]) -> dict[str, object]:
        items = []
        raw_items = row.get("items")
        for item in raw_items if isinstance(raw_items, list | tuple) else ():
            if not isinstance(item, Mapping):
                continue
            items.append(
                {
                    "schedule_id": str(item["schedule_id"]),
                    "knowledge_key": str(item["knowledge_key"]),
                    "title": str(item["title"]),
                    "due_at": iso(item.get("due_at")),
                    "risk_level": str(item["risk_level"]),
                    "critical_prerequisite_gate": bool(
                        item.get("critical_prerequisite_gate")
                    ),
                    "mastery": as_mapping(item.get("mastery")),
                    "required_capabilities": string_list(
                        item.get("required_capabilities")
                    ),
                    "schedule_version": as_int(item["schedule_version"]),
                }
            )
        critical = row.get("critical_prerequisite_gate")
        return {
            "track_id": str(row["track_id"]),
            "as_of": iso(row.get("as_of")),
            "due_count": as_int(row["due_count"]),
            "items": items,
            "critical_prerequisite_gate": (
                next(
                    (
                        item
                        for item in items
                        if item["critical_prerequisite_gate"]
                        and isinstance(critical, Mapping)
                        and str(critical.get("knowledge_key")) == item["knowledge_key"]
                    ),
                    None,
                )
                if critical is not None
                else None
            ),
        }

    def _project_session(self, row: Mapping[str, object]) -> dict[str, object]:
        items = []
        raw_items = row.get("items")
        for item in raw_items if isinstance(raw_items, list | tuple) else ():
            if not isinstance(item, Mapping):
                continue
            attempt = None
            if item.get("attempt_id") is not None:
                attempt = {
                    "attempt_id": str(item["attempt_id"]),
                    "status": "terminal" if item.get("outcome") is not None else "pending",
                    "independence": str(item.get("independence") or "independent"),
                    "assistance_kind": str(item.get("assistance_kind") or "independent"),
                    "execution_job_id": str(item["execution_job_id"])
                    if item.get("execution_job_id")
                    else None,
                    "execution_job_state": str(item["execution_job_state"])
                    if item.get("execution_job_state")
                    else None,
                    "result": (
                        {
                            "outcome": str(item["outcome"]),
                            "score": as_float(item["score"]),
                            "safe_feedback": as_mapping(item.get("safe_feedback_json")),
                            "capability_scores": as_mapping(
                                item.get("capability_scores_json")
                            ),
                            "terminal_at": iso(item.get("terminal_at")),
                        }
                        if item.get("outcome") is not None
                        else None
                    ),
                }
            tier = self._execution_tier(item)
            items.append(
                {
                    "item_id": str(item["id"]),
                    "order_index": as_int(item["order_index"]),
                    "version": as_int(item["version"]),
                    "exercise": {
                        "exercise_version_id": str(item["exercise_version_id"]),
                        "exercise_type": str(item["exercise_type"]),
                        "title": str(item["title"]),
                        "learner_prompt": as_mapping(item.get("learner_prompt_json")),
                        "starter_artifact": as_mapping(item.get("starter_artifact_json")),
                        "required_capabilities": string_list(
                            item.get("required_capabilities_json")
                        ),
                        "content_hash": str(item["content_hash"]),
                        "execution_tier": tier["execution_tier"],
                        "execution_disclosure": tier["execution_disclosure"],
                    },
                    "attempt": attempt,
                }
            )
        finalization = None
        if row.get("finalization_result_hash") is not None:
            finalization = {
                "rating": str(row["rating"]),
                "aggregate": as_mapping(row.get("aggregate_json")),
                "result_hash": str(row["finalization_result_hash"]),
            }
        return {
            "session_id": str(row["id"]),
            "track_id": str(row["track_id"]),
            "knowledge_key": str(row["knowledge_key"]),
            "plan_revision_id": str(row["plan_revision_id"]),
            "state": str(row["state"]),
            "stage": str(row["stage"]),
            "failure_code": str(row["failure_code"])
            if row.get("failure_code")
            else None,
            "recoverable": str(row["state"]) == "blocked",
            "version": as_int(row["version"]),
            "context_snapshot": as_mapping(row.get("context_snapshot_json")),
            "context_snapshot_hash": str(row["context_snapshot_hash"]),
            "items": items,
            "finalization": finalization,
            "started_at": iso(row.get("started_at")),
            "terminal_at": iso(row.get("terminal_at")),
            "idempotent_replayed": bool(row.get("idempotent_replayed", False)),
        }

    @staticmethod
    def _project_attempt(row: Mapping[str, object]) -> dict[str, object]:
        result = None
        if row.get("outcome") is not None:
            result = {
                "outcome": str(row["outcome"]),
                "score": as_float(row["score"]),
                "safe_feedback": as_mapping(row.get("safe_feedback_json")),
                "capability_scores": as_mapping(row.get("capability_scores_json")),
                "terminal_at": iso(row.get("terminal_at")),
            }
        return {
            "attempt_id": str(row.get("id") or row.get("attempt_id")),
            "attempt_type": str(
                row.get("attempt_type") or ExerciseAttemptType.REVIEW_SUBMIT.value
            ),
            "track_id": str(row["track_id"]),
            "session_id": str(row.get("review_session_id") or ""),
            "item_id": str(row.get("review_item_id") or ""),
            "knowledge_key": str(row["knowledge_key"]),
            "session_version": as_int(row.get("review_session_version")),
            "exercise_version_id": str(row["exercise_version_id"]),
            "submission_hash": str(row["submission_hash"]),
            "independence": str(row["independence"]),
            "assistance_kind": str(row.get("assistance_kind") or row["independence"]),
            "accepted_at": iso(row.get("accepted_at")),
            "status": "terminal" if result else "pending",
            "execution_job_id": str(row["execution_job_id"])
            if row.get("execution_job_id")
            else None,
            "execution_job_state": str(row["execution_job_state"])
            if row.get("execution_job_state")
            else None,
            "result": result,
            "idempotent_replayed": bool(row.get("idempotent_replayed", False)),
        }



def _find_item(session: Mapping[str, object], item_id: str) -> Mapping[str, object]:
    raw = session.get("items")
    for item in raw if isinstance(raw, list | tuple) else ():
        if isinstance(item, Mapping) and str(item.get("id")) == item_id:
            return item
    raise ReviewNotFound("review item was not found")


def _map_error(exc: Exception) -> ReviewServiceError:
    if isinstance(exc, ReviewNotFound):
        return ReviewServiceError(
            "REVIEW_NOT_FOUND",
            "Review 资源不存在或不属于当前用户。",
            status_code=404,
        )
    if isinstance(exc, ReviewVersionConflict):
        return ReviewServiceError(
            "REVIEW_VERSION_CONFLICT",
            "ReviewSession 或 schedule 已发生变化，请刷新后重试。",
            status_code=409,
        )
    if isinstance(exc, ReviewIdempotencyConflict):
        return ReviewServiceError(
            "IDEMPOTENCY_CONFLICT",
            "同一幂等标识不能用于不同的 Review 请求。",
            status_code=409,
            recoverable=False,
        )
    if isinstance(exc, ReviewNotReady):
        return ReviewServiceError(
            "REVIEW_NOT_READY",
            "ReviewSession 当前状态不允许执行该操作。",
            status_code=409,
        )
    if isinstance(exc, ExecutionSubmissionError):
        return ReviewServiceError(
            "EXECUTION_UNAVAILABLE",
            "当前受控执行环境不可用，未运行任何代码。",
            status_code=503,
            details={"diagnostic_code": str(exc)},
        )
    return ReviewServiceError(
        "VALIDATION_ERROR",
        "Review 请求不符合当前 contract。",
        status_code=422,
        recoverable=False,
    )


def _ids(user_id: str, track_id: str, session_id: str) -> tuple[str, str, str]:
    return _uuid(user_id, "user_id"), _uuid(track_id, "track_id"), _uuid(session_id, "session_id")


def _uuid(value: str, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReviewServiceError(
            "VALIDATION_ERROR",
            f"{label} 不是有效 UUID。",
            status_code=422,
            recoverable=False,
        ) from exc


def _stable_key(value: str, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized or len(normalized) > 160 or not re.fullmatch(r"[a-z0-9][a-z0-9._:-]*", normalized):
        raise ReviewServiceError(
            "VALIDATION_ERROR",
            f"{label} 不是有效 stable key。",
            status_code=422,
            recoverable=False,
        )
    return normalized


def _idempotency(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise ReviewServiceError(
            "VALIDATION_ERROR",
            "Idempotency-Key 不合法。",
            status_code=422,
            recoverable=False,
        )
    return normalized
