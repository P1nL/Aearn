from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from psycopg import Connection

from app.agents.runtime.guardrails import assert_safe_teaching_output
from app.agents.review.review_coach_agent import (
    ReviewCoachContext,
    ReviewWarmupJudgementContext,
    build_sdk_review_coach_response,
    build_sdk_review_warmup_judgement_response,
)
from app.agents.runtime.structured_judgement import (
    FieldPolicy,
    JudgementPolicy,
    StructuredJudgement,
    coerce_structured_judgements,
    normalize_judgements,
)
from app.models.reviews import ReviewAIPatchAnswer, ReviewExplanationCheck
from app.services.exercises.evaluation import build_code_completion_result, build_review_ai_patch_completion_result
from app.services.exercises.exercise_repository import get_exercise
from app.services.repositories.learner_profile import merge_stable_profile_signals
from app.services.repositories.learning_session_repository import build_code_hash
from app.services.repositories.plan_repository import IdempotencyConflictError, request_hash
from app.services.repositories.review_scheduler import apply_review_batch_update, forget_risk_for, serialize_review_state
from app.services.repositories.review_seed_bank import (
    GENERATOR_VERSION as REVIEW_CANDIDATE_POOL_VERSION,
    build_review_warmup,
    ensure_ready_review_seed_bank,
    materialize_review_seed_exercise,
    select_review_seed,
    serialize_seed_bank,
)
from app.services.runners.runtime_runner import RuntimeExecutionResult, run_exercise
from app.services.llm.llm_client import LLMCallError, LLMInvalidResponseError
from app.services.repositories.user_repository import get_user


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

REVIEW_BATCH_SCHEMA_VERSION = "review_batch_v1"
_REVIEW_BATCH_STAGES = {"warmup", "warmup_repair", "exercise", "exercise_feedback", "final_summary", "submitted"}


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


class ReviewAdaptiveSupplementRequired(ValueError):
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
            seed_bank=seed_bank,
            seed=seed,
            exercise=exercise,
        )
        seed_bank_payload = serialize_seed_bank(seed_bank)
        selected_seed_id = str(seed["id"])
    else:
        state = _ensure_review_batch_state(
            state,
            context=context,
            exercise=exercise,
        )
        state = _hydrate_completed_review_entries(conn, state)
        selected_seed_id = _state_seed_id(state)

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
                _stage_from_state(state),
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
        "current_node": _current_review_node(state, exercise=exercise),
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
        if response.get("error_code") == "REVIEW_ADAPTIVE_SUPPLEMENT_FAILED":
            raise ReviewAdaptiveSupplementRequired(str(response.get("error_message") or "adaptive supplement is required"))
        return response, True

    session = _load_review_session(conn, session_id, user_id=user_id)
    exercise = _load_session_exercise(conn, exercise_id=exercise_id, session=session)
    state = _review_stage_state_from_session(session)
    if state is None:
        raise ReviewSessionConflictError("review session has no batch state")
    state = _ensure_review_batch_state(state, exercise=exercise)
    if _stage_from_state(state) != "exercise":
        raise ReviewSessionConflictError("review session current node is not a formal exercise")
    batch = _mapping_or_empty(state.get("batch"))
    if str(batch.get("current_exercise_id") or "") != exercise_id:
        raise ReviewSessionConflictError("submitted exercise does not match active review exercise")
    current_entry = _current_plan_entry(state)
    if str(current_entry.get("status") or "") not in {"active", ""}:
        raise ReviewSessionConflictError("active review exercise has already been completed")

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
            blocked_response.update(
                {
                    "review_stage": _stage_from_state(state),
                    "review_stage_state": state,
                    "current_node": _current_review_node(state, exercise=exercise),
                    "review_exercise": exercise,
                }
            )
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

    state = _complete_current_review_plan_entry(
        state,
        exercise=exercise,
        attempt=submit_attempt,
        code_completion_result=code_completion_result,
        service_fields=service_fields,
    )
    state["session_diagnosis"] = _updated_formal_session_diagnosis(
        state.get("session_diagnosis"),
        completed_entry=_current_completed_plan_entry(state, str(submit_attempt["id"])),
        code_completion_result=code_completion_result,
    )
    state = _refresh_review_batch_progress(state)

    if _should_finalize_review_batch(state):
        final_rating, aggregate_result = _aggregate_review_batch_rating(state)
        schedule = apply_review_batch_update(
            conn,
            knowledge_point_id=str(exercise["knowledge_point_id"]),
            representative_attempt_id=str(submit_attempt["id"]),
            final_rating=final_rating,
            aggregate_result=aggregate_result,
            source="review_submit",
            request_id=_request_id_or_none(request_id) or _batch_finalization_request_id(session_id, str(submit_attempt["id"]), final_rating),
        )
        profile_attempt = _representative_profile_attempt(
            submit_attempt,
            final_rating=final_rating,
            aggregate_result=aggregate_result,
        )
        merge_stable_profile_signals(
            conn,
            str(session["user_id"]),
            attempt=profile_attempt,
            knowledge_point={
                "id": str(exercise["knowledge_point_id"]),
                "title": str(exercise.get("knowledge_point_title") or exercise.get("title") or ""),
            },
            session_id=session_id,
            source="review_submit",
        )
        state = _mark_review_batch_finalized(
            state,
            representative_attempt_id=str(submit_attempt["id"]),
            final_rating=final_rating,
            aggregate_result=aggregate_result,
            schedule=schedule,
        )
        conn.execute(
            """
            UPDATE learning_sessions
            SET status = 'finished',
                ended_at = now(),
                next_entry_point = %s,
                review_stage = 'final_summary',
                review_stage_state_json = %s::jsonb
            WHERE id = %s
            """,
            (str(exercise["knowledge_point_id"]), json.dumps(state), session_id),
        )
        response = {
            **code_completion_result,
            "attempt_id": str(submit_attempt["id"]),
            "due_at": schedule["due_at"],
            "forget_risk": schedule["forget_risk"],
            "ReviewState": schedule["ReviewState"],
            "KnowledgePoint": schedule["KnowledgePoint"],
            "code_completion_result": code_completion_result,
            "review_stage": "final_summary",
            "review_stage_state": state,
            "current_node": _current_review_node(state, exercise=None),
            "final_result": {
                "final_fsrs_rating": final_rating,
                "aggregate_result": aggregate_result,
                "due_at": schedule["due_at"],
                "forget_risk": schedule["forget_risk"],
            },
            "next_action": "schedule_review",
        }
    else:
        context = _load_due_review_context(conn, user_id=str(session["user_id"]), knowledge_point_id=str(exercise["knowledge_point_id"]))
        runtime_profile = _serialize_runtime_profile(context)
        try:
            next_exercise = _advance_to_next_review_exercise(
                conn,
                state,
                context=context,
                runtime_profile=runtime_profile,
            )
        except ReviewAdaptiveSupplementRequired as exc:
            _mark_adaptive_supplement_needed(state, reason=str(exc))
            state["review_stage"] = "exercise"
            conn.execute(
                """
                UPDATE learning_sessions
                SET status = 'active',
                    next_entry_point = %s,
                    review_stage = 'exercise',
                    review_stage_state_json = %s::jsonb
                WHERE id = %s
                """,
                (str(exercise["knowledge_point_id"]), json.dumps(state), session_id),
            )
            conn.execute(
                """
                INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
                VALUES (%s, 'submit_review_exercise_result', %s, %s::jsonb, %s)
                """,
                (
                    key,
                    payload_hash,
                    json.dumps(
                        {
                            "error_code": "REVIEW_ADAPTIVE_SUPPLEMENT_FAILED",
                            "error_message": str(exc),
                        }
                    ),
                    str(session["user_id"]),
                ),
            )
            raise
        state["review_stage"] = "exercise"
        conn.execute(
            """
            UPDATE learning_sessions
            SET status = 'active',
                next_entry_point = %s,
                review_stage = 'exercise',
                review_stage_state_json = %s::jsonb
            WHERE id = %s
            """,
            (str(exercise["knowledge_point_id"]), json.dumps(state), session_id),
        )
        response = {
            **code_completion_result,
            "attempt_id": str(submit_attempt["id"]),
            "code_completion_result": code_completion_result,
            "review_exercise": next_exercise,
            "review_stage": "exercise",
            "review_stage_state": state,
            "current_node": _current_review_node(state, exercise=next_exercise),
            "next_action": "next_exercise",
            "final_result": None,
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
    exercise_id = _state_exercise_id(state)
    exercise = get_exercise(conn, exercise_id) if exercise_id is not None else None
    state = _ensure_review_batch_state(state, exercise=exercise)
    warmup = _mapping_or_empty(state.get("warmup"))
    if action == "skip":
        result = "skipped"
        judgement_source = "explicit_skip"
        judgement_model = None
        model_feedback = None
    else:
        judgement = build_sdk_review_warmup_judgement_response(
            ReviewWarmupJudgementContext(
                knowledge_point_title=str(
                    exercise.get("knowledge_point_title")
                    or exercise.get("title")
                    or ""
                )
                if exercise is not None
                else "",
                question=str(warmup.get("question") or ""),
                expected_focus=str(warmup.get("expected_focus") or ""),
                learner_answer=answer or "",
                repair_count=_int_or_zero(warmup.get("repair_count")),
            )
        )
        result = (
            str(judgement["result"])
            if judgement is not None
            else _evaluate_warmup_answer(
                answer=answer or "",
                expected_focus=str(warmup.get("expected_focus") or ""),
                question=str(warmup.get("question") or ""),
            )
        )
        judgement_source = str(judgement.get("generation_source") or "llm") if judgement is not None else "heuristic_fallback"
        judgement_model = str(judgement.get("generation_model") or "") if judgement is not None else None
        model_feedback = str(judgement.get("feedback") or "") if judgement is not None else None
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
            "current_node": _current_review_node(response_state, exercise=exercise),
            "next_action": "retry_same",
        }
    repair_count = _int_or_zero(warmup.get("repair_count"))
    recall_level = _warmup_recall_level(result)
    next_stage = "exercise"
    feedback = model_feedback or _warmup_feedback(result)
    if recall_level in {"fuzzy", "wrong"} and repair_count < 1:
        next_stage = "warmup_repair"
        repair_count += 1
        feedback = _warmup_repair_feedback(warmup, result)
    elif recall_level in {"fuzzy", "wrong"}:
        variant = _mapping_or_empty(state.get("variant"))
        variant["guided"] = True
        state["variant"] = variant
        _mark_current_plan_guided(state)

    updated_warmup = dict(warmup)
    updated_warmup.update(
        {
            "result": result,
            "recall_level": recall_level,
            "last_answer": answer,
            "repair_count": repair_count,
            "feedback": feedback,
            "judgement_ready": True,
            "judgement_blocking_fields": [],
            "clarification_question": None,
            "judgement_source": judgement_source,
            "judgement_model": judgement_model,
            "diagnosis": _warmup_diagnosis(
                recall_level=recall_level,
                answer=answer,
                warmup=warmup,
            ),
        }
    )
    state["warmup"] = updated_warmup
    state["review_stage"] = next_stage
    state["session_diagnosis"] = _updated_session_diagnosis(
        state.get("session_diagnosis"),
        recall_level=recall_level,
        warmup=updated_warmup,
    )
    if recall_level == "skipped":
        batch = _mapping_or_empty(state.get("batch"))
        batch["difficulty_bias"] = "lower"
        state["batch"] = batch
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
        "current_node": _current_review_node(state, exercise=exercise),
        "next_action": "retry_same" if next_stage == "warmup_repair" else "start_exercise",
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
          knowledge_points.mastery_score AS kp_mastery_score,
          knowledge_points.last_exercise_result AS kp_last_exercise_result,
          knowledge_points.last_exercise_score AS kp_last_exercise_score,
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
    if not isinstance(state.get("warmup"), Mapping):
        return None
    if state.get("schema_version") == REVIEW_BATCH_SCHEMA_VERSION and isinstance(state.get("batch"), Mapping):
        return dict(state)
    if not isinstance(state.get("variant"), Mapping):
        return None
    return dict(state)


