from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from psycopg import Connection

from app.services.repositories.user_repository import get_user, serialize_user
from app.services.tutor.persistence import PostgresTutorRepository


class EntityNotFoundError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def list_local_users(conn: Connection[dict[str, object]]) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT
          users.*,
          count(DISTINCT learning_plans.id) FILTER (WHERE learning_plans.deleted_at IS NULL) AS plan_count,
          (
            SELECT lp.id::text
            FROM learning_plans lp
            WHERE lp.user_id = users.id
              AND lp.deleted_at IS NULL
              AND lp.status = 'active'
            ORDER BY lp.updated_at DESC, lp.created_at DESC
            LIMIT 1
          ) AS active_plan_id,
          (
            SELECT lp.goal_text
            FROM learning_plans lp
            WHERE lp.user_id = users.id
              AND lp.deleted_at IS NULL
              AND lp.status = 'active'
            ORDER BY lp.updated_at DESC, lp.created_at DESC
            LIMIT 1
          ) AS active_goal,
          max(
            GREATEST(
              COALESCE(learning_plans.updated_at, 'epoch'::timestamptz),
              COALESCE(learning_sessions.started_at, 'epoch'::timestamptz),
              COALESCE(learning_sessions.ended_at, 'epoch'::timestamptz),
              COALESCE(attempts.created_at, 'epoch'::timestamptz),
              COALESCE(notes.updated_at, 'epoch'::timestamptz)
            )
          ) AS last_activity_at
        FROM users
        LEFT JOIN learning_plans
          ON learning_plans.user_id = users.id
         AND learning_plans.deleted_at IS NULL
        LEFT JOIN learning_sessions
          ON learning_sessions.user_id = users.id
        LEFT JOIN attempts
          ON attempts.user_id = users.id
        LEFT JOIN notes
          ON notes.user_id = users.id
         AND notes.deleted_at IS NULL
        WHERE users.deleted_at IS NULL
        GROUP BY users.id
        ORDER BY users.updated_at DESC, users.created_at DESC
        """
    ).fetchall()
    return {
        "items": [
            {
                **serialize_user(row),
                "plan_count": _int_or_zero(row.get("plan_count")),
                "active_plan_id": row.get("active_plan_id"),
                "active_goal": row.get("active_goal"),
                "last_activity_at": _iso_or_none(_none_if_epoch(row.get("last_activity_at"))),
            }
            for row in rows
        ],
        "page_info": {
            "limit": len(rows),
            "next_cursor": None,
            "has_more": False,
        },
    }


def get_user_data_summary(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    user = _ensure_user(conn, user_id)
    counts = _summary_counts(conn, user_id)
    return {
        "user": _summary_user(user),
        "counts": counts,
        "last_activity_at": _iso_or_none(_last_activity_at(conn, user_id)),
    }


def export_user_data(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    user = _ensure_user(conn, user_id)
    summary = get_user_data_summary(conn, user_id)
    return {
        "export_version": "local_user_data_v1",
        "exported_at": datetime.now(UTC).isoformat(),
        "user": _summary_user(user),
        "preferences": {
            "learning_style": user.get("learning_style"),
            "teaching_preference": user.get("teaching_preference"),
            "encouragement_preference": user.get("encouragement_preference"),
            "profession": user.get("profession"),
            "background_context": user.get("background_context"),
            "preferred_time_slots": user.get("preferred_time_slots") or [],
            "reminder_preference": user.get("reminder_preference") or {},
        },
        "summary": summary,
        "plans": _export_plans(conn, user_id),
        "modules": _export_modules(conn, user_id),
        "knowledge_points": _export_knowledge_points(conn, user_id),
        "learning_sessions": _export_learning_sessions(conn, user_id),
        "attempt_summaries": _export_attempts(conn, user_id),
        "review_state_summaries": _export_review_states(conn, user_id),
        "review_log_summaries": _export_review_logs(conn, user_id),
        "adaptive_variant_summaries": _export_adaptive_variant_summaries(conn, user_id),
        "notes": _export_notes(conn, user_id),
        "conversation_summaries": _export_conversation_summaries(conn, user_id),
        "learning_plan_sessions": _export_learning_plan_sessions(conn, user_id),
        "planning_intake_facts": _export_planning_intake_facts(conn, user_id),
        "planning_question_events": _export_planning_question_events(conn, user_id),
        "learning_plan_drafts": _export_learning_plan_drafts(conn, user_id),
        "learning_tracks": _export_learning_tracks(conn, user_id),
        "learning_track_plan_revisions": _export_learning_track_plan_revisions(conn, user_id),
        "learning_track_nodes": _export_learning_track_nodes(conn, user_id),
        "lesson_documents": _export_lesson_documents(conn, user_id),
        "lesson_assignments": _export_lesson_assignments(conn, user_id),
        "teaching_session_summaries": _export_teaching_sessions(conn, user_id),
        "teaching_checkpoint_summaries": _export_teaching_checkpoints(conn, user_id),
        "teaching_stimulus_summaries": _export_teaching_stimuli(conn, user_id),
        "run_teaching_scope_summaries": _export_run_teaching_scopes(conn, user_id),
        "teaching_action_receipt_summaries": _export_teaching_action_receipts(conn, user_id),
        "learning_artifact_summaries": _export_learning_artifacts(conn, user_id),
        "learning_artifact_event_summaries": _export_learning_artifact_events(conn, user_id),
        "learning_artifact_reference_summaries": _export_learning_artifact_references(conn, user_id),
        "learning_artifact_attempt_link_summaries": _export_learning_artifact_attempt_links(conn, user_id),
        "demonstration_completion_summaries": _export_demonstration_completions(conn, user_id),
        "knowledge_check_response_summaries": _export_knowledge_check_responses(conn, user_id),
        "knowledge_check_assistance_summaries": _export_knowledge_check_assistance(conn, user_id),
        "model_review_artifact_summaries": _export_model_review_artifact_receipts(conn, user_id),
        "clarification_branch_summaries": _export_clarification_branches(conn, user_id),
        "clarification_branch_event_summaries": _export_clarification_branch_events(conn, user_id),
        "run_branch_scope_summaries": _export_run_branch_scopes(conn, user_id),
        "clarification_branch_item_summaries": _export_clarification_branch_items(conn, user_id),
        "continuation_intent_summaries": _export_continuation_intents(conn, user_id),
        "continuation_intent_event_summaries": _export_continuation_intent_events(conn, user_id),
        "lesson_citations": _export_lesson_citations(conn, user_id),
        "lesson_gates": _export_lesson_gates(conn, user_id),
        "exercise_attempt_summaries": _export_exercise_attempt_summaries(conn, user_id),
        "module_diagnostic_summaries": _export_module_diagnostic_summaries(conn, user_id),
        "review_schedule_summaries": _export_review_schedule_summaries(conn, user_id),
        "review_session_summaries": _export_review_session_summaries(conn, user_id),
        "review_finalization_summaries": _export_review_finalization_summaries(conn, user_id),
        "tutor_context_reference_summaries": _export_tutor_context_references(conn, user_id),
        "action_receipt_summaries": _export_action_receipt_summaries(conn, user_id),
        "model_review_authoring_summaries": _export_model_review_authoring_summaries(conn, user_id),
        "model_review_candidate_summaries": _export_model_review_candidate_summaries(conn, user_id),
        "model_review_validation_summaries": _export_model_review_validation_summaries(conn, user_id),
        "model_review_publication_summaries": _export_model_review_publication_summaries(conn, user_id),
        "model_review_evidence_summaries": _export_model_review_evidence_summaries(conn, user_id),
        "redaction": {
            "hidden_tests": "omitted",
            "private_rubrics": "omitted",
            "exercise_submission_content": "omitted",
            "solution_references": "omitted",
            "raw_prompts": "omitted",
            "provider_payloads": "omitted",
            "action_arguments": "omitted",
            "action_raw_results": "omitted",
            "action_private_verification": "omitted",
            "model_review_private_candidates": "omitted",
            "model_review_private_validation_proofs": "omitted",
            "planning_fact_hashes": "omitted",
            "planning_question_gate_reasons": "omitted",
            "review_context_snapshot_hashes": "omitted",
            "review_item_selection_hashes": "omitted",
            "teaching_checkpoint_source_hashes": "omitted",
            "teaching_document_content_hashes": "omitted",
            "teaching_full_questions_and_submissions": "omitted",
            "artifact_instruction_markdown": "omitted",
            "artifact_presentations": "omitted",
            "artifact_active_attempt_payloads": "omitted",
            "artifact_event_payloads": "omitted",
            "knowledge_check_response_payloads_and_hashes": "omitted",
            "model_review_artifact_submissions_feedback_and_hashes": "omitted",
            "artifact_action_request_hashes": "omitted",
            "demonstration_completion_nonces_and_request_hashes": "omitted",
            "artifact_reference_content_hashes": "omitted",
            "branch_request_hashes": "omitted",
            "continuation_request_hashes": "omitted",
            "continuation_idempotency_keys": "omitted",
            "continuation_claimant_ids": "omitted",
            "secrets": "omitted",
        },
    }


def reset_user_data(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    _ensure_user(conn, user_id)
    before = get_user_data_summary(conn, user_id)
    _delete_user_owned_learning_data(conn, user_id)
    user = _ensure_user(conn, user_id)
    return {
        "user": user,
        "before_summary": before,
        "summary": get_user_data_summary(conn, user_id),
        "next_action": "return_to_onboarding",
    }


def delete_user_data(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    _ensure_user(conn, user_id)
    before = get_user_data_summary(conn, user_id)
    _delete_user_owned_learning_data(conn, user_id)
    conn.execute(
        """
        UPDATE users
        SET deleted_at = now()
        WHERE id = %s AND deleted_at IS NULL
        """,
        (user_id,),
    )
    return {
        "deleted_user_id": user_id,
        "before_summary": before,
        "next_action": "select_local_profile",
    }


def _ensure_user(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    user = get_user(conn, user_id)
    if user is None:
        raise EntityNotFoundError("USER_NOT_FOUND", "用户不存在")
    return user


def _summary_user(user: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(user["id"]),
        "display_name": user["display_name"],
        "created_at": _iso_or_none(user.get("created_at")),
        "updated_at": _iso_or_none(user.get("updated_at")),
    }


def _summary_counts(conn: Connection[dict[str, object]], user_id: str) -> dict[str, int]:
    return {
        "active_plans": _count(conn, "SELECT count(*) AS count FROM learning_plans WHERE user_id = %s AND deleted_at IS NULL AND status = 'active'", user_id),
        "archived_or_deleted_plans": _count(conn, "SELECT count(*) AS count FROM learning_plans WHERE user_id = %s AND (deleted_at IS NOT NULL OR status = 'archived')", user_id),
        "modules": _count(conn, _owned_count_sql("plan_modules"), user_id),
        "knowledge_points": _count(conn, _owned_count_sql("knowledge_points"), user_id),
        "exercises": _count(conn, _owned_count_sql("exercises"), user_id),
        "learning_sessions": _count(conn, "SELECT count(*) AS count FROM learning_sessions WHERE user_id = %s", user_id),
        "attempts": _count(conn, "SELECT count(*) AS count FROM attempts WHERE user_id = %s", user_id),
        "review_states": _count(conn, "SELECT count(*) AS count FROM review_states WHERE user_id = %s", user_id),
        "review_logs": _count(conn, "SELECT count(*) AS count FROM review_logs WHERE user_id = %s", user_id),
        "review_seed_banks": _count(conn, "SELECT count(*) AS count FROM review_seed_banks WHERE user_id = %s", user_id),
        "exercise_variant_cache": _count(conn, "SELECT count(*) AS count FROM exercise_variant_cache WHERE user_id = %s AND deleted_at IS NULL", user_id),
        "notes": _count(conn, "SELECT count(*) AS count FROM notes WHERE user_id = %s AND deleted_at IS NULL", user_id),
        "onboarding_conversations": _count(conn, "SELECT count(*) AS count FROM onboarding_conversations WHERE user_id = %s", user_id),
        "onboarding_messages": _count(
            conn,
            """
            SELECT count(*) AS count
            FROM onboarding_messages
            JOIN onboarding_conversations ON onboarding_conversations.id = onboarding_messages.conversation_id
            WHERE onboarding_conversations.user_id = %s
            """,
            user_id,
        ),
        "learning_messages": _count(
            conn,
            """
            SELECT count(*) AS count
            FROM learning_messages
            JOIN learning_sessions ON learning_sessions.id = learning_messages.session_id
            WHERE learning_sessions.user_id = %s
            """,
            user_id,
        ),
        "review_messages": _count(
            conn,
            """
            SELECT count(*) AS count
            FROM review_messages
            JOIN learning_sessions ON learning_sessions.id = review_messages.review_session_id
            WHERE learning_sessions.user_id = %s
            """,
            user_id,
        ),
        "learning_plan_sessions": _count(conn, "SELECT count(*) AS count FROM tutor_learning_plan_sessions WHERE user_id = %s", user_id),
        "planning_intake_facts": _count(conn, "SELECT count(*) AS count FROM tutor_planning_intake_facts WHERE user_id = %s", user_id),
        "planning_question_events": _count(conn, "SELECT count(*) AS count FROM tutor_planning_question_events WHERE user_id = %s", user_id),
        "learning_plan_drafts": _count(conn, "SELECT count(*) AS count FROM tutor_learning_plan_drafts WHERE user_id = %s", user_id),
        "learning_tracks": _count(conn, "SELECT count(*) AS count FROM tutor_learning_tracks WHERE user_id = %s", user_id),
        "learning_track_plan_revisions": _count(conn, "SELECT count(*) AS count FROM tutor_track_plan_revisions WHERE user_id = %s", user_id),
        "learning_track_nodes": _count(conn, "SELECT count(*) AS count FROM tutor_track_plan_nodes WHERE user_id = %s", user_id),
        "learning_track_progress": _count(conn, "SELECT count(*) AS count FROM tutor_track_node_progress WHERE user_id = %s", user_id),
        "mastery_evidence": _count(conn, "SELECT count(*) AS count FROM tutor_mastery_evidence WHERE user_id = %s", user_id),
        "mastery_states": _count(conn, "SELECT count(*) AS count FROM tutor_mastery_states WHERE user_id = %s", user_id),
        "lesson_documents": _count(conn, "SELECT count(*) AS count FROM tutor_lesson_documents WHERE user_id = %s AND document_kind = 'personalized'", user_id),
        "lesson_assignments": _count(conn, "SELECT count(*) AS count FROM tutor_lesson_assignments WHERE user_id = %s", user_id),
        "teaching_sessions": _count(conn, "SELECT count(*) AS count FROM tutor_teaching_sessions WHERE user_id = %s", user_id),
        "teaching_checkpoints": _count(conn, "SELECT count(*) AS count FROM tutor_teaching_session_checkpoints WHERE user_id = %s", user_id),
        "teaching_stimuli": _count(conn, "SELECT count(*) AS count FROM tutor_run_stimulus_events WHERE user_id = %s", user_id),
        "run_teaching_scopes": _count(conn, "SELECT count(*) AS count FROM tutor_run_teaching_scopes WHERE user_id = %s", user_id),
        "teaching_action_receipts": _count(conn, "SELECT count(*) AS count FROM tutor_teaching_action_receipts WHERE user_id = %s", user_id),
        "learning_artifacts": _count(conn, "SELECT count(*) AS count FROM tutor_learning_artifacts WHERE user_id = %s", user_id),
        "learning_artifact_events": _count(conn, "SELECT count(*) AS count FROM tutor_learning_artifact_events WHERE user_id = %s", user_id),
        "learning_artifact_references": _count(conn, "SELECT count(*) AS count FROM tutor_learning_artifact_references WHERE user_id = %s", user_id),
        "learning_artifact_attempt_links": _count(conn, "SELECT count(*) AS count FROM tutor_learning_artifact_attempt_links WHERE user_id = %s", user_id),
        "demonstration_completions": _count(conn, "SELECT count(*) AS count FROM tutor_demonstration_completion_receipts WHERE user_id = %s", user_id),
        "knowledge_check_responses": _count(conn, "SELECT count(*) AS count FROM tutor_knowledge_check_response_receipts WHERE user_id = %s", user_id),
        "knowledge_check_assistance": _count(conn, "SELECT count(*) AS count FROM tutor_knowledge_check_assistance_receipts WHERE user_id = %s", user_id),
        "model_review_artifact_receipts": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_artifact_receipts WHERE user_id = %s", user_id),
        "clarification_branches": _count(conn, "SELECT count(*) AS count FROM tutor_conversation_branches WHERE user_id = %s", user_id),
        "clarification_branch_events": _count(conn, "SELECT count(*) AS count FROM tutor_conversation_branch_events WHERE user_id = %s", user_id),
        "run_branch_scopes": _count(conn, "SELECT count(*) AS count FROM tutor_run_branch_scopes WHERE user_id = %s", user_id),
        "clarification_branch_items": _count(conn, "SELECT count(*) AS count FROM tutor_conversation_branch_items WHERE user_id = %s", user_id),
        "continuation_intents": _count(conn, "SELECT count(*) AS count FROM tutor_continuation_intents WHERE user_id = %s", user_id),
        "continuation_intent_events": _count(conn, "SELECT count(*) AS count FROM tutor_continuation_intent_events WHERE user_id = %s", user_id),
        "lesson_authoring_runs": _count(conn, "SELECT count(*) AS count FROM tutor_lesson_authoring_runs WHERE user_id = %s", user_id),
        "lesson_gates": _count(conn, "SELECT count(*) AS count FROM tutor_lesson_gate_states WHERE user_id = %s", user_id),
        "exercise_attempts": _count(conn, "SELECT count(*) AS count FROM tutor_exercise_attempts WHERE user_id = %s", user_id),
        "module_diagnostics": _count(conn, "SELECT count(*) AS count FROM tutor_module_diagnostic_sessions WHERE user_id = %s", user_id),
        "review_schedules": _count(conn, "SELECT count(*) AS count FROM tutor_review_schedule_states WHERE user_id = %s", user_id),
        "review_sessions": _count(conn, "SELECT count(*) AS count FROM tutor_review_sessions WHERE user_id = %s", user_id),
        "review_finalizations": _count(conn, "SELECT count(*) AS count FROM tutor_review_finalizations WHERE user_id = %s", user_id),
        "tutor_context_references": _count(conn, "SELECT count(*) AS count FROM tutor_message_context_references WHERE user_id = %s", user_id),
        "action_receipts": _count(conn, "SELECT count(*) AS count FROM tutor_action_receipts WHERE user_id = %s", user_id),
        "model_review_authoring_runs": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_authoring_runs WHERE user_id = %s", user_id),
        "model_review_candidates": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_candidates WHERE user_id = %s", user_id),
        "model_review_validation_runs": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_validation_runs WHERE user_id = %s", user_id),
        "model_review_validation_checks": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_validation_checks WHERE user_id = %s", user_id),
        "model_review_publications": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_publications WHERE user_id = %s", user_id),
        "model_review_evidence_receipts": _count(conn, "SELECT count(*) AS count FROM tutor_model_review_evidence_receipts WHERE user_id = %s", user_id),
    }


def _owned_count_sql(table_name: str) -> str:
    if table_name == "plan_modules":
        return """
        SELECT count(*) AS count
        FROM plan_modules
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        WHERE learning_plans.user_id = %s AND plan_modules.deleted_at IS NULL AND learning_plans.deleted_at IS NULL
        """
    if table_name == "knowledge_points":
        return """
        SELECT count(*) AS count
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        WHERE learning_plans.user_id = %s AND knowledge_points.deleted_at IS NULL AND plan_modules.deleted_at IS NULL AND learning_plans.deleted_at IS NULL
        """
    if table_name == "exercises":
        return """
        SELECT count(*) AS count
        FROM exercises
        JOIN knowledge_points ON knowledge_points.id = exercises.knowledge_point_id
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        WHERE learning_plans.user_id = %s AND exercises.deleted_at IS NULL AND knowledge_points.deleted_at IS NULL AND plan_modules.deleted_at IS NULL AND learning_plans.deleted_at IS NULL
        """
    raise ValueError(f"unsupported owned count table: {table_name}")


def _count(conn: Connection[dict[str, object]], query: str, user_id: str) -> int:
    row = conn.execute(query, (user_id,)).fetchone()
    return _int_or_zero(row.get("count") if row is not None else 0)


def _last_activity_at(conn: Connection[dict[str, object]], user_id: str) -> datetime | None:
    row = conn.execute(
        """
        SELECT GREATEST(
          COALESCE((SELECT max(updated_at) FROM learning_plans WHERE user_id = %s), 'epoch'::timestamptz),
          COALESCE((SELECT max(started_at) FROM learning_sessions WHERE user_id = %s), 'epoch'::timestamptz),
          COALESCE((SELECT max(ended_at) FROM learning_sessions WHERE user_id = %s), 'epoch'::timestamptz),
          COALESCE((SELECT max(created_at) FROM attempts WHERE user_id = %s), 'epoch'::timestamptz),
          COALESCE((SELECT max(updated_at) FROM notes WHERE user_id = %s AND deleted_at IS NULL), 'epoch'::timestamptz)
        ) AS last_activity_at
        """,
        (user_id, user_id, user_id, user_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return _none_if_epoch(row.get("last_activity_at"))


def _export_plans(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, language_course_id, goal_text, language, target_level, mode, status,
               overall_progress, current_module_id, created_at, updated_at, completed_at, archived_at
        FROM learning_plans
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "language_course_id": str(row["language_course_id"]),
            "goal_text": row["goal_text"],
            "language": row["language"],
            "target_level": row["target_level"],
            "mode": row["mode"],
            "status": row["status"],
            "overall_progress": _number(row.get("overall_progress")),
            "current_module_id": _str_or_none(row.get("current_module_id")),
            "created_at": _iso_or_none(row.get("created_at")),
            "updated_at": _iso_or_none(row.get("updated_at")),
            "completed_at": _iso_or_none(row.get("completed_at")),
            "archived_at": _iso_or_none(row.get("archived_at")),
        }
        for row in rows
    ]


def _export_modules(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT plan_modules.id, plan_modules.plan_id, plan_modules.title, plan_modules.description,
               plan_modules.order_index, plan_modules.status, plan_modules.is_skippable,
               plan_modules.is_adjustable, plan_modules.estimated_sessions
        FROM plan_modules
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        WHERE learning_plans.user_id = %s
          AND learning_plans.deleted_at IS NULL
          AND plan_modules.deleted_at IS NULL
        ORDER BY learning_plans.created_at, plan_modules.order_index, plan_modules.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_knowledge_points(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT knowledge_points.id, knowledge_points.module_id, knowledge_points.language_course_id,
               knowledge_points.title, knowledge_points.description, knowledge_points.order_index,
               knowledge_points.skill_tags_json, knowledge_points.lesson_outline_json,
               knowledge_points.lesson_sources_json, knowledge_points.status,
               knowledge_points.mastery_score, knowledge_points.weak_points_json,
               knowledge_points.last_exercise_result, knowledge_points.last_exercise_score
        FROM knowledge_points
        JOIN plan_modules ON plan_modules.id = knowledge_points.module_id
        JOIN learning_plans ON learning_plans.id = plan_modules.plan_id
        WHERE learning_plans.user_id = %s
          AND learning_plans.deleted_at IS NULL
          AND plan_modules.deleted_at IS NULL
          AND knowledge_points.deleted_at IS NULL
        ORDER BY plan_modules.order_index, knowledge_points.order_index, knowledge_points.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_sessions(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, plan_id, session_type, status, started_at, ended_at, duration_seconds,
               entry_point, summary_text, next_entry_point, learning_stage, review_stage
        FROM learning_sessions
        WHERE user_id = %s
        ORDER BY started_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_attempts(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, session_id, exercise_id, attempt_type, submit_version,
               submitted_code, code_hash, filled_blanks_json, runtime_status,
               test_pass_rate, passed_test_count, total_test_count, score,
               score_breakdown_json, code_completion_result, fsrs_rating,
               test_results_json, stdout, stderr, error_message, error_cause,
               hint_usage_count, error_count, explanation_text,
               explanation_check_result, evaluation_status, created_at
        FROM attempts
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_review_states(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT knowledge_point_id, plan_id, card_state, stability, difficulty, due_at,
               elapsed_days, scheduled_days, reps, lapses, last_review_at,
               last_attempt_id, last_fsrs_rating, scheduler_version, suspended_at
        FROM review_states
        WHERE user_id = %s
        ORDER BY due_at NULLS LAST, knowledge_point_id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_review_logs(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, knowledge_point_id, plan_id, attempt_id, rating,
               scheduled_due_at, reviewed_at, source, created_at
        FROM review_logs
        WHERE user_id = %s
        ORDER BY reviewed_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_adaptive_variant_summaries(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, knowledge_point_id, template_id, template_version,
               generator_version, runner_key, runtime_tier, status,
               failure_code, created_at, last_used_at
        FROM exercise_variant_cache
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY last_used_at DESC, created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_notes(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, knowledge_point_id, title, content_markdown, agent_draft_content,
               is_user_edited, created_at, updated_at
        FROM notes
        WHERE user_id = %s AND deleted_at IS NULL
        ORDER BY updated_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_conversation_summaries(conn: Connection[dict[str, object]], user_id: str) -> dict[str, object]:
    onboarding = conn.execute(
        """
        SELECT onboarding_conversations.id, onboarding_conversations.status,
               count(onboarding_messages.id) AS message_count,
               min(onboarding_messages.created_at) AS first_message_at,
               max(onboarding_messages.created_at) AS last_message_at
        FROM onboarding_conversations
        LEFT JOIN onboarding_messages ON onboarding_messages.conversation_id = onboarding_conversations.id
        WHERE onboarding_conversations.user_id = %s
        GROUP BY onboarding_conversations.id
        ORDER BY onboarding_conversations.created_at, onboarding_conversations.id
        """,
        (user_id,),
    ).fetchall()
    learning = conn.execute(
        """
        SELECT learning_sessions.id AS session_id, learning_sessions.entry_point AS knowledge_point_id,
               count(learning_messages.id) AS message_count,
               min(learning_messages.created_at) AS first_message_at,
               max(learning_messages.created_at) AS last_message_at
        FROM learning_sessions
        LEFT JOIN learning_messages ON learning_messages.session_id = learning_sessions.id
        WHERE learning_sessions.user_id = %s
        GROUP BY learning_sessions.id
        ORDER BY learning_sessions.started_at, learning_sessions.id
        """,
        (user_id,),
    ).fetchall()
    review = conn.execute(
        """
        SELECT learning_sessions.id AS session_id, learning_sessions.entry_point AS knowledge_point_id,
               count(review_messages.id) AS message_count,
               min(review_messages.created_at) AS first_message_at,
               max(review_messages.created_at) AS last_message_at
        FROM learning_sessions
        LEFT JOIN review_messages ON review_messages.review_session_id = learning_sessions.id
        WHERE learning_sessions.user_id = %s
          AND learning_sessions.session_type = 'review'
        GROUP BY learning_sessions.id
        ORDER BY learning_sessions.started_at, learning_sessions.id
        """,
        (user_id,),
    ).fetchall()
    return {
        "onboarding": [_safe_row(row, exclude=()) for row in onboarding],
        "learning": [_safe_row(row, exclude=()) for row in learning],
        "review": [_safe_row(row, exclude=()) for row in review],
    }


def _export_learning_plan_sessions(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, status, preferred_language_id, current_draft_id,
               confirmed_track_id, version, last_error_code, last_error_at,
               created_at, updated_at, confirmed_at, cancelled_at
        FROM tutor_learning_plan_sessions
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_plan_drafts(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, session_id, draft_version, predecessor_draft_id, language_id,
               goal_text, target_level, weekly_minutes, experience_level,
               teaching_preferences_json, pace_summary, profile_json, plan_json,
               source_summary_json, content_hash, generator_version, policy_version,
               change_reason, source_run_id, source_input_revision, created_at
        FROM tutor_learning_plan_drafts
        WHERE user_id = %s
        ORDER BY session_id, draft_version
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_planning_intake_facts(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, session_id, conversation_id, field_key, value_json,
               revision, state, source_kind, source_message_id, source_run_id,
               source_input_revision, supersedes_fact_id, policy_version, created_at
        FROM tutor_planning_intake_facts
        WHERE user_id = %s
        ORDER BY session_id, field_key, revision
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_planning_question_events(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, session_id, conversation_id, field_key, question_key, status,
               source_run_id, source_message_id, source_input_revision, fact_id,
               previous_event_id, created_at
        FROM tutor_planning_question_events
        WHERE user_id = %s
        ORDER BY session_id, field_key, created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_tracks(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, language_id, goal_text, target_level, status, current_knowledge_key,
               version, last_learned_at, created_at, updated_at, archived_at
        FROM tutor_learning_tracks
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_track_plan_revisions(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, track_id, predecessor_revision_id, status, title, target_level,
               generator_version, policy_version, change_reason, content_hash,
               created_at, activated_at
        FROM tutor_track_plan_revisions
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_track_nodes(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT nodes.id, nodes.track_id, nodes.revision_id, nodes.module_id,
               nodes.knowledge_key, nodes.title, nodes.description, nodes.order_index,
               nodes.is_core, nodes.prerequisite_keys_json, nodes.required_capabilities_json,
               nodes.catalog_knowledge_key,
               progress.status AS progress_status, progress.version AS progress_version,
               mastery.confidence AS mastery_confidence,
               mastery.mastery_level, mastery.strengths_json, mastery.weaknesses_json,
               mastery.evidence_count, mastery.projector_version
        FROM tutor_track_plan_nodes AS nodes
        LEFT JOIN tutor_track_node_progress AS progress
          ON (progress.track_id, progress.user_id, progress.knowledge_key) =
             (nodes.track_id, nodes.user_id, nodes.knowledge_key)
        LEFT JOIN tutor_mastery_states AS mastery
          ON (mastery.track_id, mastery.user_id, mastery.knowledge_key) =
             (nodes.track_id, nodes.user_id, nodes.knowledge_key)
        WHERE nodes.user_id = %s
        ORDER BY nodes.track_id, nodes.revision_id, nodes.module_id, nodes.order_index, nodes.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_lesson_documents(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, track_id, knowledge_key, language_id, active_plan_revision_id,
               standard_document_id, predecessor_document_id, schema_version,
               content_standard_version, generator_version, policy_version,
               source_set_hash, profile_hash, title, coverage_keys_json, blocks_json,
               content_hash, change_summary_json, created_at
        FROM tutor_lesson_documents
        WHERE user_id = %s AND document_kind = 'personalized'
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_lesson_assignments(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, track_id, knowledge_key, document_id, source_plan_revision_id,
               predecessor_assignment_id, assignment_version, status, impact_json,
               content_hash, started_at, activated_at, created_at, updated_at
        FROM tutor_lesson_assignments
        WHERE user_id = %s
        ORDER BY track_id, knowledge_key, assignment_version
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]



def _export_teaching_sessions(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT id,track_id,conversation_id,knowledge_key,status,mode,current_checkpoint_id,version,
                  progress_version,lesson_assignment_id,assignment_version,document_id,paused_at,completed_at,
                  last_activity_at,created_at,updated_at
           FROM tutor_teaching_sessions WHERE user_id=%s ORDER BY track_id,created_at,id""",
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_teaching_checkpoints(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT id,teaching_session_id,conversation_id,predecessor_checkpoint_id,session_version,
                  source_run_id,source_stimulus_id,schema_version,policy_version,created_at,
                  jsonb_array_length(COALESCE(state_json->'suspended_focuses','[]'::jsonb)) AS suspended_focus_count,
                  jsonb_array_length(COALESCE(state_json->'unresolved_questions','[]'::jsonb)) AS unresolved_question_count,
                  jsonb_array_length(COALESCE(state_json->'covered_concepts','[]'::jsonb)) AS covered_concept_count
           FROM tutor_teaching_session_checkpoints WHERE user_id=%s ORDER BY teaching_session_id,session_version""",
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_teaching_stimuli(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT id,run_id,conversation_id,teaching_session_id,stimulus_kind,message_id,input_revision,
                  control_key,client_action_id,domain_event_kind,source_id,source_version,created_at
           FROM tutor_run_stimulus_events WHERE user_id=%s ORDER BY created_at,id""",
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_run_teaching_scopes(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT run_id,conversation_id,teaching_session_id,checkpoint_id,stimulus_id,session_version,
                  track_id,knowledge_key,mode,lesson_assignment_id,assignment_version,document_id,
                  schema_version,policy_version,created_at
           FROM tutor_run_teaching_scopes WHERE user_id=%s ORDER BY created_at,run_id""",
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_teaching_action_receipts(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """SELECT id,run_id,conversation_id,teaching_session_id,checkpoint_id,stimulus_id,action,
                  objective_id,focus_id,focus_resolution,pause_kind,source_handles_json,
                  teaching_moves_json,learner_response_mode,schema_version,policy_version,created_at
           FROM tutor_teaching_action_receipts WHERE user_id=%s ORDER BY created_at,id""",
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]

def _export_learning_artifacts(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT artifacts.id, artifacts.conversation_id, artifacts.turn_id,
               artifacts.learning_track_id, artifacts.knowledge_key, artifacts.teaching_session_id,
               artifacts.checkpoint_id, artifacts.track_version, artifacts.progress_version,
               artifacts.assignment_version, artifacts.owner_kind, artifacts.owner_id,
               artifacts.owner_version, artifacts.owner_context_version,
               artifacts.artifact_schema_version, artifacts.artifact_kind, artifacts.purpose,
               artifacts.state, artifacts.blocking, artifacts.title, artifacts.difficulty,
               artifacts.presentation_kind, artifacts.active_attempt_id, artifacts.version,
               artifacts.terminal_at, artifacts.created_at, artifacts.updated_at,
               jsonb_array_length(artifacts.allowed_actions_json) AS allowed_action_count,
               (SELECT count(*)::int FROM tutor_learning_artifact_events AS events
                WHERE events.artifact_id = artifacts.id) AS event_count,
               (SELECT count(*)::int FROM tutor_learning_artifact_references AS refs
                WHERE refs.artifact_id = artifacts.id) AS reference_count,
               (SELECT count(*)::int FROM tutor_learning_artifact_attempt_links AS links
                WHERE links.artifact_id = artifacts.id) AS attempt_link_count
        FROM tutor_learning_artifacts AS artifacts
        WHERE artifacts.user_id = %s
        ORDER BY artifacts.created_at, artifacts.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_artifact_events(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, artifact_id, conversation_id, teaching_session_id, event_sequence,
               event_kind, from_version, to_version, state, action_kind, client_action_id,
               created_at
        FROM tutor_learning_artifact_events
        WHERE user_id = %s
        ORDER BY artifact_id, event_sequence
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_artifact_references(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, artifact_id, conversation_id, teaching_session_id, reference_index,
               reference_kind, reference_id, reference_version, label, created_at
        FROM tutor_learning_artifact_references
        WHERE user_id = %s
        ORDER BY artifact_id, reference_index
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_learning_artifact_attempt_links(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, artifact_id, conversation_id, teaching_session_id, learning_track_id,
               attempt_id, artifact_version, created_at
        FROM tutor_learning_artifact_attempt_links
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_demonstration_completions(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, artifact_id, conversation_id, learning_track_id,
               teaching_session_id, checkpoint_id, artifact_version,
               completion_kind, event_key, visible_elapsed_ms,
               required_visible_ms, completed_at
        FROM tutor_demonstration_completion_receipts
        WHERE user_id = %s
        ORDER BY completed_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_knowledge_check_responses(
    conn: Connection[dict[str, object]], user_id: str
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id,artifact_id,conversation_id,learning_track_id,knowledge_key,
               teaching_session_id,artifact_version,response_kind,outcome,assistance_kind,
               independent_mastery_eligible,score_policy_version,created_at
        FROM tutor_knowledge_check_response_receipts
        WHERE user_id=%s ORDER BY created_at,id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_model_review_artifact_receipts(
    conn: Connection[dict[str, object]], user_id: str
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id,artifact_id,conversation_id,learning_track_id,knowledge_key,
               teaching_session_id,artifact_version,exercise_version_id,verdict,
               outcome,score,assistance_kind,remediation_handle,policy_version,created_at
        FROM tutor_model_review_artifact_receipts
        WHERE user_id=%s ORDER BY created_at,id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_knowledge_check_assistance(
    conn: Connection[dict[str, object]], user_id: str
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id,artifact_id,conversation_id,learning_track_id,knowledge_key,
               teaching_session_id,artifact_version,assistance_kind,hint_level,created_at
        FROM tutor_knowledge_check_assistance_receipts
        WHERE user_id=%s ORDER BY created_at,id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_clarification_branches(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, learning_track_id, knowledge_key,
               teaching_session_id, checkpoint_id, artifact_id,
               predecessor_branch_id, depth, state, version, round_count,
               latest_disposition, opened_turn_id, opened_input_revision,
               resolved_turn_id, created_at, updated_at, resolved_at,
               superseded_by_session_id, superseded_at
        FROM tutor_conversation_branches
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_clarification_branch_events(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, branch_id, conversation_id, artifact_id,
               predecessor_event_id, branch_version, event_kind,
               message_classification, control_kind, disposition,
               source_turn_id, source_input_revision, response_message_id,
               assistance_kind, assistance_receipt_kind, assistance_receipt_id,
               superseding_session_id, created_at
        FROM tutor_conversation_branch_events
        WHERE user_id = %s
        ORDER BY branch_id, branch_version
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_run_branch_scopes(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT run_id, conversation_id, branch_id, artifact_id,
               teaching_session_id, checkpoint_id, learning_track_id,
               knowledge_key, branch_version, branch_round,
               source_input_revision, message_classification, control_kind,
               created_at
        FROM tutor_run_branch_scopes
        WHERE user_id = %s
        ORDER BY created_at, run_id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_clarification_branch_items(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, branch_id, conversation_id, artifact_id, run_id,
               branch_round, item_sequence, item_kind, item_id, item_role,
               created_at
        FROM tutor_conversation_branch_items
        WHERE user_id = %s
        ORDER BY branch_id, item_sequence
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_continuation_intents(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, learning_track_id, knowledge_key,
               teaching_session_id, checkpoint_id, artifact_id, branch_id,
               source_kind, source_id, source_version, priority,
               session_version, artifact_version, track_version,
               progress_version, assignment_version, state, version,
               not_before, claim_generation, claim_expires_at,
               consumed_run_id, terminal_reason, created_at, updated_at
        FROM tutor_continuation_intents
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_continuation_intent_events(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, intent_id, conversation_id, artifact_id,
               predecessor_event_id, intent_version, event_kind, state,
               claim_generation, claim_expires_at, consumed_run_id,
               reason_code, created_at
        FROM tutor_continuation_intent_events
        WHERE user_id = %s
        ORDER BY intent_id, intent_version
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_lesson_citations(conn: Connection[dict[str, object]], user_id: str) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT document_id, knowledge_key, citation_id, source_id, display_name,
               provider, trust_tier, source_type, source_version_label,
               source_version_kind, canonical_url, section_path_json,
               grounding_chunk_id, document_content_hash, chunk_content_hash,
               fetched_at, snapshotted_at
        FROM tutor_lesson_source_snapshots
        WHERE user_id = %s
        ORDER BY document_id, citation_id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_lesson_gates(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT bindings.id AS binding_id, bindings.track_id, bindings.knowledge_key,
               bindings.gate_key, slots.gate_kind, bindings.requirement_kind,
               bindings.pass_policy_version, bindings.pass_threshold,
               bindings.execution_requirement, bindings.binding_contract_hash,
               versions.exercise_key, versions.exercise_type, versions.version AS exercise_version,
               versions.title AS exercise_title, versions.learner_prompt_json,
               states.state, states.attempt_count, states.best_score, states.version AS gate_version,
               states.passed_at, states.created_at, states.updated_at
        FROM tutor_lesson_gate_bindings AS bindings
        JOIN tutor_lesson_gate_slots AS slots ON slots.id = bindings.slot_id
        JOIN tutor_exercise_versions AS versions ON versions.id = bindings.exercise_version_id
        LEFT JOIN tutor_lesson_gate_states AS states
          ON states.gate_binding_id = bindings.id AND states.user_id = bindings.user_id
        WHERE bindings.user_id = %s
        ORDER BY bindings.track_id, bindings.knowledge_key, bindings.gate_key
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_exercise_attempt_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT attempts.id, attempts.attempt_type, attempts.track_id, attempts.plan_revision_id,
               attempts.knowledge_key, attempts.lesson_assignment_id, attempts.gate_binding_id,
               attempts.diagnostic_session_id, attempts.diagnostic_item_id,
               attempts.review_session_id, attempts.review_item_id,
               attempts.learning_item_version_id,
               attempts.exercise_version_id, attempts.submission_hash, attempts.hint_state_hash,
               attempts.independence, attempts.assistance_kind, attempts.accepted_at,
               submissions.submission_kind, submissions.content_text,
               results.outcome, results.score, results.safe_feedback_json,
               results.capability_scores_json, results.policy_version, results.terminal_at
        FROM tutor_exercise_attempts AS attempts
        JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = attempts.id
        LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
        WHERE attempts.user_id = %s
        ORDER BY attempts.accepted_at, attempts.id
        """,
        (user_id,),
    ).fetchall()
    exported: list[dict[str, object]] = []
    for row in rows:
        item = _safe_row(row, exclude=("content_text",))
        if str(row.get("submission_kind") or "") == "structured_answer":
            summary = _model_review_submission_summary(row.get("content_text"))
            if summary is not None:
                item["review_submission_summary"] = summary
        exported.append(item)
    return exported


def _export_module_diagnostic_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT sessions.id, sessions.track_id, sessions.module_key,
               versions.version AS diagnostic_version, versions.policy_version,
               versions.core_capabilities_json, versions.pass_threshold,
               sessions.source_plan_revision_id, sessions.proposed_plan_revision_id,
               sessions.state, sessions.impact_json, sessions.weak_capabilities_json,
               sessions.version, sessions.started_at, sessions.terminal_at,
               sessions.cooldown_until, sessions.confirmed_at,
               count(items.id)::int AS item_count
        FROM tutor_module_diagnostic_sessions AS sessions
        JOIN tutor_module_diagnostic_versions AS versions ON versions.id = sessions.diagnostic_version_id
        LEFT JOIN tutor_module_diagnostic_items AS items ON items.session_id = sessions.id
        WHERE sessions.user_id = %s
        GROUP BY sessions.id, versions.id
        ORDER BY sessions.started_at, sessions.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_review_schedule_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, track_id, knowledge_key, source_plan_revision_id, status,
               card_state, stability, difficulty, due_at, last_review_at,
               review_count, lapse_count, last_rating, risk_level,
               scheduler_version, version, created_at, updated_at
        FROM tutor_review_schedule_states
        WHERE user_id = %s
        ORDER BY track_id, knowledge_key
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_review_session_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT sessions.id, sessions.track_id, sessions.plan_revision_id,
               sessions.knowledge_key, sessions.state, sessions.stage,
               sessions.failure_code, sessions.version, sessions.started_at,
               sessions.terminal_at, sessions.created_at, sessions.updated_at,
               count(items.id)::int AS item_count,
               count(attempts.id)::int AS attempt_count
        FROM tutor_review_sessions AS sessions
        LEFT JOIN tutor_review_items AS items ON items.session_id = sessions.id
        LEFT JOIN tutor_exercise_attempts AS attempts
          ON attempts.review_item_id = items.id AND attempts.attempt_type = 'review_submit'
        WHERE sessions.user_id = %s
        GROUP BY sessions.id
        ORDER BY sessions.started_at, sessions.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_review_finalization_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, session_id, track_id, knowledge_key, rating,
               aggregate_json, created_at
        FROM tutor_review_finalizations
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_action_receipt_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT invocation_id, run_id, conversation_id, input_revision, action_id,
               action_version, status, authority_kind, authority_id, safe_summary,
               verification_status, diagnostic_code, recovery_kind, recovery_code,
               retry_after_seconds, terminal_at
        FROM tutor_action_receipts
        WHERE user_id = %s
        ORDER BY terminal_at, invocation_id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]



