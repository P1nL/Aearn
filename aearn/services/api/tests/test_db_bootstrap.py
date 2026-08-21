import json
import uuid
from datetime import timedelta

import psycopg
import pytest

from app.core.config import get_settings
from app.db.bootstrap import bootstrap_database, language_course_intent_coverage
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


def test_language_course_intent_schema_coverage_and_publication_gate() -> None:
    bootstrap_database()
    bootstrap_database()
    with connect() as conn:
        tables = {
            str(row["table_name"])
            for row in conn.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('tutor_learning_intents', 'language_course_intent_tags')
                """
            ).fetchall()
        }
        assert tables == {"tutor_learning_intents", "language_course_intent_tags"}
        assert language_course_intent_coverage(conn) == {
            "missing_course_ids": [],
            "missing_course_slugs": [],
            "missing_intent_keys": [],
        }
        runtime = conn.execute(
            "SELECT id FROM runtime_profiles WHERE slug = 'rt_python_stdout'"
        ).fetchone()
        assert runtime is not None
        with pytest.raises(psycopg.errors.CheckViolation, match="language_course_intent_coverage_missing"):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO language_courses (
                      slug, language, title, description, level, runtime_profile_id,
                      supported_exercise_types_json
                    ) VALUES (
                      'course_missing_intent_tags', 'python', 'Missing tags', 'coverage gate',
                      'beginner', %s, '[]'::jsonb
                    )
                    """,
                    (runtime["id"],),
                )
                conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


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

PROVIDER_ATTEMPT_RECEIPT_CONSTRAINTS = (
    "uq_tutor_provider_attempt_receipts_identity",
    "fk_tutor_provider_attempt_receipt_run_user",
    "fk_tutor_provider_attempt_receipt_run_conversation",
    "chk_tutor_provider_attempt_receipt_cached_input",
    "chk_tutor_provider_attempt_receipt_calculated_total",
    "chk_tutor_provider_attempt_receipt_usage_availability",
    "chk_tutor_provider_attempt_receipt_outcome_diagnostic",
    "chk_tutor_provider_attempt_receipt_transport_usage",
)

CONVERSATION_TURNRUN_CONSTRAINTS = (
    "fk_tutor_runs_superseded_by_run",
    "chk_tutor_conversations_title",
    "chk_tutor_runs_continuation_kind",
    "chk_tutor_messages_public_thinking_text",
    "chk_tutor_messages_public_thinking_single_representation",
    "uq_tutor_turn_public_thinking_streams_scope",
    "fk_tutor_turn_public_thinking_stream_run_scope",
    "fk_tutor_turn_public_thinking_stream_event",
    "chk_tutor_turn_public_thinking_stream_timestamps",
    "chk_tutor_conversation_events_kind",
    "chk_tutor_conversation_events_projection_version",
)

CONTEXT_SUMMARY_CONSTRAINTS = (
    "chk_tutor_outbox_summary_evidence",
    "chk_tutor_curation_jobs_projection_kind",
    "uq_tutor_outbox_id_conversation",
    "fk_tutor_outbox_covered_message",
    "uq_tutor_context_summary_id_scope",
    "fk_tutor_context_summary_conversation_user",
    "fk_tutor_context_summary_outbox_conversation",
    "fk_tutor_context_summary_covered_message",
    "fk_tutor_context_summary_prior_scope",
    "chk_tutor_context_summary_v2_shape",
)

LESSON_SCHEMA_CONSTRAINTS = (
    "uq_tutor_lesson_documents_id_scope",
    "fk_tutor_lesson_document_user",
    "fk_tutor_lesson_document_track_user",
    "fk_tutor_lesson_document_revision_scope",
    "fk_tutor_lesson_document_standard",
    "fk_tutor_lesson_document_predecessor",
    "chk_tutor_lesson_document_scope_shape",
    "chk_tutor_lesson_document_predecessor_distinct",
    "uq_tutor_lesson_source_snapshots_document_citation",
    "uq_tutor_lesson_source_snapshots_id_scope",
    "fk_tutor_lesson_block_citation_snapshot",
    "uq_tutor_lesson_gate_slots_document_key",
    "uq_tutor_lesson_gate_slots_document_block",
    "uq_tutor_lesson_assignments_id_scope",
    "fk_tutor_lesson_assignment_track_user",
    "fk_tutor_lesson_assignment_document_scope",
    "fk_tutor_lesson_assignment_revision_scope",
    "fk_tutor_lesson_assignment_predecessor",
    "chk_tutor_lesson_assignment_predecessor_distinct",
    "chk_tutor_lesson_assignment_activation",
    "uq_tutor_lesson_authoring_runs_id_user",
    "uq_tutor_lesson_authoring_runs_idempotency",
    "fk_tutor_lesson_authoring_run_track_user",
    "fk_tutor_lesson_authoring_run_revision_scope",
    "chk_tutor_lesson_authoring_run_lease",
    "chk_tutor_lesson_authoring_run_terminal",
    "uq_tutor_lesson_authoring_attempt_identity",
    "fk_tutor_lesson_authoring_attempt_run_user",
    "chk_tutor_lesson_authoring_attempt_usage",
)

