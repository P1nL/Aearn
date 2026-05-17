from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from psycopg import Connection

from app.services.review_scheduler import forget_risk_for, serialize_review_state
from app.services.user_repository import get_user


INACTIVITY_THRESHOLD = timedelta(hours=72)


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def get_dashboard(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
) -> dict[str, object]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")

    plan = _load_active_plan(conn, user_id=user_id)
    if plan is None:
        raise EntityNotFoundError("PLAN_NOT_FOUND", "学习计划不存在")

    knowledge_points = _load_plan_knowledge_points(conn, plan_id=str(plan["plan_id"]))
    active_session = _load_active_learning_session(conn, user_id=user_id, plan_id=str(plan["plan_id"]))
    latest_session = active_session or _load_latest_learning_session(conn, user_id=user_id, plan_id=str(plan["plan_id"]))
    current_point = _resolve_current_learning_point(knowledge_points, active_session, latest_session, plan)
    due_items = _load_due_review_items(conn, user_id=user_id, limit=20)
    high_risk_item = next((item for item in due_items if item["forget_risk"] == "high"), None)
    latest_learning_activity = _load_latest_learning_activity(conn, user_id=user_id, plan_id=str(plan["plan_id"]))
    resume_available = _session_has_valid_entry(latest_session, knowledge_points)
    high_risk_resume = (
        latest_learning_activity is not None
        and datetime.now(UTC) - latest_learning_activity >= INACTIVITY_THRESHOLD
        and high_risk_item is not None
    )

    return {
        "active_goal": plan["goal_text"],
        "current_stage": current_point["module_title"] if current_point is not None else plan["current_module_title"],
        "current_language": plan["language"],
        "current_course": {
            "id": plan["course_id"],
            "title": plan["course_title"],
        },
        "today_learning_tasks": _build_today_learning_tasks(
            knowledge_points,
            current_point=current_point,
            plan_id=str(plan["plan_id"]),
            current_module_id=_string_or_none(plan.get("current_module_id")),
        ),
        "today_review_count": len(due_items),
        "overall_progress": _decimal_to_float(plan.get("overall_progress")),
        "resume_available": resume_available,
        "next_entry_point": _build_dashboard_entry_point(
            plan_id=str(plan["plan_id"]),
            current_point=current_point,
            high_risk_item=high_risk_item,
            resume_available=resume_available,
            high_risk_resume=high_risk_resume,
        ),
    }


def get_resume_context(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
) -> dict[str, object]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")

    plan = _load_plan(conn, user_id=user_id, plan_id=plan_id)
    if plan is None:
        raise EntityNotFoundError("PLAN_NOT_FOUND", "学习计划不存在")

    knowledge_points = _load_plan_knowledge_points(conn, plan_id=plan_id)
    latest_session = _load_latest_learning_session(conn, user_id=user_id, plan_id=plan_id)
    due_items = _load_due_review_items(conn, user_id=user_id, limit=20)
    fallback_point = _resolve_current_learning_point(knowledge_points, None, latest_session, plan)

    if latest_session is None or not _session_has_valid_entry(latest_session, knowledge_points):
        return {
            "last_session_summary": None,
            "next_entry_point": _build_learning_entry_point(plan_id=plan_id, knowledge_point_id=_knowledge_point_id_or_none(fallback_point)),
            "current_module": _serialize_module_summary(fallback_point, plan),
            "current_stage": fallback_point["module_title"] if fallback_point is not None else plan["current_module_title"],
            "today_review_count": len(due_items),
            "resume_available": False,
        }

    current_point = _resolve_current_learning_point(knowledge_points, latest_session, latest_session, plan)
    latest_attempt = _load_latest_attempt_for_session(conn, session_id=str(latest_session["id"]))
    knowledge_point_id = _extract_knowledge_point_id(latest_session.get("next_entry_point")) or _knowledge_point_id_or_none(current_point)
    if knowledge_point_id is None:
        knowledge_point_id = _knowledge_point_id_or_none(fallback_point)

    return {
        "last_session_summary": _session_summary_text(latest_session, current_point=current_point, latest_attempt=latest_attempt),
        "next_entry_point": _build_learning_entry_point(plan_id=plan_id, knowledge_point_id=knowledge_point_id),
        "current_module": _serialize_module_summary(current_point or fallback_point, plan),
        "current_stage": (current_point or fallback_point)["module_title"] if (current_point or fallback_point) is not None else plan["current_module_title"],
        "today_review_count": len(due_items),
        "resume_available": True,
    }


def _build_dashboard_entry_point(
    *,
    plan_id: str,
    current_point: Mapping[str, object] | None,
    high_risk_item: Mapping[str, object] | None,
    resume_available: bool,
    high_risk_resume: bool,
) -> dict[str, object]:
    if high_risk_resume and high_risk_item is not None:
        return {
            "type": "review",
            "plan_id": plan_id,
            "knowledge_point_id": high_risk_item["knowledge_point_id"],
            "next_action": "review_variant",
        }
    if resume_available:
        return {
            "type": "resume",
            "plan_id": plan_id,
            "next_action": "advance_next",
        }
    return _build_learning_entry_point(plan_id=plan_id, knowledge_point_id=_knowledge_point_id_or_none(current_point))


