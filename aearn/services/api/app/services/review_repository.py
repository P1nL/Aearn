from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from psycopg import Connection

from app.agents.guardrails import assert_safe_teaching_output
from app.agents.review_coach_agent import ReviewCoachContext, build_sdk_review_coach_response
from app.agents.structured_judgement import (
    FieldPolicy,
    JudgementPolicy,
    StructuredJudgement,
    coerce_structured_judgements,
    normalize_judgements,
)
from app.models.reviews import ReviewAIPatchAnswer, ReviewExplanationCheck
from app.services.evaluation import build_code_completion_result, build_review_ai_patch_completion_result
from app.services.exercise_repository import get_exercise
from app.services.learner_profile import merge_stable_profile_signals
from app.services.learning_session_repository import build_code_hash
from app.services.plan_repository import IdempotencyConflictError, request_hash
from app.services.review_scheduler import apply_attempt_review_update, forget_risk_for, serialize_review_state
from app.services.review_seed_bank import (
    build_review_warmup,
    ensure_ready_review_seed_bank,
    materialize_review_seed_exercise,
    select_review_seed,
    serialize_seed_bank,
)
from app.services.runtime_runner import RuntimeExecutionResult, run_exercise
from app.services.llm_client import LLMCallError, LLMInvalidResponseError
from app.services.user_repository import get_user


REVIEW_WARMUP_JUDGEMENT_POLICY = JudgementPolicy(
    fields=[
        FieldPolicy(
            name="warmup_correctness",
            required=True,
            fallback_question="请用一句话说明你记得的关键风险；如果不确定也可以跳过热身。",
        ),
    ],
    default_fallback_question="请用一句话说明你记得的关键风险；如果不确定也可以跳过热身。",
)
REVIEW_EXPLANATION_JUDGEMENT_POLICY = JudgementPolicy(
    fields=[
        FieldPolicy(
            name="review_explanation_sufficiency",
            required=True,
            fallback_question="请再补充这次复习提交为什么能覆盖当前知识点风险。",
        ),
        FieldPolicy(
            name="weak_point_signal",
            required=False,
            fallback_question="请指出这次答案和薄弱点之间的关系。",
            blocks_on=("ambiguous", "unsupported"),
        ),
        FieldPolicy(
            name="repair_needed",
            required=False,
            fallback_question="请明确下一步是重试还是进入变体练习。",
            blocks_on=("ambiguous", "unsupported"),
        ),
    ],
    default_fallback_question="请再补一句这次提交为什么能覆盖当前知识点风险。",
)


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

    state = _review_stage_state_from_session(session)
    exercise: dict[str, object] | None = None
    seed_bank_payload: dict[str, object] | None = None
    selected_seed_id: str | None = None
    if state is not None:
        exercise_id = _state_exercise_id(state)
        if exercise_id is not None:
            exercise = get_exercise(conn, exercise_id)
        selected_seed_id = _state_seed_id(state)

    if exercise is None or state is None:
        seed_bank = ensure_ready_review_seed_bank(conn, context=context, runtime_profile=runtime_profile)
        seed = select_review_seed(seed_bank=seed_bank, context=context, runtime_profile=runtime_profile)
        exercise = materialize_review_seed_exercise(
            conn,
            seed_bank=seed_bank,
            seed=seed,
            context=context,
            runtime_profile=runtime_profile,
        )
        state = _initial_review_stage_state(
            context=context,
            seed_bank_id=str(seed_bank["id"]),
            seed=seed,
            exercise=exercise,
        )
        seed_bank_payload = serialize_seed_bank(seed_bank)
        selected_seed_id = str(seed["id"])

    if session is None:
        session = conn.execute(
            """
            INSERT INTO learning_sessions (
              user_id, plan_id, session_type, status, entry_point, next_entry_point,
              review_stage, review_stage_state_json, request_id
            )
            VALUES (%s, %s, 'review', 'active', %s, %s, %s, %s::jsonb, %s)
            RETURNING *
            """,
            (
                user_id,
                context["plan_id"],
                knowledge_point_id,
                knowledge_point_id,
                "warmup",
                json.dumps(state),
                _request_id_or_none(request_id),
            ),
        ).fetchone()
        if session is None:
            raise RuntimeError("review session insert returned no row")
    else:
        reused = True
        conn.execute(
            """
            UPDATE learning_sessions
            SET review_stage = %s,
                review_stage_state_json = %s::jsonb
            WHERE id = %s
            """,
            (_stage_from_state(state), json.dumps(state), session["id"]),
        )
        session = dict(session)
        session["review_stage"] = _stage_from_state(state)
        session["review_stage_state_json"] = state

    response: dict[str, object] = {
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
        "review_stage": _stage_from_state(state),
        "review_stage_state": state,
        "warmup": state["warmup"],
        "selected_seed_id": selected_seed_id,
    }
    if seed_bank_payload is not None:
        response["seed_bank"] = seed_bank_payload
    review_coach_context = _build_review_coach_context(context, exercise, conn)
    review_coach_response = build_sdk_review_coach_response(review_coach_context)
    if review_coach_response is None:
        raise LLMCallError("Review coach requires configured model API")
    response["variant_reason"] = _safe_review_coach_text(review_coach_response.get("variant_reason"))
    response["initial_agent_message"] = _safe_review_coach_text(
        review_coach_response.get("initial_agent_message"),
    )
    return response, reused