PLANNING_FACT_SCHEMA_CONSTRAINTS = (
    "uq_tutor_planning_intake_facts_id_scope",
    "uq_tutor_planning_intake_facts_session_field_revision",
    "uq_tutor_planning_intake_facts_source_value",
    "fk_tutor_planning_intake_fact_session_user",
    "fk_tutor_planning_intake_fact_conversation_user",
    "fk_tutor_planning_intake_fact_run_user",
    "fk_tutor_planning_intake_fact_message_conversation",
    "fk_tutor_planning_intake_fact_input_evidence",
    "fk_tutor_planning_intake_fact_predecessor_scope",
    "chk_tutor_planning_intake_fact_predecessor_distinct",
    "chk_tutor_planning_intake_fact_revision_shape",
    "uq_tutor_planning_question_events_session_hash",
    "uq_tutor_planning_question_events_id_scope",
    "fk_tutor_planning_question_event_session_user",
    "fk_tutor_planning_question_event_conversation_user",
    "fk_tutor_planning_question_event_run_user",
    "fk_tutor_planning_question_event_message_conversation",
    "fk_tutor_planning_question_event_fact_scope",
    "fk_tutor_planning_question_event_previous_scope",
    "chk_tutor_planning_question_event_source_shape",
    "chk_tutor_planning_question_events_status",
)

ACTION_SCHEMA_CONSTRAINTS = (
    "uq_tutor_action_invocations_run_key",
    "uq_tutor_action_invocations_id_run",
    "fk_tutor_action_invocation_parent_run",
    "fk_tutor_action_invocation_run_user",
    "fk_tutor_action_invocation_run_conversation",
    "chk_tutor_action_invocations_parent_distinct",
    "chk_tutor_action_invocations_terminal",
    "chk_tutor_action_invocations_lease_owner",
    "uq_tutor_action_attempts_identity",
    "fk_tutor_action_attempt_invocation_run",
    "chk_tutor_action_attempt_authority",
    "fk_tutor_action_verification_invocation_run",
    "chk_tutor_action_verification_authority",
    "fk_tutor_action_receipt_invocation_run",
    "fk_tutor_action_receipt_run_user",
    "fk_tutor_action_receipt_run_conversation",
    "chk_tutor_action_receipt_authority",
    "chk_tutor_action_receipt_retry",
)

MODEL_REVIEW_SCHEMA_CONSTRAINTS = (
    "uq_tutor_model_review_authoring_scope",
    "fk_tutor_model_review_authoring_candidate",
    "fk_tutor_model_review_authoring_validation",
    "fk_tutor_model_review_authoring_publication",
    "uq_tutor_model_review_candidates_scope",
    "fk_tutor_model_review_candidate_run",
    "uq_tutor_model_review_validation_candidate",
    "fk_tutor_model_review_validation_candidate",
    "uq_tutor_model_review_validation_check",
    "uq_tutor_model_review_publication_candidate",
    "uq_tutor_model_review_publication_gate",
    "fk_tutor_model_review_evidence_publication_scope",
)


