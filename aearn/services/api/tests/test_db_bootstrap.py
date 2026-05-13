import uuid

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect


def _database_available() -> bool:
    try:
        with psycopg.connect(get_settings().database_url, connect_timeout=2) as conn:
            conn.execute("select 1")
        return True
    except psycopg.OperationalError:
        return False


pytestmark = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not available; run aearn infra compose for DB smoke tests.",
)


def test_bootstrap_is_repeatable_and_seeds_catalog() -> None:
    bootstrap_database()
    bootstrap_database()

    with connect() as conn:
        runtime_count = conn.execute("select count(*) as count from runtime_profiles").fetchone()
        course_count = conn.execute("select count(*) as count from language_courses").fetchone()

    assert runtime_count is not None
    assert course_count is not None
    assert runtime_count["count"] >= 5
    assert course_count["count"] >= 5


def test_core_learning_relationships_can_be_inserted() -> None:
    bootstrap_database()
    suffix = uuid.uuid4().hex[:8]

    with connect() as conn:
        user = conn.execute(
            "insert into users (display_name) values (%s) returning id",
            (f"Smoke User {suffix}",),
        ).fetchone()
        course = conn.execute(
            """
            select language_courses.id, language_courses.language, runtime_profiles.id as runtime_profile_id
            from language_courses
            join runtime_profiles on runtime_profiles.id = language_courses.runtime_profile_id
            where language_courses.slug = 'course_js_dom_beginner'
            """,
        ).fetchone()
        assert user is not None
        assert course is not None

        plan = conn.execute(
            """
            insert into learning_plans (
              user_id, language_course_id, goal_text, language, target_level, mode
            )
            values (%s, %s, %s, %s, 'beginner', 'goal_based')
            returning id
            """,
            (user["id"], course["id"], "Learn DOM events", course["language"]),
        ).fetchone()
        assert plan is not None

        module = conn.execute(
            """
            insert into plan_modules (plan_id, title, order_index, is_skippable)
            values (%s, 'DOM Basics', 0, false)
            returning id
            """,
            (plan["id"],),
        ).fetchone()
        assert module is not None

        conn.execute(
            "update learning_plans set current_module_id = %s where id = %s",
            (module["id"], plan["id"]),
        )

        knowledge_point = conn.execute(
            """
            insert into knowledge_points (
              module_id, language_course_id, title, order_index, skill_tags_json
            )
            values (%s, %s, 'Event state', 0, '["dom", "event"]'::jsonb)
            returning id
            """,
            (module["id"], course["id"]),
        ).fetchone()
        assert knowledge_point is not None

        exercise = conn.execute(
            """
            insert into exercises (
              knowledge_point_id, runtime_profile_id, title, exercise_type,
              prompt_markdown, starter_code
            )
            values (%s, %s, 'Fill event state', 'code_blank', 'Prompt', 'let count = 0;')
            returning id
            """,
            (knowledge_point["id"], course["runtime_profile_id"]),
        ).fetchone()
        assert exercise is not None

        session = conn.execute(
            """
            insert into learning_sessions (user_id, plan_id, session_type, entry_point)
            values (%s, %s, 'learn', 'smoke')
            returning id
            """,
            (user["id"], plan["id"]),
        ).fetchone()
        assert session is not None

        attempt = conn.execute(
            """
            insert into attempts (
              session_id, exercise_id, user_id, attempt_type, submitted_code,
              code_hash, runtime_status, total_test_count
            )
            values (%s, %s, %s, 'run', 'let count = 0;', %s, 'success', 1)
            returning id
            """,
            (session["id"], exercise["id"], user["id"], f"hash-{suffix}"),
        ).fetchone()
        assert attempt is not None

        conn.execute(
            """
            insert into review_states (knowledge_point_id, user_id, plan_id, last_attempt_id)
            values (%s, %s, %s, %s)
            """,
            (knowledge_point["id"], user["id"], plan["id"], attempt["id"]),
        )

        review_state = conn.execute(
            "select card_state from review_states where knowledge_point_id = %s",
            (knowledge_point["id"],),
        ).fetchone()
        conn.rollback()

    assert review_state is not None
    assert review_state["card_state"] == "new"