def submit_review_exercise_result(
    conn: Connection[dict[str, object]],
    *,
    user_id: str | None = None,
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
    review_ai_patch_answer: ReviewAIPatchAnswer | None,
    provided_code_hash: str | None,
    request_id: str | None,
    request_body: Mapping[str, object],
) -> tuple[dict[str, object], bool]:
    answer_payload = review_ai_patch_answer.model_dump() if review_ai_patch_answer is not None else None
    code_hash = provided_code_hash or _review_submit_code_hash(code, filled_blanks, answer_payload)
    key = f"review-exercise-result:{session_id}:{exercise_id}:{attempt_id or code_hash}:{submit_version}"
    payload_hash = request_hash(request_body)
    stored = _load_idempotency_record(conn, key, user_id=user_id)
    if stored is not None:
        if stored["request_hash"] != payload_hash:
            raise IdempotencyConflictError("same review result key was used with a different request body")
        response = stored["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored review result response is invalid")
        return response, True

    session = _load_review_session(conn, session_id, user_id=user_id)
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)

    if exercise["exercise_type"] == "review_ai_patch":
        if answer_payload is None:
            raise InvalidReviewRequestError("review_ai_patch_answer is required")
        submitted_code = code or json.dumps(answer_payload, ensure_ascii=False)
        runtime_result = RuntimeExecutionResult(
            runtime_status="success",
            stdout="",
            stderr="",
            test_pass_rate=1.0,
            passed_test_count=0,
            total_test_count=0,
            test_results=[],
            error_message=None,
            next_action="schedule_review",
            preview_html=None,
            core_blank_gate=True,
            any_blank_passed=True,
            logic_pass=True,
        )
        code_completion_result, service_fields = build_review_ai_patch_completion_result(exercise, answer_payload)
    else:
        if not code.strip():
            raise InvalidReviewRequestError("code must not be blank")
        submitted_code = code
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
        blocked_response = _blocked_review_explanation_check_response(explanation_check_payload)
        if blocked_response is not None:
            conn.execute(
                """
                INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
                VALUES (%s, 'submit_review_exercise_result', %s, %s::jsonb, %s)
                """,
                (key, payload_hash, json.dumps(blocked_response), str(session["user_id"])),
            )
            return blocked_response, False
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
            "submitted_code": submitted_code,
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
    merge_stable_profile_signals(
        conn,
        str(session["user_id"]),
        attempt=submit_attempt,
        knowledge_point={"id": str(exercise["knowledge_point_id"]), "title": str(exercise.get("knowledge_point_title") or exercise.get("title") or "")},
        session_id=session_id,
        source="review_submit",
    )
    submitted_state = _mark_review_stage_submitted(session)
    conn.execute(
        """
        UPDATE learning_sessions
        SET status = 'finished',
            ended_at = now(),
            next_entry_point = %s,
            review_stage = 'submitted',
            review_stage_state_json = %s::jsonb
        WHERE id = %s
        """,
        (str(exercise["knowledge_point_id"]), json.dumps(submitted_state), session_id),
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
        INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
        VALUES (%s, 'submit_review_exercise_result', %s, %s::jsonb, %s)
        """,
        (key, payload_hash, json.dumps(response), str(session["user_id"])),
    )
    return response, False


def record_review_warmup_result(
    conn: Connection[dict[str, object]],
    *,
    user_id: str | None = None,
    session_id: str,
    action: str,
    answer: str | None,
) -> dict[str, object]:
    session = _load_review_session(conn, session_id, user_id=user_id)
    state = _review_stage_state_from_session(session)
    if state is None:
        raise ReviewSessionConflictError("review session has no warmup state")
    warmup = _mapping_or_empty(state.get("warmup"))
    if action == "skip":
        result = "skipped"
    else:
        result = _evaluate_warmup_answer(
            answer=answer or "",
            expected_focus=str(warmup.get("expected_focus") or ""),
            question=str(warmup.get("question") or ""),
        )
    normalized_warmup = _normalize_review_warmup_judgement(result)
    if not normalized_warmup["ready"]:
        response_warmup = dict(warmup)
        feedback = str(
            normalized_warmup.get("clarification_question")
            or _warmup_feedback(result)
        )
        response_warmup.update(
            {
                "result": result,
                "last_answer": answer,
                "feedback": feedback,
                "judgement_ready": False,
                "judgement_blocking_fields": normalized_warmup["blocking_fields"],
                "clarification_question": feedback,
            }
        )
        response_state = dict(state)
        response_state["warmup"] = response_warmup
        return {
            "session_id": session_id,
            "review_stage": str(session.get("review_stage") or _stage_from_state(state)),
            "warmup": response_warmup,
            "review_stage_state": response_state,
            "next_action": "retry_same",
        }
    repair_count = _int_or_zero(warmup.get("repair_count"))
    next_stage = "variant_practice"
    feedback = _warmup_feedback(result)
    if result in {"incorrect", "unclear"} and repair_count < 1:
        next_stage = "warmup_repair"
        repair_count += 1
        feedback = "先做一次短修正：用一句话指出当前知识点里最容易出错的风险，然后进入变体题。"
    elif result in {"incorrect", "unclear"}:
        variant = _mapping_or_empty(state.get("variant"))
        variant["guided"] = True
        state["variant"] = variant

    updated_warmup = dict(warmup)
    updated_warmup.update(
        {
            "result": result,
            "last_answer": answer,
            "repair_count": repair_count,
            "feedback": feedback,
        }
    )
    state["warmup"] = updated_warmup
    state["review_stage"] = next_stage
    conn.execute(
        """
        UPDATE learning_sessions
        SET review_stage = %s,
            review_stage_state_json = %s::jsonb
        WHERE id = %s
        """,
        (next_stage, json.dumps(state), session_id),
    )
    return {
        "session_id": session_id,
        "review_stage": next_stage,
        "warmup": updated_warmup,
        "review_stage_state": state,
        "next_action": "start_variant",
    }


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
    return {str(row["user_id"]): _int_or_zero(row["due_count"]) for row in rows}


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


def _load_review_session(
    conn: Connection[dict[str, object]],
    session_id: str,
    *,
    user_id: str | None = None,
) -> Mapping[str, object]:
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
    if user_id is not None and str(session["user_id"]) != user_id:
        raise EntityNotFoundError("SESSION_NOT_FOUND", "复习会话不存在")
    return session


def _load_idempotency_record(
    conn: Connection[dict[str, object]],
    key: str,
    *,
    user_id: str | None,
) -> Mapping[str, object] | None:
    if user_id is None:
        return conn.execute(
            """
            SELECT request_hash, response_json
            FROM idempotency_records
            WHERE key = %s
              AND invalidated_at IS NULL
            """,
            (key,),
        ).fetchone()
    return conn.execute(
        """
        SELECT request_hash, response_json
        FROM idempotency_records
        WHERE key = %s
          AND user_id = %s
          AND invalidated_at IS NULL
        """,
        (key, user_id),
    ).fetchone()


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
        passed_test_count=_int_or_zero(attempt.get("passed_test_count")),
        total_test_count=_int_or_zero(attempt.get("total_test_count")),
        test_results=test_results,
        error_message=str(attempt["error_message"]) if attempt.get("error_message") else None,
        next_action="retry_same",
        preview_html=None,
        core_blank_gate=_float_or_zero(attempt.get("test_pass_rate")) >= 1.0,
        any_blank_passed=_int_or_zero(attempt.get("passed_test_count")) > 0,
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


def _safe_review_coach_text(value: object) -> str:
    if not isinstance(value, str):
        raise LLMInvalidResponseError("Review coach response field must be a string")
    stripped = value.strip()
    if not stripped:
        raise LLMInvalidResponseError("Review coach response field must not be blank")
    assert_safe_teaching_output(stripped)
    return stripped


def _initial_agent_message(context: Mapping[str, object]) -> str:
    return f"这次复习围绕 {context['title']}，先用变体题验证你是否真的能接管这类代码。"


def _build_review_coach_context(
    context: Mapping[str, object],
    exercise: Mapping[str, object],
    conn: Connection[dict[str, object]],
) -> ReviewCoachContext:
    latest_attempt = _load_latest_review_attempt_summary(
        conn,
        user_id=str(context["user_id"]),
        knowledge_point_id=str(context["id"]),
        attempt_id=str(context["last_attempt_id"]) if context.get("last_attempt_id") else None,
    )
    return ReviewCoachContext(
        knowledge_point_id=str(context["id"]),
        knowledge_point_title=str(context["title"]),
        knowledge_point_description=str(context.get("description") or ""),
        weak_points_json=tuple(str(item) for item in _string_list(context.get("weak_points_json"))[:8]),
        mastery_score=_float_or_zero(context.get("mastery_score")) if context.get("mastery_score") is not None else None,
        due_at=_iso_or_none(context.get("due_at")),
        forget_risk=forget_risk_for(serialize_review_state(context)),
        last_fsrs_rating=str(context.get("last_fsrs_rating")) if context.get("last_fsrs_rating") else None,
        review_exercise_id=str(exercise["id"]),
        review_exercise_title=str(exercise["title"]),
        review_exercise_type=str(exercise["exercise_type"]),
        review_exercise_prompt=str(exercise.get("prompt_markdown") or ""),
        runtime_language=str(_exercise_runtime_profile(exercise)["language"]),
        runtime_tier=str(_exercise_runtime_profile(exercise)["runtime_tier"]),
        visible_tests=_visible_review_tests(exercise),
        latest_attempt=latest_attempt,
    )


def _load_latest_review_attempt_summary(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    knowledge_point_id: str,
    attempt_id: str | None,
) -> Mapping[str, object] | None:
    if attempt_id is None:
        return None
    row = conn.execute(
        """
        SELECT
          attempts.id,
          attempts.attempt_type,
          attempts.runtime_status,
          attempts.test_pass_rate,
          attempts.passed_test_count,
          attempts.total_test_count,
          attempts.error_message,
          attempts.error_cause,
          attempts.explanation_text,
          attempts.hint_usage_count,
          attempts.error_count,
          attempts.score,
          attempts.fsrs_rating
        FROM attempts
        JOIN exercises ON exercises.id = attempts.exercise_id
        WHERE attempts.id = %s
          AND attempts.user_id = %s
          AND exercises.knowledge_point_id = %s
        LIMIT 1
        """,
        (attempt_id, user_id, knowledge_point_id),
    ).fetchone()
    if row is None:
        return None
    return {
        "attempt_id": str(row["id"]),
        "attempt_type": row["attempt_type"],
        "runtime_status": row["runtime_status"],
        "test_pass_rate": _float_or_zero(row.get("test_pass_rate")),
        "passed_test_count": row["passed_test_count"],
        "total_test_count": row["total_test_count"],
        "error_message": row["error_message"],
        "error_cause": row["error_cause"],
        "explanation_text": row["explanation_text"],
        "hint_usage_count": row["hint_usage_count"],
        "error_count": row["error_count"],
        "score": row["score"],
        "fsrs_rating": row["fsrs_rating"],
    }


def _visible_review_tests(exercise: Mapping[str, object]) -> list[dict[str, object]]:
    tests = exercise.get("test_cases") or []
    if not isinstance(tests, list):
        return []
    visible: list[dict[str, object]] = []
    for test in tests:
        if not isinstance(test, Mapping):
            continue
        if str(test.get("case_type") or "").lower() == "hidden":
            continue
        visible.append(
            {
                "case_type": test.get("case_type"),
                "weight": test.get("weight"),
                "is_critical": bool(test.get("is_critical", False)),
                "timeout_ms": test.get("timeout_ms"),
                "order_index": test.get("order_index"),
            }
        )
    return visible[:8]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _review_stage_state_from_session(session: Mapping[str, object] | None) -> dict[str, object] | None:
    if session is None:
        return None
    state = session.get("review_stage_state_json")
    if not isinstance(state, Mapping):
        return None
    if not isinstance(state.get("warmup"), Mapping) or not isinstance(state.get("variant"), Mapping):
        return None
    return dict(state)


def _initial_review_stage_state(
    *,
    context: Mapping[str, object],
    seed_bank_id: str,
    seed: Mapping[str, object],
    exercise: Mapping[str, object],
) -> dict[str, object]:
    return {
        "review_stage": "warmup",
        "knowledge_point_id": str(context["id"]),
        "seed_bank_id": seed_bank_id,
        "seed_id": str(seed["id"]),
        "warmup": build_review_warmup(seed, context),
        "variant": {
            "exercise_id": str(exercise["id"]),
            "exercise_type": str(exercise["exercise_type"]),
            "guided": False,
            "selection_reason": _variant_reason(context),
        },
    }


def _state_exercise_id(state: Mapping[str, object]) -> str | None:
    variant = state.get("variant")
    if not isinstance(variant, Mapping):
        return None
    exercise_id = variant.get("exercise_id")
    return str(exercise_id) if exercise_id else None


def _state_seed_id(state: Mapping[str, object]) -> str | None:
    seed_id = state.get("seed_id")
    return str(seed_id) if seed_id else None


def _stage_from_state(state: Mapping[str, object]) -> str:
    stage = state.get("review_stage")
    if stage in {"warmup", "warmup_repair", "variant_practice", "submitted"}:
        return str(stage)
    warmup = state.get("warmup")
    if isinstance(warmup, Mapping) and warmup.get("result") in {"correct", "skipped"}:
        return "variant_practice"
    return "warmup"


def _mark_review_stage_submitted(session: Mapping[str, object]) -> dict[str, object]:
    state = _review_stage_state_from_session(session) or {}
    state["review_stage"] = "submitted"
    return state


def _normalize_review_warmup_judgement(result: str) -> dict[str, object]:
    if result in {"correct", "incorrect", "skipped"}:
        judgement = StructuredJudgement(status="confirmed")
    elif result == "unclear":
        judgement = StructuredJudgement(
            status="ambiguous",
            ambiguity_type="answer_unclear",
            clarification_question=REVIEW_WARMUP_JUDGEMENT_POLICY.default_fallback_question,
        )
    else:
        judgement = StructuredJudgement(
            status="unsupported",
            ambiguity_reason="warmup result is unsupported",
            clarification_question=REVIEW_WARMUP_JUDGEMENT_POLICY.default_fallback_question,
        )
    normalized = normalize_judgements(
        {"warmup_correctness": result},
        {"warmup_correctness": judgement},
        REVIEW_WARMUP_JUDGEMENT_POLICY,
    )
    return {
        "ready": normalized.ready,
        "blocking_fields": list(normalized.blocking_fields),
        "clarification_question": normalized.clarification_question,
    }


def _blocked_review_explanation_check_response(
    explanation_check_payload: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if explanation_check_payload is None:
        return None
    normalized = _normalize_review_explanation_check_judgement(explanation_check_payload)
    if normalized["ready"]:
        return None
    question = str(
        normalized.get("clarification_question")
        or "请再补一句这次提交为什么能覆盖当前知识点风险。"
    )
    response = {
        "result": "failed",
        "score": 0,
        "score_breakdown": {"explanation_check": 0},
        "hard_gates": {
            "runtime_gate": False,
            "test_gate": False,
            "core_blank_gate": False,
            "explanation_gate": False,
        },
        "test_pass_rate": 0.0,
        "hint_usage_count": 0,
        "error_count": 0,
        "weak_points": [],
        "error_cause": None,
        "feedback": question,
        "next_action": "retry_same",
        "fsrs_rating": "Again",
        "judgement_ready": False,
        "judgement_blocking_fields": normalized["blocking_fields"],
        "clarification_question": question,
    }
    response["code_completion_result"] = dict(response)
    return response


def _normalize_review_explanation_check_judgement(
    payload: Mapping[str, object],
) -> dict[str, object]:
    raw_judgements = payload.get("judgements")
    if isinstance(raw_judgements, Mapping):
        judgements = coerce_structured_judgements(raw_judgements, REVIEW_EXPLANATION_JUDGEMENT_POLICY)
    else:
        judgements = {
            "review_explanation_sufficiency": StructuredJudgement(status="confirmed"),
            "weak_point_signal": StructuredJudgement(status="confirmed"),
            "repair_needed": StructuredJudgement(status="confirmed"),
        }
    normalized = normalize_judgements(
        {
            "review_explanation_sufficiency": payload.get("result"),
            "weak_point_signal": payload.get("feedback"),
            "repair_needed": payload.get("result") if str(payload.get("result") or "") != "passed" else None,
        },
        judgements,
        REVIEW_EXPLANATION_JUDGEMENT_POLICY,
    )
    return {
        "ready": normalized.ready,
        "blocking_fields": list(normalized.blocking_fields),
        "clarification_question": normalized.clarification_question,
    }


def _evaluate_warmup_answer(*, answer: str, expected_focus: str, question: str) -> str:
    normalized = answer.strip().lower()
    if not normalized or normalized in {"不太确定", "完全忘了", "不知道", "unclear", "not sure"}:
        return "unclear"
    focus_tokens = [token.lower() for token in expected_focus.replace("_", " ").split() if len(token) >= 2]
    if focus_tokens and any(token in normalized for token in focus_tokens[:6]):
        return "correct"
    concept_markers = ("状态", "作用域", "返回", "stdout", "测试", "class", "selector", "state", "scope", "return", "test")
    if any(marker in normalized for marker in concept_markers):
        return "correct"
    if len(answer.strip()) >= 20 and any(marker in question for marker in ("出错", "风险", "回忆")):
        return "correct"
    return "incorrect"


def _warmup_feedback(result: str) -> str:
    if result == "correct":
        return "热身通过，继续完成变体练习。"
    if result == "skipped":
        return "已跳过热身，本轮 FSRS 仍只看变体练习提交。"
    if result == "unclear":
        return "回答还不够明确，先用一句话补充风险点。"
    return "回答和当前知识点不匹配，先做一次短修正。"


def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _review_submit_code_hash(
    code: str,
    filled_blanks: Mapping[str, str],
    review_ai_patch_answer: Mapping[str, object] | None,
) -> str:
    if review_ai_patch_answer is not None:
        return build_code_hash(json.dumps(review_ai_patch_answer, sort_keys=True, ensure_ascii=False), {})
    return build_code_hash(code, filled_blanks)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _request_id_or_none(request_id: str | None) -> str | None:
    if request_id in {None, "", "req_unset"}:
        return None
    return request_id


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _float_or_zero(value: object) -> float:
    if value is None:
        return 0.0
    try:
        return float(cast(Any, value))
    except (TypeError, ValueError):
        return 0.0
    return 0.0


def _int_or_zero(value: object) -> int:
    if value is None:
        return 0
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return 0


def _exercise_runtime_profile(exercise: Mapping[str, object]) -> Mapping[str, object]:
    runtime_profile = exercise.get("runtime_profile")
    if not isinstance(runtime_profile, Mapping):
        raise RuntimeError("exercise runtime profile is invalid")
    return runtime_profile
