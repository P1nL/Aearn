from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal

from psycopg import Connection

from app.services.evaluation import (
    build_code_completion_result,
)
from app.services.exercise_guidance import (
    build_error_explanation_response,
    build_explanation_check_response,
    build_hint_response,
    resolve_blank,
)
from app.services.exercise_repository import get_exercise, get_or_create_exercise_for_knowledge_point
from app.services.plan_repository import IdempotencyConflictError, request_hash
from app.services.review_scheduler import apply_attempt_review_update
from app.services.runtime_runner import RuntimeExecutionResult, run_exercise
from app.services.user_repository import get_user


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SessionStateConflictError(ValueError):
    pass


class InvalidLearningSessionRequestError(ValueError):
    pass


class EvaluationConflictError(ValueError):
    pass


def start_learning_session(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
    request_id: str | None,
) -> tuple[dict[str, object], bool]:
    context = _load_learning_context(conn, user_id=user_id, plan_id=plan_id, knowledge_point_id=knowledge_point_id)
    runtime_profile = _serialize_runtime_profile(context)
    exercise = get_or_create_exercise_for_knowledge_point(
        conn,
        knowledge_point=context,
        runtime_profile=runtime_profile,
    )

    reused = False
    session = conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE user_id = %s
          AND plan_id = %s
          AND entry_point = %s
          AND session_type = 'learn'
          AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id, plan_id, knowledge_point_id),
    ).fetchone()
    if session is None:
        session = conn.execute(
            """
            INSERT INTO learning_sessions (
              user_id, plan_id, session_type, status, entry_point, next_entry_point, request_id
            )
            VALUES (%s, %s, 'learn', 'active', %s, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                plan_id,
                knowledge_point_id,
                knowledge_point_id,
                _request_id_or_none(request_id),
            ),
        ).fetchone()
        if session is None:
            raise RuntimeError("learning session insert returned no row")
    else:
        reused = True

    conn.execute(
        """
        UPDATE learning_plans
        SET current_module_id = %s
        WHERE id = %s
        """,
        (context["module_id"], plan_id),
    )
    conn.execute(
        """
        UPDATE knowledge_points
        SET status = 'learning', last_session_id = %s
        WHERE id = %s
        """,
        (session["id"], knowledge_point_id),
    )

    response = {
        "session_id": str(session["id"]),
        "session_type": session["session_type"],
        "context_snapshot": {
            "current_stage": context["module_title"],
            "LearningPlan": {
                "id": str(context["plan_id"]),
                "current_module_id": str(context["module_id"]),
            },
            "KnowledgePoint": {
                "id": str(context["id"]),
                "title": context["title"],
                "status": "learning",
            },
            "RuntimeProfile": runtime_profile,
        },
        "exercise": exercise,
        "initial_agent_message": _initial_agent_message(runtime_profile["runtime_tier"], str(context["title"])),
        "session_state": "learning",
    }
    return response, reused


def run_learning_session_exercise(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    exercise_id: str,
    code: str,
    filled_blanks: Mapping[str, str],
    run_mode: str,
    runtime_profile_id: str | None,
    provided_code_hash: str | None,
    request_id: str | None,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    session = _load_session(conn, session_id, allowed_session_types={"learn", "review"})
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)
    if runtime_profile_id is not None and runtime_profile_id != exercise["runtime_profile"]["id"]:
        raise SessionStateConflictError("runtime_profile_id does not match the exercise runtime profile")

    code_hash = provided_code_hash or build_code_hash(code, filled_blanks)
    key = default_run_key(session_id=session_id, exercise_id=exercise_id, code_hash=code_hash, run_mode=run_mode)
    stored = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    payload_hash = request_hash(request_body)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same run key was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored run response is invalid")
        return response, True

    runtime_result = run_exercise(exercise, code, filled_blanks, run_mode)
    attempt_error_count = 0 if runtime_result.runtime_status == "success" and runtime_result.test_pass_rate >= 1.0 else 1
    attempt = conn.execute(
        """
        INSERT INTO attempts (
          session_id, exercise_id, user_id, attempt_type, submit_version, submitted_code,
          code_hash, filled_blanks_json, runtime_status, test_pass_rate, passed_test_count,
          total_test_count, test_results_json, stdout, stderr, error_message, error_cause,
          hint_usage_count, error_count, evaluation_status, request_id
        )
        VALUES (
          %(session_id)s, %(exercise_id)s, %(user_id)s, 'run', 1, %(submitted_code)s,
          %(code_hash)s, %(filled_blanks_json)s::jsonb, %(runtime_status)s, %(test_pass_rate)s, %(passed_test_count)s,
          %(total_test_count)s, %(test_results_json)s::jsonb, %(stdout)s, %(stderr)s, %(error_message)s, %(error_cause)s,
          0, %(error_count)s, 'pending', %(request_id)s
        )
        RETURNING *
        """,
        {
            "session_id": session_id,
            "exercise_id": exercise_id,
            "user_id": str(session["user_id"]),
            "submitted_code": code,
            "code_hash": code_hash,
            "filled_blanks_json": json.dumps(filled_blanks),
            "runtime_status": runtime_result.runtime_status,
            "test_pass_rate": runtime_result.test_pass_rate,
            "passed_test_count": runtime_result.passed_test_count,
            "total_test_count": runtime_result.total_test_count,
            "test_results_json": json.dumps(runtime_result.test_results),
            "stdout": runtime_result.stdout,
            "stderr": runtime_result.stderr,
            "error_message": runtime_result.error_message,
            "error_cause": runtime_result.error_message,
            "error_count": attempt_error_count,
            "request_id": _request_id_or_none(request_id),
        },
    ).fetchone()
    if attempt is None:
        raise RuntimeError("run attempt insert returned no row")

    response = _serialize_run_response(attempt, runtime_result)
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'run_learning_session_exercise', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def submit_learning_session_exercise(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    exercise_id: str,
    attempt_id: str,
    code: str,
    filled_blanks: Mapping[str, str],
    submit_version: int | None,
    explanation: str | None,
    hint_usage_count: int,
    error_count: int | None,
    provided_code_hash: str | None,
    request_id: str | None,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    session = _load_session(conn, session_id)
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)
    run_attempt = _load_run_attempt(conn, attempt_id=attempt_id, session_id=session_id, exercise_id=exercise_id)
    if run_attempt["runtime_status"] == "unsupported":
        raise SessionStateConflictError("unsupported runtime attempts cannot be submitted")

    actual_submit_version = submit_version or 1
    key = default_submit_key(
        session_id=session_id,
        exercise_id=exercise_id,
        attempt_id=attempt_id,
        submit_version=actual_submit_version,
    )
    stored = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    payload_hash = request_hash(request_body)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same submit key was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored submit response is invalid")
        return response, True

    code_hash = provided_code_hash or build_code_hash(code, filled_blanks)
    if code_hash == run_attempt["code_hash"] and filled_blanks == run_attempt["filled_blanks_json"]:
        runtime_result = _runtime_result_from_attempt(run_attempt)
    else:
        runtime_result = run_exercise(exercise, code, filled_blanks, "visible_tests")

    stored_explanation_check_result = _normalized_explanation_check_result(run_attempt.get("explanation_check_result"))
    stored_explanation_text = _string_or_none(run_attempt.get("explanation_text"))
    effective_hint_usage_count = max(hint_usage_count, int(run_attempt.get("hint_usage_count") or 0))
    effective_error_count = max(
        error_count if error_count is not None else 0,
        int(run_attempt.get("error_count") or 0),
        0 if runtime_result.runtime_status == "success" and runtime_result.test_pass_rate >= 1.0 else 1,
    )
    effective_explanation = explanation if explanation is not None else stored_explanation_text
    if explanation is not None and explanation.strip() != (stored_explanation_text or "").strip():
        stored_explanation_check_result = None
    code_completion_result, service_fields = build_code_completion_result(
        exercise,
        runtime_result,
        hint_usage_count=effective_hint_usage_count,
        error_count=effective_error_count,
        explanation=effective_explanation,
        explanation_check_result=stored_explanation_check_result,
    )

    submit_attempt = conn.execute(
        """
        INSERT INTO attempts (
          session_id, exercise_id, user_id, attempt_type, submit_version, submitted_code,
          code_hash, filled_blanks_json, runtime_status, test_pass_rate, passed_test_count,
          total_test_count, score, score_breakdown_json, code_completion_result, fsrs_rating,
          test_results_json, stdout, stderr, error_message, error_cause,
          hint_usage_count, error_count, explanation_text, explanation_check_result,
          evaluation_status, request_id
        )
        VALUES (
          %(session_id)s, %(exercise_id)s, %(user_id)s, 'submit', %(submit_version)s, %(submitted_code)s,
          %(code_hash)s, %(filled_blanks_json)s::jsonb, %(runtime_status)s, %(test_pass_rate)s, %(passed_test_count)s,
          %(total_test_count)s, %(score)s, %(score_breakdown_json)s::jsonb, %(code_completion_result)s::jsonb, %(fsrs_rating)s,
          %(test_results_json)s::jsonb, %(stdout)s, %(stderr)s, %(error_message)s, %(error_cause)s,
          %(hint_usage_count)s, %(error_count)s, %(explanation_text)s, %(explanation_check_result)s::jsonb,
          %(evaluation_status)s, %(request_id)s
        )
        RETURNING *
        """,
        {
            "session_id": session_id,
            "exercise_id": exercise_id,
            "user_id": str(session["user_id"]),
            "submit_version": actual_submit_version,
            "submitted_code": code,
            "code_hash": code_hash,
            "filled_blanks_json": json.dumps(filled_blanks),
            "runtime_status": runtime_result.runtime_status,
            "test_pass_rate": runtime_result.test_pass_rate,
            "passed_test_count": runtime_result.passed_test_count,
            "total_test_count": runtime_result.total_test_count,
            "score": code_completion_result["score"],
            "score_breakdown_json": json.dumps(code_completion_result["score_breakdown"]),
            "code_completion_result": json.dumps(code_completion_result),
            "fsrs_rating": code_completion_result["fsrs_rating"],
            "test_results_json": json.dumps(runtime_result.test_results),
            "stdout": runtime_result.stdout,
            "stderr": runtime_result.stderr,
            "error_message": runtime_result.error_message,
            "error_cause": code_completion_result["error_cause"],
            "hint_usage_count": effective_hint_usage_count,
            "error_count": effective_error_count,
            "explanation_text": effective_explanation,
            "explanation_check_result": json.dumps(service_fields["explanation_check_result"]),
            "evaluation_status": service_fields["evaluation_status"],
            "request_id": _request_id_or_none(request_id),
        },
    ).fetchone()
    if submit_attempt is None:
        raise RuntimeError("submit attempt insert returned no row")

    knowledge_point_result = _update_learning_records(
        conn,
        session=session,
        exercise=exercise,
        submit_attempt=submit_attempt,
        code_completion_result=code_completion_result,
        explanation_check_result=service_fields["explanation_check_result"],
        request_id=request_id,
    )
    response = {
        "attempt_id": str(submit_attempt["id"]),
        "code_completion_result": code_completion_result,
        "KnowledgePoint": knowledge_point_result["KnowledgePoint"],
        "ReviewState": knowledge_point_result["ReviewState"],
        "next_action": code_completion_result["next_action"],
    }
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'submit_learning_session_exercise', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def request_learning_hint(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    exercise_id: str,
    attempt_id: str,
    current_code: str,
    blank_id: str,
    hint_level: str,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    session = _load_session(conn, session_id)
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)
    attempt = _load_run_attempt(conn, attempt_id=attempt_id, session_id=session_id, exercise_id=exercise_id)
    blank = resolve_blank(exercise, blank_id)
    if blank is None:
        raise InvalidLearningSessionRequestError("blank_id does not match the current exercise")

    key = f"hint:{attempt_id}:{blank['blank_key']}:{hint_level}"
    stored = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    payload_hash = request_hash(request_body)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same hint key was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored hint response is invalid")
        return response, True

    next_hint_count = int(attempt.get("hint_usage_count") or 0) + 1
    response = build_hint_response(
        exercise,
        blank=blank,
        hint_level=hint_level,
        current_code=current_code,
        hint_usage_count=next_hint_count,
    )
    conn.execute(
        """
        UPDATE attempts
        SET hint_usage_count = %s
        WHERE id = %s
        """,
        (next_hint_count, attempt_id),
    )
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'request_learning_hint', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def explain_learning_attempt_error(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    attempt_id: str,
    error_message: str,
    stderr: str,
    failed_tests: Sequence[Mapping[str, object]],
    current_code: str,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    session = _load_session(conn, session_id)
    attempt = _load_session_attempt(conn, attempt_id=attempt_id, session_id=session_id, attempt_type="run")
    exercise = _load_session_exercise(conn, exercise_id=str(attempt["exercise_id"]), session=session)
    if not error_message and not stderr and not failed_tests:
        raise InvalidLearningSessionRequestError("error context is required")

    payload_hash = request_hash(request_body)
    key = f"explain-error:{attempt_id}:{payload_hash}"
    stored = conn.execute(
        "SELECT response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    if stored is not None:
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored explain-error response is invalid")
        return response, True

    related_knowledge_points = [_load_knowledge_point_summary(conn, str(exercise["knowledge_point_id"]))]
    response = build_error_explanation_response(
        exercise,
        error_message=error_message,
        stderr=stderr,
        failed_tests=failed_tests,
        current_code=current_code,
        related_knowledge_points=related_knowledge_points,
    )
    conn.execute(
        """
        UPDATE attempts
        SET error_cause = %s
        WHERE id = %s
        """,
        (response["error_cause"], attempt_id),
    )
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'explain_learning_attempt_error', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def check_learning_attempt_explanation(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    attempt_id: str,
    explanation: str,
    focus: str,
    round_number: int,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    if round_number > 2:
        raise EvaluationConflictError("explanation checks are limited to two rounds")

    session = _load_session(conn, session_id)
    attempt = _load_session_attempt(conn, attempt_id=attempt_id, session_id=session_id, attempt_type="run")
    exercise = _load_session_exercise(conn, exercise_id=str(attempt["exercise_id"]), session=session)

    key = f"check-explanation:{attempt_id}:{round_number}"
    stored = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    payload_hash = request_hash(request_body)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same explanation-check round was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored explanation-check response is invalid")
        return response, True

    response = build_explanation_check_response(
        exercise,
        explanation=explanation,
        focus=focus,
        round_number=round_number,
    )
    conn.execute(
        """
        UPDATE attempts
        SET explanation_text = %s,
            explanation_check_result = %s::jsonb
        WHERE id = %s
        """,
        (explanation, json.dumps(response), attempt_id),
    )
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'check_learning_attempt_explanation', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def default_run_key(*, session_id: str, exercise_id: str, code_hash: str, run_mode: str) -> str:
    return f"run-exercise:{session_id}:{exercise_id}:{code_hash}:{run_mode}"


def default_submit_key(*, session_id: str, exercise_id: str, attempt_id: str, submit_version: int) -> str:
    return f"submit-exercise:{session_id}:{exercise_id}:{attempt_id}:{submit_version}"


def build_code_hash(code: str, filled_blanks: Mapping[str, str]) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "code": code,
                "filled_blanks": filled_blanks,
            },
            sort_keys=True,
        ).encode("utf-8"),
    ).hexdigest()
    return f"sha256:{digest}"


def _load_learning_context(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
    knowledge_point_id: str,
) -> Mapping[str, object]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")

    plan = conn.execute(
        """
        SELECT *
        FROM learning_plans
        WHERE id = %s AND user_id = %s AND deleted_at IS NULL
        """,
        (plan_id, user_id),
    ).fetchone()
    if plan is None:
        raise EntityNotFoundError("PLAN_NOT_FOUND", "学习计划不存在")

    context = conn.execute(
        """
        SELECT
          knowledge_points.*,
          plan_modules.plan_id,
          plan_modules.title AS module_title,
          language_courses.title AS course_title,
          runtime_profiles.id AS runtime_profile_id,
          runtime_profiles.slug AS runtime_profile_slug,
          runtime_profiles.runtime_tier,
          runtime_profiles.language AS runtime_language,
          runtime_profiles.runner,
          runtime_profiles.supports_realtime_preview,
          runtime_profiles.supports_stdout,
          runtime_profiles.supports_tests,
          runtime_profiles.compile_required,
          runtime_profiles.timeout_ms,
          runtime_profiles.memory_limit_mb,
          runtime_profiles.sandbox_policy
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        WHERE knowledge_points.id = %s
          AND plan_modules.plan_id = %s
          AND knowledge_points.deleted_at IS NULL
          AND plan_modules.deleted_at IS NULL
        LIMIT 1
        """,
        (knowledge_point_id, plan_id),
    ).fetchone()
    if context is None:
        raise EntityNotFoundError("KNOWLEDGE_POINT_NOT_FOUND", "知识点不存在")
    return context


def _load_session(
    conn: Connection[dict[str, object]],
    session_id: str,
    *,
    allowed_session_types: set[str] | None = None,
) -> Mapping[str, object]:
    expected_types = allowed_session_types or {"learn"}
    session = conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE id = %s AND status = 'active'
        """,
        (session_id,),
    ).fetchone()
    if session is None or str(session["session_type"]) not in expected_types:
        raise EntityNotFoundError("SESSION_NOT_FOUND", "学习会话不存在")
    return session