def _initial_review_stage_state(
    *,
    context: Mapping[str, object],
    seed_bank: Mapping[str, object],
    seed: Mapping[str, object],
    exercise: Mapping[str, object],
) -> dict[str, object]:
    legacy_state = {
        "review_stage": "warmup",
        "knowledge_point_id": str(context["id"]),
        "seed_bank_id": str(seed_bank["id"]),
        "seed_id": str(seed["id"]),
        "warmup": build_review_warmup(seed, context),
        "variant": {
            "exercise_id": str(exercise["id"]),
            "exercise_type": str(exercise["exercise_type"]),
            "guided": False,
            "selection_reason": _variant_reason(context),
        },
    }
    return _ensure_review_batch_state(
        legacy_state,
        context=context,
        exercise=exercise,
        seed_bank=seed_bank,
        seed=seed,
    )


def _ensure_review_batch_state(
    state: Mapping[str, object],
    *,
    context: Mapping[str, object] | None = None,
    exercise: Mapping[str, object] | None = None,
    seed_bank: Mapping[str, object] | None = None,
    seed: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Normalize legacy review state into the resumable batch state contract."""
    normalized = dict(state)
    warmup = _normalize_warmup_state(_mapping_or_empty(normalized.get("warmup")))
    seed_metadata = _review_seed_metadata(seed=seed, exercise=exercise)
    candidate_id = _candidate_id_for_state(normalized, seed=seed, seed_metadata=seed_metadata)
    exercise_id = _exercise_id_for_state(normalized, exercise=exercise)
    batch_counts = _review_batch_counts(context)
    batch = _mapping_or_empty(normalized.get("batch"))
    current_stage = _normalize_review_stage(str(normalized.get("review_stage") or "warmup"))
    batch.update(
        {
            "status": str(batch.get("status") or "active"),
            "min_exercise_count": _int_or_zero(batch.get("min_exercise_count")) or batch_counts["min"],
            "target_exercise_count": _int_or_zero(batch.get("target_exercise_count")) or batch_counts["target"],
            "max_exercise_count": _int_or_zero(batch.get("max_exercise_count")) or batch_counts["max"],
            "completed_count": _int_or_zero(batch.get("completed_count")),
            "current_exercise_id": exercise_id,
            "current_candidate_id": candidate_id,
            "can_finalize": bool(batch.get("can_finalize", False)),
        }
    )

    pool = _mapping_or_empty(normalized.get("pool"))
    seed_bank_id = _seed_bank_id_for_state(normalized, seed_bank=seed_bank, seed_metadata=seed_metadata)
    pool.update(
        {
            "seed_bank_id": seed_bank_id,
            "generator_version": str(
                seed_bank.get("generator_version")
                if seed_bank is not None
                else pool.get("generator_version") or seed_metadata.get("seed_generator_version") or REVIEW_CANDIDATE_POOL_VERSION
            ),
            "candidate_count": _candidate_count_for_pool(pool, seed_bank=seed_bank),
            "adaptive_supplements": pool.get("adaptive_supplements") if isinstance(pool.get("adaptive_supplements"), list) else [],
        }
    )

    exercise_plan = _exercise_plan_for_state(
        normalized,
        candidate_id=candidate_id,
        exercise=exercise,
        seed=seed,
        seed_metadata=seed_metadata,
    )
    variant = _variant_for_state(
        normalized,
        exercise=exercise,
        context=context,
        seed_metadata=seed_metadata,
    )
    session_diagnosis = _initial_session_diagnosis(
        normalized.get("session_diagnosis"),
        context=context,
    )

    return {
        **normalized,
        "schema_version": REVIEW_BATCH_SCHEMA_VERSION,
        "review_stage": current_stage,
        "knowledge_point_id": str(
            normalized.get("knowledge_point_id")
            or (context.get("id") if context is not None else "")
            or (exercise.get("knowledge_point_id") if exercise is not None else "")
        ),
        "seed_bank_id": seed_bank_id,
        "seed_id": candidate_id,
        "batch": batch,
        "warmup": warmup,
        "session_diagnosis": session_diagnosis,
        "pool": pool,
        "exercise_plan": exercise_plan,
        "variant": variant,
        "finalization": _mapping_or_empty(normalized.get("finalization")) or {
            "status": "pending",
            "representative_attempt_id": None,
            "final_fsrs_rating": None,
            "aggregate_result": None,
        },
    }


def _normalize_warmup_state(warmup: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(warmup)
    result = str(normalized.get("result") or "pending")
    recall_level = _warmup_recall_level(result) if result != "pending" else None
    normalized.setdefault("result", "pending")
    normalized.setdefault("repair_count", 0)
    normalized.setdefault("last_answer", None)
    normalized.setdefault("feedback", None)
    normalized["recall_level"] = normalized.get("recall_level") or recall_level
    diagnosis = normalized.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        normalized["diagnosis"] = _empty_warmup_diagnosis()
    return normalized


def _empty_warmup_diagnosis() -> dict[str, object]:
    return {
        "recall_level": None,
        "confidence": None,
        "evidence": [],
        "missing_points": [],
        "misconception": "",
        "suggested_focus": [],
    }


def _review_batch_counts(context: Mapping[str, object] | None) -> dict[str, int]:
    if context is None:
        return {"min": 3, "target": 4, "max": 6}
    weak_points = _string_list(context.get("weak_points_json"))
    mastery_score = context.get("mastery_score")
    high_risk = (
        str(context.get("last_fsrs_rating") or "") == "Again"
        or _int_or_zero(context.get("lapses")) > 0
        or (mastery_score is not None and _float_or_zero(mastery_score) < 0.45)
        or len(weak_points) >= 2
    )
    return {"min": 3, "target": 5 if high_risk else 4, "max": 6}


def _review_seed_metadata(
    *,
    seed: Mapping[str, object] | None,
    exercise: Mapping[str, object] | None,
) -> dict[str, object]:
    if seed is not None:
        metadata = seed.get("metadata")
        if isinstance(metadata, Mapping):
            return dict(metadata)
        metadata_json = seed.get("metadata_json")
        if isinstance(metadata_json, Mapping):
            return dict(metadata_json)
    if exercise is None:
        return {}
    metadata_json = exercise.get("metadata_json")
    if not isinstance(metadata_json, Mapping):
        return {}
    review_seed = metadata_json.get("review_seed")
    if isinstance(review_seed, Mapping):
        return {
            **dict(review_seed),
            "seed_generator_version": metadata_json.get("seed_generator_version"),
        }
    return {}


def _candidate_id_for_state(
    state: Mapping[str, object],
    *,
    seed: Mapping[str, object] | None,
    seed_metadata: Mapping[str, object],
) -> str:
    if seed is not None and seed.get("id"):
        return str(seed["id"])
    batch = state.get("batch")
    if isinstance(batch, Mapping) and batch.get("current_candidate_id"):
        return str(batch["current_candidate_id"])
    if seed_metadata.get("candidate_id"):
        return str(seed_metadata["candidate_id"])
    if seed_metadata.get("seed_id"):
        return str(seed_metadata["seed_id"])
    seed_id = state.get("seed_id")
    return str(seed_id) if seed_id else ""


def _seed_bank_id_for_state(
    state: Mapping[str, object],
    *,
    seed_bank: Mapping[str, object] | None,
    seed_metadata: Mapping[str, object],
) -> str:
    if seed_bank is not None and seed_bank.get("id"):
        return str(seed_bank["id"])
    if state.get("seed_bank_id"):
        return str(state["seed_bank_id"])
    if seed_metadata.get("seed_bank_id"):
        return str(seed_metadata["seed_bank_id"])
    pool = state.get("pool")
    if isinstance(pool, Mapping) and pool.get("seed_bank_id"):
        return str(pool["seed_bank_id"])
    return ""


def _exercise_id_for_state(
    state: Mapping[str, object],
    *,
    exercise: Mapping[str, object] | None,
) -> str:
    if exercise is not None and exercise.get("id"):
        return str(exercise["id"])
    batch = state.get("batch")
    if isinstance(batch, Mapping) and batch.get("current_exercise_id"):
        return str(batch["current_exercise_id"])
    variant = state.get("variant")
    if isinstance(variant, Mapping) and variant.get("exercise_id"):
        return str(variant["exercise_id"])
    return ""


def _candidate_count_for_pool(
    pool: Mapping[str, object],
    *,
    seed_bank: Mapping[str, object] | None,
) -> int:
    if seed_bank is not None:
        count = _int_or_zero(seed_bank.get("seed_count"))
        if count:
            return count
        seeds = seed_bank.get("seeds_json")
        if isinstance(seeds, list):
            return len(seeds)
    return _int_or_zero(pool.get("candidate_count"))


def _exercise_plan_for_state(
    state: Mapping[str, object],
    *,
    candidate_id: str,
    exercise: Mapping[str, object] | None,
    seed: Mapping[str, object] | None,
    seed_metadata: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_plan = state.get("exercise_plan")
    if isinstance(raw_plan, list) and raw_plan:
        return [dict(item) for item in raw_plan if isinstance(item, Mapping)]
    if exercise is None:
        return []
    capability = seed.get("capability") if seed is not None else seed_metadata.get("capability")
    focus_tags = _string_list(seed.get("focus_tags")) if seed is not None else _string_list(seed_metadata.get("focus_tags"))
    return [
        {
            "position": 1,
            "candidate_id": candidate_id,
            "exercise_id": str(exercise["id"]),
            "status": "active",
            "capability": capability,
            "exercise_type": str(exercise["exercise_type"]),
            "focus_tags": focus_tags,
            "is_core": bool(seed_metadata.get("is_core", False)),
        }
    ]


def _variant_for_state(
    state: Mapping[str, object],
    *,
    exercise: Mapping[str, object] | None,
    context: Mapping[str, object] | None,
    seed_metadata: Mapping[str, object],
) -> dict[str, object]:
    variant = _mapping_or_empty(state.get("variant"))
    if exercise is not None:
        variant.setdefault("exercise_id", str(exercise["id"]))
        variant.setdefault("exercise_type", str(exercise["exercise_type"]))
    variant.setdefault("guided", False)
    variant.setdefault(
        "selection_reason",
        str(seed_metadata.get("selection_reason") or (_variant_reason(context) if context is not None else "")),
    )
    return variant


def _initial_session_diagnosis(
    value: object,
    *,
    context: Mapping[str, object] | None,
) -> dict[str, object]:
    if isinstance(value, Mapping):
        diagnosis = dict(value)
    else:
        diagnosis = {}
    diagnosis.setdefault("recall_level", None)
    diagnosis.setdefault("weak_points", _string_list(context.get("weak_points_json")) if context is not None else [])
    diagnosis.setdefault("passed_focus_tags", [])
    diagnosis.setdefault("failed_focus_tags", [])
    diagnosis.setdefault("skip_count", 0)
    diagnosis.setdefault("core_failure_count", 0)
    diagnosis.setdefault("last_result", None)
    return diagnosis


def _current_review_node(
    state: Mapping[str, object],
    *,
    exercise: Mapping[str, object] | None,
) -> dict[str, object]:
    stage = _stage_from_state(state)
    batch = _mapping_or_empty(state.get("batch"))
    target_count = _int_or_zero(batch.get("target_exercise_count")) or 4
    if stage in {"warmup", "warmup_repair"}:
        return {
            "type": stage,
            "stage": stage,
            "can_pause": True,
            "warmup": _mapping_or_empty(state.get("warmup")),
            "position": 0,
            "target_count": target_count,
        }
    if stage in {"submitted", "final_summary"}:
        finalization = _mapping_or_empty(state.get("finalization"))
        return {
            "type": "final_summary",
            "stage": stage,
            "can_pause": False,
            "finalization": finalization,
            "completed_count": _int_or_zero(batch.get("completed_count")),
            "target_count": target_count,
            "final_fsrs_rating": finalization.get("final_fsrs_rating"),
            "due_at": finalization.get("due_at"),
            "forget_risk": finalization.get("forget_risk"),
        }
    plan_entry = _current_plan_entry(state)
    return {
        "type": "exercise",
        "stage": "exercise",
        "can_pause": True,
        "exercise": dict(exercise) if isinstance(exercise, Mapping) else {},
        "position": _int_or_zero(plan_entry.get("position")) or 1,
        "target_count": target_count,
        "completed_count": _int_or_zero(batch.get("completed_count")),
        "candidate_id": str(plan_entry.get("candidate_id") or batch.get("current_candidate_id") or ""),
    }


def _current_plan_entry(state: Mapping[str, object]) -> dict[str, object]:
    batch = _mapping_or_empty(state.get("batch"))
    current_exercise_id = str(batch.get("current_exercise_id") or "")
    plan = state.get("exercise_plan")
    if isinstance(plan, list):
        for item in plan:
            if not isinstance(item, Mapping):
                continue
            if current_exercise_id and str(item.get("exercise_id") or "") == current_exercise_id:
                return dict(item)
        for item in plan:
            if isinstance(item, Mapping) and str(item.get("status") or "") == "active":
                return dict(item)
    return {}


def _complete_current_review_plan_entry(
    state: Mapping[str, object],
    *,
    exercise: Mapping[str, object],
    attempt: Mapping[str, object],
    code_completion_result: Mapping[str, object],
    service_fields: Mapping[str, object],
) -> dict[str, object]:
    updated = dict(state)
    plan = updated.get("exercise_plan")
    if not isinstance(plan, list):
        raise ReviewSessionConflictError("review exercise plan is missing")
    current_entry = _current_plan_entry(updated)
    current_exercise_id = str(current_entry.get("exercise_id") or "")
    if not current_exercise_id:
        raise ReviewSessionConflictError("active review exercise plan entry is missing")
    seed_metadata = _review_seed_metadata(seed=None, exercise=exercise)
    completed = {
        **current_entry,
        "status": "completed",
        "attempt_id": str(attempt["id"]),
        "exercise_id": str(exercise["id"]),
        "exercise": dict(exercise),
        "exercise_title": str(exercise.get("title") or current_entry.get("exercise_title") or current_entry.get("title") or ""),
        "submitted_code": str(attempt.get("submitted_code") or ""),
        "filled_blanks": _mapping_or_empty(attempt.get("filled_blanks_json")),
        "explanation": str(attempt.get("explanation_text") or ""),
        "review_ai_patch_answer": _review_ai_patch_answer_from_attempt(attempt, exercise=exercise),
        "candidate_id": str(current_entry.get("candidate_id") or seed_metadata.get("candidate_id") or ""),
        "capability": str(current_entry.get("capability") or seed_metadata.get("capability") or ""),
        "exercise_type": str(exercise["exercise_type"]),
        "focus_tags": _unique_strings(_string_list(current_entry.get("focus_tags")) + _string_list(seed_metadata.get("focus_tags"))),
        "is_core": bool(current_entry.get("is_core") or seed_metadata.get("is_core", False)),
        "result": str(code_completion_result.get("result") or "failed"),
        "score": _int_or_zero(code_completion_result.get("score")),
        "fsrs_rating": str(code_completion_result.get("fsrs_rating") or ""),
        "score_breakdown": _mapping_or_empty(code_completion_result.get("score_breakdown")),
        "evidence_quality": _evidence_quality_for_result(code_completion_result, service_fields),
        "feedback": str(code_completion_result.get("feedback") or ""),
        "weak_points": _string_list(code_completion_result.get("weak_points")),
        "code_completion_result": dict(code_completion_result),
        "completed_at": _iso_or_none(attempt.get("created_at")),
    }
    updated_plan: list[dict[str, object]] = []
    replaced = False
    for item in plan:
        if isinstance(item, Mapping) and str(item.get("exercise_id") or "") == current_exercise_id:
            updated_plan.append(completed)
            replaced = True
        elif isinstance(item, Mapping):
            updated_plan.append(dict(item))
    if not replaced:
        updated_plan.append(completed)
    updated["exercise_plan"] = updated_plan
    return updated


def _hydrate_completed_review_entries(
    conn: Connection[dict[str, object]],
    state: Mapping[str, object],
) -> dict[str, object]:
    """Backfill persisted card summaries for sessions created before the card-result contract."""
    plan = state.get("exercise_plan")
    if not isinstance(plan, list):
        return dict(state)

    updated_plan: list[dict[str, object]] = []
    changed = False
    for item in plan:
        if not isinstance(item, Mapping):
            continue
        updated_item = dict(item)
        if str(updated_item.get("status") or "") != "completed":
            updated_plan.append(updated_item)
            continue
        attempt_id = str(updated_item.get("attempt_id") or "")
        if not attempt_id:
            updated_plan.append(updated_item)
            continue
        row = conn.execute(
            """
            SELECT attempts.id::text AS attempt_id,
                   attempts.exercise_id::text AS exercise_id,
                   attempts.submitted_code,
                   attempts.filled_blanks_json,
                   attempts.explanation_text,
                   attempts.code_completion_result,
                   attempts.score,
                   attempts.test_pass_rate,
                   attempts.hint_usage_count,
                   attempts.error_count,
                   attempts.error_cause,
                   attempts.score_breakdown_json,
                   exercises.title AS exercise_title
            FROM attempts
            JOIN exercises ON exercises.id = attempts.exercise_id
            WHERE attempts.id = %s
            LIMIT 1
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            updated_plan.append(updated_item)
            continue

        completion = _mapping_or_empty(row.get("code_completion_result"))
        exercise = get_exercise(conn, str(row.get("exercise_id") or ""))
        if not isinstance(updated_item.get("exercise"), Mapping) and exercise is not None:
            updated_item["exercise"] = dict(exercise)
            changed = True
        if not str(updated_item.get("exercise_title") or ""):
            updated_item["exercise_title"] = str(row.get("exercise_title") or "")
            changed = True
        if not str(updated_item.get("submitted_code") or "") and row.get("submitted_code") is not None:
            updated_item["submitted_code"] = str(row.get("submitted_code") or "")
            changed = True
        if not isinstance(updated_item.get("filled_blanks"), Mapping):
            updated_item["filled_blanks"] = _mapping_or_empty(row.get("filled_blanks_json"))
            changed = True
        if not str(updated_item.get("explanation") or "") and row.get("explanation_text") is not None:
            updated_item["explanation"] = str(row.get("explanation_text") or "")
            changed = True
        if not isinstance(updated_item.get("review_ai_patch_answer"), Mapping):
            patch_answer = _review_ai_patch_answer_from_attempt(row, exercise=exercise)
            if patch_answer:
                updated_item["review_ai_patch_answer"] = patch_answer
                changed = True
        if not str(updated_item.get("feedback") or "") and completion.get("feedback") is not None:
            updated_item["feedback"] = str(completion.get("feedback") or "")
            changed = True
        if not updated_item.get("weak_points") and completion.get("weak_points") is not None:
            updated_item["weak_points"] = _string_list(completion.get("weak_points"))
            changed = True
        if not isinstance(updated_item.get("code_completion_result"), Mapping) and completion:
            updated_item["code_completion_result"] = dict(completion)
            changed = True
        if _int_or_zero(updated_item.get("score")) == 0 and row.get("score") is not None:
            updated_item["score"] = _int_or_zero(row.get("score"))
            changed = True
        if row.get("test_pass_rate") is not None and "test_pass_rate" not in updated_item:
            updated_item["test_pass_rate"] = _float_or_zero(row.get("test_pass_rate"))
            changed = True
        if row.get("hint_usage_count") is not None and "hint_usage_count" not in updated_item:
            updated_item["hint_usage_count"] = _int_or_zero(row.get("hint_usage_count"))
            changed = True
        if row.get("error_count") is not None and "error_count" not in updated_item:
            updated_item["error_count"] = _int_or_zero(row.get("error_count"))
            changed = True
        if row.get("error_cause") is not None and "error_cause" not in updated_item:
            updated_item["error_cause"] = str(row.get("error_cause") or "")
            changed = True
        if not isinstance(updated_item.get("score_breakdown"), Mapping):
            score_breakdown = _mapping_or_empty(row.get("score_breakdown_json") or completion.get("score_breakdown"))
            if score_breakdown:
                updated_item["score_breakdown"] = score_breakdown
                changed = True
        updated_plan.append(updated_item)

    if not changed:
        return dict(state)
    updated = dict(state)
    updated["exercise_plan"] = updated_plan
    return updated


def _review_ai_patch_answer_from_attempt(
    attempt: Mapping[str, object],
    *,
    exercise: Mapping[str, object] | None,
) -> dict[str, object]:
    if exercise is None or str(exercise.get("exercise_type") or "") != "review_ai_patch":
        return {}
    submitted_code = str(attempt.get("submitted_code") or "").strip()
    if not submitted_code.startswith("{"):
        return {}
    try:
        parsed = json.loads(submitted_code)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    verdict = str(parsed.get("verdict") or "")
    next_action = str(parsed.get("next_action") or "")
    if verdict not in {"pass", "fail", "uncertain"} or next_action not in {"accept", "reject", "request_change", "run_more_tests"}:
        return {}
    return {
        "verdict": verdict,
        "evidence": str(parsed.get("evidence") or ""),
        "knowledge_point_risk": str(parsed.get("knowledge_point_risk") or ""),
        "next_action": next_action,
    }


def _current_completed_plan_entry(state: Mapping[str, object], attempt_id: str) -> dict[str, object]:
    plan = state.get("exercise_plan")
    if isinstance(plan, list):
        for item in plan:
            if isinstance(item, Mapping) and str(item.get("attempt_id") or "") == attempt_id:
                return dict(item)
    return {}


def _updated_formal_session_diagnosis(
    value: object,
    *,
    completed_entry: Mapping[str, object],
    code_completion_result: Mapping[str, object],
) -> dict[str, object]:
    diagnosis = _initial_session_diagnosis(value, context=None)
    focus_tags = _string_list(completed_entry.get("focus_tags"))
    result = str(completed_entry.get("result") or code_completion_result.get("result") or "failed")
    rating = str(completed_entry.get("fsrs_rating") or code_completion_result.get("fsrs_rating") or "")
    passed = result in {"passed", "easy"} and rating in {"Good", "Easy"}
    diagnosis["last_result"] = result
    diagnosis["last_fsrs_rating"] = rating
    if passed:
        diagnosis["passed_focus_tags"] = _unique_strings(_string_list(diagnosis.get("passed_focus_tags")) + focus_tags)
    else:
        diagnosis["failed_focus_tags"] = _unique_strings(_string_list(diagnosis.get("failed_focus_tags")) + focus_tags)
        diagnosis["weak_points"] = _unique_strings(
            _string_list(diagnosis.get("weak_points"))
            + _string_list(code_completion_result.get("weak_points"))
            + focus_tags[:3]
        )
    if bool(completed_entry.get("is_core")) and not passed:
        diagnosis["core_failure_count"] = _int_or_zero(diagnosis.get("core_failure_count")) + 1
    if rating == "Again":
        diagnosis["skip_count"] = _int_or_zero(diagnosis.get("skip_count")) + 1
    return diagnosis


def _refresh_review_batch_progress(state: Mapping[str, object]) -> dict[str, object]:
    updated = dict(state)
    batch = _mapping_or_empty(updated.get("batch"))
    coverage = _review_batch_coverage(updated)
    completed_count = len(_completed_review_entries(updated))
    batch["completed_count"] = completed_count
    batch["coverage"] = coverage
    batch["can_finalize"] = _can_finalize_review_batch(updated, completed_count=completed_count, coverage=coverage)
    updated["batch"] = batch
    return updated


def _review_batch_coverage(state: Mapping[str, object]) -> dict[str, object]:
    completed = _completed_review_entries(state)
    diagnosis = _mapping_or_empty(state.get("session_diagnosis"))
    required = _required_review_capabilities(state)
    covered = _unique_strings([str(entry.get("capability") or "") for entry in completed if entry.get("capability")])
    failed_core = _unique_strings(
        [
            str(entry.get("capability") or "")
            for entry in completed
            if bool(entry.get("is_core")) and str(entry.get("result") or "") not in {"passed", "easy"}
        ]
    )
    passed_focus = _string_list(diagnosis.get("passed_focus_tags"))
    failed_focus = _string_list(diagnosis.get("failed_focus_tags"))
    weak_points = _string_list(diagnosis.get("weak_points"))
    unresolved = [tag for tag in _unique_strings(failed_focus + weak_points) if tag not in set(passed_focus)]
    return {
        "required_capabilities": required,
        "covered_capabilities": covered,
        "failed_core_capabilities": failed_core,
        "unresolved_focus_tags": unresolved,
    }


def _required_review_capabilities(state: Mapping[str, object]) -> list[str]:
    batch = _mapping_or_empty(state.get("batch"))
    coverage = _mapping_or_empty(batch.get("coverage"))
    existing = _string_list(coverage.get("required_capabilities"))
    if existing:
        return existing
    return ["basic_application", "concept_explanation", "debugging"]


def _can_finalize_review_batch(
    state: Mapping[str, object],
    *,
    completed_count: int,
    coverage: Mapping[str, object],
) -> bool:
    batch = _mapping_or_empty(state.get("batch"))
    min_count = _int_or_zero(batch.get("min_exercise_count")) or 3
    target_count = _int_or_zero(batch.get("target_exercise_count")) or 4
    max_count = _int_or_zero(batch.get("max_exercise_count")) or 6
    if completed_count >= max_count:
        return True
    if completed_count < min_count:
        return False
    diagnosis = _mapping_or_empty(state.get("session_diagnosis"))
    core_failures = _int_or_zero(diagnosis.get("core_failure_count"))
    if core_failures and completed_count < target_count:
        return False
    required = set(_string_list(coverage.get("required_capabilities")))
    covered = set(_string_list(coverage.get("covered_capabilities")))
    required_coverage_count = min(3, len(required)) if required else 2
    if len(covered & required) >= required_coverage_count:
        return True
    return completed_count >= target_count


def _should_finalize_review_batch(state: Mapping[str, object]) -> bool:
    batch = _mapping_or_empty(state.get("batch"))
    completed_count = _int_or_zero(batch.get("completed_count"))
    max_count = _int_or_zero(batch.get("max_exercise_count")) or 6
    return completed_count >= max_count or bool(batch.get("can_finalize"))


def _advance_to_next_review_exercise(
    conn: Connection[dict[str, object]],
    state: dict[str, object],
    *,
    context: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> dict[str, object]:
    pool = _mapping_or_empty(state.get("pool"))
    seed_bank_id = str(pool.get("seed_bank_id") or state.get("seed_bank_id") or "")
    seed_bank = _load_ready_review_seed_bank(conn, seed_bank_id)
    seed = _select_next_review_seed(seed_bank=seed_bank, state=state, runtime_profile=runtime_profile)
    exercise = materialize_review_seed_exercise(
        conn,
        seed_bank=seed_bank,
        seed=seed,
        context=context,
        runtime_profile=runtime_profile,
    )
    seed_metadata = _review_seed_metadata(seed=seed, exercise=exercise)
    plan = state.get("exercise_plan")
    if not isinstance(plan, list):
        plan = []
    next_entry = {
        "position": len([item for item in plan if isinstance(item, Mapping)]) + 1,
        "candidate_id": str(seed["id"]),
        "exercise_id": str(exercise["id"]),
        "status": "active",
        "capability": str(seed.get("capability") or seed_metadata.get("capability") or ""),
        "exercise_type": str(exercise["exercise_type"]),
        "focus_tags": _string_list(seed.get("focus_tags")) or _string_list(seed_metadata.get("focus_tags")),
        "is_core": bool(seed_metadata.get("is_core", False)),
        "selection_reason": str(seed_metadata.get("selection_reason") or seed.get("review_focus") or ""),
    }
    plan.append(next_entry)
    state["exercise_plan"] = plan
    batch = _mapping_or_empty(state.get("batch"))
    batch["current_exercise_id"] = str(exercise["id"])
    batch["current_candidate_id"] = str(seed["id"])
    state["batch"] = batch
    state["seed_id"] = str(seed["id"])
    pool["adaptive_supplement_status"] = "not_needed"
    state["pool"] = pool
    state["variant"] = _variant_for_state(state, exercise=exercise, context=context, seed_metadata=seed_metadata)
    return exercise


def _load_ready_review_seed_bank(conn: Connection[dict[str, object]], seed_bank_id: str) -> Mapping[str, object]:
    if not seed_bank_id:
        raise ReviewAdaptiveSupplementRequired("review candidate pool is missing")
    row = conn.execute(
        """
        SELECT *
        FROM review_seed_banks
        WHERE id = %s
          AND status = 'ready'
        LIMIT 1
        """,
        (seed_bank_id,),
    ).fetchone()
    if row is None:
        raise ReviewAdaptiveSupplementRequired("ready review candidate pool is missing")
    return row


def _select_next_review_seed(
    *,
    seed_bank: Mapping[str, object],
    state: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> Mapping[str, object]:
    seeds = [dict(item) for item in _seed_list(seed_bank.get("seeds_json"))]
    if not seeds:
        raise ReviewAdaptiveSupplementRequired("review candidate pool is empty")
    supported_types = _string_list(runtime_profile.get("supported_exercise_types"))
    used_candidate_ids = _used_candidate_ids(state)
    scored: list[tuple[int, int, Mapping[str, object]]] = []
    for index, seed in enumerate(seeds):
        candidate_id = str(seed.get("id") or "")
        if not candidate_id or candidate_id in used_candidate_ids:
            continue
        exercise_type = str(seed.get("exercise_type") or "")
        if supported_types and exercise_type not in supported_types:
            continue
        if _seed_avoid_conflicts(seed, state):
            continue
        scored.append((_next_seed_score(seed, state), -index, seed))
    if not scored:
        raise ReviewAdaptiveSupplementRequired("ready review candidate pool cannot cover the remaining review need")
    return max(scored, key=lambda item: (item[0], item[1]))[2]


def _seed_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _used_candidate_ids(state: Mapping[str, object]) -> set[str]:
    plan = state.get("exercise_plan")
    if not isinstance(plan, list):
        return set()
    return {str(item.get("candidate_id") or "") for item in plan if isinstance(item, Mapping) and item.get("candidate_id")}


def _seed_avoid_conflicts(seed: Mapping[str, object], state: Mapping[str, object]) -> bool:
    avoid_if = seed.get("avoid_if")
    if not isinstance(avoid_if, Mapping):
        return False
    current_recent = str(_mapping_or_empty(state.get("batch")).get("current_candidate_id") or "")
    if current_recent and current_recent in set(_string_list(avoid_if.get("recent_candidate_ids"))):
        return True
    diagnosis = _mapping_or_empty(state.get("session_diagnosis"))
    if _int_or_zero(diagnosis.get("core_failure_count")):
        return False
    already_passed = set(_string_list(avoid_if.get("already_passed_focus_tags")))
    if not already_passed:
        return False
    passed_focus = set(_string_list(diagnosis.get("passed_focus_tags")))
    return already_passed <= passed_focus


def _next_seed_score(seed: Mapping[str, object], state: Mapping[str, object]) -> int:
    diagnosis = _mapping_or_empty(state.get("session_diagnosis"))
    coverage = _mapping_or_empty(_mapping_or_empty(state.get("batch")).get("coverage"))
    covered_capabilities = set(_string_list(coverage.get("covered_capabilities")))
    required_capabilities = set(_string_list(coverage.get("required_capabilities")) or _required_review_capabilities(state))
    failed_focus = set(_string_list(diagnosis.get("failed_focus_tags")))
    weak_points = set(_string_list(diagnosis.get("weak_points")))
    focus_tags = set(_string_list(seed.get("focus_tags")))
    capability = str(seed.get("capability") or "")
    score = 0
    if capability and capability not in covered_capabilities:
        score += 60 if capability in required_capabilities else 35
    if focus_tags & failed_focus:
        score += 40
    if focus_tags & weak_points:
        score += 25
    metadata = seed.get("metadata")
    is_core = isinstance(metadata, Mapping) and bool(metadata.get("is_core", False))
    if is_core:
        score += 8
    if _int_or_zero(diagnosis.get("core_failure_count")) and is_core:
        score += 15
    if _int_or_zero(diagnosis.get("skip_count")):
        score += max(0, 6 - _int_or_zero(seed.get("difficulty")))
    previous_type = _last_completed_exercise_type(state)
    if previous_type and previous_type == str(seed.get("exercise_type") or ""):
        score -= 20
    return score


def _last_completed_exercise_type(state: Mapping[str, object]) -> str:
    completed = _completed_review_entries(state)
    if not completed:
        return ""
    return str(completed[-1].get("exercise_type") or "")


def _completed_review_entries(state: Mapping[str, object]) -> list[dict[str, object]]:
    plan = state.get("exercise_plan")
    if not isinstance(plan, list):
        return []
    return [dict(item) for item in plan if isinstance(item, Mapping) and str(item.get("status") or "") == "completed"]


def _mark_adaptive_supplement_needed(state: dict[str, object], *, reason: str) -> None:
    pool = _mapping_or_empty(state.get("pool"))
    pool["adaptive_supplement_status"] = "needed"
    pool["adaptive_supplement_failure_code"] = "REVIEW_ADAPTIVE_SUPPLEMENT_FAILED"
    pool["adaptive_supplement_failure_reason"] = reason
    state["pool"] = pool
    batch = _mapping_or_empty(state.get("batch"))
    batch["can_finalize"] = False
    state["batch"] = batch


def _aggregate_review_batch_rating(state: Mapping[str, object]) -> tuple[str, dict[str, object]]:
    completed = _completed_review_entries(state)
    diagnosis = _mapping_or_empty(state.get("session_diagnosis"))
    coverage = _mapping_or_empty(_mapping_or_empty(state.get("batch")).get("coverage"))
    pass_count = sum(1 for entry in completed if str(entry.get("result") or "") in {"passed", "easy"})
    partial_count = sum(1 for entry in completed if str(entry.get("result") or "") == "partial")
    fail_count = sum(1 for entry in completed if str(entry.get("result") or "") == "failed")
    core_failure_count = sum(
        1
        for entry in completed
        if bool(entry.get("is_core")) and str(entry.get("result") or "") not in {"passed", "easy"}
    )
    skip_count = _int_or_zero(diagnosis.get("skip_count"))
    scores = [_int_or_zero(entry.get("score")) for entry in completed]
    score = round(sum(scores) / len(scores)) if scores else 0
    weak_points = _unique_strings(
        _string_list(diagnosis.get("weak_points")) + _string_list(coverage.get("unresolved_focus_tags"))
    )
    strong_evidence = all(str(entry.get("evidence_quality") or "strong") == "strong" for entry in completed)
    final_rating = "Good"
    rating_reason = "Batch performance is stable enough for normal review scheduling."
    if fail_count >= 2 or skip_count >= 2 or core_failure_count >= 2:
        final_rating = "Again"
        rating_reason = "Repeated failures or skips show the knowledge point needs relearning."
    elif core_failure_count >= 1:
        final_rating = "Hard"
        rating_reason = "A core review capability still failed, so the batch cannot receive a high rating."
    elif fail_count == 1 and pass_count < 2:
        final_rating = "Hard"
        rating_reason = "A failure remains without enough stable recovery evidence."
    elif partial_count >= 2:
        final_rating = "Hard"
        rating_reason = "Multiple partial results indicate unresolved weakness."
    elif fail_count == 0 and partial_count == 0 and skip_count == 0 and strong_evidence and pass_count >= 3:
        final_rating = "Easy"
        rating_reason = "All required review checks passed with strong evidence."
    elif fail_count <= 1 and pass_count >= 2:
        final_rating = "Good"
        rating_reason = "One small non-core miss is outweighed by stable performance across the batch."
    aggregate_result: dict[str, object] = {
        "result": "passed" if final_rating in {"Good", "Easy"} else "partial" if final_rating == "Hard" else "failed",
        "final_fsrs_rating": final_rating,
        "completed_count": len(completed),
        "pass_count": pass_count,
        "partial_count": partial_count,
        "fail_count": fail_count,
        "core_failure_count": core_failure_count,
        "skip_count": skip_count,
        "score": score,
        "weak_points": weak_points,
        "unresolved_focus_tags": _string_list(coverage.get("unresolved_focus_tags")),
        "covered_capabilities": _string_list(coverage.get("covered_capabilities")),
        "score_breakdown": {
            "pass_count": pass_count,
            "partial_count": partial_count,
            "fail_count": fail_count,
            "core_failure_count": core_failure_count,
            "skip_count": skip_count,
        },
        "rating_reason": rating_reason,
    }
    return final_rating, aggregate_result


def _mark_review_batch_finalized(
    state: Mapping[str, object],
    *,
    representative_attempt_id: str,
    final_rating: str,
    aggregate_result: Mapping[str, object],
    schedule: Mapping[str, object],
) -> dict[str, object]:
    updated = dict(state)
    batch = _mapping_or_empty(updated.get("batch"))
    batch["status"] = "finalized"
    batch["can_finalize"] = True
    batch["completed_count"] = len(_completed_review_entries(updated))
    updated["batch"] = batch
    finalization = _mapping_or_empty(updated.get("finalization"))
    finalization.update(
        {
            "status": "applied",
            "representative_attempt_id": representative_attempt_id,
            "final_fsrs_rating": final_rating,
            "aggregate_result": dict(aggregate_result),
            "due_at": schedule.get("due_at"),
            "forget_risk": schedule.get("forget_risk"),
            "review_state": schedule.get("ReviewState"),
        }
    )
    updated["finalization"] = finalization
    updated["review_stage"] = "final_summary"
    return updated


def _representative_profile_attempt(
    attempt: Mapping[str, object],
    *,
    final_rating: str,
    aggregate_result: Mapping[str, object],
) -> dict[str, object]:
    profile_attempt = dict(attempt)
    profile_attempt["fsrs_rating"] = final_rating
    profile_attempt["score"] = _int_or_zero(aggregate_result.get("score"))
    profile_attempt["error_count"] = _int_or_zero(aggregate_result.get("fail_count"))
    profile_attempt["runtime_status"] = "success" if final_rating in {"Good", "Easy"} else "review_batch_partial"
    profile_attempt["test_pass_rate"] = 1.0 if final_rating in {"Good", "Easy"} else 0.5
    profile_attempt["code_completion_result"] = {
        "result": aggregate_result.get("result"),
        "score": aggregate_result.get("score"),
        "score_breakdown": aggregate_result.get("score_breakdown") or {},
        "weak_points": aggregate_result.get("weak_points") or [],
        "fsrs_rating": final_rating,
    }
    return profile_attempt


def _batch_finalization_request_id(session_id: str, attempt_id: str, rating: str) -> str:
    return f"review-batch-finalization:{session_id}:{attempt_id}:{rating}"


def _evidence_quality_for_result(
    code_completion_result: Mapping[str, object],
    service_fields: Mapping[str, object],
) -> str:
    patch_result = code_completion_result.get("review_ai_patch_result")
    if isinstance(patch_result, Mapping):
        return str(patch_result.get("evidence_quality") or "weak")
    explanation = service_fields.get("explanation_check_result")
    if isinstance(explanation, Mapping) and _int_or_zero(explanation.get("score")) < 2:
        return "weak"
    return "strong" if _int_or_zero(code_completion_result.get("score")) >= 7 else "weak"


def _mark_current_plan_guided(state: dict[str, object]) -> None:
    current_entry = _current_plan_entry(state)
    if not current_entry:
        return
    plan = state.get("exercise_plan")
    if not isinstance(plan, list):
        return
    current_exercise_id = str(current_entry.get("exercise_id") or "")
    for item in plan:
        if isinstance(item, dict) and str(item.get("exercise_id") or "") == current_exercise_id:
            item["guided"] = True
            return


def _state_exercise_id(state: Mapping[str, object]) -> str | None:
    batch = state.get("batch")
    if isinstance(batch, Mapping):
        exercise_id = batch.get("current_exercise_id")
        if exercise_id:
            return str(exercise_id)
    variant = state.get("variant")
    if not isinstance(variant, Mapping):
        return None
    exercise_id = variant.get("exercise_id")
    return str(exercise_id) if exercise_id else None


def _state_seed_id(state: Mapping[str, object]) -> str | None:
    batch = state.get("batch")
    if isinstance(batch, Mapping) and batch.get("current_candidate_id"):
        return str(batch["current_candidate_id"])
    seed_id = state.get("seed_id")
    return str(seed_id) if seed_id else None


def _stage_from_state(state: Mapping[str, object]) -> str:
    stage = state.get("review_stage")
    if stage in _REVIEW_BATCH_STAGES:
        return str(stage)
    if stage == "variant_practice":
        return "exercise"
    warmup = state.get("warmup")
    if isinstance(warmup, Mapping) and warmup.get("result") in {"correct", "skipped"}:
        return "exercise"
    return "warmup"


def _normalize_review_stage(stage: str) -> str:
    if stage in _REVIEW_BATCH_STAGES:
        return stage
    if stage == "variant_practice":
        return "exercise"
    return "warmup"


def _mark_review_stage_submitted(session: Mapping[str, object]) -> dict[str, object]:
    state = _review_stage_state_from_session(session) or {}
    state["review_stage"] = "submitted"
    return state


def _warmup_recall_level(result: str) -> str:
    if result == "correct":
        return "clear"
    if result == "unclear":
        return "fuzzy"
    if result == "skipped":
        return "skipped"
    return "wrong"


def _warmup_diagnosis(
    *,
    recall_level: str,
    answer: str | None,
    warmup: Mapping[str, object],
) -> dict[str, object]:
    focus_tags = _warmup_focus_tags(warmup)
    evidence = [answer.strip()] if isinstance(answer, str) and answer.strip() else []
    if recall_level == "skipped":
        evidence = ["skipped_warmup"]
    confidence = {
        "clear": 0.9,
        "fuzzy": 0.45,
        "wrong": 0.2,
        "skipped": 0.0,
    }.get(recall_level, 0.3)
    return {
        "recall_level": recall_level,
        "confidence": confidence,
        "evidence": evidence[:3],
        "missing_points": [] if recall_level == "clear" else focus_tags[:3],
        "misconception": "" if recall_level == "clear" else str(warmup.get("expected_focus") or ""),
        "suggested_focus": focus_tags[:6],
    }


def _warmup_focus_tags(warmup: Mapping[str, object]) -> list[str]:
    tags = _string_list(warmup.get("keywords"))
    expected_focus = str(warmup.get("expected_focus") or "").strip()
    if expected_focus:
        tags.append(expected_focus)
    return _unique_strings(tags)


def _updated_session_diagnosis(
    value: object,
    *,
    recall_level: str,
    warmup: Mapping[str, object],
) -> dict[str, object]:
    diagnosis = _initial_session_diagnosis(value, context=None)
    focus_tags = _warmup_focus_tags(warmup)
    diagnosis["recall_level"] = recall_level
    diagnosis["last_result"] = recall_level
    if recall_level == "clear":
        diagnosis["passed_focus_tags"] = _unique_strings(_string_list(diagnosis.get("passed_focus_tags")) + focus_tags)
    else:
        diagnosis["weak_points"] = _unique_strings(_string_list(diagnosis.get("weak_points")) + focus_tags[:3])
        diagnosis["failed_focus_tags"] = _unique_strings(_string_list(diagnosis.get("failed_focus_tags")) + focus_tags)
    if recall_level == "skipped":
        diagnosis["skip_count"] = _int_or_zero(diagnosis.get("skip_count")) + 1
    return diagnosis


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_review_warmup_judgement(result: str) -> dict[str, object]:
    if result in {"correct", "incorrect", "unclear", "skipped"}:
        judgement = StructuredJudgement(status="confirmed")
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
        return "这个点够用了，下面用一道题确认你能不能在代码里认出来。"
    if result == "skipped":
        return "先不硬回忆了，下面从基础题把这个点找回来。"
    if result == "unclear":
        return "这个点还没稳住，下一题我会带着提示走。"
    return "这句还没碰到当前知识点最容易踩坑的地方，下一题我会带着提示走。"


def _warmup_repair_feedback(warmup: Mapping[str, object], result: str) -> str:
    question = str(warmup.get("question") or "").strip()
    prompt = question or "这类代码最容易让人误判的地方是什么？"
    if result == "unclear":
        return f"我还没法确认你抓住了这个点。换个更具体的说法：{prompt}"
    return f"这句还没碰到当前知识点最容易踩坑的地方。换个更具体的说法：{prompt}"


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