REVIEW_SCHEMA_CONSTRAINTS = (
    "uq_tutor_review_schedule_track_key",
    "fk_tutor_review_schedule_progress",
    "fk_tutor_review_schedule_revision",
    "uq_tutor_review_schedule_event_source",
    "uq_tutor_review_schedule_event_scope",
    "fk_tutor_review_schedule_event_scope",
    "uq_tutor_review_sessions_idempotency",
    "fk_tutor_review_session_revision",
    "fk_tutor_review_session_progress",
    "chk_tutor_review_session_terminal",
    "chk_tutor_review_session_failure",
    "chk_tutor_review_session_stage",
    "uq_tutor_review_warmup_session",
    "fk_tutor_review_warmup_session",
    "uq_tutor_review_items_session_order",
    "fk_tutor_review_item_session",
    "fk_tutor_review_item_node",
    "fk_tutor_review_hint_item",
    "chk_tutor_exercise_attempts_type",
    "fk_tutor_exercise_attempt_review_item_scope",
    "uq_tutor_review_finalization_session",
    "fk_tutor_review_finalization_session",
    "fk_tutor_review_finalization_mastery",
    "fk_tutor_review_finalization_schedule_event",
)


CONTEXT_REFERENCE_SCHEMA_CONSTRAINTS = (
    "uq_tutor_message_context_references_input_index",
    "uq_tutor_message_context_references_message_index",
    "uq_tutor_message_context_references_id_user",
    "fk_tutor_context_reference_run_user",
    "fk_tutor_context_reference_run_conversation",
    "fk_tutor_context_reference_message_conversation",
    "fk_tutor_context_reference_input_revision",
    "fk_tutor_context_reference_track_user",
    "fk_tutor_context_reference_document_scope",
    "fk_tutor_context_reference_attempt_scope",
    "fk_tutor_context_reference_review_scope",
    "chk_tutor_message_context_reference_shape",
)


PRACTICE_SCHEMA_CONSTRAINTS = (
    "uq_tutor_exercise_versions_key_version",
    "chk_tutor_exercise_versions_execution_shape",
    "uq_tutor_lesson_gate_bindings_document_key",
    "fk_tutor_lesson_gate_binding_slot",
    "uq_tutor_lesson_gate_states_assignment_binding",
    "fk_tutor_lesson_gate_state_assignment_scope",
    "fk_tutor_lesson_gate_state_binding_scope",
    "chk_tutor_lesson_gate_states_passed",
    "uq_tutor_module_diagnostic_sessions_idempotency",
    "fk_tutor_module_diagnostic_session_revision_scope",
    "chk_tutor_module_diagnostic_sessions_terminal",
    "chk_tutor_module_diagnostic_sessions_confirmation",
    "fk_tutor_module_diagnostic_item_session_scope",
    "fk_tutor_module_diagnostic_item_node_scope",
    "uq_tutor_exercise_attempts_idempotency",
    "chk_tutor_exercise_attempts_owner_shape",
    "fk_tutor_exercise_attempt_submission_scope",
    "fk_tutor_exercise_attempt_result_scope",
    "fk_tutor_exercise_hint_assignment_scope",
    "chk_tutor_execution_intents_source_shape",
    "fk_tutor_execution_intent_gate_submission",
    "chk_tutor_execution_jobs_owner_shape",
    "fk_tutor_execution_job_gate_intent_scope",
    "fk_tutor_exercise_execution_link_job_scope",
)

RUNTIME_PROJECTION_SCHEMA_CONSTRAINTS = (
    "chk_tutor_runs_runtime_kind",
    "uq_tutor_conversation_runtime_threads_scope",
    "fk_tutor_conversation_runtime_thread_conversation_scope",
    "uq_tutor_runtime_bindings_scope",
    "fk_tutor_runtime_binding_run_scope",
    "fk_tutor_runtime_binding_message_scope",
    "fk_tutor_runtime_binding_conversation_thread_scope",
    "chk_tutor_runtime_binding_terminal",
    "uq_tutor_runtime_text_items_identity",
    "uq_tutor_runtime_text_items_scope",
    "fk_tutor_runtime_text_item_binding_scope",
    "fk_tutor_runtime_text_item_conversation_thread_scope",
    "fk_tutor_runtime_text_item_message_scope",
    "chk_tutor_runtime_text_item_terminal",
    "uq_tutor_runtime_item_receipts_event",
    "uq_tutor_runtime_item_receipts_sequence",
    "chk_tutor_runtime_receipt_projection_sequence",
    "chk_tutor_runtime_receipt_source_range",
    "fk_tutor_runtime_receipt_binding_scope",
    "chk_tutor_runtime_receipt_public_item",
    "chk_tutor_runtime_item_receipts_event_kind",
    "chk_tutor_runtime_item_receipts_item_kind",
    "chk_tutor_runtime_item_receipts_public_item_kind",
    "fk_tutor_runtime_error_binding_scope",
)

