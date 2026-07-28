import json
import uuid
from datetime import timedelta

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from tutor_execution_support import create_pending_execution_job


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


EXECUTION_SCOPE_CONSTRAINTS = (
    "uq_tutor_effects_id_run",
    "uq_tutor_effects_id_run_effect",
    "uq_tutor_input_events_run_message_revision",
    "uq_tutor_execution_intents_id_scope",
    "fk_tutor_execution_intent_consumed_effect_run",
    "fk_tutor_execution_intent_accepted_input",
    "fk_tutor_execution_job_intent_scope",
    "fk_tutor_execution_job_effect_scope",
)

EXECUTION_LIFECYCLE_CONSTRAINTS = (
    "chk_tutor_execution_jobs_terminal_result",
    "chk_tutor_execution_jobs_claimed_lease",
    "chk_tutor_execution_jobs_launch_reservation",
    "chk_tutor_execution_jobs_reserved_running",
    "chk_tutor_execution_jobs_running_started",
)

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
    "tutor_execution_intents",
    "tutor_execution_jobs",
    "tutor_execution_attempts",
    "tutor_executor_health",
    "tutor_run_traces",
    "tutor_memory_curation_outbox",
    "tutor_curation_proposals",
    "tutor_proactive_preferences",
    "tutor_proactive_signals",
    "tutor_proactive_candidates",
    "tutor_curation_jobs",
    "tutor_scheduler_audit",
    "tutor_plan_revisions",
    "tutor_active_plans",
    "tutor_plan_revision_actions",
    "tutor_memory_preferences",
    "tutor_memory_entries",
    "tutor_context_summaries",
    "tutor_curation_projection_receipts",
    "tutor_activity_records",
    "tutor_inbox_items",
    "tutor_api_idempotency_records",
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
                    "trg_tutor_execution_jobs_updated_at",
                    "trg_tutor_execution_jobs_lifecycle_guard",
                    "trg_tutor_executor_health_updated_at",
                    "trg_tutor_memory_curation_outbox_updated_at",
                    "trg_tutor_curation_proposals_updated_at",
                    "trg_tutor_proactive_preferences_updated_at",
                    "trg_tutor_proactive_candidates_updated_at",
                    "trg_tutor_proactive_candidates_lifecycle",
                    "trg_tutor_curation_jobs_updated_at",
                    "trg_tutor_curation_jobs_lifecycle",
                    "trg_tutor_plan_revisions_immutable",
                    "trg_tutor_plan_actions_immutable",
                    "trg_tutor_memory_entries_lifecycle",
                    "trg_tutor_activity_records_immutable",
                    "trg_tutor_inbox_items_lifecycle",
                    "trg_tutor_active_plans_updated_at",
                    "trg_tutor_memory_preferences_updated_at",
                    "trg_tutor_memory_entries_updated_at",
                    "trg_tutor_inbox_items_updated_at",
                ],
            ),
        ).fetchall()
        assert {str(row["table_name"]) for row in table_rows} == set(TARGET_TUTOR_TABLES)
        assert {str(row["tgname"]) for row in trigger_rows} == {
            "trg_tutor_conversations_updated_at",
            "trg_tutor_runs_updated_at",
            "trg_tutor_effects_updated_at",
            "trg_tutor_execution_jobs_updated_at",
            "trg_tutor_execution_jobs_lifecycle_guard",
            "trg_tutor_executor_health_updated_at",
            "trg_tutor_memory_curation_outbox_updated_at",
            "trg_tutor_curation_proposals_updated_at",
            "trg_tutor_proactive_preferences_updated_at",
            "trg_tutor_proactive_candidates_updated_at",
            "trg_tutor_proactive_candidates_lifecycle",
            "trg_tutor_curation_jobs_updated_at",
            "trg_tutor_curation_jobs_lifecycle",
            "trg_tutor_plan_revisions_immutable",
            "trg_tutor_plan_actions_immutable",
            "trg_tutor_memory_entries_lifecycle",
            "trg_tutor_activity_records_immutable",
            "trg_tutor_inbox_items_lifecycle",
            "trg_tutor_active_plans_updated_at",
            "trg_tutor_memory_preferences_updated_at",
            "trg_tutor_memory_entries_updated_at",
            "trg_tutor_inbox_items_updated_at",
        }
        executor_indexes = conn.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND indexname = ANY(%s)
            """,
            (
                [
                    "idx_tutor_execution_intents_run_expiry",
                    "idx_tutor_execution_jobs_claim",
                    "idx_tutor_execution_attempts_job_created",
                    "idx_tutor_executor_health_heartbeat",
                    "idx_tutor_plan_revisions_user_created",
                    "idx_tutor_memory_entries_user_state",
                    "idx_tutor_curation_projection_receipts_user_created",
                    "idx_tutor_activity_records_user_created",
                    "idx_tutor_inbox_items_user_state",
                    "idx_tutor_api_idempotency_user_created",
                ],
            ),
        ).fetchall()
        assert {str(row["indexname"]) for row in executor_indexes} == {
            "idx_tutor_execution_intents_run_expiry",
            "idx_tutor_execution_jobs_claim",
            "idx_tutor_execution_attempts_job_created",
            "idx_tutor_executor_health_heartbeat",
            "idx_tutor_plan_revisions_user_created",
            "idx_tutor_memory_entries_user_state",
            "idx_tutor_curation_projection_receipts_user_created",
            "idx_tutor_activity_records_user_created",
            "idx_tutor_inbox_items_user_state",
            "idx_tutor_api_idempotency_user_created",
        }
        execution_constraint_rows = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            (list(EXECUTION_SCOPE_CONSTRAINTS + EXECUTION_LIFECYCLE_CONSTRAINTS),),
        ).fetchall()
        assert {str(row["conname"]) for row in execution_constraint_rows} == set(
            EXECUTION_SCOPE_CONSTRAINTS + EXECUTION_LIFECYCLE_CONSTRAINTS
        )

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


def test_tutor_execution_schema_rejects_cross_scope_and_lifecycle_mutations(tutor_persistence) -> None:
    """The database, not only Python guards, owns the execution job invariants."""

    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    _, job_id = create_pending_execution_job(fixture, now=now)
    job = fixture.connection.execute(
        """
        SELECT id, intent_id, effect_record_id, effect_key
        FROM tutor_execution_jobs
        WHERE id = %s
        """,
        (job_id,),
    ).fetchone()
    assert job is not None

    other_run = fixture.repository.create_run(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        origin="interactive",
    )
    other_effect = fixture.connection.execute(
        """
        INSERT INTO tutor_effects (
          run_id, effect_id, idempotency_key, effect_type, expected_input_revision,
          payload_hash, lease_owner_id, lease_generation, status, safe_outcome_json, safe_outcome_hash
        )
        VALUES (%s, %s, %s, 'runner.execute', 0, %s, 'schema-check', 1, 'denied', '{}'::jsonb, %s)
        RETURNING id
        """,
        (
            other_run.run_id,
            str(job["effect_key"]),
            "schema-cross-scope-effect",
            "a" * 64,
            "b" * 64,
        ),
    ).fetchone()
    assert other_effect is not None

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_execution_intents SET input_revision = input_revision + 1 WHERE id = %s",
                (job["intent_id"],),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                UPDATE tutor_execution_intents
                SET consumed_at = now(), consumed_by_effect_id = %s
                WHERE id = %s
                """,
                (other_effect["id"], job["intent_id"]),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_execution_jobs SET effect_record_id = %s WHERE id = %s",
                (other_effect["id"], job_id),
            )

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                UPDATE tutor_execution_jobs
                SET run_id = %s, effect_record_id = %s
                WHERE id = %s
                """,
                (other_run.run_id, other_effect["id"], job_id),
            )

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_execution_jobs SET state = 'completed' WHERE id = %s",
                (job_id,),
            )

    fixture.connection.execute(
        """
        UPDATE tutor_execution_jobs
        SET state = 'claimed', lease_owner_id = 'schema-executor', lease_generation = 1,
            lease_expires_at = %s
        WHERE id = %s
        """,
        (now + timedelta(seconds=30), job_id),
    )
    fixture.connection.execute(
        """
        UPDATE tutor_execution_jobs
        SET state = 'launch_reserved', launch_token = 'schema-launch-token',
            launch_generation = 1, launch_reserved_at = %s
        WHERE id = %s
        """,
        (now, job_id),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_execution_jobs SET launch_token = 'replacement-token' WHERE id = %s",
                (job_id,),
            )

    fixture.connection.execute(
        """
        UPDATE tutor_execution_jobs
        SET state = 'completed', result_json = %s::jsonb, result_hash = %s,
            terminal_at = %s, cleanup_state = 'completed'
        WHERE id = %s
        """,
        (json.dumps({"status": "success"}), "c" * 64, now, job_id),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                UPDATE tutor_execution_jobs
                SET state = 'pending', result_json = NULL, result_hash = NULL, terminal_at = NULL
                WHERE id = %s
                """,
                (job_id,),
            )

    fixture.connection.execute(
        """
        UPDATE tutor_execution_jobs
        SET state = 'failed', result_json = %s::jsonb, result_hash = %s, cleanup_state = 'failed'
        WHERE id = %s
        """,
        (json.dumps({"status": "failed"}), "d" * 64, job_id),
    )
    terminal = fixture.connection.execute(
        "SELECT state, launch_token, cleanup_state FROM tutor_execution_jobs WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert terminal == {
        "state": "failed",
        "launch_token": "schema-launch-token",
        "cleanup_state": "failed",
    }