def _build_learning_entry_point(*, plan_id: str, knowledge_point_id: str | None) -> dict[str, object]:
    return {
        "type": "learning_session",
        "plan_id": plan_id,
        "knowledge_point_id": knowledge_point_id,
        "next_action": "advance_next",
    }


def _build_today_learning_tasks(
    knowledge_points: Sequence[Mapping[str, object]],
    *,
    current_point: Mapping[str, object] | None,
    plan_id: str,
    current_module_id: str | None,
) -> list[dict[str, object]]:
    active_module_id = _knowledge_point_module_id_or_none(current_point) or current_module_id
    preferred = [
        point
        for point in knowledge_points
        if point["status"] != "mastered" and (active_module_id is None or str(point["module_id"]) == active_module_id)
    ]
    candidates = preferred if preferred else [point for point in knowledge_points if point["status"] != "mastered"]
    return [
        {
            "type": "learning_session",
            "plan_id": plan_id,
            "knowledge_point_id": str(point["id"]),
            "title": point["title"],
        }
        for point in candidates[:3]
    ]


def _resolve_current_learning_point(
    knowledge_points: Sequence[Mapping[str, object]],
    active_session: Mapping[str, object] | None,
    latest_session: Mapping[str, object] | None,
    plan: Mapping[str, object],
) -> Mapping[str, object] | None:
    active_entry = _extract_knowledge_point_id(active_session.get("entry_point") if active_session is not None else None)
    if active_entry is not None:
        matched = _find_knowledge_point(knowledge_points, active_entry)
        if matched is not None:
            return matched

    latest_entry = _extract_knowledge_point_id(latest_session.get("entry_point") if latest_session is not None else None)
    if latest_entry is not None:
        matched = _find_knowledge_point(knowledge_points, latest_entry)
        if matched is not None:
            return matched

    current_module_id = _string_or_none(plan.get("current_module_id"))
    if current_module_id is not None:
        for point in knowledge_points:
            if str(point["module_id"]) == current_module_id and point["status"] != "mastered":
                return point

    for point in knowledge_points:
        if point["status"] != "mastered":
            return point
    return knowledge_points[0] if knowledge_points else None


def _session_has_valid_entry(
    session: Mapping[str, object] | None,
    knowledge_points: Sequence[Mapping[str, object]],
) -> bool:
    if session is None:
        return False
    knowledge_point_id = _extract_knowledge_point_id(session.get("entry_point"))
    return knowledge_point_id is not None and _find_knowledge_point(knowledge_points, knowledge_point_id) is not None


def _find_knowledge_point(
    knowledge_points: Sequence[Mapping[str, object]],
    knowledge_point_id: str,
) -> Mapping[str, object] | None:
    for point in knowledge_points:
        if str(point["id"]) == knowledge_point_id:
            return point
    return None


def _load_active_plan(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT
          learning_plans.id AS plan_id,
          learning_plans.goal_text,
          learning_plans.language,
          learning_plans.overall_progress,
          learning_plans.current_module_id,
          plan_modules.title AS current_module_title,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM learning_plans
        JOIN language_courses ON language_courses.id = learning_plans.language_course_id
        LEFT JOIN plan_modules
          ON plan_modules.id = learning_plans.current_module_id
         AND plan_modules.deleted_at IS NULL
        WHERE learning_plans.user_id = %s
          AND learning_plans.status = 'active'
          AND learning_plans.deleted_at IS NULL
        ORDER BY learning_plans.created_at DESC
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()


def _load_plan(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT
          learning_plans.id AS plan_id,
          learning_plans.goal_text,
          learning_plans.language,
          learning_plans.overall_progress,
          learning_plans.current_module_id,
          plan_modules.title AS current_module_title,
          language_courses.id AS course_id,
          language_courses.title AS course_title
        FROM learning_plans
        JOIN language_courses ON language_courses.id = learning_plans.language_course_id
        LEFT JOIN plan_modules
          ON plan_modules.id = learning_plans.current_module_id
         AND plan_modules.deleted_at IS NULL
        WHERE learning_plans.id = %s
          AND learning_plans.user_id = %s
          AND learning_plans.deleted_at IS NULL
        LIMIT 1
        """,
        (plan_id, user_id),
    ).fetchone()


def _load_plan_knowledge_points(
    conn: Connection[dict[str, object]],
    *,
    plan_id: str,
) -> list[Mapping[str, object]]:
    return conn.execute(
        """
        SELECT
          knowledge_points.*,
          plan_modules.title AS module_title,
          plan_modules.order_index AS module_order_index
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        WHERE plan_modules.plan_id = %s
          AND plan_modules.deleted_at IS NULL
          AND knowledge_points.deleted_at IS NULL
        ORDER BY plan_modules.order_index, knowledge_points.order_index
        """,
        (plan_id,),
    ).fetchall()


def _load_active_learning_session(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE user_id = %s
          AND plan_id = %s
          AND session_type = 'learn'
          AND status = 'active'
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (user_id, plan_id),
    ).fetchone()


def _load_latest_learning_session(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT *
        FROM learning_sessions
        WHERE user_id = %s
          AND plan_id = %s
          AND session_type = 'learn'
        ORDER BY COALESCE(updated_at, started_at, created_at) DESC
        LIMIT 1
        """,
        (user_id, plan_id),
    ).fetchone()


def _load_latest_attempt_for_session(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
) -> Mapping[str, object] | None:
    return conn.execute(
        """
        SELECT *
        FROM attempts
        WHERE session_id = %s
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (session_id,),
    ).fetchone()


def _load_due_review_items(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    limit: int,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT
          review_states.*,
          knowledge_points.id AS kp_id,
          knowledge_points.title AS kp_title,
          knowledge_points.mastery_score AS kp_mastery_score
        FROM review_states
        JOIN knowledge_points ON knowledge_points.id = review_states.knowledge_point_id
        JOIN learning_plans ON learning_plans.id = review_states.plan_id
        WHERE review_states.user_id = %s
          AND review_states.due_at IS NOT NULL
          AND review_states.due_at <= now()
          AND review_states.suspended_at IS NULL
          AND learning_plans.status = 'active'
          AND learning_plans.deleted_at IS NULL
          AND knowledge_points.deleted_at IS NULL
        ORDER BY review_states.due_at ASC, review_states.lapses DESC, knowledge_points.mastery_score ASC
        LIMIT %s
        """,
        (user_id, limit),
    ).fetchall()
    items: list[dict[str, object]] = []
    for row in rows:
        review_state = serialize_review_state(row)
        items.append(
            {
                "knowledge_point_id": str(row["kp_id"]),
                "knowledge_point_title": row["kp_title"],
                "forget_risk": forget_risk_for(review_state),
                "review_state": review_state,
            }
        )
    return items


def _load_latest_learning_activity(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_id: str,
) -> datetime | None:
    row = conn.execute(
        """
        SELECT
          GREATEST(
            COALESCE(MAX(learning_sessions.started_at), 'epoch'::timestamptz),
            COALESCE(MAX(learning_sessions.ended_at), 'epoch'::timestamptz),
            COALESCE(MAX(attempts.created_at), 'epoch'::timestamptz)
          ) AS latest_activity
        FROM learning_sessions
        LEFT JOIN attempts ON attempts.session_id = learning_sessions.id
        WHERE learning_sessions.user_id = %s
          AND learning_sessions.plan_id = %s
          AND learning_sessions.session_type = 'learn'
        """,
        (user_id, plan_id),
    ).fetchone()
    if row is None:
        return None
    value = row.get("latest_activity")
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _session_summary_text(
    session: Mapping[str, object],
    *,
    current_point: Mapping[str, object] | None,
    latest_attempt: Mapping[str, object] | None,
) -> str:
    stored = session.get("summary_text")
    if isinstance(stored, str) and stored.strip():
        return stored

    title = current_point["title"] if current_point is not None else "当前练习"
    module_title = current_point["module_title"] if current_point is not None else "当前阶段"
    if latest_attempt is None:
        return f"上次停在 {module_title} / {title}，可继续当前练习。"

    completion = latest_attempt.get("code_completion_result")
    if isinstance(completion, Mapping):
        result = str(completion.get("result") or "").strip()
        if result:
            result_label = {
                "failed": "未通过",
                "partial": "部分通过",
                "passed": "通过",
                "easy": "轻松通过",
            }.get(result, result)
            return f"上次停在 {module_title} / {title}，最近一次提交结果为{result_label}。"

    runtime_status = str(latest_attempt.get("runtime_status") or "").strip()
    if runtime_status:
        return f"上次停在 {module_title} / {title}，最近一次运行状态为 {runtime_status}。"
    return f"上次停在 {module_title} / {title}，可继续当前练习。"


def _serialize_module_summary(
    current_point: Mapping[str, object] | None,
    plan: Mapping[str, object],
) -> dict[str, object] | None:
    module_id = _knowledge_point_module_id_or_none(current_point) or _string_or_none(plan.get("current_module_id"))
    module_title = current_point["module_title"] if current_point is not None else plan.get("current_module_title")
    if module_id is None or module_title in {None, ""}:
        return None
    return {
        "id": module_id,
        "title": module_title,
    }


def _extract_knowledge_point_id(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if candidate.startswith("{"):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, Mapping):
            knowledge_point_id = payload.get("knowledge_point_id")
            return str(knowledge_point_id) if knowledge_point_id else None
        return None
    return candidate


def _knowledge_point_id_or_none(point: Mapping[str, object] | None) -> str | None:
    if point is None:
        return None
    return str(point["id"])


def _knowledge_point_module_id_or_none(point: Mapping[str, object] | None) -> str | None:
    if point is None:
        return None
    return str(point["module_id"])


def _string_or_none(value: object) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0
