import json
from collections.abc import Mapping

from psycopg import Connection

from app.models.onboarding import UserCreateRequest


ALLOWED_PREFERENCE_FIELDS = {
    "display_name",
    "learning_style",
    "teaching_preference",
    "encouragement_preference",
    "profession",
    "background_context",
    "preferred_time_slots",
    "reminder_preference",
}

FORBIDDEN_PREFERENCE_FIELDS = {
    "attempt_policy",
    "attempt_persistence",
    "attempt_required_fields",
    "score_rules",
    "scoring_rules",
    "score_breakdown",
    "fsrs_rules",
    "fsrs_parameters",
    "fsrs_rating",
    "due_at",
    "review_state",
}


def create_user(
    conn: Connection[dict[str, object]],
    payload: UserCreateRequest,
) -> dict[str, object]:
    row = conn.execute(
        """
        INSERT INTO users (
          display_name, learning_style, teaching_preference, encouragement_preference,
          profession, background_context, preferred_time_slots, reminder_preference
        )
        VALUES (
          %(display_name)s, %(learning_style)s, %(teaching_preference)s,
          %(encouragement_preference)s, %(profession)s, %(background_context)s,
          %(preferred_time_slots)s::jsonb, %(reminder_preference)s::jsonb
        )
        RETURNING *
        """,
        {
            **payload.model_dump(exclude={"preferred_time_slots", "reminder_preference"}),
            "preferred_time_slots": json.dumps(payload.preferred_time_slots),
            "reminder_preference": json.dumps(payload.reminder_preference),
        },
    ).fetchone()
    if row is None:
        raise RuntimeError("user insert returned no row")
    return serialize_user(row)


def get_user(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object] | None:
    row = conn.execute(
        "SELECT * FROM users WHERE id = %s AND deleted_at IS NULL",
        (user_id,),
    ).fetchone()
    return serialize_user(row) if row is not None else None


def update_preferences(
    conn: Connection[dict[str, object]],
    user_id: str,
    payload: Mapping[str, object],
) -> tuple[dict[str, object] | None, set[str], set[str]]:
    keys = set(payload.keys())
    forbidden = keys & FORBIDDEN_PREFERENCE_FIELDS
    unknown = keys - ALLOWED_PREFERENCE_FIELDS - FORBIDDEN_PREFERENCE_FIELDS
    if forbidden or unknown:
        return None, forbidden, unknown

    if not payload:
        user = get_user(conn, user_id)
        return user, set(), set()

    assignments: list[str] = []
    params: dict[str, object] = {"user_id": user_id}
    for field_name, value in payload.items():
        if field_name in {"preferred_time_slots", "reminder_preference"}:
            assignments.append(f"{field_name} = %({field_name})s::jsonb")
            params[field_name] = json.dumps(value)
        else:
            assignments.append(f"{field_name} = %({field_name})s")
            params[field_name] = value

    row = conn.execute(
        f"""
        UPDATE users
        SET {", ".join(assignments)}
        WHERE id = %(user_id)s AND deleted_at IS NULL
        RETURNING *
        """,
        params,
    ).fetchone()
    return serialize_user(row) if row is not None else None, set(), set()


def serialize_user(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "display_name": row["display_name"],
        "learning_style": row["learning_style"],
        "teaching_preference": row["teaching_preference"],
        "encouragement_preference": row["encouragement_preference"],
        "profession": row["profession"],
        "background_context": row["background_context"],
        "preferred_time_slots": row["preferred_time_slots"],
        "reminder_preference": row["reminder_preference"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }

