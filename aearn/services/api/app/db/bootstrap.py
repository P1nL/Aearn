import json
from pathlib import Path

from psycopg import Connection

from app.db.connection import connect
from app.db.seeds import LANGUAGE_COURSE_SEEDS, RUNTIME_PROFILE_SEEDS


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def bootstrap_database() -> None:
    with connect() as conn:
        apply_schema(conn)
        seed_runtime_profiles(conn)
        seed_language_courses(conn)
        conn.commit()


def apply_schema(conn: Connection[dict[str, object]]) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def seed_runtime_profiles(conn: Connection[dict[str, object]]) -> None:
    for seed in RUNTIME_PROFILE_SEEDS:
        conn.execute(
            """
            INSERT INTO runtime_profiles (
              slug, runtime_tier, language, runner, supports_realtime_preview,
              supports_stdout, supports_tests, compile_required, timeout_ms,
              memory_limit_mb, sandbox_policy
            )
            VALUES (
              %(slug)s, %(runtime_tier)s, %(language)s, %(runner)s,
              %(supports_realtime_preview)s, %(supports_stdout)s, %(supports_tests)s,
              %(compile_required)s, %(timeout_ms)s, %(memory_limit_mb)s,
              %(sandbox_policy)s::jsonb
            )
            ON CONFLICT (slug) DO UPDATE SET
              runtime_tier = EXCLUDED.runtime_tier,
              language = EXCLUDED.language,
              runner = EXCLUDED.runner,
              supports_realtime_preview = EXCLUDED.supports_realtime_preview,
              supports_stdout = EXCLUDED.supports_stdout,
              supports_tests = EXCLUDED.supports_tests,
              compile_required = EXCLUDED.compile_required,
              timeout_ms = EXCLUDED.timeout_ms,
              memory_limit_mb = EXCLUDED.memory_limit_mb,
              sandbox_policy = EXCLUDED.sandbox_policy,
              archived_at = NULL
            """,
            seed | {"sandbox_policy": json.dumps(seed["sandbox_policy"])},
        )


def seed_language_courses(conn: Connection[dict[str, object]]) -> None:
    for seed in LANGUAGE_COURSE_SEEDS:
        conn.execute(
            """
            INSERT INTO language_courses (
              slug, language, title, description, level, runtime_profile_id,
              supported_exercise_types_json
            )
            SELECT
              %(slug)s, %(language)s, %(title)s, %(description)s, %(level)s,
              runtime_profiles.id, %(supported_exercise_types_json)s::jsonb
            FROM runtime_profiles
            WHERE runtime_profiles.slug = %(runtime_profile_slug)s
            ON CONFLICT (slug) DO UPDATE SET
              language = EXCLUDED.language,
              title = EXCLUDED.title,
              description = EXCLUDED.description,
              level = EXCLUDED.level,
              runtime_profile_id = EXCLUDED.runtime_profile_id,
              supported_exercise_types_json = EXCLUDED.supported_exercise_types_json,
              archived_at = NULL
            """,
            seed
            | {
                "supported_exercise_types_json": json.dumps(
                    seed["supported_exercise_types_json"],
                ),
            },
        )


if __name__ == "__main__":
    bootstrap_database()
    print("Aearn database bootstrap complete.")
