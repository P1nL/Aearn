from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from app.services.learning.lesson_contracts import ExerciseGateBlock
from app.services.learning.practice.contracts import ExerciseSourceKind
from app.services.learning.practice.model_review_fixtures import MODEL_REVIEW_FIXTURES
from app.services.learning.practice.model_review_repository import PostgresModelReviewRepository
from app.services.learning.practice.repository import PostgresExerciseGateRepository
from app.services.learning.practice.service import ExerciseGateService
from app.services.repositories.local_user_data_repository import export_user_data, reset_user_data
from app.services.tutor.cutover import HarnessCutoverService
from lesson_document_support import sample_lesson_document
from test_lesson_document_repository import _publish

pytest_plugins = ("test_lesson_document_repository",)


def _model_review_document(*, personalized: bool):
    document = sample_lesson_document(personalized=personalized)
    blocks = list(document.blocks)
    gate = blocks[7]
    assert isinstance(gate, ExerciseGateBlock)
    blocks[7] = replace(gate, assessment_contract_version="model_code_review_v1")
    return replace(document, blocks=tuple(blocks))


def _finding_submission() -> dict[str, object]:
    return {
        "schema_version": "model_code_review_submission_v1",
        "verdict": "correctness_issue",
        "findings": [
            {
                "client_finding_id": "finding-export-1",
                "finding_kind": "correctness",
                "start_line": 2,
                "end_line": 2,
                "category": "edge_case",
                "severity": "high",
                "trigger_condition": "private trigger detail must not be exported",
                "principle": "private principle detail must not be exported",
                "impact": "private impact detail must not be exported",
                "validation_method": "private validation method must not be exported",
                "suggested_fix": "private suggested fix must not be exported",
                "supplemental_note": "private supplemental note must not be exported",
            }
        ],
        "supplemental_note": "private top-level note must not be exported",
    }