def _load_session_exercise(
    conn: Connection[dict[str, object]],
    *,
    exercise_id: str,
    session: Mapping[str, object],
) -> dict[str, object]:
    exercise = get_exercise(conn, exercise_id)
    if exercise is None:
        raise EntityNotFoundError("EXERCISE_NOT_FOUND", "练习不存在")
    if exercise["knowledge_point_id"] != str(session["entry_point"]):
        raise SessionStateConflictError("exercise does not belong to the session entry point")
    return exercise


def _load_run_attempt(
    conn: Connection[dict[str, object]],
    *,
    attempt_id: str,
    session_id: str,
    exercise_id: str,
) -> Mapping[str, object]:
    attempt = _load_session_attempt(conn, attempt_id=attempt_id, session_id=session_id, attempt_type="run")
    if str(attempt["exercise_id"]) != exercise_id:
        raise EntityNotFoundError("ATTEMPT_NOT_FOUND", "运行记录不存在")
    return attempt


def _load_session_attempt(
    conn: Connection[dict[str, object]],
    *,
    attempt_id: str,
    session_id: str,
    attempt_type: str,
) -> Mapping[str, object]:
    attempt = conn.execute(
        """
        SELECT *
        FROM attempts
        WHERE id = %s
          AND session_id = %s
          AND attempt_type = %s
        """,
        (attempt_id, session_id, attempt_type),
    ).fetchone()
    if attempt is None:
        raise EntityNotFoundError("ATTEMPT_NOT_FOUND", "运行记录不存在")
    return attempt


def _serialize_runtime_profile(context: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(context["runtime_profile_id"]),
        "slug": context["runtime_profile_slug"],
        "runtime_tier": context["runtime_tier"],
        "language": context["runtime_language"],
        "runner": context["runner"],
        "supports_realtime_preview": context["supports_realtime_preview"],
        "supports_stdout": context["supports_stdout"],
        "supports_tests": context["supports_tests"],
        "compile_required": context["compile_required"],
        "timeout_ms": context["timeout_ms"],
        "memory_limit_mb": context["memory_limit_mb"],
        "sandbox_policy": context["sandbox_policy"],
    }


def _serialize_run_response(attempt: Mapping[str, object], runtime_result: RuntimeExecutionResult) -> dict[str, object]:
    return {
        "attempt_id": str(attempt["id"]),
        "attempt_type": "run",
        "runtime_status": runtime_result.runtime_status,
        "preview_html": runtime_result.preview_html,
        "stdout": runtime_result.stdout,
        "stderr": runtime_result.stderr,
        "test_pass_rate": runtime_result.test_pass_rate,
        "passed_test_count": runtime_result.passed_test_count,
        "total_test_count": runtime_result.total_test_count,
        "test_results": runtime_result.test_results,
        "error_message": runtime_result.error_message,
        "next_action": runtime_result.next_action,
    }


def _runtime_result_from_attempt(attempt: Mapping[str, object]) -> RuntimeExecutionResult:
    test_results = attempt.get("test_results_json") or []
    if not isinstance(test_results, list):
        test_results = []
    return RuntimeExecutionResult(
        runtime_status=str(attempt["runtime_status"]),
        stdout=str(attempt.get("stdout") or ""),
        stderr=str(attempt.get("stderr") or ""),
        test_pass_rate=_decimal_to_float(attempt.get("test_pass_rate")),
        passed_test_count=int(attempt.get("passed_test_count") or 0),
        total_test_count=int(attempt.get("total_test_count") or 0),
        test_results=test_results,
        error_message=str(attempt["error_message"]) if attempt.get("error_message") else None,
        next_action="retry_same",
        preview_html=None,
        core_blank_gate=_decimal_to_float(attempt.get("test_pass_rate")) >= 1.0,
        any_blank_passed=int(attempt.get("passed_test_count") or 0) > 0,
        logic_pass=_decimal_to_float(attempt.get("test_pass_rate")) >= 1.0,
    )


def _update_learning_records(
    conn: Connection[dict[str, object]],
    *,
    session: Mapping[str, object],
    exercise: Mapping[str, object],
    submit_attempt: Mapping[str, object],
    code_completion_result: Mapping[str, object],
    explanation_check_result: Mapping[str, object],
    request_id: str | None,
) -> dict[str, object]:
    return apply_attempt_review_update(
        conn,
        knowledge_point_id=str(exercise["knowledge_point_id"]),
        attempt_id=str(submit_attempt["id"]),
        source="learn_submit",
        request_id=request_id,
    )


