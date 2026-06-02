from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from psycopg import Connection

from app.services.exercises.evaluation import knowledge_point_status_for, mastery_score_for


VALID_FSRS_RATINGS = {"Again", "Hard", "Good", "Easy"}
VALID_SCHEDULING_ATTEMPT_TYPES = {"submit", "review_submit"}
SCHEDULER_VERSION = "fsrs_v1_fallback"
LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


class ReviewSchedulingError(ValueError):
    pass


def apply_attempt_review_update(
    conn: Connection[dict[str, object]],
    *,
    knowledge_point_id: str,
    attempt_id: str,
    source: str,
    request_id: str | None,
) -> dict[str, object]:
    attempt = conn.execute(
        """
        SELECT attempts.*, exercises.knowledge_point_id AS exercise_knowledge_point_id
        FROM attempts
        JOIN exercises ON exercises.id = attempts.exercise_id
        WHERE attempts.id = %s
        FOR UPDATE OF attempts
        """,
        (attempt_id,),
    ).fetchone()
    if attempt is None:
        raise ReviewSchedulingError("attempt not found")

    state = conn.execute(
        """
        SELECT *
        FROM review_states
        WHERE knowledge_point_id = %s
        FOR UPDATE
        """,
        (knowledge_point_id,),
    ).fetchone()
    if state is None:
        raise ReviewSchedulingError("review state missing for knowledge point")

    rating = str(attempt.get("fsrs_rating") or "")
    normalized_request_id = _request_id_or_none(request_id) or default_review_update_key(
        knowledge_point_id=knowledge_point_id,
        attempt_id=attempt_id,
        rating=rating,
    )
    existing_log = conn.execute(
        """
        SELECT next_state_json
        FROM review_logs
        WHERE request_id = %s
           OR (attempt_id = %s AND rating = %s AND source = %s)
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (normalized_request_id, attempt_id, rating, source),
    ).fetchone()
    if existing_log is not None:
        next_state = existing_log["next_state_json"]
        if not isinstance(next_state, Mapping):
            raise ReviewSchedulingError("stored review log next_state_json is invalid")
        knowledge_point = _load_knowledge_point(conn, knowledge_point_id)
        return {
            "KnowledgePoint": serialize_knowledge_point(knowledge_point),
            "ReviewState": normalize_review_state_payload(next_state),
            "due_at": next_state.get("due_at"),
            "forget_risk": forget_risk_for(next_state),
        }

    _validate_attempt_for_review_update(attempt, state, knowledge_point_id, source)
    previous_state = serialize_review_state(state)
    reviewed_at = _aware_datetime(attempt.get("created_at")) or datetime.now(UTC)
    next_state_values = _compute_next_state(state, rating, reviewed_at)

    review_state = conn.execute(
        """
        UPDATE review_states
        SET
          card_state = %(card_state)s,
          stability = %(stability)s,
          difficulty = %(difficulty)s,
          due_at = %(due_at)s,
          elapsed_days = %(elapsed_days)s,
          scheduled_days = %(scheduled_days)s,
          reps = reps + 1,
          lapses = lapses + %(lapse_increment)s,
          last_review_at = %(reviewed_at)s,
          last_attempt_id = %(attempt_id)s,
          last_fsrs_rating = %(rating)s,
          scheduler_version = %(scheduler_version)s,
          fsrs_parameters = %(fsrs_parameters)s::jsonb,
          suspended_at = NULL
        WHERE knowledge_point_id = %(knowledge_point_id)s
        RETURNING *
        """,
        {
            **next_state_values,
            "attempt_id": attempt_id,
            "rating": rating,
            "reviewed_at": reviewed_at,
            "scheduler_version": SCHEDULER_VERSION,
            "fsrs_parameters": json.dumps({"scheduler_fallback": True}),
            "knowledge_point_id": knowledge_point_id,
        },
    ).fetchone()
    if review_state is None:
        raise ReviewSchedulingError("review state update returned no row")

    code_completion_result = _mapping_or_empty(attempt.get("code_completion_result"))
    result = str(code_completion_result.get("result", "failed"))
    score = _int_or_zero(code_completion_result.get("score"))
    updated_knowledge_point = conn.execute(
        """
        UPDATE knowledge_points
        SET
          status = %s,
          mastery_score = %s,
          weak_points_json = %s::jsonb,
          last_exercise_result = %s,
          last_exercise_score = %s,
          last_exercise_breakdown_json = %s::jsonb,
          last_explanation_check_result = %s::jsonb,
          last_session_id = %s
        WHERE id = %s
        RETURNING *
        """,
        (
            knowledge_point_status_for(result),
            mastery_score_for(result, score),
            json.dumps(code_completion_result.get("weak_points") or []),
            result,
            score,
            json.dumps(code_completion_result.get("score_breakdown") or {}),
            json.dumps(_json_compatible(attempt.get("explanation_check_result") or {})),
            attempt["session_id"],
            knowledge_point_id,
        ),
    ).fetchone()
    if updated_knowledge_point is None:
        raise ReviewSchedulingError("knowledge point update returned no row")

    next_state = serialize_review_state(review_state)
    conn.execute(
        """
        INSERT INTO review_logs (
          knowledge_point_id, user_id, plan_id, attempt_id, rating,
          previous_state_json, next_state_json, scheduled_due_at, reviewed_at, source, request_id
        )
        VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
        """,
        (
            knowledge_point_id,
            state["user_id"],
            state["plan_id"],
            attempt_id,
            rating,
            json.dumps(previous_state),
            json.dumps(next_state),
            review_state["due_at"],
            reviewed_at,
            source,
            normalized_request_id,
        ),
    )
    return {
        "KnowledgePoint": serialize_knowledge_point(updated_knowledge_point),
        "ReviewState": next_state,
        "due_at": next_state["due_at"],
        "forget_risk": forget_risk_for(next_state),
    }


def default_review_update_key(*, knowledge_point_id: str, attempt_id: str, rating: str) -> str:
    return f"review:update:{knowledge_point_id}:{attempt_id}:{rating}"


def serialize_review_state(row: Mapping[str, object]) -> dict[str, object]:
    reps = _int_or_zero(row.get("reps") or row.get("review_count"))
    lapses = _int_or_zero(row.get("lapses") or row.get("lapse_count"))
    return {
        "knowledge_point_id": str(row["knowledge_point_id"]),
        "card_state": row["card_state"],
        "stability": _decimal_to_float(row.get("stability")),
        "difficulty": _decimal_to_float(row.get("difficulty")),
        "due_at": _iso_or_none(row.get("due_at")),
        "last_review_at": _iso_or_none(row.get("last_review_at")),
        "review_count": reps,
        "lapse_count": lapses,
        "reps": reps,
        "lapses": lapses,
        "elapsed_days": _int_or_zero(row.get("elapsed_days")),
        "scheduled_days": _int_or_zero(row.get("scheduled_days")),
        "last_attempt_id": str(row["last_attempt_id"]) if row.get("last_attempt_id") else None,
        "last_fsrs_rating": row.get("last_fsrs_rating"),
        "scheduler_version": row.get("scheduler_version") or SCHEDULER_VERSION,
    }


def normalize_review_state_payload(payload: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(payload)
    reps = _int_or_zero(normalized.get("review_count") or normalized.get("reps"))
    lapses = _int_or_zero(normalized.get("lapse_count") or normalized.get("lapses"))
    normalized["review_count"] = reps
    normalized["lapse_count"] = lapses
    normalized["reps"] = reps
    normalized["lapses"] = lapses
    return normalized


def serialize_knowledge_point(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "mastery_score": _decimal_to_float(row["mastery_score"]),
        "last_exercise_result": row["last_exercise_result"],
        "last_exercise_score": row["last_exercise_score"],
    }


def forget_risk_for(review_state: Mapping[str, object]) -> str:
    rating = review_state.get("last_fsrs_rating")
    if rating == "Again" or review_state.get("card_state") in {"learning", "relearning"}:
        return "high"
    if rating == "Hard":
        return "normal"
    return "low"


def _validate_attempt_for_review_update(
    attempt: Mapping[str, object],
    state: Mapping[str, object],
    knowledge_point_id: str,
    source: str,
) -> None:
    attempt_type = str(attempt.get("attempt_type") or "")
    expected_source = "review_submit" if attempt_type == "review_submit" else "learn_submit"
    if attempt_type not in VALID_SCHEDULING_ATTEMPT_TYPES:
        raise ReviewSchedulingError("only submit and review_submit attempts update review state")
    if source != expected_source:
        raise ReviewSchedulingError("review update source does not match attempt type")
    if str(attempt.get("exercise_knowledge_point_id")) != knowledge_point_id:
        raise ReviewSchedulingError("attempt exercise does not match knowledge point")
    if str(attempt.get("user_id")) != str(state.get("user_id")):
        raise ReviewSchedulingError("attempt user does not match review state user")
    if attempt.get("evaluation_status") != "evaluated":
        raise ReviewSchedulingError("attempt has not been evaluated")
    rating = str(attempt.get("fsrs_rating") or "")
    if rating not in VALID_FSRS_RATINGS:
        raise ReviewSchedulingError("attempt fsrs rating is invalid")
    code_completion_result = _mapping_or_empty(attempt.get("code_completion_result"))
    if code_completion_result.get("fsrs_rating") != rating:
        raise ReviewSchedulingError("attempt result fsrs rating does not match attempt rating")


def _compute_next_state(
    previous: Mapping[str, object],
    rating: str,
    reviewed_at: datetime,
) -> dict[str, object]:
    previous_card_state = str(previous["card_state"])
    previous_stability = _decimal_to_float(previous.get("stability")) or 1.0
    previous_difficulty = _decimal_to_float(previous.get("difficulty")) or 6.0
    last_review_at = _aware_datetime(previous.get("last_review_at"))
    elapsed_days = max((reviewed_at - last_review_at).days, 0) if last_review_at else 0

    if rating == "Again":
        due_at = reviewed_at + timedelta(minutes=10)
        return {
            "card_state": "relearning" if previous_card_state in {"review", "relearning"} else "learning",
            "stability": 0.1,
            "difficulty": round(min(max(previous_difficulty + 0.8, 7.0), 10.0), 4),
            "due_at": due_at,
            "elapsed_days": elapsed_days,
            "scheduled_days": 0,
            "lapse_increment": 1 if previous_card_state in {"review", "relearning"} else 0,
        }
    if rating == "Hard":
        return {
            "card_state": "review" if previous_card_state == "review" else previous_card_state if previous_card_state == "relearning" else "learning",
            "stability": round(max(previous_stability, 1.0), 4),
            "difficulty": round(min(previous_difficulty + 0.3, 10.0), 4),
            "due_at": _next_review_slot(reviewed_at, 1),
            "elapsed_days": elapsed_days,
            "scheduled_days": 1,
            "lapse_increment": 0,
        }
    if rating == "Easy":
        return {
            "card_state": "review",
            "stability": round(max(previous_stability * 2.5, 7.0), 4),
            "difficulty": round(max(previous_difficulty - 0.3, 1.0), 4),
            "due_at": _next_review_slot(reviewed_at, 7),
            "elapsed_days": elapsed_days,
            "scheduled_days": 7,
            "lapse_increment": 0,
        }
    return {
        "card_state": "review",
        "stability": round(max(previous_stability * 1.8, 3.0), 4),
        "difficulty": round(previous_difficulty, 4),
        "due_at": _next_review_slot(reviewed_at, 3),
        "elapsed_days": elapsed_days,
        "scheduled_days": 3,
        "lapse_increment": 0,
    }


def _next_review_slot(base: datetime, days: int) -> datetime:
    local_base = _aware_datetime(base).astimezone(LOCAL_TIMEZONE)
    local_target = datetime.combine(local_base.date() + timedelta(days=days), time(hour=20), tzinfo=LOCAL_TIMEZONE)
    return local_target.astimezone(UTC)


def _load_knowledge_point(conn: Connection[dict[str, object]], knowledge_point_id: str) -> Mapping[str, object]:
    row = conn.execute(
        "SELECT * FROM knowledge_points WHERE id = %s",
        (knowledge_point_id,),
    ).fetchone()
    if row is None:
        raise ReviewSchedulingError("knowledge point not found")
    return row


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _json_compatible(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    return value


def _aware_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    return datetime.now(UTC)


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    return _aware_datetime(value).isoformat()


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _int_or_zero(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _request_id_or_none(request_id: str | None) -> str | None:
    if request_id in {None, "", "req_unset"}:
        return None
    return request_id
