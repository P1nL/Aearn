from collections.abc import Mapping

from psycopg import Connection


def list_courses(
    conn: Connection[dict[str, object]],
    *,
    language: str | None = None,
    level: str | None = None,
) -> list[dict[str, object]]:
    conditions = ["language_courses.archived_at IS NULL"]
    params: dict[str, object] = {}
    if language is not None:
        conditions.append("language_courses.language = %(language)s")
        params["language"] = language
    if level is not None:
        conditions.append("language_courses.level = %(level)s")
        params["level"] = level

    rows = conn.execute(
        f"""
        SELECT
          language_courses.*,
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
        FROM language_courses
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        WHERE {" AND ".join(conditions)}
        ORDER BY language_courses.language, language_courses.level, language_courses.title
        """,
        params,
    ).fetchall()
    return [serialize_course(row) for row in rows]


def get_course(
    conn: Connection[dict[str, object]],
    course_id: str | None = None,
    *,
    language: str | None = None,
) -> dict[str, object] | None:
    conditions = ["language_courses.archived_at IS NULL"]
    params: dict[str, object] = {}
    if course_id:
        conditions.append("(language_courses.id::text = %(course_id)s OR language_courses.slug = %(course_id)s)")
        params["course_id"] = course_id
    elif language:
        conditions.append("language_courses.language = %(language)s")
        conditions.append("language_courses.level = 'beginner'")
        params["language"] = language
    else:
        return None

    row = conn.execute(
        f"""
        SELECT
          language_courses.*,
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
        FROM language_courses
        JOIN runtime_profiles ON runtime_profiles.id = language_courses.runtime_profile_id
        WHERE {" AND ".join(conditions)}
        ORDER BY language_courses.title
        LIMIT 1
        """,
        params,
    ).fetchone()
    return serialize_course(row) if row is not None else None


def serialize_course(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "slug": row["slug"],
        "language": row["language"],
        "title": row["title"],
        "description": row["description"],
        "level": row["level"],
        "runtime_profile_id": str(row["runtime_profile_id"]),
        "runtime_profile": {
            "id": str(row["runtime_profile_id"]),
            "slug": row["runtime_profile_slug"],
            "runtime_tier": row["runtime_tier"],
            "language": row["runtime_language"],
            "runner": row["runner"],
            "supports_realtime_preview": row["supports_realtime_preview"],
            "supports_stdout": row["supports_stdout"],
            "supports_tests": row["supports_tests"],
            "compile_required": row["compile_required"],
            "timeout_ms": row["timeout_ms"],
            "memory_limit_mb": row["memory_limit_mb"],
            "sandbox_policy": row["sandbox_policy"],
        },
        "supported_exercise_types_json": row["supported_exercise_types_json"],
    }