def _serialize_knowledge_point(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "mastery_score": _decimal_to_float(row["mastery_score"]),
        "last_exercise_result": row["last_exercise_result"],
        "last_exercise_score": row["last_exercise_score"],
    }


def _load_knowledge_point_summary(
    conn: Connection[dict[str, object]],
    knowledge_point_id: str,
) -> dict[str, object]:
    row = conn.execute(
        """
        SELECT id, title
        FROM knowledge_points
        WHERE id = %s
        """,
        (knowledge_point_id,),
    ).fetchone()
    if row is None:
        raise EntityNotFoundError("KNOWLEDGE_POINT_NOT_FOUND", "知识点不存在")
    return {
        "id": str(row["id"]),
        "title": str(row["title"]),
    }


def _serialize_review_state(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "knowledge_point_id": str(row["knowledge_point_id"]),
        "card_state": row["card_state"],
        "due_at": row["due_at"].isoformat() if row.get("due_at") else None,
        "last_attempt_id": str(row["last_attempt_id"]) if row.get("last_attempt_id") else None,
        "last_fsrs_rating": row.get("last_fsrs_rating"),
        "scheduled_days": row.get("scheduled_days"),
        "reps": row.get("reps"),
        "lapses": row.get("lapses"),
    }


def _initial_agent_message(runtime_tier: str, knowledge_point_title: str) -> str:
    if runtime_tier == "python_stdout_test":
        return f"先看 {knowledge_point_title}：确认 stdout 和 return 各自负责什么。"
    if runtime_tier == "compiled_sandbox_later":
        return f"这次先做 {knowledge_point_title} 的静态补全，不进入完整编译运行。"
    return f"先看 {knowledge_point_title}：关注事件绑定位置和共享状态更新。"


def _request_id_or_none(request_id: str | None) -> str | None:
    if request_id in {None, "", "req_unset"}:
        return None
    return request_id


def _normalized_explanation_check_result(value: object) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0
