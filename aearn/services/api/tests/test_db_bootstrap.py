import json
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
    assert runtime_count["count"] >= 9
    assert course_count["count"] >= 8

    with connect() as conn:
        ts_runtime = conn.execute(
            """
            SELECT runtime_tier, language, runner
            FROM runtime_profiles
            WHERE slug = 'rt_node_typescript'
            """,
        ).fetchone()
        sql_runtime = conn.execute(
            """
            SELECT runtime_tier, language, runner, sandbox_policy
            FROM runtime_profiles
            WHERE slug = 'rt_sql_sqlite_query'
            """,
        ).fetchone()
        active_cpp_course = conn.execute(
            """
            SELECT id
            FROM language_courses
            WHERE language = 'cpp' AND archived_at IS NULL
            """,
        ).fetchone()

    assert ts_runtime is not None
    assert ts_runtime["runtime_tier"] == "node_typescript_test"
    assert ts_runtime["language"] == "typescript"
    assert ts_runtime["runner"] == "node"
    assert sql_runtime is not None
    assert sql_runtime["runtime_tier"] == "sql_query_test"
    assert sql_runtime["language"] == "sql"
    assert sql_runtime["runner"] == "sql"
    assert sql_runtime["sandbox_policy"]["dialect"] == "sqlite"
    assert active_cpp_course is None


TARGET_TUTOR_TABLES = (
    "tutor_conversations",
    "tutor_messages",
    "tutor_catalog_snapshots",
    "tutor_runs",
    "tutor_run_skill_selections",
    "tutor_run_input_events",
    "tutor_run_checkpoints",
    "tutor_run_events",
    "tutor_capability_invocations",
    "tutor_effects",
    "tutor_run_traces",
    "tutor_memory_curation_outbox",
    "tutor_curation_proposals",
)


def test_tutor_target_schema_is_repeatable_and_enforces_run_event_identity() -> None:
    bootstrap_database()
    bootstrap_database()
    suffix = uuid.uuid4().hex[:8]

    with connect() as conn:
        table_rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ANY(%s)",
            (list(TARGET_TUTOR_TABLES),),
        ).fetchall()
        trigger_rows = conn.execute(
            """
            SELECT tgname
            FROM pg_trigger
            WHERE tgname = ANY(%s)
              AND NOT tgisinternal
            """,
            (
                [
                    "trg_tutor_conversations_updated_at",
                    "trg_tutor_runs_updated_at",
                    "trg_tutor_effects_updated_at",
                    "trg_tutor_memory_curation_outbox_updated_at",
                    "trg_tutor_curation_proposals_updated_at",
                ],
            ),
        ).fetchall()
        assert {str(row["table_name"]) for row in table_rows} == set(TARGET_TUTOR_TABLES)
        assert {str(row["tgname"]) for row in trigger_rows} == {
            "trg_tutor_conversations_updated_at",
            "trg_tutor_runs_updated_at",
            "trg_tutor_effects_updated_at",
            "trg_tutor_memory_curation_outbox_updated_at",
            "trg_tutor_curation_proposals_updated_at",
        }

        user = conn.execute(
            "INSERT INTO users (display_name) VALUES (%s) RETURNING id",
            (f"Tutor Schema Smoke {suffix}",),
        ).fetchone()
        assert user is not None
        digest = "a" * 64
        catalog = conn.execute(
            """
            INSERT INTO tutor_catalog_snapshots (digest, manifest_json, redaction_version)
            VALUES (%s, %s::jsonb, 'tutor_safe_projection_v1')
            RETURNING digest
            """,
            (digest, json.dumps({"catalog_digest": digest, "skills": []})),
        ).fetchone()
        assert catalog is not None
        conversation = conn.execute(
            "INSERT INTO tutor_conversations (user_id) VALUES (%s) RETURNING id",
            (user["id"],),
        ).fetchone()
        assert conversation is not None
        run = conn.execute(
            """
            INSERT INTO tutor_runs (
              user_id, conversation_id, origin, status, policy_json,
              policy_version, policy_fingerprint, catalog_digest
            )
            VALUES (%s, %s, 'interactive', 'queued', %s::jsonb, 'tutor_policy_v1', %s, %s)
            RETURNING id
            """,
            (
                user["id"],
                conversation["id"],
                json.dumps(
                    {
                        "deadline": "2030-01-01T00:00:00+00:00",
                        "max_iterations": 1,
                        "max_model_calls": 1,
                        "max_capability_calls": 0,
                        "max_effects": 0,
                        "context_token_budget": 8,
                        "lease_duration_seconds": 30,
                    }
                ),
                "b" * 64,
                digest,
            ),
        ).fetchone()
        assert run is not None
        event = conn.execute(
            """
            INSERT INTO tutor_run_events (
              run_id, event_sequence, event_key, kind, input_revision, payload_json, payload_hash
            )
            VALUES (%s, 1, 'bootstrap-smoke', 'input_accepted', 0, %s::jsonb, %s)
            RETURNING id
            """,
            (run["id"], json.dumps({"kind": "input_accepted"}), "c" * 64),
        ).fetchone()
        assert event is not None
        with pytest.raises(psycopg.errors.UniqueViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_run_events (
                      run_id, event_sequence, event_key, kind, input_revision, payload_json, payload_hash
                    )
                    VALUES (%s, 1, 'bootstrap-smoke-duplicate', 'input_accepted', 0, %s::jsonb, %s)
                    """,
                    (run["id"], json.dumps({"kind": "input_accepted"}), "d" * 64),
                )
        conn.rollback()


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