def _export_tutor_context_references(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, conversation_id, run_id, message_id, input_revision,
               reference_index, reference_kind, track_id, knowledge_key,
               document_id, attempt_id, review_session_id, exercise_version_id,
               source_version, source_hash, safe_payload_json, safe_payload_hash, created_at
        FROM tutor_message_context_references
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]

def _export_model_review_authoring_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, track_id, knowledge_key, plan_revision_id, lesson_assignment_id,
               gate_key, validation_profile_version, request_hash, profile_hash,
               state, attempt_count, candidate_id, validation_run_id, publication_id,
               failure_code, terminal_at, created_at, updated_at
        FROM tutor_model_review_authoring_runs
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_model_review_candidate_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, authoring_run_id, track_id, knowledge_key, public_hash,
               candidate_hash, generator_version, prompt_schema_version,
               validation_profile_version, state, created_at, updated_at
        FROM tutor_model_review_candidates
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_model_review_validation_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT validations.id, validations.authoring_run_id, validations.candidate_id,
               validations.track_id, validations.validation_profile_version,
               validations.candidate_hash, validations.state,
               validations.action_receipt_hash, validations.authority_hash,
               validations.check_summary_code, validations.failure_code,
               validations.safe_summary, validations.terminal_at,
               validations.created_at, validations.updated_at,
               count(checks.id)::int AS check_count,
               count(checks.id) FILTER (WHERE checks.status = 'passed')::int AS passed_check_count,
               count(checks.id) FILTER (WHERE checks.status = 'failed')::int AS failed_check_count,
               count(checks.id) FILTER (WHERE checks.status = 'not_applicable')::int AS not_applicable_check_count
        FROM tutor_model_review_validation_runs AS validations
        LEFT JOIN tutor_model_review_validation_checks AS checks
          ON checks.validation_run_id = validations.id AND checks.user_id = validations.user_id
        WHERE validations.user_id = %s
        GROUP BY validations.id
        ORDER BY validations.created_at, validations.id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_model_review_publication_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, authoring_run_id, candidate_id, validation_run_id,
               track_id, knowledge_key, lesson_assignment_id, gate_binding_id,
               exercise_version_id, validation_authority_hash, published_at, created_at
        FROM tutor_model_review_publications
        WHERE user_id = %s
        ORDER BY published_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _export_model_review_evidence_summaries(
    conn: Connection[dict[str, object]],
    user_id: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT id, publication_id, lesson_assignment_id, gate_binding_id,
               evidence_hash, created_at
        FROM tutor_model_review_evidence_receipts
        WHERE user_id = %s
        ORDER BY created_at, id
        """,
        (user_id,),
    ).fetchall()
    return [_safe_row(row, exclude=()) for row in rows]


def _model_review_submission_summary(content: object) -> dict[str, object] | None:
    if not isinstance(content, str):
        return None
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != "model_code_review_submission_v1"
        or not isinstance(payload.get("findings"), list)
    ):
        return None
    findings: list[dict[str, object]] = []
    for value in payload["findings"]:
        if not isinstance(value, dict):
            return None
        findings.append(
            {
                key: value[key]
                for key in (
                    "client_finding_id", "finding_kind", "start_line", "end_line",
                    "category", "severity",
                )
                if key in value
            }
        )
    return {
        "schema_version": "model_code_review_export_summary_v1",
        "verdict": payload.get("verdict"),
        "findings": findings,
    }


def _delete_learning_track_data(conn: Connection[dict[str, object]], user_id: str) -> None:
    # Scope snapshots are children of durable Tutor runs/conversations. Cancel
    # active runs first so an old continuation cannot resume after its authority
    # rows are removed, while preserving existing conversation/history rows.
    now = datetime.now(UTC)
    tutor_repository = PostgresTutorRepository(conn)
    active_runs = conn.execute(
        """
        SELECT id
        FROM tutor_runs
        WHERE user_id = %s
          AND (
            origin = 'interactive'
            OR id IN (
              SELECT internal_run_id
              FROM tutor_model_review_authoring_runs
              WHERE user_id = %s AND internal_run_id IS NOT NULL
            )
          )
          AND terminal_outcome IS NULL
          AND cancelled_at IS NULL
          AND superseded_by_run_id IS NULL
        ORDER BY created_at, id
        """,
        (user_id, user_id),
    ).fetchall()
    for run in active_runs:
        tutor_repository.request_cancellation(
            user_id=user_id,
            run_id=str(run["id"]),
            now=now,
        )
    conn.execute("SELECT set_config('aearn.learning_track_purge_user_id', %s, true)", (user_id,))
    conn.execute("SET CONSTRAINTS ALL DEFERRED")
    conn.execute(
        "DELETE FROM tutor_continuation_intent_events WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_continuation_intents WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_conversation_branch_items WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_run_branch_scopes WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_conversation_branch_events WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        "DELETE FROM tutor_conversation_branches WHERE user_id = %s",
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM tutor_conversation_events
        WHERE user_id = %s
          AND item_kind = 'artifact'
          AND item_id IN (
            SELECT id FROM tutor_learning_artifacts WHERE user_id = %s
          )
        """,
        (user_id, user_id),
    )
    conn.execute("DELETE FROM tutor_knowledge_check_assistance_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_knowledge_check_response_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_artifact_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_learning_artifact_events WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_learning_artifact_references WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_learning_artifact_attempt_links WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_demonstration_completion_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_learning_artifacts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_teaching_action_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_run_teaching_scopes WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_run_stimulus_events WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_teaching_session_checkpoints WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_teaching_sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_message_context_references WHERE user_id = %s", (user_id,))
    conn.execute(
        """
        DELETE FROM tutor_action_receipts WHERE user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM tutor_action_verifications
        WHERE invocation_id IN (SELECT id FROM tutor_action_invocations WHERE user_id = %s)
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM tutor_action_attempts
        WHERE invocation_id IN (SELECT id FROM tutor_action_invocations WHERE user_id = %s)
        """,
        (user_id,),
    )
    action_rows = conn.execute(
        """
        WITH RECURSIVE action_depth AS (
          SELECT id, parent_invocation_id, 0 AS depth
          FROM tutor_action_invocations
          WHERE user_id = %s AND parent_invocation_id IS NULL
          UNION ALL
          SELECT child.id, child.parent_invocation_id, parent.depth + 1
          FROM tutor_action_invocations AS child
          JOIN action_depth AS parent ON parent.id = child.parent_invocation_id
          WHERE child.user_id = %s
        )
        SELECT id FROM action_depth ORDER BY depth DESC, id
        """,
        (user_id, user_id),
    ).fetchall()
    for row in action_rows:
        conn.execute(
            "DELETE FROM tutor_action_invocations WHERE id = %s AND user_id = %s",
            (row["id"], user_id),
        )
    conn.execute(
        """
        UPDATE tutor_execution_jobs
        SET cancellation_requested_at = COALESCE(cancellation_requested_at, %s)
        WHERE user_id = %s AND owner_kind IN ('exercise_attempt', 'model_review_validation')
          AND state NOT IN ('completed', 'timed_out', 'cancelled', 'unavailable', 'launch_uncertain', 'failed')
        """,
        (now, user_id),
    )
    conn.execute(
        """
        DELETE FROM tutor_execution_attempts
        WHERE job_id IN (
          SELECT id FROM tutor_execution_jobs
          WHERE user_id = %s AND owner_kind = 'exercise_attempt'
        )
        """,
        (user_id,),
    )
    conn.execute("DELETE FROM tutor_exercise_execution_links WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_execution_jobs WHERE user_id = %s AND owner_kind = 'exercise_attempt'", (user_id,))
    conn.execute("DELETE FROM tutor_execution_intents WHERE user_id = %s AND source_kind = 'exercise_submission'", (user_id,))
    model_review_internal_rows = conn.execute(
        """
        SELECT internal_run_id, internal_conversation_id
        FROM tutor_model_review_authoring_runs
        WHERE user_id = %s
          AND internal_run_id IS NOT NULL
          AND internal_conversation_id IS NOT NULL
        """,
        (user_id,),
    ).fetchall()
    model_review_run_ids = tuple(row["internal_run_id"] for row in model_review_internal_rows)
    model_review_conversation_ids = tuple(row["internal_conversation_id"] for row in model_review_internal_rows)
    conn.execute("DELETE FROM tutor_review_finalizations WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_hint_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_warmup_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_evidence_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_validation_checks WHERE user_id = %s", (user_id,))
    conn.execute(
        """
        DELETE FROM tutor_execution_attempts
        WHERE job_id IN (
          SELECT id FROM tutor_execution_jobs
          WHERE user_id = %s AND owner_kind = 'model_review_validation'
        )
        """,
        (user_id,),
    )
    conn.execute("DELETE FROM tutor_execution_jobs WHERE user_id = %s AND owner_kind = 'model_review_validation'", (user_id,))
    conn.execute("DELETE FROM tutor_execution_intents WHERE user_id = %s AND source_kind = 'model_review_candidate'", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_publications WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_validation_runs WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_candidates WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_authoring_attempt_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_model_review_authoring_runs WHERE user_id = %s", (user_id,))
    _delete_model_review_internal_runs(
        conn,
        user_id=user_id,
        run_ids=model_review_run_ids,
        conversation_ids=model_review_conversation_ids,
    )
    conn.execute("DELETE FROM tutor_exercise_attempt_results WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_exercise_attempt_submissions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_exercise_attempts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_items WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_schedule_events WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_review_schedule_states WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_exercise_hint_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_gate_states WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_module_diagnostic_items WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_module_diagnostic_sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_gate_bindings WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_authoring_attempt_receipts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_authoring_runs WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_assignments WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_block_citations WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_gate_slots WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_source_snapshots WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_lesson_documents WHERE user_id = %s AND document_kind = 'personalized'", (user_id,))
    question_event_rows = conn.execute(
        """
        WITH RECURSIVE event_depth AS (
          SELECT id, previous_event_id, 0 AS depth
          FROM tutor_planning_question_events
          WHERE user_id = %s AND previous_event_id IS NULL
          UNION ALL
          SELECT child.id, child.previous_event_id, parent.depth + 1
          FROM tutor_planning_question_events AS child
          JOIN event_depth AS parent ON parent.id = child.previous_event_id
          WHERE child.user_id = %s
        )
        SELECT id FROM event_depth ORDER BY depth DESC, id
        """,
        (user_id, user_id),
    ).fetchall()
    for row in question_event_rows:
        conn.execute(
            "DELETE FROM tutor_planning_question_events WHERE id = %s AND user_id = %s",
            (row["id"], user_id),
        )
    fact_rows = conn.execute(
        """
        SELECT id
        FROM tutor_planning_intake_facts
        WHERE user_id = %s
        ORDER BY session_id, field_key, revision DESC, id
        """,
        (user_id,),
    ).fetchall()
    for row in fact_rows:
        conn.execute(
            "DELETE FROM tutor_planning_intake_facts WHERE id = %s AND user_id = %s",
            (row["id"], user_id),
        )
    conn.execute("DELETE FROM tutor_learning_plan_drafts WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_learning_plan_sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_run_learning_scopes WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_conversation_learning_scopes WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_mastery_states WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_mastery_evidence WHERE user_id = %s", (user_id,))
    conn.execute("UPDATE tutor_learning_tracks SET current_knowledge_key = NULL WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_track_node_progress WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_track_plan_migrations WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_track_plan_nodes WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_track_plan_modules WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_track_active_plans WHERE user_id = %s", (user_id,))

    revision_rows = conn.execute(
        """
        WITH RECURSIVE revision_depth AS (
          SELECT id, predecessor_revision_id, 0 AS depth
          FROM tutor_track_plan_revisions
          WHERE user_id = %s AND predecessor_revision_id IS NULL
          UNION ALL
          SELECT child.id, child.predecessor_revision_id, parent.depth + 1
          FROM tutor_track_plan_revisions AS child
          JOIN revision_depth AS parent ON parent.id = child.predecessor_revision_id
          WHERE child.user_id = %s
        )
        SELECT id
        FROM revision_depth
        ORDER BY depth DESC, id
        """,
        (user_id, user_id),
    ).fetchall()
    for row in revision_rows:
        conn.execute(
            "DELETE FROM tutor_track_plan_revisions WHERE id = %s AND user_id = %s",
            (row["id"], user_id),
        )
    conn.execute("DELETE FROM tutor_learning_tracks WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM tutor_api_idempotency_records WHERE user_id = %s", (user_id,))


def _delete_model_review_internal_runs(
    conn: Connection[dict[str, object]],
    *,
    user_id: str,
    run_ids: Sequence[object],
    conversation_ids: Sequence[object],
) -> None:
    if not run_ids:
        return
    run_id_values = list(run_ids)
    conversation_id_values = list(conversation_ids)
    conn.execute(
        "DELETE FROM tutor_interactive_dispatch_jobs WHERE run_id = ANY(%s::uuid[])",
        (run_id_values,),
    )
    conn.execute(
        "DELETE FROM tutor_turn_public_thinking_streams WHERE run_id = ANY(%s::uuid[])",
        (run_id_values,),
    )
    conn.execute(
        """
        DELETE FROM tutor_conversation_events
        WHERE user_id = %s
          AND (turn_id = ANY(%s::uuid[]) OR conversation_id = ANY(%s::uuid[]))
        """,
        (user_id, run_id_values, conversation_id_values),
    )
    for table_name in (
        "tutor_capability_invocations",
        "tutor_run_public_process_steps",
        "tutor_run_traces",
        "tutor_run_checkpoints",
        "tutor_run_skill_selections",
        "tutor_message_context_references",
        "tutor_run_input_events",
        "tutor_run_events",
        "tutor_effects",
        "tutor_run_public_processes",
        "tutor_teaching_action_receipts",
        "tutor_run_teaching_scopes",
        "tutor_run_stimulus_events",
        "tutor_run_learning_scopes",
    ):
        conn.execute(
            f"DELETE FROM {table_name} WHERE run_id = ANY(%s::uuid[])",
            (run_id_values,),
        )
    conn.execute(
        """
        DELETE FROM tutor_runs
        WHERE user_id = %s AND id = ANY(%s::uuid[])
          AND origin = 'proactive'
          AND conversation_id = ANY(%s::uuid[])
        """,
        (user_id, run_id_values, conversation_id_values),
    )
    conn.execute(
        """
        DELETE FROM tutor_conversation_learning_scopes
        WHERE user_id = %s AND conversation_id = ANY(%s::uuid[])
        """,
        (user_id, conversation_id_values),
    )
    conn.execute(
        "DELETE FROM tutor_messages WHERE conversation_id = ANY(%s::uuid[])",
        (conversation_id_values,),
    )
    conn.execute(
        """
        DELETE FROM tutor_conversations
        WHERE user_id = %s AND id = ANY(%s::uuid[])
          AND visibility = 'internal' AND kind = 'proactive'
        """,
        (user_id, conversation_id_values),
    )


def _delete_user_owned_learning_data(conn: Connection[dict[str, object]], user_id: str) -> None:
    _delete_learning_track_data(conn, user_id)
    conn.execute("DELETE FROM idempotency_records WHERE user_id = %s OR key LIKE %s OR response_json::text LIKE %s", (user_id, f"%{user_id}%", f"%{user_id}%"))
    conn.execute(
        """
        DELETE FROM learning_messages
        USING learning_sessions
        WHERE learning_messages.session_id = learning_sessions.id
          AND learning_sessions.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM review_messages
        USING learning_sessions
        WHERE review_messages.review_session_id = learning_sessions.id
          AND learning_sessions.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM onboarding_messages
        USING onboarding_conversations
        WHERE onboarding_messages.conversation_id = onboarding_conversations.id
          AND onboarding_conversations.user_id = %s
        """,
        (user_id,),
    )
    conn.execute("DELETE FROM review_logs WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM review_states WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM review_seed_banks WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM exercise_variant_cache WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM notes WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM attempts WHERE user_id = %s", (user_id,))
    conn.execute(
        """
        UPDATE knowledge_points
        SET last_session_id = NULL
        FROM plan_modules, learning_plans
        WHERE knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute("DELETE FROM learning_sessions WHERE user_id = %s", (user_id,))
    conn.execute(
        """
        DELETE FROM teaching_chunks
        USING knowledge_points, plan_modules, learning_plans
        WHERE teaching_chunks.knowledge_point_id = knowledge_points.id
          AND knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM test_cases
        USING exercises, knowledge_points, plan_modules, learning_plans
        WHERE test_cases.exercise_id = exercises.id
          AND exercises.knowledge_point_id = knowledge_points.id
          AND knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM code_blanks
        USING exercises, knowledge_points, plan_modules, learning_plans
        WHERE code_blanks.exercise_id = exercises.id
          AND exercises.knowledge_point_id = knowledge_points.id
          AND knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM exercises
        USING knowledge_points, plan_modules, learning_plans
        WHERE exercises.knowledge_point_id = knowledge_points.id
          AND knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute("UPDATE learning_plans SET current_module_id = NULL WHERE user_id = %s", (user_id,))
    conn.execute(
        """
        DELETE FROM knowledge_points
        USING plan_modules, learning_plans
        WHERE knowledge_points.module_id = plan_modules.id
          AND plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute(
        """
        DELETE FROM plan_modules
        USING learning_plans
        WHERE plan_modules.plan_id = learning_plans.id
          AND learning_plans.user_id = %s
        """,
        (user_id,),
    )
    conn.execute("DELETE FROM learning_plans WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM learner_profiles WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM onboarding_conversations WHERE user_id = %s", (user_id,))


def _safe_row(row: Mapping[str, object], *, exclude: Sequence[str]) -> dict[str, object]:
    excluded = set(exclude)
    return {
        key: _safe_value(value)
        for key, value in row.items()
        if key not in excluded
    }


def _safe_value(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    return value


def _iso_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value)


def _none_if_epoch(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return None if aware <= epoch else aware


def _int_or_zero(value: object) -> int:
    if not isinstance(value, int | float | str | bytes | bytearray):
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _number(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _str_or_none(value: object) -> str | None:
    if value in {None, ""}:
        return None
    return str(value)
