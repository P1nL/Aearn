import hashlib
import json
from collections.abc import Mapping
from collections.abc import Sequence
from decimal import Decimal

from psycopg import Connection

from app.models.onboarding import PlanDraft
from app.services.catalog import get_course
from app.services.plan_generator import normalize_target_level
from app.services.user_repository import get_user


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
    existing = conn.execute(
        "SELECT request_hash, response_json FROM idempotency_records WHERE key = %s",
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
    if get_user(conn, user_id) is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")
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
            kp_row = conn.execute(
                """
                INSERT INTO knowledge_points (
                  module_id, language_course_id, title, description, order_index,
                  skill_tags_json
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                RETURNING *
                """,
                (
                    module_row["id"],
                    plan_draft.language_course_id,
                    knowledge_point.title,
                    knowledge_point.description,
                    len(knowledge_point_rows),
                    json.dumps(knowledge_point.skill_tags),
                ),
            ).fetchone()
            if kp_row is None:
                raise RuntimeError("knowledge point insert returned no row")
            knowledge_point_rows.append(kp_row)
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
        INSERT INTO idempotency_records (key, operation, request_hash, response_json)
        VALUES (%s, 'confirm_plan', %s, %s::jsonb)
        """,
        (idempotency_key, request_hash, json.dumps(response, default=str)),
    )
    return response, False


def get_plan_detail(conn: Connection[dict[str, object]], plan_id: str) -> dict[str, object] | None:
    plan = conn.execute(
        "SELECT * FROM learning_plans WHERE id = %s AND deleted_at IS NULL",
        (plan_id,),
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
        SELECT knowledge_points.*
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        WHERE plan_modules.plan_id = %s AND knowledge_points.deleted_at IS NULL
        ORDER BY plan_modules.order_index, knowledge_points.order_index
        """,
        (plan_id,),
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
    return {
        "LearningPlan": _serialize_plan(plan),
        "modules": [_serialize_module(module) for module in modules],
        "knowledge_points": [_serialize_knowledge_point(kp) for kp in knowledge_points],
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


def _serialize_knowledge_point(row: Mapping[str, object]) -> dict[str, object]:
    return {
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


def _decimal_to_float(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0