TUTOR_SCHEMA_CONSTRAINTS = (
    EXECUTION_SCOPE_CONSTRAINTS
    + EXECUTION_LIFECYCLE_CONSTRAINTS
    + PROVIDER_ATTEMPT_RECEIPT_CONSTRAINTS
    + CONVERSATION_TURNRUN_CONSTRAINTS
    + CONTEXT_SUMMARY_CONSTRAINTS
    + PLANNING_FACT_SCHEMA_CONSTRAINTS
    + ACTION_SCHEMA_CONSTRAINTS
    + LESSON_SCHEMA_CONSTRAINTS
    + PRACTICE_SCHEMA_CONSTRAINTS
    + REVIEW_SCHEMA_CONSTRAINTS
    + CONTEXT_REFERENCE_SCHEMA_CONSTRAINTS
    + MODEL_REVIEW_SCHEMA_CONSTRAINTS
    + RUNTIME_PROJECTION_SCHEMA_CONSTRAINTS
)

TARGET_TUTOR_TABLES = (
    "tutor_conversations",
    "tutor_messages",
    "tutor_message_context_references",
    "tutor_catalog_snapshots",
    "tutor_codex_runtime_health",
    "tutor_runs",
    "tutor_conversation_runtime_threads",
    "tutor_run_runtime_bindings",
    "tutor_runtime_text_items",
    "tutor_runtime_item_receipts",
    "tutor_runtime_public_errors",
    "tutor_provider_attempt_receipts",
    "tutor_run_skill_selections",
    "tutor_run_input_events",
    "tutor_run_checkpoints",
    "tutor_run_events",
    "tutor_capability_invocations",
    "tutor_action_invocations",
    "tutor_action_attempts",
    "tutor_action_verifications",
    "tutor_action_receipts",
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
    "tutor_planning_intake_facts",
    "tutor_planning_question_events",
    "tutor_run_public_processes",
    "tutor_run_public_process_steps",
    "tutor_turn_public_thinking_streams",
    "tutor_lesson_documents",
    "tutor_lesson_source_snapshots",
    "tutor_lesson_block_citations",
    "tutor_lesson_gate_slots",
    "tutor_lesson_assignments",
    "tutor_lesson_authoring_runs",
    "tutor_lesson_authoring_attempt_receipts",
    "tutor_exercise_versions",
    "tutor_exercise_private_rubrics",
    "tutor_lesson_gate_bindings",
    "tutor_lesson_gate_states",
    "tutor_module_diagnostic_versions",
    "tutor_module_diagnostic_sessions",
    "tutor_module_diagnostic_items",
    "tutor_exercise_attempts",
    "tutor_exercise_attempt_submissions",
    "tutor_exercise_attempt_results",
    "tutor_exercise_hint_receipts",
    "tutor_exercise_execution_links",
    "tutor_review_schedule_states",
    "tutor_review_schedule_events",
    "tutor_review_sessions",
    "tutor_review_warmup_receipts",
    "tutor_review_items",
    "tutor_review_hint_receipts",
    "tutor_review_finalizations",
    "tutor_model_review_authoring_runs",
    "tutor_model_review_authoring_attempt_receipts",
    "tutor_model_review_candidates",
    "tutor_model_review_validation_runs",
    "tutor_model_review_validation_checks",
    "tutor_model_review_publications",
    "tutor_model_review_evidence_receipts",
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
                    "trg_tutor_provider_attempt_receipts_immutable",
                    "trg_tutor_planning_intake_facts_immutable",
                    "trg_tutor_planning_question_events_immutable",
                    "trg_tutor_action_attempts_immutable",
                    "trg_tutor_action_verifications_immutable",
                    "trg_tutor_action_receipts_immutable",
                    "trg_tutor_action_invocations_lifecycle",
                    "trg_tutor_action_invocations_updated_at",
                    "trg_tutor_conversations_updated_at",
                    "trg_tutor_runs_updated_at",
                    "trg_tutor_runs_runtime_kind_immutable",
                    "trg_tutor_conversation_runtime_threads_lifecycle",
                    "trg_tutor_conversation_runtime_threads_updated_at",
                    "trg_tutor_runtime_bindings_lifecycle",
                    "trg_tutor_runtime_bindings_updated_at",
                    "trg_tutor_runtime_text_items_lifecycle",
                    "trg_tutor_runtime_text_items_updated_at",
                    "trg_tutor_runtime_receipts_immutable",
                    "trg_tutor_runtime_errors_immutable",
                    "trg_tutor_effects_updated_at",
                    "trg_tutor_execution_jobs_updated_at",
                    "trg_tutor_execution_jobs_lifecycle_guard",
                    "trg_tutor_codex_runtime_health_updated_at",
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
                    "trg_tutor_context_summaries_immutable",
                    "trg_tutor_activity_records_immutable",
                    "trg_tutor_inbox_items_lifecycle",
                    "trg_tutor_active_plans_updated_at",
                    "trg_tutor_memory_preferences_updated_at",
                    "trg_tutor_memory_entries_updated_at",
                    "trg_tutor_inbox_items_updated_at",
                    "trg_tutor_public_processes_updated_at",
                    "trg_tutor_lesson_documents_lineage",
                    "trg_tutor_lesson_documents_immutable",
                    "trg_tutor_lesson_source_snapshots_immutable",
                    "trg_tutor_lesson_block_citations_immutable",
                    "trg_tutor_lesson_gate_slots_immutable",
                    "trg_tutor_lesson_assignments_updated_at",
                    "trg_tutor_lesson_assignments_lifecycle",
                    "trg_tutor_lesson_authoring_runs_updated_at",
                    "trg_tutor_lesson_authoring_runs_lifecycle",
                    "trg_tutor_lesson_authoring_attempt_receipts_immutable",
                    "trg_tutor_exercise_versions_immutable",
                    "trg_tutor_exercise_private_rubrics_immutable",
                    "trg_tutor_lesson_gate_bindings_immutable",
                    "trg_tutor_lesson_gate_states_updated_at",
                    "trg_tutor_lesson_gate_states_lifecycle",
                    "trg_tutor_module_diagnostic_versions_immutable",
                    "trg_tutor_module_diagnostic_sessions_updated_at",
                    "trg_tutor_module_diagnostic_sessions_lifecycle",
                    "trg_tutor_module_diagnostic_items_immutable",
                    "trg_tutor_exercise_attempts_immutable",
                    "trg_tutor_exercise_attempt_submissions_immutable",
                    "trg_tutor_exercise_attempt_results_immutable",
                    "trg_tutor_exercise_hint_receipts_immutable",
                    "trg_tutor_exercise_execution_links_immutable",
                    "trg_tutor_review_schedule_states_updated_at",
                    "trg_tutor_review_schedule_states_lifecycle",
                    "trg_tutor_review_sessions_updated_at",
                    "trg_tutor_review_sessions_lifecycle",
                    "trg_tutor_review_schedule_events_immutable",
                    "trg_tutor_review_warmups_immutable",
                    "trg_tutor_review_items_immutable",
                    "trg_tutor_review_hints_immutable",
                    "trg_tutor_review_finalizations_immutable",
                    "trg_tutor_message_context_references_immutable",
                ],
            ),
        ).fetchall()
        assert {str(row["table_name"]) for row in table_rows} == set(TARGET_TUTOR_TABLES)
        summary_column_rows = conn.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
              AND column_name = ANY(%s)
            """,
            (
                ["tutor_memory_curation_outbox", "tutor_curation_jobs", "tutor_context_summaries"],
                [
                    "projection_kind",
                    "conversation_id",
                    "summary_schema_version",
                    "summary_policy_version",
                    "summary_json",
                    "summary_source_hash",
                    "source_hash",
                    "prior_summary_id",
                    "prior_summary_hash",
                    "covered_through_created_at",
                    "covered_through_message_id",
                ],
            ),
        ).fetchall()
        summary_columns = {(str(row["table_name"]), str(row["column_name"])) for row in summary_column_rows}
        assert {
            ("tutor_memory_curation_outbox", "projection_kind"),
            ("tutor_memory_curation_outbox", "summary_schema_version"),
            ("tutor_memory_curation_outbox", "summary_policy_version"),
            ("tutor_memory_curation_outbox", "summary_source_hash"),
            ("tutor_memory_curation_outbox", "prior_summary_id"),
            ("tutor_memory_curation_outbox", "prior_summary_hash"),
            ("tutor_memory_curation_outbox", "covered_through_created_at"),
            ("tutor_memory_curation_outbox", "covered_through_message_id"),
            ("tutor_curation_jobs", "projection_kind"),
            ("tutor_context_summaries", "conversation_id"),
            ("tutor_context_summaries", "summary_schema_version"),
            ("tutor_context_summaries", "summary_policy_version"),
            ("tutor_context_summaries", "summary_json"),
            ("tutor_context_summaries", "source_hash"),
            ("tutor_context_summaries", "prior_summary_id"),
            ("tutor_context_summaries", "prior_summary_hash"),
            ("tutor_context_summaries", "covered_through_created_at"),
            ("tutor_context_summaries", "covered_through_message_id"),
        }.issubset(summary_columns)
        runtime_receipt_columns = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'tutor_runtime_item_receipts'
              AND column_name = ANY(%s)
            """,
            (
                [
                    "projection_sequence",
                    "source_sequence_start",
                    "source_sequence_end",
                    "source_delta_count",
                    "source_content_hash",
                ],
            ),
        ).fetchall()
        assert {str(row["column_name"]) for row in runtime_receipt_columns} == {
            "projection_sequence",
            "source_sequence_start",
            "source_sequence_end",
            "source_delta_count",
            "source_content_hash",
        }
        assert {str(row["tgname"]) for row in trigger_rows} == {
            "trg_tutor_provider_attempt_receipts_immutable",
            "trg_tutor_planning_intake_facts_immutable",
            "trg_tutor_planning_question_events_immutable",
            "trg_tutor_action_attempts_immutable",
            "trg_tutor_action_verifications_immutable",
            "trg_tutor_action_receipts_immutable",
            "trg_tutor_action_invocations_lifecycle",
            "trg_tutor_action_invocations_updated_at",
            "trg_tutor_conversations_updated_at",
            "trg_tutor_runs_updated_at",
            "trg_tutor_runs_runtime_kind_immutable",
            "trg_tutor_conversation_runtime_threads_lifecycle",
            "trg_tutor_conversation_runtime_threads_updated_at",
            "trg_tutor_runtime_bindings_lifecycle",
            "trg_tutor_runtime_bindings_updated_at",
            "trg_tutor_runtime_text_items_lifecycle",
            "trg_tutor_runtime_text_items_updated_at",
            "trg_tutor_runtime_receipts_immutable",
            "trg_tutor_runtime_errors_immutable",
            "trg_tutor_effects_updated_at",
            "trg_tutor_execution_jobs_updated_at",
            "trg_tutor_execution_jobs_lifecycle_guard",
            "trg_tutor_codex_runtime_health_updated_at",
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
            "trg_tutor_context_summaries_immutable",
            "trg_tutor_activity_records_immutable",
            "trg_tutor_inbox_items_lifecycle",
            "trg_tutor_active_plans_updated_at",
            "trg_tutor_memory_preferences_updated_at",
            "trg_tutor_memory_entries_updated_at",
            "trg_tutor_inbox_items_updated_at",
            "trg_tutor_public_processes_updated_at",
            "trg_tutor_lesson_documents_lineage",
            "trg_tutor_lesson_documents_immutable",
            "trg_tutor_lesson_source_snapshots_immutable",
            "trg_tutor_lesson_block_citations_immutable",
            "trg_tutor_lesson_gate_slots_immutable",
            "trg_tutor_lesson_assignments_updated_at",
            "trg_tutor_lesson_assignments_lifecycle",
            "trg_tutor_lesson_authoring_runs_updated_at",
            "trg_tutor_lesson_authoring_runs_lifecycle",
            "trg_tutor_lesson_authoring_attempt_receipts_immutable",
            "trg_tutor_exercise_versions_immutable",
            "trg_tutor_exercise_private_rubrics_immutable",
            "trg_tutor_lesson_gate_bindings_immutable",
            "trg_tutor_lesson_gate_states_updated_at",
            "trg_tutor_lesson_gate_states_lifecycle",
            "trg_tutor_module_diagnostic_versions_immutable",
            "trg_tutor_module_diagnostic_sessions_updated_at",
            "trg_tutor_module_diagnostic_sessions_lifecycle",
            "trg_tutor_module_diagnostic_items_immutable",
            "trg_tutor_exercise_attempts_immutable",
            "trg_tutor_exercise_attempt_submissions_immutable",
            "trg_tutor_exercise_attempt_results_immutable",
            "trg_tutor_exercise_hint_receipts_immutable",
            "trg_tutor_exercise_execution_links_immutable",
            "trg_tutor_review_schedule_states_updated_at",
            "trg_tutor_review_schedule_states_lifecycle",
            "trg_tutor_review_sessions_updated_at",
            "trg_tutor_review_sessions_lifecycle",
            "trg_tutor_review_schedule_events_immutable",
            "trg_tutor_review_warmups_immutable",
            "trg_tutor_review_items_immutable",
            "trg_tutor_review_hints_immutable",
            "trg_tutor_review_finalizations_immutable",
            "trg_tutor_message_context_references_immutable",
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
                    "idx_tutor_provider_attempt_receipts_run_created",
                    "idx_tutor_execution_intents_run_expiry",
                    "idx_tutor_execution_jobs_claim",
                    "idx_tutor_execution_attempts_job_created",
                    "idx_tutor_codex_runtime_health_observed",
                    "idx_tutor_executor_health_heartbeat",
                    "idx_tutor_plan_revisions_user_created",
                    "idx_tutor_memory_entries_user_state",
                    "idx_tutor_curation_projection_receipts_user_created",
                    "idx_tutor_context_summaries_conversation_coverage",
                    "idx_tutor_activity_records_user_created",
                    "idx_tutor_inbox_items_user_state",
                    "idx_tutor_api_idempotency_user_created",
                    "idx_tutor_planning_intake_facts_user_session",
                    "idx_tutor_planning_intake_facts_message",
                    "idx_tutor_planning_question_events_session_field",
                    "uq_tutor_planning_question_events_previous",
                    "idx_tutor_action_invocations_run_created",
                    "idx_tutor_action_invocations_state_created",
                    "idx_tutor_action_receipts_run_terminal",
                    "uq_tutor_action_receipts_current_verified",
                    "uq_tutor_runs_interactive_foreground",
                    "uq_tutor_conversation_runtime_threads_active",
                    "idx_tutor_conversation_runtime_threads_owner",
                    "idx_tutor_runtime_bindings_conversation_thread",
                    "uq_tutor_runtime_bindings_turn",
                    "idx_tutor_runtime_bindings_run_state",
                    "idx_tutor_runtime_text_items_active",
                    "idx_tutor_runtime_text_items_message",
                    "idx_tutor_runtime_receipts_run_sequence",
                    "idx_tutor_runtime_errors_conversation",
                    "idx_tutor_conversations_public_activity",
                    "idx_tutor_public_processes_conversation_activity",
                    "idx_tutor_public_process_steps_run_ordinal",
                    "uq_tutor_lesson_documents_standard_identity",
                    "uq_tutor_lesson_documents_personalized_identity",
                    "idx_tutor_lesson_documents_track_key_created",
                    "idx_tutor_lesson_source_snapshots_document",
                    "uq_tutor_lesson_assignments_one_active",
                    "idx_tutor_lesson_assignments_track_key_created",
                    "idx_tutor_lesson_authoring_runs_claim",
                    "idx_tutor_lesson_authoring_runs_track_key",
                    "uq_tutor_module_diagnostic_sessions_active",
                    "idx_tutor_lesson_gate_states_assignment",
                    "idx_tutor_exercise_attempts_gate",
                    "idx_tutor_exercise_attempts_diagnostic",
                    "idx_tutor_module_diagnostic_sessions_track",
                    "uq_tutor_review_sessions_one_active",
                    "idx_tutor_review_schedule_due",
                    "idx_tutor_review_schedule_events_created",
                    "idx_tutor_review_sessions_scope",
                    "idx_tutor_review_items_session",
                    "idx_tutor_review_hints_item",
                    "idx_tutor_exercise_attempts_review",
                    "uq_tutor_exercise_attempts_review_item",
                    "idx_tutor_message_context_references_message",
                    "idx_tutor_message_context_references_input",
                ],
            ),
        ).fetchall()
        assert {str(row["indexname"]) for row in executor_indexes} == {
            "idx_tutor_provider_attempt_receipts_run_created",
            "idx_tutor_execution_intents_run_expiry",
            "idx_tutor_execution_jobs_claim",
            "idx_tutor_execution_attempts_job_created",
            "idx_tutor_codex_runtime_health_observed",
            "idx_tutor_executor_health_heartbeat",
            "idx_tutor_plan_revisions_user_created",
            "idx_tutor_memory_entries_user_state",
            "idx_tutor_curation_projection_receipts_user_created",
            "idx_tutor_context_summaries_conversation_coverage",
            "idx_tutor_activity_records_user_created",
            "idx_tutor_inbox_items_user_state",
            "idx_tutor_api_idempotency_user_created",
            "idx_tutor_planning_intake_facts_user_session",
            "idx_tutor_planning_intake_facts_message",
            "idx_tutor_planning_question_events_session_field",
            "uq_tutor_planning_question_events_previous",
            "idx_tutor_action_invocations_run_created",
            "idx_tutor_action_invocations_state_created",
            "idx_tutor_action_receipts_run_terminal",
            "uq_tutor_action_receipts_current_verified",
            "uq_tutor_runs_interactive_foreground",
            "uq_tutor_conversation_runtime_threads_active",
            "idx_tutor_conversation_runtime_threads_owner",
            "idx_tutor_runtime_bindings_conversation_thread",
            "uq_tutor_runtime_bindings_turn",
            "idx_tutor_runtime_bindings_run_state",
            "idx_tutor_runtime_text_items_active",
            "idx_tutor_runtime_text_items_message",
            "idx_tutor_runtime_receipts_run_sequence",
            "idx_tutor_runtime_errors_conversation",
            "idx_tutor_conversations_public_activity",
            "idx_tutor_public_processes_conversation_activity",
            "idx_tutor_public_process_steps_run_ordinal",
            "uq_tutor_lesson_documents_standard_identity",
            "uq_tutor_lesson_documents_personalized_identity",
            "idx_tutor_lesson_documents_track_key_created",
            "idx_tutor_lesson_source_snapshots_document",
            "uq_tutor_lesson_assignments_one_active",
            "idx_tutor_lesson_assignments_track_key_created",
            "idx_tutor_lesson_authoring_runs_claim",
            "idx_tutor_lesson_authoring_runs_track_key",
            "uq_tutor_module_diagnostic_sessions_active",
            "idx_tutor_lesson_gate_states_assignment",
            "idx_tutor_exercise_attempts_gate",
            "idx_tutor_exercise_attempts_diagnostic",
            "idx_tutor_module_diagnostic_sessions_track",
            "uq_tutor_review_sessions_one_active",
            "idx_tutor_review_schedule_due",
            "idx_tutor_review_schedule_events_created",
            "idx_tutor_review_sessions_scope",
            "idx_tutor_review_items_session",
            "idx_tutor_review_hints_item",
            "idx_tutor_exercise_attempts_review",
            "uq_tutor_exercise_attempts_review_item",
            "idx_tutor_message_context_references_message",
            "idx_tutor_message_context_references_input",
        }
        execution_constraint_rows = conn.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s)",
            (list(TUTOR_SCHEMA_CONSTRAINTS),),
        ).fetchall()
        assert {str(row["conname"]) for row in execution_constraint_rows} == set(
            TUTOR_SCHEMA_CONSTRAINTS
        )
        continuation_constraint = conn.execute(
            """
            SELECT pg_get_constraintdef(oid) AS definition
            FROM pg_constraint
            WHERE conname = 'chk_tutor_runs_continuation_kind'
            """
        ).fetchone()
        assert continuation_constraint is not None
        continuation_definition = str(continuation_constraint["definition"])
        for continuation_kind in (
            "clarification",
            "planning_input",
            "approval",
            "capability_result",
            "external_result",
        ):
            assert continuation_kind in continuation_definition
        assert "plan_drafting" not in continuation_definition

        model_review_cycle_rows = conn.execute(
            """
            SELECT conname, condeferrable, condeferred, confdeltype
            FROM pg_constraint
            WHERE conname = ANY(%s)
            """,
            (
                [
                    "fk_tutor_model_review_authoring_candidate",
                    "fk_tutor_model_review_authoring_validation",
                    "fk_tutor_model_review_authoring_publication",
                ],
            ),
        ).fetchall()
        assert {str(row["conname"]) for row in model_review_cycle_rows} == {
            "fk_tutor_model_review_authoring_candidate",
            "fk_tutor_model_review_authoring_validation",
            "fk_tutor_model_review_authoring_publication",
        }
        assert all(bool(row["condeferrable"]) for row in model_review_cycle_rows)
        assert all(not bool(row["condeferred"]) for row in model_review_cycle_rows)
        assert all(str(row["confdeltype"]) == "a" for row in model_review_cycle_rows)

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

    other_conversation_id = fixture.repository.create_conversation(user_id=fixture.user_id)
    other_run = fixture.repository.create_run(
        user_id=fixture.user_id,
        conversation_id=other_conversation_id,
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