def test_model_review_export_reset_and_cutover_inventory(lesson_repo) -> None:
    conn, lesson_repository, user_id, track_id, snapshot = lesson_repo
    published = _publish(
        conn,
        lesson_repository,
        user_id,
        track_id,
        snapshot,
        action="initial",
        standard_document=_model_review_document(personalized=False),
        personalized_document=_model_review_document(personalized=True),
    )
    started = lesson_repository.start_assignment(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        assignment_id=published.assignment_id,
        expected_assignment_version=1,
        expected_progress_version=1,
        now=datetime(2026, 8, 12, 1, tzinfo=UTC),
    )
    practice = PostgresExerciseGateRepository(conn)
    model_reviews = PostgresModelReviewRepository(conn)
    scope = practice.read_scope(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
    )
    slot = model_reviews.read_slot(scope=scope, gate_key="python.variables.basic")
    authoring, created = model_reviews.create_or_replay_authoring_run(
        scope=scope,
        slot=slot,
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
    )
    assert created is True
    claimed = model_reviews.claim(
        run_id=authoring.run_id,
        owner="model-review-export-test",
        now=datetime(2026, 8, 12, 2, tzinfo=UTC),
    )
    assert claimed is not None
    running = model_reviews.mark_running(claimed)
    internal_snapshot, _lease = model_reviews.ensure_internal_run(
        run=running,
        now=datetime(2026, 8, 12, 2, 1, tzinfo=UTC),
    )
    running = model_reviews.read_authoring_run(run_id=running.run_id, user_id=user_id)
    source = MODEL_REVIEW_FIXTURES[0]
    exercise = replace(
        source.exercise,
        exercise_key=f"python.variables.review.export.{uuid4().hex[:12]}",
        source_kind=ExerciseSourceKind.REGISTERED_AUTHOR,
        required_capabilities=running.required_capabilities,
    )
    candidate = model_reviews.create_candidate(
        run=running,
        exercise=exercise,
        rubric=source.rubric,
    )
    validation = model_reviews.create_or_replay_validation(
        run=running,
        candidate=candidate,
        action_invocation_id=f"model-review-export-{uuid4().hex[:12]}",
    )
    required_checks = (
        "schema",
        "parser",
        "compile_or_typecheck",
        "visible_tests",
        "hidden_tests",
        "finding_reachability",
        "rubric_consistency",
        "coverage",
        "redaction",
    )
    for check_type in required_checks:
        conn.execute(
            """
            INSERT INTO tutor_model_review_validation_checks (
              validation_run_id, user_id, check_type, status,
              execution_job_id, proof_hash, safe_code
            ) VALUES (%s, %s, %s, 'passed', NULL, %s, 'model_review_check_passed')
            """,
            (validation.validation_id, user_id, check_type, "a" * 64),
        )
    authority_hash = "b" * 64
    conn.execute(
        "UPDATE tutor_model_review_validation_runs SET state = 'running' WHERE id = %s",
        (validation.validation_id,),
    )
    conn.execute(
        """
        UPDATE tutor_model_review_validation_runs
        SET state = 'verified', authority_hash = %s,
            check_summary_code = 'all_checks_passed',
            safe_summary = 'Model review candidate passed controlled validation.',
            terminal_at = %s
        WHERE id = %s
        """,
        (authority_hash, datetime(2026, 8, 12, 3, tzinfo=UTC), validation.validation_id),
    )
    model_reviews.attach_action_receipt(
        validation_id=validation.validation_id,
        user_id=user_id,
        action_receipt_hash="c" * 64,
    )
    conn.execute(
        "UPDATE tutor_model_review_candidates SET state = 'verified' WHERE id = %s",
        (candidate.candidate_id,),
    )
    validation = model_reviews.read_validation(validation_id=validation.validation_id, user_id=user_id)
    running = model_reviews.read_authoring_run(run_id=running.run_id, user_id=user_id)
    publication_id = model_reviews.publish(
        run=running,
        candidate=model_reviews.read_candidate(candidate_id=candidate.candidate_id, user_id=user_id),
        validation=validation,
        now=datetime(2026, 8, 12, 4, tzinfo=UTC),
    )
    gate = ExerciseGateService(conn).read_gates(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
    )["items"][0]
    evidence = ExerciseGateService(conn).model_review_evidence(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        expected_gate_version=int(gate["gate_version"]),
        idempotency_key=f"evidence-{uuid4()}",
    )
    attempt = ExerciseGateService(conn).attempt_gate(
        user_id=user_id,
        track_id=track_id,
        knowledge_key="python.variables",
        gate_key="python.variables.basic",
        attempt_type="submit",
        submission=None,
        review_submission=_finding_submission(),
        expected_track_version=1,
        expected_progress_version=int(started["progress_version"]),
        expected_assignment_version=1,
        expected_gate_version=int(evidence["gate_version"]),
        idempotency_key=f"attempt-{uuid4()}",
    )
    conn.commit()
    exercise_version_id = str(attempt["exercise_version_id"])

    exported = export_user_data(conn, user_id)
    assert exported["summary"]["counts"]["model_review_authoring_runs"] == 1
    assert exported["summary"]["counts"]["model_review_validation_checks"] == 9
    assert exported["model_review_authoring_summaries"][0]["state"] == "completed"
    assert exported["model_review_candidate_summaries"][0]["state"] == "published"
    assert exported["model_review_validation_summaries"][0]["check_count"] == 9
    assert exported["model_review_publication_summaries"][0]["id"] == publication_id
    assert len(exported["model_review_evidence_summaries"]) == 1
    submission_summary = exported["exercise_attempt_summaries"][0]["review_submission_summary"]
    assert submission_summary == {
        "schema_version": "model_code_review_export_summary_v1",
        "verdict": "correctness_issue",
        "findings": [
            {
                "client_finding_id": "finding-export-1",
                "finding_kind": "correctness",
                "start_line": 2,
                "end_line": 2,
                "category": "edge_case",
                "severity": "high",
            }
        ],
    }
    serialized = json.dumps(exported, ensure_ascii=False).casefold()
    for private_marker in (
        "private trigger detail",
        "private principle detail",
        "private validation method",
        "private suggested fix",
        "private top-level note",
        "expected_findings",
        "matcher_tokens",
        "private_test_bundle",
        "def average(total, count)",
    ):
        assert private_marker not in serialized

    inventory = HarnessCutoverService(conn)._inventory(user_id)
    assert inventory.target_counts["tutor_model_review_authoring_runs"] == 1
    assert inventory.target_counts["tutor_model_review_validation_checks"] == 9
    assert inventory.target_counts["tutor_model_review_publications"] == 1
    assert inventory.target_counts["tutor_model_review_evidence_receipts"] == 1

    reset = reset_user_data(conn, user_id)
    conn.commit()
    for count_name in (
        "model_review_authoring_runs",
        "model_review_candidates",
        "model_review_validation_runs",
        "model_review_validation_checks",
        "model_review_publications",
        "model_review_evidence_receipts",
    ):
        assert reset["summary"]["counts"][count_name] == 0
    assert conn.execute(
        "SELECT 1 FROM tutor_runs WHERE id = %s",
        (internal_snapshot.run_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM tutor_conversations WHERE id = %s",
        (internal_snapshot.conversation_id,),
    ).fetchone() is None
    assert conn.execute(
        "SELECT 1 FROM tutor_exercise_versions WHERE id = %s",
        (exercise_version_id,),
    ).fetchone() is not None
