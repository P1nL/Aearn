import hashlib
import json
from collections.abc import Mapping
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from psycopg import Connection

from app.models.onboarding import PlanDraft
from app.services.curriculum.catalog import get_course
from app.services.curriculum.plan_generator import normalize_target_level
from app.services.curriculum.teaching_chunks import index_knowledge_point_chunks
from app.services.repositories.review_scheduler import LOCAL_TIMEZONE
from app.services.repositories.user_repository import get_user


class PlanDraftError(ValueError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def confirm_plan(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    plan_draft: PlanDraft,
    idempotency_key: str,
    request_hash: str,
) -> tuple[dict[str, object], bool]:
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")
    existing = conn.execute(
        """
        SELECT request_hash, response_json
        FROM idempotency_records
        WHERE key = %s AND invalidated_at IS NULL
        """,
        (idempotency_key,),
    ).fetchone()
    if existing is not None:
        if existing["request_hash"] != request_hash:
            raise IdempotencyConflictError("same idempotency key was used with a different request body")
        response = existing["response_json"]
        if not isinstance(response, dict):
            raise RuntimeError("stored idempotency response is invalid")
        return response, True

    _validate_plan_draft(plan_draft, user_id)
    course = get_course(conn, plan_draft.language_course_id)
    if course is None:
        raise EntityNotFoundError("COURSE_NOT_FOUND", "课程不存在")
    if course["language"] != plan_draft.language:
        raise PlanDraftError("plan_draft language does not match course")

    plan = conn.execute(
        """
        INSERT INTO learning_plans (
          user_id, language_course_id, goal_text, language, target_level, mode, deadline
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING *
        """,
        (
            user_id,
            plan_draft.language_course_id,
            plan_draft.goal_text,
            plan_draft.language,
            normalize_target_level(plan_draft.target_level),
            plan_draft.mode,
            plan_draft.deadline,
        ),
    ).fetchone()
    if plan is None:
        raise RuntimeError("plan insert returned no row")

    module_rows: list[dict[str, object]] = []
    knowledge_point_rows: list[dict[str, object]] = []
    for module in plan_draft.modules:
        module_row = conn.execute(
            """
            INSERT INTO plan_modules (
              plan_id, title, description, order_index, is_skippable,
              is_adjustable, estimated_sessions
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                plan["id"],
                module.title,
                module.description,
                module.order_index,
                module.is_skippable,
                module.is_adjustable,
                module.estimated_sessions,
            ),
        ).fetchone()
        if module_row is None:
            raise RuntimeError("module insert returned no row")
        module_rows.append(module_row)

        for knowledge_point in module.knowledge_points:
            lesson_outline, lesson_sources = _curated_lesson_content(
                language=plan_draft.language,
                title=knowledge_point.title,
                description=knowledge_point.description,
            )
            kp_row = conn.execute(
                """
                INSERT INTO knowledge_points (
                  module_id, language_course_id, title, description, order_index,
                  skill_tags_json, lesson_outline_json, lesson_sources_json
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                RETURNING *
                """,
                (
                    module_row["id"],
                    plan_draft.language_course_id,
                    knowledge_point.title,
                    knowledge_point.description,
                    len(knowledge_point_rows),
                    json.dumps(knowledge_point.skill_tags),
                    json.dumps(lesson_outline),
                    json.dumps(lesson_sources),
                ),
            ).fetchone()
            if kp_row is None:
                raise RuntimeError("knowledge point insert returned no row")
            knowledge_point_rows.append(kp_row)
            index_knowledge_point_chunks(conn, str(kp_row["id"]), kp_row)
            conn.execute(
                """
                INSERT INTO review_states (knowledge_point_id, user_id, plan_id)
                VALUES (%s, %s, %s)
                """,
                (kp_row["id"], user_id, plan["id"]),
            )

    first_module_id = module_rows[0]["id"] if module_rows else None
    if first_module_id is not None:
        conn.execute(
            "UPDATE learning_plans SET current_module_id = %s WHERE id = %s",
            (first_module_id, plan["id"]),
        )
        plan["current_module_id"] = first_module_id

    response = _build_plan_response(plan, module_rows, knowledge_point_rows)
    conn.execute(
        """
        INSERT INTO idempotency_records (key, operation, request_hash, response_json, user_id)
        VALUES (%s, 'confirm_plan', %s, %s::jsonb, %s)
        """,
        (idempotency_key, request_hash, json.dumps(response, default=str), user_id),
    )
    return response, False


def get_plan_detail(
    conn: Connection[dict[str, object]],
    plan_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, object] | None:
    params: tuple[object, ...]
    user_clause = ""
    if user_id is not None:
        user_clause = "AND user_id = %s"
        params = (plan_id, user_id)
    else:
        params = (plan_id,)
    plan = conn.execute(
        f"""
        SELECT *
        FROM learning_plans
        WHERE id = %s
          AND deleted_at IS NULL
          {user_clause}
        """,
        params,
    ).fetchone()
    if plan is None:
        return None
    modules = conn.execute(
        """
        SELECT * FROM plan_modules
        WHERE plan_id = %s AND deleted_at IS NULL
        ORDER BY order_index
        """,
        (plan_id,),
    ).fetchall()
    knowledge_points = conn.execute(
        """
        SELECT
          knowledge_points.*,
          review_states.knowledge_point_id AS review_state_knowledge_point_id,
          review_states.due_at AS review_state_due_at,
          review_states.suspended_at AS review_state_suspended_at,
          (
            review_states.due_at IS NOT NULL
            AND review_states.due_at <= now()
            AND review_states.suspended_at IS NULL
          ) AS review_state_is_due
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        LEFT JOIN review_states
          ON review_states.knowledge_point_id = knowledge_points.id
         AND review_states.plan_id = %s
        WHERE plan_modules.plan_id = %s AND knowledge_points.deleted_at IS NULL
        ORDER BY plan_modules.order_index, knowledge_points.order_index
        """,
        (plan_id, plan_id),
    ).fetchall()
    return _build_plan_response(plan, modules, knowledge_points)


def request_hash(payload: Mapping[str, object]) -> str:
    body = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def default_confirm_key(user_id: str, draft_id: str) -> str:
    return f"confirm-plan:{user_id}:{draft_id}"


def _validate_plan_draft(plan_draft: PlanDraft, user_id: str) -> None:
    if plan_draft.user_id != user_id:
        raise PlanDraftError("plan_draft user_id does not match request user_id")
    if not plan_draft.modules:
        raise PlanDraftError("plan_draft must include at least one module")
    if not any(not module.is_skippable for module in plan_draft.modules):
        raise PlanDraftError("plan_draft must include at least one non-skippable core module")
    for module in plan_draft.modules:
        if not module.knowledge_points:
            raise PlanDraftError("each module must include at least one knowledge point")


def _build_plan_response(
    plan: Mapping[str, object],
    modules: Sequence[Mapping[str, object]],
    knowledge_points: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    first_knowledge_point = knowledge_points[0] if knowledge_points else None
    plan_status = str(plan["status"])
    return {
        "LearningPlan": _serialize_plan(plan),
        "modules": [_serialize_module(module) for module in modules],
        "knowledge_points": [_serialize_knowledge_point(kp, plan_status=plan_status) for kp in knowledge_points],
        "next_entry_point": {
            "type": "learning_session",
            "plan_id": str(plan["id"]),
            "knowledge_point_id": str(first_knowledge_point["id"]) if first_knowledge_point else None,
        },
    }


def _serialize_plan(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "language_course_id": str(row["language_course_id"]),
        "goal_text": row["goal_text"],
        "language": row["language"],
        "target_level": row["target_level"],
        "mode": row["mode"],
        "deadline": row["deadline"],
        "status": row["status"],
        "overall_progress": _decimal_to_float(row["overall_progress"]),
        "current_module_id": str(row["current_module_id"]) if row.get("current_module_id") else None,
    }


def _serialize_module(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "plan_id": str(row["plan_id"]),
        "title": row["title"],
        "description": row["description"],
        "order_index": row["order_index"],
        "status": row["status"],
        "is_skippable": row["is_skippable"],
        "is_adjustable": row["is_adjustable"],
        "estimated_sessions": row["estimated_sessions"],
    }


def _serialize_knowledge_point(row: Mapping[str, object], *, plan_status: str = "active") -> dict[str, object]:
    payload = {
        "id": str(row["id"]),
        "module_id": str(row["module_id"]),
        "language_course_id": str(row["language_course_id"]),
        "title": row["title"],
        "description": row["description"],
        "order_index": row["order_index"],
        "skill_tags_json": row["skill_tags_json"],
        "status": row["status"],
        "mastery_score": _decimal_to_float(row["mastery_score"]),
    }
    if row.get("review_state_knowledge_point_id") is not None:
        payload["review_state"] = _serialize_review_state_preview(row, plan_status=plan_status)
    return payload


def _serialize_review_state_preview(row: Mapping[str, object], *, plan_status: str) -> dict[str, object]:
    due_at = row.get("review_state_due_at")
    unavailable = plan_status != "active" or row.get("review_state_suspended_at") is not None
    is_due = bool(row.get("review_state_is_due")) and not unavailable
    return {
        "due_at": _iso_or_none(due_at),
        "is_due": is_due,
        "label": "已安排，当前不可复习" if unavailable else _review_state_label(due_at, is_due=is_due),
    }


def _review_state_label(due_at: object, *, is_due: bool) -> str:
    if due_at is None:
        return "已安排，等待同步"
    if is_due:
        return "已到期"
    if not isinstance(due_at, datetime):
        return "已安排，未到期"
    local_due_at = _aware_datetime(due_at).astimezone(LOCAL_TIMEZONE)
    return f"未到期 · 下次 {local_due_at:%m-%d %H:%M}"


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _aware_datetime(value).isoformat()
    return str(value)


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _curated_lesson_content(
    *,
    language: str,
    title: str,
    description: str | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    overview = description or f"理解 {title} 的基本行为，并能用自己的话说明原因。"
    if language == "javascript":
        return (
            [
                {
                    "id": "core_concept",
                    "title": title,
                    "note": overview,
                },
                {
                    "id": "runtime_behavior",
                    "title": "事件与状态行为",
                    "note": "事件回调会在交互发生时运行；需要跨交互保留的状态应位于可复用的作用域。",
                },
                {
                    "id": "verification",
                    "title": "可验证的结果",
                    "note": "用可见 DOM 结果或测试断言确认事件是否绑定、状态是否按预期更新。",
                },
            ],
            [
                {
                    "title": "MDN Web Docs: EventTarget.addEventListener()",
                    "url": "https://developer.mozilla.org/docs/Web/API/EventTarget/addEventListener",
                },
                {
                    "title": "MDN JavaScript Guide: Closures",
                    "url": "https://developer.mozilla.org/docs/Web/JavaScript/Guide/Closures",
                },
            ],
        )
    if language == "python":
        return (
            [
                {"id": "core_concept", "title": title, "note": overview},
                {
                    "id": "value_flow",
                    "title": "返回值与输出",
                    "note": "函数的返回值供调用方继续计算，stdout 只负责可见输出与调试观察。",
                },
                {
                    "id": "verification",
                    "title": "断言验证",
                    "note": "通过可见测试比较输入和返回值，使用 stdout 辅助定位而不是替代结果。",
                },
            ],
            [
                {
                    "title": "Python Documentation: Defining Functions",
                    "url": "https://docs.python.org/3/tutorial/controlflow.html#defining-functions",
                },
            ],
        )
    return (
        [
            {"id": "core_concept", "title": title, "note": overview},
            {
                "id": "structure",
                "title": "代码结构",
                "note": "先读清类型、参数和返回值之间的约束，再判断代码行为。",
            },
            {
                "id": "verification",
                "title": "静态检查",
                "note": "当前阶段以阅读和补全为主，不把尚未提供的运行能力当作验证事实。",
            },
        ],
        [
            {
                "title": f"Official {language} language documentation",
                "url": "",
            },
        ],
    )
