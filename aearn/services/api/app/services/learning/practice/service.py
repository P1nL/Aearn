"""Verified-only service boundary for Lesson Gates and module diagnostics."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection

from aearn_shared.execution import ExecutionAction, SafeExecutionResultV1
from app.services.learning.contracts import ExecutionComposition, ExecutionTier
from app.services.learning.execution_tiers import ExecutionTierInputs, ExecutionTierResolver
from app.services.learning.practice.contracts import ExerciseAttemptType
from app.services.learning.practice.diagnostics import PostgresModuleDiagnosticRepository
from app.services.learning.practice.policies import evaluate_static_reasoning, score_execution_result
from app.services.learning.practice.repository import (
    PostgresExerciseGateRepository,
    PracticeIdempotencyConflict,
    PracticeNotFound,
    PracticeNotReady,
    PracticeRepositoryError,
    PracticeVersionConflict,
    _float,
    _int,
    _string_list,
    request_hash,
)
from app.services.runners.language_capabilities import require_language_capability
from app.services.tutor.execution import (
    ExecutionIntentRepository,
    ExecutionSubmissionError,
    default_runtime_registry,
)


LocalExerciseRunner = Callable[[Mapping[str, object], str], SafeExecutionResultV1]


class ExerciseGateServiceError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        recoverable: bool = True,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})
        super().__init__(message)


class _ExecutorAvailability:
    def __init__(self, repository: ExecutionIntentRepository) -> None:
        self._repository = repository

    def is_runtime_available(self, runtime_id: str) -> bool:
        return self._repository.availability_for_runtime(runtime_id).available


class ExerciseGateService:
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
        self._repository = PostgresExerciseGateRepository(conn)
        self._diagnostics = PostgresModuleDiagnosticRepository(conn)
        self._execution = execution_repository or ExecutionIntentRepository(conn)
        self._composition = composition
        self._local_runner_available = local_runner_available
        self._local_runner = local_runner
        self._tier_resolver = ExecutionTierResolver()

    def read_gates(self, *, user_id: str, track_id: str, knowledge_key: str) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        try:
            rows = self._repository.read_gates(user_id=user, track_id=track, knowledge_key=key)
            scope = self._repository.read_scope(user_id=user, track_id=track, knowledge_key=key)
        except PracticeNotFound as exc:
            raise _not_found() from exc
        return {
            "track_id": track,
            "knowledge_key": key,
            "track_version": scope.track_version,
            "progress_version": scope.progress_version,
            "assignment_id": scope.assignment_id,
            "assignment_version": scope.assignment_version,
            "items": [self._project_gate(row) for row in rows],
        }

    def prepare_gate(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        expected_track_version: int,
        expected_progress_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        gate = _stable_key(gate_key, "gate_key")
        return self._mutate(
            user_id=user,
            operation=f"lesson.gate.prepare:{track}:{key}:{gate}",
            idempotency_key=idempotency_key,
            request_body={
                "track_id": track,
                "knowledge_key": key,
                "gate_key": gate,
                "expected_track_version": expected_track_version,
                "expected_progress_version": expected_progress_version,
            },
            action=lambda: self._prepare(
                user_id=user,
                track_id=track,
                knowledge_key=key,
                gate_key=gate,
                expected_track_version=expected_track_version,
                expected_progress_version=expected_progress_version,
            ),
        )

    def hint(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        expected_gate_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        gate = _stable_key(gate_key, "gate_key")
        body = {
            "track_id": track,
            "knowledge_key": key,
            "gate_key": gate,
            "expected_gate_version": expected_gate_version,
        }
        try:
            with self._conn.transaction():
                return self._project_hint(
                    self._repository.append_hint(
                        user_id=user,
                        track_id=track,
                        knowledge_key=key,
                        gate_key=gate,
                        expected_gate_version=expected_gate_version,
                        idempotency_key=_idempotency_key(idempotency_key),
                        request_hash=request_hash(body),
                    )
                )
        except PracticeRepositoryError as exc:
            raise _map_repository_error(exc) from exc

    def attempt_gate(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        attempt_type: str,
        submission: str,
        expected_track_version: int,
        expected_progress_version: int,
        expected_assignment_version: int,
        expected_gate_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user, track, key = _scope_ids(user_id, track_id, knowledge_key)
        gate = _stable_key(gate_key, "gate_key")
        try:
            kind = ExerciseAttemptType(attempt_type)
        except ValueError as exc:
            raise ExerciseGateServiceError(
                "VALIDATION_ERROR",
                "attempt_type 必须是 run 或 submit。",
                status_code=422,
                recoverable=False,
            ) from exc
        if kind is ExerciseAttemptType.DIAGNOSTIC_SUBMIT:
            raise ExerciseGateServiceError("VALIDATION_ERROR", "Gate 不接受诊断提交类型。", status_code=422)
        try:
            gate_row = self._repository.read_gate(
                user_id=user,
                track_id=track,
                knowledge_key=key,
                gate_key=gate,
            )
        except PracticeRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        tier = self._execution_tier(gate_row)
        if tier["execution_tier"] == ExecutionTier.STATIC_ONLY.value:
            if kind is ExerciseAttemptType.RUN or bool(gate_row.get("execution_required")):
                raise ExerciseGateServiceError(
                    "EXECUTION_UNAVAILABLE",
                    "此练习只允许确定性静态提交，未运行任何代码。",
                    status_code=503,
                )
        elif tier["execution_tier"] not in {
            ExecutionTier.CONTAINER_VERIFIED.value,
            ExecutionTier.TEACHING_LOCAL.value,
        }:
            raise ExerciseGateServiceError(
                "EXECUTION_UNAVAILABLE",
                str(tier["execution_disclosure"]),
                status_code=503,
            )
        body = {
            "track_id": track,
            "knowledge_key": key,
            "gate_key": gate,
            "attempt_type": kind.value,
            "submission_hash": hashlib.sha256(submission.encode("utf-8")).hexdigest(),
            "expected_track_version": expected_track_version,
            "expected_progress_version": expected_progress_version,
            "expected_assignment_version": expected_assignment_version,
            "expected_gate_version": expected_gate_version,
        }
        try:
            with self._conn.transaction():
                attempt = self._repository.create_gate_attempt(
                    user_id=user,
                    track_id=track,
                    knowledge_key=key,
                    gate_key=gate,
                    attempt_type=kind,
                    submission=submission,
                    expected_track_version=expected_track_version,
                    expected_progress_version=expected_progress_version,
                    expected_assignment_version=expected_assignment_version,
                    expected_gate_version=expected_gate_version,
                    idempotency_key=_idempotency_key(idempotency_key),
                    request_hash=request_hash(body),
                    now=datetime.now(UTC),
                )
                response = self._dispatch_attempt(attempt=attempt, submission=submission, tier=tier)
                response["execution_tier"] = tier["execution_tier"]
                response["execution_disclosure"] = tier["execution_disclosure"]
                return response
        except (PracticeRepositoryError, ExecutionSubmissionError) as exc:
            raise _map_execution_or_repository_error(exc) from exc

    def read_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        attempt_id: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        knowledge = _stable_key(knowledge_key, "knowledge_key")
        attempt = _uuid(attempt_id, "attempt_id")
        try:
            with self._conn.transaction():
                row = self._repository.read_attempt(user_id=user, attempt_id=attempt)
                if (
                    str(row["track_id"]) != track
                    or str(row["knowledge_key"]) != knowledge
                    or str(row["attempt_type"]) == ExerciseAttemptType.DIAGNOSTIC_SUBMIT.value
                ):
                    raise PracticeNotFound("Lesson Gate Attempt was not found")
                if row.get("result_hash") is None and row.get("execution_job_id") is not None:
                    safe_result = self._execution.read_exercise_safe_result(user_id=user, attempt_id=attempt)
                    if safe_result is not None:
                        required = self._required_capabilities(str(row["exercise_version_id"]))
                        result = score_execution_result(safe_result, required_capabilities=required)
                        if str(row["attempt_type"]) == ExerciseAttemptType.DIAGNOSTIC_SUBMIT.value:
                            return self._project_diagnostic(
                                self._diagnostics.finalize_attempt(
                                    user_id=user,
                                    track_id=str(row["track_id"]),
                                    attempt_id=attempt,
                                    result=result,
                                    now=datetime.now(UTC),
                                )
                            )
                        row = self._repository.finalize_gate_attempt(
                            user_id=user,
                            attempt_id=attempt,
                            result=result,
                            now=datetime.now(UTC),
                        )
                return self._project_attempt(row)
        except (PracticeRepositoryError, ExecutionSubmissionError) as exc:
            raise _map_execution_or_repository_error(exc) from exc

    def create_diagnostic(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        expected_track_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        module = _stable_key(module_key, "module_key")
        body = {
            "track_id": track,
            "module_key": module,
            "expected_track_version": expected_track_version,
        }
        try:
            with self._conn.transaction():
                return self._project_diagnostic(
                    self._diagnostics.create_session(
                        user_id=user,
                        track_id=track,
                        module_key=module,
                        expected_track_version=expected_track_version,
                        idempotency_key=_idempotency_key(idempotency_key),
                        request_hash=request_hash(body),
                        now=datetime.now(UTC),
                    )
                )
        except PracticeRepositoryError as exc:
            raise _map_diagnostic_error(exc) from exc

    def read_diagnostic(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        session_id: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        module = _stable_key(module_key, "module_key")
        session = _uuid(session_id, "session_id")
        try:
            row = self._diagnostics.read_session(user_id=user, track_id=track, session_id=session)
            if str(row["module_key"]) != module:
                raise PracticeNotFound("module diagnostic session was not found")
            return self._project_diagnostic(row)
        except PracticeRepositoryError as exc:
            raise _map_diagnostic_error(exc) from exc

    def attempt_diagnostic(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        session_id: str,
        item_id: str,
        submission: str,
        expected_track_version: int,
        expected_session_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        module = _stable_key(module_key, "module_key")
        session = _uuid(session_id, "session_id")
        item = _uuid(item_id, "item_id")
        body = {
            "track_id": track,
            "module_key": module,
            "session_id": session,
            "item_id": item,
            "submission_hash": hashlib.sha256(submission.encode("utf-8")).hexdigest(),
            "expected_track_version": expected_track_version,
            "expected_session_version": expected_session_version,
        }
        try:
            with self._conn.transaction():
                attempt = self._diagnostics.create_attempt(
                    user_id=user,
                    track_id=track,
                    module_key=module,
                    session_id=session,
                    item_id=item,
                    submission=submission,
                    expected_track_version=expected_track_version,
                    expected_session_version=expected_session_version,
                    idempotency_key=_idempotency_key(idempotency_key),
                    request_hash=request_hash(body),
                    now=datetime.now(UTC),
                )
                exercise = self._exercise_row(str(attempt["exercise_version_id"]))
                tier = self._execution_tier(exercise)
                if tier["execution_tier"] not in {
                    ExecutionTier.CONTAINER_VERIFIED.value,
                    ExecutionTier.TEACHING_LOCAL.value,
                }:
                    raise ExerciseGateServiceError(
                        "EXECUTION_UNAVAILABLE",
                        str(tier["execution_disclosure"]),
                        status_code=503,
                    )
                response = self._dispatch_attempt(attempt=attempt, submission=submission, tier=tier)
                response["execution_tier"] = tier["execution_tier"]
                response["execution_disclosure"] = tier["execution_disclosure"]
                return response
        except ExerciseGateServiceError:
            raise
        except (PracticeRepositoryError, ExecutionSubmissionError) as exc:
            raise _map_execution_or_repository_error(exc) from exc

    def confirm_diagnostic_skip(
        self,
        *,
        user_id: str,
        track_id: str,
        module_key: str,
        session_id: str,
        expected_track_version: int,
        expected_session_version: int,
        idempotency_key: str,
    ) -> dict[str, object]:
        user = _uuid(user_id, "user_id")
        track = _uuid(track_id, "track_id")
        module = _stable_key(module_key, "module_key")
        session = _uuid(session_id, "session_id")
        return self._mutate(
            user_id=user,
            operation=f"module.diagnostic.confirm:{track}:{session}",
            idempotency_key=idempotency_key,
            request_body={
                "track_id": track,
                "module_key": module,
                "session_id": session,
                "expected_track_version": expected_track_version,
                "expected_session_version": expected_session_version,
            },
            action=lambda: self._project_diagnostic(
                self._diagnostics.confirm_skip(
                    user_id=user,
                    track_id=track,
                    module_key=module,
                    session_id=session,
                    expected_session_version=expected_session_version,
                    expected_track_version=expected_track_version,
                    now=datetime.now(UTC),
                )
            ),
        )

    def _prepare(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        expected_track_version: int,
        expected_progress_version: int,
    ) -> dict[str, object]:
        try:
            rows = self._repository.prepare_gates(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=knowledge_key,
                expected_track_version=expected_track_version,
                expected_progress_version=expected_progress_version,
                now=datetime.now(UTC),
            )
        except PracticeRepositoryError as exc:
            raise _map_repository_error(exc) from exc
        selected = next((row for row in rows if str(row["gate_key"]) == gate_key), None)
        if selected is None:
            raise ExerciseGateServiceError(
                "LESSON_GATE_NOT_READY",
                "当前课程 Gate 尚未绑定可用练习。",
                status_code=409,
            )
        return {"gate": self._project_gate(selected), "status": "ready"}

    def _dispatch_attempt(
        self,
        *,
        attempt: Mapping[str, object],
        submission: str,
        tier: Mapping[str, object],
    ) -> dict[str, object]:
        if bool(attempt.get("idempotent_replayed")):
            stored = self._repository.read_attempt(
                user_id=str(attempt["user_id"]),
                attempt_id=str(attempt["id"]),
            )
            if stored.get("result_hash") is not None or stored.get("execution_job_id") is not None:
                return self._project_attempt(stored)
        if tier["execution_tier"] == ExecutionTier.STATIC_ONLY.value:
            if str(attempt["attempt_type"]) != ExerciseAttemptType.SUBMIT.value:
                raise ExerciseGateServiceError(
                    "EXECUTION_UNAVAILABLE",
                    "静态练习不提供 Run，未运行任何代码。",
                    status_code=503,
                )
            rubric = self._conn.execute(
                """
                SELECT reference_answer_json FROM tutor_exercise_private_rubrics
                WHERE exercise_version_id = %s
                """,
                (attempt["exercise_version_id"],),
            ).fetchone()
            reference = _mapping_dict(rubric.get("reference_answer_json")) if rubric is not None else {}
            raw_answers = reference.get("accepted_answers")
            accepted_answers = (
                tuple(str(item) for item in raw_answers if isinstance(item, str) and item.strip())
                if isinstance(raw_answers, list | tuple)
                else ()
            )
            if not accepted_answers:
                fallback = reference.get("content") or reference.get("answer")
                accepted_answers = (str(fallback),) if isinstance(fallback, str) and fallback.strip() else ()
            if not accepted_answers:
                raise ExerciseGateServiceError(
                    "LESSON_GATE_NOT_READY",
                    "静态练习缺少可验证的评分 contract。",
                    status_code=409,
                )
            result = evaluate_static_reasoning(
                answer=submission,
                accepted_answers=accepted_answers,
                required_capabilities=_string_list(attempt.get("required_capabilities_json")),
                threshold=_float(attempt.get("pass_threshold")),
                now=datetime.now(UTC),
            )
            return self._project_attempt(
                self._repository.finalize_gate_attempt(
                    user_id=str(attempt["user_id"]),
                    attempt_id=str(attempt["id"]),
                    result=result,
                    now=datetime.now(UTC),
                )
            )
        if tier["execution_tier"] == ExecutionTier.CONTAINER_VERIFIED.value:
            action = (
                ExecutionAction.RUN
                if str(attempt["attempt_type"]) == ExerciseAttemptType.RUN.value
                else ExecutionAction.TEST
            )
            job = self._execution.create_or_replay_exercise_job(
                user_id=str(attempt["user_id"]),
                attempt_id=str(attempt["id"]),
                submission_id=str(attempt["submission_id"]),
                exercise_version_id=str(attempt["exercise_version_id"]),
                action=action,
            )
            response = self._project_attempt(attempt)
            response.update(status="pending", execution_job_id=job.job_id, execution_job_state=job.state.value)
            return response
        if self._local_runner is None:
            raise ExerciseGateServiceError(
                "EXECUTION_UNAVAILABLE",
                "教学本地执行器未配置，未运行任何代码。",
                status_code=503,
            )
        safe_result = self._local_runner(attempt, submission)
        result = score_execution_result(
            safe_result,
            required_capabilities=self._required_capabilities(str(attempt["exercise_version_id"])),
        )
        if str(attempt["attempt_type"]) == ExerciseAttemptType.DIAGNOSTIC_SUBMIT.value:
            return self._project_diagnostic(
                self._diagnostics.finalize_attempt(
                    user_id=str(attempt["user_id"]),
                    track_id=str(attempt["track_id"]),
                    attempt_id=str(attempt["id"]),
                    result=result,
                    now=datetime.now(UTC),
                )
            )
        return self._project_attempt(
            self._repository.finalize_gate_attempt(
                user_id=str(attempt["user_id"]),
                attempt_id=str(attempt["id"]),
                result=result,
                now=datetime.now(UTC),
            )
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
                    "该练习依赖真实执行，但当前没有 reviewed container lock 与兼容 executor；"
                    "系统没有回退到本机运行。"
                ),
                "runtime_id": None,
            }
        return {
            "execution_tier": projection.tier.value,
            "execution_disclosure": projection.disclosure,
            "runtime_id": projection.runtime_id,
        }

    def _exercise_row(self, exercise_version_id: str) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_exercise_versions WHERE id = %s AND validation_status = 'ready'",
            (exercise_version_id,),
        ).fetchone()
        if row is None:
            raise PracticeNotReady("exercise version is not ready")
        return dict(row)

    def _required_capabilities(self, exercise_version_id: str) -> tuple[str, ...]:
        row = self._exercise_row(exercise_version_id)
        return tuple(_string_list(row.get("required_capabilities_json")))

    def _project_gate(self, row: Mapping[str, object]) -> dict[str, object]:
        if row.get("binding_id") is None or row.get("exercise_version_id") is None:
            return {
                "gate_key": str(row["gate_key"]),
                "gate_kind": str(row["gate_kind"]),
                "assessment_contract_version": str(row["assessment_contract_version"]),
                "required_capabilities": _string_list(row.get("slot_capabilities_json")),
                "learner_prompt": str(row["learner_prompt"]),
                "status": "unbound",
                "allowed_actions": ["prepare"],
                "exercise": None,
            }
        tier = self._execution_tier(row)
        allowed: list[str] = []
        if tier["execution_tier"] in {
            ExecutionTier.CONTAINER_VERIFIED.value,
            ExecutionTier.TEACHING_LOCAL.value,
        } and str(row.get("gate_state")) != "passed":
            allowed = ["hint", "run", "submit"]
        elif not bool(row.get("execution_required")) and tier["execution_tier"] == ExecutionTier.STATIC_ONLY.value:
            allowed = ["hint", "submit"]
        latest_result = None
        if row.get("latest_outcome") is not None:
            latest_result = {
                "outcome": str(row["latest_outcome"]),
                "score": _float(row.get("latest_score")),
                "safe_feedback": _mapping_dict(row.get("latest_safe_feedback_json")),
                "terminal_at": _iso(row.get("latest_terminal_at")),
            }
        return {
            "gate_key": str(row["gate_key"]),
            "gate_kind": str(row["gate_kind"]),
            "assessment_contract_version": str(row["assessment_contract_version"]),
            "required_capabilities": _string_list(row.get("slot_capabilities_json")),
            "learner_prompt": str(row["learner_prompt"]),
            "binding_id": str(row["binding_id"]),
            "binding_contract_hash": str(row["binding_contract_hash"]),
            "requirement_kind": str(row["requirement_kind"]),
            "pass_policy_version": str(row["pass_policy_version"]),
            "pass_threshold": _float(row["pass_threshold"]),
            "execution_requirement": str(row["execution_requirement"]),
            "status": str(row.get("gate_state") or "available"),
            "gate_version": _int(row.get("gate_version")),
            "attempt_count": _int(row.get("attempt_count")),
            "best_score": _float(row.get("best_score")),
            "latest_attempt_id": str(row["latest_attempt_id"]) if row.get("latest_attempt_id") else None,
            "passed_at": _iso(row.get("passed_at")),
            "execution_tier": tier["execution_tier"],
            "execution_disclosure": tier["execution_disclosure"],
            "allowed_actions": allowed,
            "exercise": {
                "exercise_version_id": str(row["exercise_version_id"]),
                "exercise_key": str(row["exercise_key"]),
                "exercise_type": str(row["exercise_type"]),
                "version": str(row["exercise_version"]),
                "title": str(row["exercise_title"]),
                "learner_prompt": _mapping_dict(row.get("learner_prompt_json")),
                "starter_artifact": _mapping_dict(row.get("starter_artifact_json")),
                "required_capabilities": _string_list(row.get("required_capabilities_json")),
                "content_hash": str(row["exercise_content_hash"]),
            },
            "latest_result": latest_result,
        }

    @staticmethod
    def _project_hint(row: Mapping[str, object]) -> dict[str, object]:
        return {
            "hint_id": str(row["id"]),
            "hint_level": _int(row["hint_level"]),
            "hint_policy_version": str(row["hint_policy_version"]),
            "safe_hint": _mapping_dict(row.get("safe_hint_json")),
            "gate_version": _int(row["gate_version"]),
            "created_at": _iso(row.get("created_at")),
            "idempotent_replayed": bool(row.get("idempotent_replayed", False)),
        }

    @staticmethod
    def _project_attempt(row: Mapping[str, object]) -> dict[str, object]:
        result = None
        if row.get("outcome") is not None:
            result = {
                "outcome": str(row["outcome"]),
                "score": _float(row.get("score")),
                "safe_feedback": _mapping_dict(row.get("safe_feedback_json")),
                "capability_scores": _mapping_dict(row.get("capability_scores_json")),
                "terminal_at": _iso(row.get("terminal_at")),
            }
        return {
            "attempt_id": str(row.get("id") or row.get("attempt_id")),
            "attempt_type": str(row["attempt_type"]),
            "track_id": str(row["track_id"]),
            "knowledge_key": str(row["knowledge_key"]),
            "exercise_version_id": str(row["exercise_version_id"]),
            "submission_hash": str(row["submission_hash"]),
            "independence": str(row["independence"]),
            "accepted_at": _iso(row.get("accepted_at")),
            "status": "terminal" if result else "pending",
            "execution_job_id": str(row["execution_job_id"]) if row.get("execution_job_id") else None,
            "execution_job_state": str(row["execution_job_state"]) if row.get("execution_job_state") else None,
            "result": result,
            "projected": row.get("projected"),
            "route_changed": bool(row.get("route_changed", False)),
            "mastery": row.get("mastery"),
            "idempotent_replayed": bool(row.get("idempotent_replayed", False)),
        }

    @staticmethod
    def _project_diagnostic(row: Mapping[str, object]) -> dict[str, object]:
        items = []
        raw_items = row.get("items")
        for item in raw_items if isinstance(raw_items, list | tuple) else ():
            if not isinstance(item, Mapping):
                continue
            result = None
            if item.get("outcome") is not None:
                result = {
                    "outcome": str(item["outcome"]),
                    "score": _float(item.get("score")),
                    "safe_feedback": dict(item["safe_feedback_json"])
                    if isinstance(item.get("safe_feedback_json"), Mapping)
                    else {},
                    "terminal_at": _iso(item.get("terminal_at")),
                }
            items.append(
                {
                    "item_id": str(item["id"]),
                    "item_key": str(item["item_key"]),
                    "order_index": _int(item["order_index"]),
                    "capability_key": str(item["capability_key"]),
                    "knowledge_key": str(item["knowledge_key"]),
                    "threshold": _float(item["threshold"]),
                    "exercise": {
                        "exercise_version_id": str(item["exercise_version_id"]),
                        "exercise_key": str(item["exercise_key"]),
                        "exercise_type": str(item["exercise_type"]),
                        "version": str(item["exercise_version"]),
                        "title": str(item["exercise_title"]),
                        "learner_prompt": dict(item["learner_prompt_json"])
                        if isinstance(item.get("learner_prompt_json"), Mapping)
                        else {},
                        "starter_artifact": dict(item["starter_artifact_json"])
                        if isinstance(item.get("starter_artifact_json"), Mapping)
                        else {},
                    },
                    "attempt_id": str(item["attempt_id"]) if item.get("attempt_id") else None,
                    "execution_job_state": str(item["execution_job_state"])
                    if item.get("execution_job_state")
                    else None,
                    "result": result,
                }
            )
        return {
            "session_id": str(row["id"]),
            "track_id": str(row["track_id"]),
            "module_key": str(row["module_key"]),
            "diagnostic_version": str(row["diagnostic_version"]),
            "policy_version": str(row["policy_version"]),
            "core_capabilities": _string_list(row.get("core_capabilities_json")),
            "pass_threshold": _float(row["pass_threshold"]),
            "require_all_core": bool(row["require_all_core"]),
            "independent_only": bool(row["independent_only"]),
            "cooldown_seconds": _int(row["cooldown_seconds"]),
            "state": str(row["state"]),
            "version": _int(row["version"]),
            "source_plan_revision_id": str(row["source_plan_revision_id"]),
            "proposed_plan_revision_id": str(row["proposed_plan_revision_id"])
            if row.get("proposed_plan_revision_id")
            else None,
            "impact": _mapping_dict(row.get("impact_json")),
            "weak_capabilities": _string_list(row.get("weak_capabilities_json")),
            "started_at": _iso(row.get("started_at")),
            "terminal_at": _iso(row.get("terminal_at")),
            "cooldown_until": _iso(row.get("cooldown_until")),
            "confirmed_at": _iso(row.get("confirmed_at")),
            "items": items,
            "idempotent_replayed": bool(row.get("idempotent_replayed", False)),
        }

    def _mutate(
        self,
        *,
        user_id: str,
        operation: str,
        idempotency_key: str,
        request_body: Mapping[str, object],
        action: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        key = _idempotency_key(idempotency_key)
        hashed = request_hash(request_body)
        try:
            with self._conn.transaction():
                self._conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                    (user_id, f"{operation}:{key}"),
                )
                existing = self._conn.execute(
                    """
                    SELECT request_hash, response_json FROM tutor_api_idempotency_records
                    WHERE user_id = %s AND operation = %s AND idempotency_key = %s FOR UPDATE
                    """,
                    (user_id, operation, key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_hash"]) != hashed:
                        raise PracticeIdempotencyConflict("idempotency key conflicts with stored request")
                    response = dict(existing["response_json"]) if isinstance(existing["response_json"], Mapping) else {}
                    response["idempotent_replayed"] = True
                    return response
                response = action()
                response["idempotent_replayed"] = False
                self._conn.execute(
                    """
                    INSERT INTO tutor_api_idempotency_records (
                      user_id, operation, idempotency_key, request_hash, response_json
                    ) VALUES (%s, %s, %s, %s, %s::jsonb)
                    """,
                    (user_id, operation, key, hashed, json.dumps(response, ensure_ascii=False, default=str)),
                )
                return response
        except ExerciseGateServiceError:
            raise
        except PracticeRepositoryError as exc:
            raise _map_repository_error(exc) from exc


def _mapping_dict(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): item for key, item in value.items()}


def _scope_ids(user_id: str, track_id: str, knowledge_key: str) -> tuple[str, str, str]:
    return _uuid(user_id, "user_id"), _uuid(track_id, "track_id"), _stable_key(knowledge_key, "knowledge_key")


def _uuid(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExerciseGateServiceError(
            "VALIDATION_ERROR",
            f"{label} 必须是 UUID。",
            status_code=422,
            recoverable=False,
        ) from exc


def _stable_key(value: object, label: str) -> str:
    normalized = str(value or "").strip().lower()
    import re

    if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,159}", normalized):
        raise ExerciseGateServiceError(
            "VALIDATION_ERROR",
            f"{label} 格式不合法。",
            status_code=422,
            recoverable=False,
        )
    return normalized


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}", normalized):
        raise ExerciseGateServiceError(
            "VALIDATION_ERROR",
            "client_action_id 格式不合法。",
            status_code=422,
            recoverable=False,
        )
    return normalized


def _map_repository_error(error: PracticeRepositoryError) -> ExerciseGateServiceError:
    if isinstance(error, PracticeNotFound):
        return _not_found()
    if isinstance(error, PracticeVersionConflict):
        return ExerciseGateServiceError(
            "LESSON_GATE_VERSION_CONFLICT",
            "课程、Gate 或学习进度已经更新，请刷新后重试。",
            status_code=409,
        )
    if isinstance(error, PracticeIdempotencyConflict):
        return ExerciseGateServiceError(
            "EXERCISE_ATTEMPT_CONFLICT",
            "同一幂等标识不能用于不同的练习请求。",
            status_code=409,
            recoverable=False,
        )
    if isinstance(error, PracticeNotReady):
        return ExerciseGateServiceError(
            "LESSON_GATE_NOT_READY",
            "当前练习 Gate 尚不可执行，请刷新课程状态。",
            status_code=409,
        )
    return ExerciseGateServiceError(
        "VALIDATION_ERROR",
        "练习请求不符合当前 contract。",
        status_code=422,
        recoverable=False,
    )


def _map_diagnostic_error(error: PracticeRepositoryError) -> ExerciseGateServiceError:
    if isinstance(error, PracticeNotFound):
        return ExerciseGateServiceError(
            "MODULE_DIAGNOSTIC_NOT_ALLOWED",
            "当前模块诊断不可用，或诊断会话不属于此学习范围。",
            status_code=404,
        )
    if isinstance(error, PracticeVersionConflict):
        return ExerciseGateServiceError(
            "MODULE_DIAGNOSTIC_VERSION_CONFLICT",
            "学习路线或诊断状态已经更新，请刷新后重试。",
            status_code=409,
        )
    if isinstance(error, PracticeIdempotencyConflict):
        return ExerciseGateServiceError(
            "EXERCISE_ATTEMPT_CONFLICT",
            "同一幂等标识不能用于不同的模块诊断请求。",
            status_code=409,
            recoverable=False,
        )
    if isinstance(error, PracticeNotReady):
        cooldown = "cooldown" in str(error).casefold()
        return ExerciseGateServiceError(
            "MODULE_DIAGNOSTIC_COOLDOWN" if cooldown else "MODULE_DIAGNOSTIC_NOT_ALLOWED",
            "模块诊断仍在冷却期内。" if cooldown else "当前模块不允许启动或继续诊断。",
            status_code=409,
        )
    return ExerciseGateServiceError(
        "VALIDATION_ERROR",
        "模块诊断请求不符合当前 contract。",
        status_code=422,
        recoverable=False,
    )


def _map_execution_or_repository_error(error: Exception) -> ExerciseGateServiceError:
    if isinstance(error, PracticeRepositoryError):
        return _map_repository_error(error)
    code = error.code if isinstance(error, ExecutionSubmissionError) else "execution_unavailable"
    return ExerciseGateServiceError(
        "EXECUTION_UNAVAILABLE",
        "当前没有可验证的受控执行环境，系统未回退到本机运行。",
        status_code=503,
        details={"availability_code": code},
    )


def _not_found() -> ExerciseGateServiceError:
    return ExerciseGateServiceError(
        "LESSON_GATE_NOT_FOUND",
        "课程 Gate 或所属学习范围不存在。",
        status_code=404,
        recoverable=False,
    )


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
