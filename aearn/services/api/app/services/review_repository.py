from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime

from psycopg import Connection

from app.models.reviews import ReviewExplanationCheck
from app.services.evaluation import build_code_completion_result
from app.services.exercise_repository import get_exercise, get_or_create_exercise_for_knowledge_point
from app.services.learning_session_repository import build_code_hash
from app.services.plan_repository import IdempotencyConflictError, request_hash
from app.services.review_scheduler import apply_attempt_review_update, forget_risk_for, serialize_review_state
from app.services.runtime_runner import RuntimeExecutionResult, run_exercise
from app.services.user_repository import get_user


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ReviewNotDueError(ValueError):
    pass


class ReviewSessionConflictError(ValueError):
    pass


class InvalidReviewRequestError(ValueError):
    pass


def get_today_reviews(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    due_before: datetime | None,
    limit: int,
) -> dict[str, object]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")

    effective_due_before = _aware_datetime(due_before) if due_before is not None else datetime.now(UTC)
    rows = conn.execute(
        """
        SELECT
          review_states.*,
          knowledge_points.id AS kp_id,
          knowledge_points.title AS kp_title,
          knowledge_points.description AS kp_description,
          knowledge_points.status AS kp_status,
          knowledge_points.weak_points_json AS kp_weak_points_json,
          knowledge_points.mastery_score AS kp_mastery_score
        FROM review_states
        JOIN knowledge_points ON knowledge_points.id = review_states.knowledge_point_id
        JOIN learning_plans ON learning_plans.id = review_states.plan_id
        WHERE review_states.user_id = %s
          AND review_states.due_at IS NOT NULL
          AND review_states.due_at <= %s
          AND review_states.suspended_at IS NULL
          AND learning_plans.status = 'active'
          AND learning_plans.deleted_at IS NULL
          AND knowledge_points.deleted_at IS NULL
        ORDER BY review_states.due_at ASC, review_states.lapses DESC, knowledge_points.mastery_score ASC
        LIMIT %s
        """,
        (user_id, effective_due_before, limit),
    ).fetchall()
    return {
        "items": [_serialize_due_review(row) for row in rows],
        "page_info": {
            "limit": limit,
            "next_cursor": None,
            "has_more": False,
        },
        "timezone": "Asia/Shanghai",
        "generated_at": datetime.now(UTC).isoformat(),
    }


def start_review_session(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    request_id: str | None,
) -> tuple[dict[str, object], bool]:
    context = _load_due_review_context(conn, user_id=user_id, knowledge_point_id=knowledge_point_id)
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
          AND session_type = 'review'
          AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id, context["plan_id"], knowledge_point_id),
    ).fetchone()
    if session is None:
        session = conn.execute(
            """
            INSERT INTO learning_sessions (
              user_id, plan_id, session_type, status, entry_point, next_entry_point, request_id
            )
            VALUES (%s, %s, 'review', 'active', %s, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                context["plan_id"],
                knowledge_point_id,
                knowledge_point_id,
                _request_id_or_none(request_id),
            ),
        ).fetchone()
        if session is None:
            raise RuntimeError("review session insert returned no row")
    else:
        reused = True

    response = {
        "session_id": str(session["id"]),
        "session_type": "review",
        "knowledge_point": {
            "id": str(context["id"]),
            "title": context["title"],
            "status": context["status"],
            "weak_points_json": context["weak_points_json"],
        },
        "review_exercise": exercise,
        "ReviewState": serialize_review_state(context),
        "variant_reason": _variant_reason(context),
        "initial_agent_message": f"这次复习围绕 {context['title']}，先用变体题验证你是否真的能接管这类代码。",
    }
    return response, reused


def submit_review_exercise_result(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    exercise_id: str,
    attempt_id: str | None,
    code: str,
    filled_blanks: Mapping[str, str],
    submit_version: int,
    explanation: str | None,
    hint_usage_count: int,
    error_count: int,
    explanation_check: ReviewExplanationCheck | None,
    provided_code_hash: str | None,
    request_id: str | None,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    code_hash = provided_code_hash or build_code_hash(code, filled_blanks)
    key = f"review-exercise-result:{session_id}:{exercise_id}:{attempt_id or code_hash}:{submit_version}"
    stored = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
        (key,),
    ).fetchone()
    payload_hash = request_hash(request_body)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same review result key was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored review result response is invalid")
        return response, True

    session = _load_review_session(conn, session_id)
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)
    run_attempt = _load_review_run_attempt(
        conn,
        attempt_id=attempt_id,
        session_id=session_id,
        exercise_id=exercise_id,
    )
    if run_attempt is not None and code_hash == run_attempt["code_hash"] and filled_blanks == run_attempt["filled_blanks_json"]:
        runtime_result = _runtime_result_from_attempt(run_attempt)
    else:
        runtime_result = run_exercise(exercise, code, filled_blanks, "visible_tests")

    explanation_check_payload = explanation_check.model_dump() if explanation_check is not None else None
    code_completion_result, service_fields = build_code_completion_result(
        exercise,
        runtime_result,
        hint_usage_count=hint_usage_count,
        error_count=max(error_count, 0 if runtime_result.runtime_status == "success" and runtime_result.test_pass_rate >= 1.0 else 1),
        explanation=explanation,
        explanation_check_result=explanation_check_payload,
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
          %(session_id)s, %(exercise_id)s, %(user_id)s, 'review_submit', %(submit_version)s, %(submitted_code)s,
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
            "submit_version": submit_version,
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
            "hint_usage_count": hint_usage_count,
            "error_count": code_completion_result["error_count"],
            "explanation_text": explanation,
            "explanation_check_result": json.dumps(service_fields["explanation_check_result"]),
            "evaluation_status": service_fields["evaluation_status"],
            "request_id": _request_id_or_none(request_id),
        },
    ).fetchone()
    if submit_attempt is None:
        raise RuntimeError("review submit attempt insert returned no row")

    schedule = apply_attempt_review_update(
        conn,
        knowledge_point_id=str(exercise["knowledge_point_id"]),
        attempt_id=str(submit_attempt["id"]),
        source="review_submit",
        request_id=request_id,
    )
    conn.execute(
        """
        UPDATE learning_sessions
        SET status = 'finished',
            ended_at = now(),
            next_entry_point = %s
        WHERE id = %s
        """,
        (str(exercise["knowledge_point_id"]), session_id),
    )

    response = {
        **code_completion_result,
        "attempt_id": str(submit_attempt["id"]),
        "due_at": schedule["due_at"],
        "forget_risk": schedule["forget_risk"],
        "ReviewState": schedule["ReviewState"],
        "KnowledgePoint": schedule["KnowledgePoint"],
        "code_completion_result": code_completion_result,
        "next_action": code_completion_result["next_action"],
    }
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'submit_review_exercise_result', %s, %s::jsonb)
        """,
        (key, payload_hash, json.dumps(response)),
    )
    return response, False


def due_review_counts(conn: Connection[dict[str, object]]) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT user_id::text AS user_id, count(*)::int AS due_count
        FROM review_states
        WHERE due_at IS NOT NULL
          AND due_at <= now()
          AND suspended_at IS NULL
        GROUP BY user_id
        ORDER BY user_id
        """
    ).fetchall()
    return {str(row["user_id"]): int(row["due_count"]) for row in rows}


def _load_due_review_context(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
) -> Mapping[str, object]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")
    context = conn.execute(
        """
        SELECT
          review_states.*,
          knowledge_points.*,
          learning_plans.status AS plan_status,
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
        FROM review_states
        JOIN knowledge_points ON knowledge_points.id = review_states.knowledge_point_id
        JOIN learning_plans ON learning_plans.id = review_states.plan_id
        JOIN language_courses ON language_courses.id = knowledge_points.language_course_id
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        WHERE review_states.user_id = %s
          AND review_states.knowledge_point_id = %s
          AND knowledge_points.deleted_at IS NULL
          AND learning_plans.deleted_at IS NULL
        LIMIT 1
        """,
        (user_id, knowledge_point_id),
    ).fetchone()
    if context is None:
        raise EntityNotFoundError("KNOWLEDGE_POINT_NOT_FOUND", "知识点不存在")
    if context["plan_status"] != "active" or context.get("suspended_at") is not None or context.get("due_at") is None:
        raise ReviewNotDueError("review is not due")
    due_at = context["due_at"]
    if isinstance(due_at, datetime) and due_at > datetime.now(UTC):
        raise ReviewNotDueError("review is not due")
    return context


def _load_review_session(conn: Connection[dict[str, object]], session_id: str) -> Mapping[str, object]:
    session = conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE id = %s AND session_type = 'review' AND status = 'active'
        """,
        (session_id,),
    ).fetchone()
    if session is None:
        raise EntityNotFoundError("SESSION_NOT_FOUND", "复习会话不存在")
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
        raise ReviewSessionConflictError("exercise does not belong to the review session")
    return exercise


def _load_review_run_attempt(
    conn: Connection[dict[str, object]],
    *,
    attempt_id: str | None,
    session_id: str,
    exercise_id: str,
) -> Mapping[str, object] | None:
    if attempt_id is None:
        return None
    attempt = conn.execute(
        """
        SELECT *
        FROM attempts
        WHERE id = %s
          AND session_id = %s
          AND exercise_id = %s
          AND attempt_type = 'run'
        """,
        (attempt_id, session_id, exercise_id),
    ).fetchone()
    if attempt is None:
        raise EntityNotFoundError("ATTEMPT_NOT_FOUND", "运行记录不存在")
    return attempt


def _runtime_result_from_attempt(attempt: Mapping[str, object]) -> RuntimeExecutionResult:
    test_results = attempt.get("test_results_json") or []
    if not isinstance(test_results, list):
        test_results = []
    return RuntimeExecutionResult(
        runtime_status=str(attempt["runtime_status"]),
        stdout=str(attempt.get("stdout") or ""),
        stderr=str(attempt.get("stderr") or ""),
        test_pass_rate=_float_or_zero(attempt.get("test_pass_rate")),
        passed_test_count=int(attempt.get("passed_test_count") or 0),
        total_test_count=int(attempt.get("total_test_count") or 0),
        test_results=test_results,
        error_message=str(attempt["error_message"]) if attempt.get("error_message") else None,
        next_action="retry_same",
        preview_html=None,
        core_blank_gate=_float_or_zero(attempt.get("test_pass_rate")) >= 1.0,
        any_blank_passed=int(attempt.get("passed_test_count") or 0) > 0,
        logic_pass=_float_or_zero(attempt.get("test_pass_rate")) >= 1.0,
    )


def _serialize_due_review(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "ReviewState": serialize_review_state(row),
        "KnowledgePoint": {
            "id": str(row["kp_id"]),
            "title": row["kp_title"],
            "description": row["kp_description"],
            "status": row["kp_status"],
            "weak_points_json": row["kp_weak_points_json"],
            "mastery_score": _float_or_zero(row.get("kp_mastery_score")),
        },
        "forget_risk": forget_risk_for(serialize_review_state(row)),
    }


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


def _variant_reason(context: Mapping[str, object]) -> str:
    weak_points = context.get("weak_points_json") or []
    if isinstance(weak_points, list) and weak_points:
        return f"上次薄弱点是 {weak_points[0]}，本次用同一知识点的变体题确认迁移能力。"
    if context.get("last_fsrs_rating") == "Again":
        return "上次复习未通过，本次先用更短路径确认核心概念。"
    return "本次不重复聊天问答，改用同构代码练习检查是否能独立验证。"


def _request_id_or_none(request_id: str | None) -> str | None:
    if request_id in {None, "", "req_unset"}:
        return None
    return request_id


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _float_or_zero(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return float(value) if value is not None else 0.0
