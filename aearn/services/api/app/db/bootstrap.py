import json
from time import sleep

from psycopg import Connection
from psycopg.errors import DeadlockDetected, SerializationFailure

from app.db.connection import connect
from app.db.schema import load_schema_fragments
from app.db.seeds import (
    ARCHIVED_LANGUAGE_COURSE_SLUGS,
    LANGUAGE_COURSE_INTENT_TAG_SEEDS,
    LANGUAGE_COURSE_SEEDS,
    LEARNING_INTENT_SEEDS,
    PLANNING_INTENT_POLICY_VERSION,
    RUNTIME_PROFILE_SEEDS,
)


_BOOTSTRAP_ADVISORY_LOCK_KEY = 0x414541524E534348
_BOOTSTRAP_MAX_ATTEMPTS = 3
_BOOTSTRAP_RETRY_DELAY_SECONDS = 0.05
_RETRIABLE_BOOTSTRAP_ERRORS = (DeadlockDetected, SerializationFailure)


def bootstrap_database() -> None:
    for attempt in range(_BOOTSTRAP_MAX_ATTEMPTS):
        try:
            with connect() as conn:
                # Serialize bootstrap owners across API, tests, and worker processes.
                # Business DML does not take this lock, so deadlocks still retry the
                # complete transaction instead of committing partial fragments.
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (_BOOTSTRAP_ADVISORY_LOCK_KEY,))
                apply_schema(conn)
                seed_runtime_profiles(conn)
                seed_language_courses(conn)
                archive_language_courses(conn)
                seed_learning_intents(conn)
                seed_language_course_intent_tags(conn)
                require_language_course_intent_coverage(conn)
                conn.commit()
            return
        except _RETRIABLE_BOOTSTRAP_ERRORS:
            if attempt + 1 >= _BOOTSTRAP_MAX_ATTEMPTS:
                raise
            sleep(_BOOTSTRAP_RETRY_DELAY_SECONDS * (attempt + 1))


def apply_schema(conn: Connection[dict[str, object]]) -> None:
    for fragment in load_schema_fragments():
        conn.execute(fragment.sql)


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


def seed_learning_intents(conn: Connection[dict[str, object]]) -> None:
    for seed in LEARNING_INTENT_SEEDS:
        conn.execute(
            """
            INSERT INTO tutor_learning_intents (
              intent_key, display_name, state, policy_version
            ) VALUES (%(intent_key)s, %(display_name)s, %(state)s, %(policy_version)s)
            ON CONFLICT (intent_key) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              state = EXCLUDED.state,
              policy_version = EXCLUDED.policy_version
            """,
            seed | {"policy_version": PLANNING_INTENT_POLICY_VERSION},
        )


def seed_language_course_intent_tags(conn: Connection[dict[str, object]]) -> None:
    for seed in LANGUAGE_COURSE_INTENT_TAG_SEEDS:
        row = conn.execute(
            """
            INSERT INTO language_course_intent_tags (
              course_id, intent_key, relevance_rank, is_primary, policy_version
            )
            SELECT courses.id, %(intent_key)s, %(relevance_rank)s, %(is_primary)s, %(policy_version)s
            FROM language_courses AS courses
            WHERE courses.slug = %(course_slug)s
            ON CONFLICT (course_id, intent_key) DO UPDATE SET
              relevance_rank = EXCLUDED.relevance_rank,
              is_primary = EXCLUDED.is_primary,
              policy_version = EXCLUDED.policy_version
            RETURNING course_id
            """,
            seed | {"policy_version": PLANNING_INTENT_POLICY_VERSION},
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"language course intent backfill course is missing: {seed['course_slug']}"
            )


def language_course_intent_coverage(conn: Connection[dict[str, object]]) -> dict[str, list[str]]:
    missing_courses = conn.execute(
        """
        SELECT courses.id::text AS course_id, courses.slug
        FROM language_courses AS courses
        WHERE courses.archived_at IS NULL
          AND NOT EXISTS (
            SELECT 1
            FROM language_course_intent_tags AS tags
            JOIN tutor_learning_intents AS intents
              ON intents.intent_key = tags.intent_key AND intents.state = 'active'
            WHERE tags.course_id = courses.id
          )
        ORDER BY courses.slug
        """
    ).fetchall()
    missing_intents = conn.execute(
        """
        SELECT intents.intent_key
        FROM tutor_learning_intents AS intents
        WHERE intents.state = 'active'
          AND NOT EXISTS (
            SELECT 1
            FROM language_course_intent_tags AS tags
            JOIN language_courses AS courses
              ON courses.id = tags.course_id AND courses.archived_at IS NULL
            WHERE tags.intent_key = intents.intent_key
          )
        ORDER BY intents.intent_key
        """
    ).fetchall()
    return {
        "missing_course_ids": [str(row["course_id"]) for row in missing_courses],
        "missing_course_slugs": [str(row["slug"]) for row in missing_courses],
        "missing_intent_keys": [str(row["intent_key"]) for row in missing_intents],
    }


def require_language_course_intent_coverage(conn: Connection[dict[str, object]]) -> None:
    coverage = language_course_intent_coverage(conn)
    if any(coverage.values()):
        raise RuntimeError(f"language course intent coverage is incomplete: {coverage}")
    conn.execute("SELECT assert_language_course_intent_coverage()")


def archive_language_courses(conn: Connection[dict[str, object]]) -> None:
    if not ARCHIVED_LANGUAGE_COURSE_SLUGS:
        return
    conn.execute(
        """
        UPDATE language_courses
        SET archived_at = COALESCE(archived_at, now())
        WHERE slug = ANY(%s)
          AND archived_at IS NULL
        """,
        (list(ARCHIVED_LANGUAGE_COURSE_SLUGS),),
    )


if __name__ == "__main__":
    bootstrap_database()
    print("Aearn database bootstrap complete.")
