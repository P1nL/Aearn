"""PostgreSQL authority for model code-review authoring and publication."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from psycopg import Connection

from aearn_shared.execution import ExecutionAction, ExecutionJobState, ExecutionJobV1, SafeExecutionResultV1
from app.agents.harness.actions import ActionInvocation
from app.agents.harness.contracts import TutorLease, TutorPolicySnapshot, TutorRunSnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExercisePrivateRubric,
    ExerciseSourceKind,
    ExerciseType,
    ExerciseVersion,
    LessonGateBinding,
    canonical_hash,
)
from app.services.learning.practice.model_review_contracts import (
    ModelReviewArtifactV1,
    ModelReviewPromptV1,
    ModelReviewRubricV1,
    ModelReviewValidationReceiptV1,
)
from app.services.learning.practice.model_review_templates import (
    expected_model_review_test_outcomes,
    model_review_template_coverage_proof,
    validate_controlled_model_review_candidate,
)
from app.services.learning.practice.model_review_quality import (
    candidate_hash as publication_candidate_hash,
    model_review_public_redaction_proof,
)
from app.services.learning.practice.quality import require_exercise_quality
from app.services.learning.practice.repository import (
    GateScope,
    PracticeIdempotencyConflict,
    PracticeNotFound,
    PracticeVersionConflict,
    _float,
    _int,
    _json,
    _requirement_kind,
    _string_list,
)
from app.services.tutor.execution import ExecutionIntentRepository, ExecutionSubmissionError
from app.services.tutor.persistence import PostgresTutorRepository


MODEL_REVIEW_GENERATOR_VERSION = "model_review_author_v2"
MODEL_REVIEW_PROMPT_SCHEMA_VERSION = "model_review_author_prompt_v2"
MODEL_REVIEW_VALIDATION_PROFILE_VERSION = "model_review_validation_v1"
MODEL_REVIEW_PASS_POLICY_VERSION = "model_review_pass_v1"


class ModelReviewRepositoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelReviewAuthoringRunRecord:
    run_id: str
    user_id: str
    track_id: str
    knowledge_key: str
    plan_revision_id: str
    lesson_assignment_id: str
    document_id: str
    slot_id: str
    gate_key: str
    expected_track_version: int
    expected_progress_version: int
    expected_assignment_version: int
    language_id: str
    required_capabilities: tuple[str, ...]
    mastery_level: str
    mastery_confidence: float
    validation_profile_version: str
    request_hash: str
    state: str
    attempt_count: int
    lease_generation: int
    internal_conversation_id: str | None
    internal_run_id: str | None
    candidate_id: str | None
    validation_run_id: str | None
    publication_id: str | None
    failure_code: str | None
    failure_message: str | None


@dataclass(frozen=True, slots=True)
class ModelReviewCandidateRecord:
    candidate_id: str
    authoring_run_id: str
    user_id: str
    track_id: str
    knowledge_key: str
    public_payload: Mapping[str, object]
    private_payload: Mapping[str, object]
    public_hash: str
    private_hash: str
    candidate_hash: str
    validation_profile_version: str
    state: str


@dataclass(frozen=True, slots=True)
class ModelReviewValidationRecord:
    validation_id: str
    authoring_run_id: str
    candidate_id: str
    user_id: str
    track_id: str
    validation_profile_version: str
    candidate_hash: str
    state: str
    action_invocation_id: str | None
    authority_hash: str | None
    action_receipt_hash: str | None


class PostgresModelReviewRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def read_slot(self, *, scope: GateScope, gate_key: str, for_update: bool = False) -> dict[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_lesson_gate_slots WHERE document_id = %s AND gate_key = %s"
            + (" FOR UPDATE" if for_update else ""),
            (scope.document_id, gate_key),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("Lesson Gate slot was not found")
        return dict(row)

    @staticmethod
    def is_model_review_slot(slot: Mapping[str, object]) -> bool:
        return str(slot.get("assessment_contract_version") or "") == "model_code_review_v1"

    def create_or_replay_authoring_run(
        self,
        *,
        scope: GateScope,
        slot: Mapping[str, object],
        expected_track_version: int,
        expected_progress_version: int,
    ) -> tuple[ModelReviewAuthoringRunRecord, bool]:
        if scope.track_version != expected_track_version or scope.progress_version != expected_progress_version:
            raise PracticeVersionConflict("LearningTrack or progress changed")
        mastery = self._conn.execute(
            "SELECT mastery_level, confidence FROM tutor_mastery_states WHERE user_id = %s AND track_id = %s AND knowledge_key = %s",
            (scope.user_id, scope.track_id, scope.knowledge_key),
        ).fetchone()
        mastery_level = str(mastery.get("mastery_level") or "unseen") if mastery else "unseen"
        mastery_confidence = _float(mastery.get("confidence")) if mastery else 0.0
        capabilities = tuple(_string_list(slot.get("required_capabilities_json")))
        profile_hash = canonical_hash(
            {
                "language_id": scope.language_id,
                "knowledge_key": scope.knowledge_key,
                "required_capabilities": capabilities,
                "mastery_level": mastery_level,
                "mastery_confidence": round(mastery_confidence, 4),
                "validation_profile_version": MODEL_REVIEW_VALIDATION_PROFILE_VERSION,
            }
        )
        request_hash = canonical_hash(
            {
                "track_id": scope.track_id,
                "plan_revision_id": scope.plan_revision_id,
                "assignment_id": scope.assignment_id,
                "assignment_version": scope.assignment_version,
                "document_id": scope.document_id,
                "slot_id": str(slot["id"]),
                "gate_key": str(slot["gate_key"]),
                "assessment_contract_version": str(slot["assessment_contract_version"]),
                "profile_hash": profile_hash,
            }
        )
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_model_review_authoring_runs
            WHERE user_id = %s AND lesson_assignment_id = %s AND gate_key = %s AND request_hash = %s
            FOR UPDATE
            """,
            (scope.user_id, scope.assignment_id, str(slot["gate_key"]), request_hash),
        ).fetchone()
        if existing:
            return _authoring(existing), False
        row = self._conn.execute(
            """
            INSERT INTO tutor_model_review_authoring_runs (
              user_id, track_id, knowledge_key, plan_revision_id, lesson_assignment_id,
              document_id, slot_id, gate_key, expected_track_version, expected_progress_version,
              expected_assignment_version, language_id, required_capabilities_json,
              mastery_level, mastery_confidence, misconception_tags_json,
              validation_profile_version, request_hash, profile_hash, state
            ) VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
              %s, %s, '[]'::jsonb, %s, %s, %s, 'pending'
            ) RETURNING *
            """,
            (
                scope.user_id, scope.track_id, scope.knowledge_key, scope.plan_revision_id,
                scope.assignment_id, scope.document_id, slot["id"], slot["gate_key"],
                expected_track_version, expected_progress_version, scope.assignment_version,
                scope.language_id, _json(capabilities), mastery_level, mastery_confidence,
                MODEL_REVIEW_VALIDATION_PROFILE_VERSION, request_hash, profile_hash,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("model review authoring insert failed")
        return _authoring(row), True

    def read_authoring_run(self, *, run_id: str, user_id: str | None = None, for_update: bool = False) -> ModelReviewAuthoringRunRecord:
        sql = "SELECT * FROM tutor_model_review_authoring_runs WHERE id = %s"
        params: tuple[object, ...] = (run_id,)
        if user_id is not None:
            sql += " AND user_id = %s"
            params = (run_id, user_id)
        row = self._conn.execute(sql + (" FOR UPDATE" if for_update else ""), params).fetchone()
        if row is None:
            raise PracticeNotFound("model review authoring run was not found")
        return _authoring(row)

    def read_authoring_for_slot(self, *, user_id: str, assignment_id: str, gate_key: str) -> ModelReviewAuthoringRunRecord | None:
        row = self._conn.execute(
            """
            SELECT * FROM tutor_model_review_authoring_runs
            WHERE user_id = %s AND lesson_assignment_id = %s AND gate_key = %s
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (user_id, assignment_id, gate_key),
        ).fetchone()
        return _authoring(row) if row else None

    def claim(self, *, run_id: str, owner: str, now: datetime) -> ModelReviewAuthoringRunRecord | None:
        row = self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs
            SET state = CASE WHEN state = 'pending' THEN 'claimed' ELSE state END,
                lease_owner_id = %s, lease_generation = lease_generation + 1,
                lease_expires_at = %s, attempt_count = attempt_count + 1
            WHERE id = %s AND state IN ('pending', 'claimed', 'running', 'validating')
              AND (lease_expires_at IS NULL OR lease_expires_at <= %s OR lease_owner_id = %s)
            RETURNING *
            """,
            (owner, now + timedelta(seconds=120), run_id, now, owner),
        ).fetchone()
        return _authoring(row) if row else None

    def release(self, *, run_id: str, lease_generation: int) -> None:
        self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs
            SET lease_owner_id = NULL, lease_expires_at = NULL
            WHERE id = %s AND lease_generation = %s
              AND state IN ('claimed', 'running', 'validating')
            """,
            (run_id, lease_generation),
        )

    def mark_running(self, run: ModelReviewAuthoringRunRecord) -> ModelReviewAuthoringRunRecord:
        if run.state in {"running", "validating"}:
            return run
        row = self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs SET state = 'running'
            WHERE id = %s AND lease_generation = %s AND state = 'claimed' RETURNING *
            """,
            (run.run_id, run.lease_generation),
        ).fetchone()
        if row is None:
            raise PracticeVersionConflict("model review authoring claim changed")
        return _authoring(row)

    def record_author_attempt(
        self,
        *,
        run: ModelReviewAuthoringRunRecord,
        provider: str,
        model: str,
        protocol: str,
        outcome: Literal["success", "invalid", "unavailable"],
        diagnostic_code: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
        request_hash: str,
        response_hash: str | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_model_review_authoring_attempt_receipts (
              authoring_run_id, user_id, attempt_index, provider, model, protocol,
              outcome, diagnostic_code, input_tokens, output_tokens, request_hash, response_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (authoring_run_id, attempt_index) DO NOTHING
            """,
            (
                run.run_id, run.user_id, run.attempt_count, provider, model, protocol,
                outcome, diagnostic_code, input_tokens, output_tokens, request_hash, response_hash,
            ),
        )

    def create_candidate(
        self,
        *,
        run: ModelReviewAuthoringRunRecord,
        exercise: ExerciseVersion,
        rubric: ExercisePrivateRubric,
    ) -> ModelReviewCandidateRecord:
        public_payload = exercise.public_payload()
        private_payload = {
            "rubric_version": rubric.rubric_version,
            "private_test_bundle": [dict(item) for item in rubric.private_test_bundle],
            "reference_answer": dict(rubric.reference_answer),
            "score_policy": dict(rubric.score_policy),
            "rubric_hash": rubric.rubric_hash,
        }
        public_hash = canonical_hash(public_payload)
        private_hash = canonical_hash(private_payload)
        candidate_hash = publication_candidate_hash(exercise, rubric)
        existing = self._conn.execute(
            "SELECT * FROM tutor_model_review_candidates WHERE user_id = %s AND candidate_hash = %s",
            (run.user_id, candidate_hash),
        ).fetchone()
        if existing:
            return _candidate(existing)
        row = self._conn.execute(
            """
            INSERT INTO tutor_model_review_candidates (
              authoring_run_id, user_id, track_id, knowledge_key, public_payload_json,
              private_payload_json, public_hash, private_hash, candidate_hash,
              generator_version, prompt_schema_version, validation_profile_version, state
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, 'draft')
            RETURNING *
            """,
            (
                run.run_id, run.user_id, run.track_id, run.knowledge_key, _json(public_payload),
                _json(private_payload), public_hash, private_hash, candidate_hash,
                MODEL_REVIEW_GENERATOR_VERSION, MODEL_REVIEW_PROMPT_SCHEMA_VERSION,
                run.validation_profile_version,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("model review candidate insert failed")
        candidate = _candidate(row)
        self._conn.execute(
            "UPDATE tutor_model_review_authoring_runs SET candidate_id = %s WHERE id = %s AND candidate_id IS NULL",
            (candidate.candidate_id, run.run_id),
        )
        return candidate

    def read_candidate(self, *, candidate_id: str, user_id: str) -> ModelReviewCandidateRecord:
        row = self._conn.execute(
            "SELECT * FROM tutor_model_review_candidates WHERE id = %s AND user_id = %s",
            (candidate_id, user_id),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("model review candidate was not found")
        return _candidate(row)


    def ensure_internal_run(
        self, *, run: ModelReviewAuthoringRunRecord, now: datetime
    ) -> tuple[TutorRunSnapshot, TutorLease]:
        repository = PostgresTutorRepository(self._conn)
        if run.internal_run_id:
            snapshot = repository.load_snapshot(user_id=run.user_id, run_id=run.internal_run_id)
            if snapshot is None:
                raise PracticeNotFound("internal model review Tutor run was not found")
        else:
            conversation_id = str(uuid4())
            self._conn.execute(
                """
                INSERT INTO tutor_conversations (id, user_id, status, visibility, kind)
                VALUES (%s, %s, 'active', 'internal', 'proactive')
                """,
                (conversation_id, run.user_id),
            )
            self._conn.execute(
                """
                INSERT INTO tutor_conversation_learning_scopes (
                  conversation_id, user_id, scope_kind, learning_track_id
                ) VALUES (%s, %s, 'learning_track', %s)
                """,
                (conversation_id, run.user_id, run.track_id),
            )
            catalog = compile_published_skill_catalog()
            repository.record_catalog_snapshot(catalog)
            snapshot = repository.create_run(
                user_id=run.user_id,
                conversation_id=conversation_id,
                catalog_digest=catalog.digest,
                policy=TutorPolicySnapshot(
                    deadline=now + timedelta(minutes=5),
                    max_iterations=0,
                    max_model_calls=0,
                    max_capability_calls=1,
                    max_effects=1,
                    context_token_budget=256,
                    lease_duration_seconds=120,
                ),
                origin="proactive",
                policy_version="model_review_action_policy_v1",
            )
            self._conn.execute(
                """
                INSERT INTO tutor_run_learning_scopes (
                  run_id, user_id, conversation_id, scope_kind, learning_track_id,
                  task_kind, knowledge_key, scope_version
                ) VALUES (%s, %s, %s, 'learning_track', %s, 'model_code_review', %s, %s)
                """,
                (
                    snapshot.run_id, run.user_id, conversation_id, run.track_id,
                    run.knowledge_key, run.expected_track_version,
                ),
            )
            updated = self._conn.execute(
                """
                UPDATE tutor_model_review_authoring_runs
                SET internal_conversation_id = %s, internal_run_id = %s
                WHERE id = %s AND lease_generation = %s AND internal_run_id IS NULL
                RETURNING id
                """,
                (conversation_id, snapshot.run_id, run.run_id, run.lease_generation),
            ).fetchone()
            if updated is None:
                raise PracticeVersionConflict("model review internal run changed")
        lease = repository.acquire_lease(
            user_id=run.user_id,
            run_id=snapshot.run_id,
            owner_id=f"model-review-{run.run_id}",
            now=now,
            duration_seconds=120,
        )
        if lease is None:
            raise PracticeVersionConflict("internal model review Tutor lease is unavailable")
        current = repository.load_snapshot(user_id=run.user_id, run_id=snapshot.run_id)
        if current is None:
            raise PracticeNotFound("internal model review Tutor run was not found")
        return current, lease

    def create_or_replay_validation(
        self,
        *,
        run: ModelReviewAuthoringRunRecord,
        candidate: ModelReviewCandidateRecord,
        action_invocation_id: str,
    ) -> ModelReviewValidationRecord:
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_model_review_validation_runs
            WHERE candidate_id = %s AND validation_profile_version = %s
            """,
            (candidate.candidate_id, candidate.validation_profile_version),
        ).fetchone()
        if existing:
            return _validation(existing)
        row = self._conn.execute(
            """
            INSERT INTO tutor_model_review_validation_runs (
              authoring_run_id, candidate_id, user_id, track_id,
              validation_profile_version, candidate_hash, state, action_invocation_id
            ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s) RETURNING *
            """,
            (
                run.run_id, candidate.candidate_id, run.user_id, run.track_id,
                candidate.validation_profile_version, candidate.candidate_hash, action_invocation_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("model review validation insert failed")
        value = _validation(row)
        self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs
            SET validation_run_id = %s, state = 'validating'
            WHERE id = %s AND lease_generation = %s AND state = 'running'
            """,
            (value.validation_id, run.run_id, run.lease_generation),
        )
        self._conn.execute(
            "UPDATE tutor_model_review_candidates SET state = 'validating' WHERE id = %s AND state = 'draft'",
            (candidate.candidate_id,),
        )
        return value

    def read_validation(
        self, *, validation_id: str, user_id: str, for_update: bool = False
    ) -> ModelReviewValidationRecord:
        row = self._conn.execute(
            "SELECT * FROM tutor_model_review_validation_runs WHERE id = %s AND user_id = %s"
            + (" FOR UPDATE" if for_update else ""),
            (validation_id, user_id),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("model review validation was not found")
        return _validation(row)

    def create_or_replay_validation_job(
        self,
        *,
        validation: ModelReviewValidationRecord,
        invocation: ActionInvocation,
        candidate: ModelReviewCandidateRecord,
        now: datetime,
    ) -> ExecutionJobV1:
        existing = self._conn.execute(
            "SELECT * FROM tutor_execution_jobs WHERE model_review_validation_id = %s",
            (validation.validation_id,),
        ).fetchone()
        if existing:
            return _job(existing)
        runtime_id = _runtime_id(candidate.public_payload)
        execution = ExecutionIntentRepository(self._conn)
        availability = execution.availability_for_runtime(runtime_id, now=now)
        if not availability.available:
            raise ExecutionSubmissionError(availability.code)
        lock = execution._registry.lock_for(runtime_id)  # noqa: SLF001
        if lock is None:
            raise ExecutionSubmissionError("runtime_lock_unavailable")
        intent_id = str(uuid4())
        job_id = str(uuid4())
        run_authority = self._conn.execute(
            "SELECT catalog_digest, policy_fingerprint FROM tutor_runs WHERE id = %s AND user_id = %s",
            (invocation.run_id, validation.user_id),
        ).fetchone()
        if run_authority is None:
            raise PracticeNotFound("internal model review Tutor run was not found")
        self._conn.execute(
            """
            INSERT INTO tutor_execution_intents (
              id, user_id, conversation_id, run_id, source_message_id, exercise_id,
              input_revision, origin, action, catalog_digest, policy_fingerprint,
              budget_fingerprint, budget_execution_count, issued_at, expires_at,
              consumed_at, consumed_by_effect_id, source_kind,
              model_review_candidate_id, model_review_validation_id
            ) VALUES (
              %s, %s, %s, %s, NULL, NULL, %s, 'proactive', %s, %s, %s,
              %s, 1, %s, %s, %s, NULL, 'model_review_candidate', %s, %s
            )
            """,
            (
                intent_id, validation.user_id, invocation.conversation_id, invocation.run_id,
                invocation.input_revision, ExecutionAction.TEST.value, str(run_authority["catalog_digest"]),
                str(run_authority["policy_fingerprint"]), _reference_hash("model-review-validation-budget-v1"),
                now, now + timedelta(seconds=120), now,
                candidate.candidate_id, validation.validation_id,
            ),
        )
        row = self._conn.execute(
            """
            INSERT INTO tutor_execution_jobs (
              id, effect_record_id, effect_key, intent_id, user_id, conversation_id,
              run_id, runtime_id, lock_fingerprint, source_reference_hash,
              test_reference_hash, state, owner_kind, model_review_validation_id
            ) VALUES (
              %s, NULL, NULL, %s, %s, %s, %s, %s, %s, %s, %s,
              'pending', 'model_review_validation', %s
            ) RETURNING *
            """,
            (
                job_id, intent_id, validation.user_id, invocation.conversation_id, invocation.run_id,
                runtime_id, lock.fingerprint, _reference_hash(candidate.candidate_hash),
                _reference_hash(candidate.private_hash), validation.validation_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("model review execution job insert failed")
        self._conn.execute(
            "UPDATE tutor_model_review_validation_runs SET state = 'running' WHERE id = %s AND state = 'pending'",
            (validation.validation_id,),
        )
        return _job(row)

    def read_validation_job(self, *, validation_id: str, user_id: str) -> ExecutionJobV1 | None:
        row = self._conn.execute(
            "SELECT * FROM tutor_execution_jobs WHERE model_review_validation_id = %s AND user_id = %s",
            (validation_id, user_id),
        ).fetchone()
        return _job(row) if row else None


    def verify_terminal_job(
        self,
        *,
        validation: ModelReviewValidationRecord,
        candidate: ModelReviewCandidateRecord,
        job: ExecutionJobV1,
        now: datetime,
    ) -> tuple[str, str]:
        if validation.candidate_hash != candidate.candidate_hash:
            raise PracticeVersionConflict("model review validation candidate is stale")
        if job.state is not ExecutionJobState.COMPLETED or job.result is None or job.result.status.value != "success":
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        exercise, rubric = _candidate_material(candidate)
        if job.runtime_id != _runtime_id(candidate.public_payload):
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        template = validate_controlled_model_review_candidate(exercise=exercise, rubric=rubric)
        prompt = ModelReviewPromptV1.model_validate(dict(exercise.learner_prompt))
        artifact = ModelReviewArtifactV1.model_validate(dict(exercise.starter_artifact))
        private = ModelReviewRubricV1.model_validate(dict(rubric.reference_answer))
        coverage = model_review_template_coverage_proof(template=template, rubric=rubric)
        expected_outcomes = expected_model_review_test_outcomes(rubric)
        feedback = tuple(job.result.test_feedback)
        expected_passed_count = sum(expected_pass for _, expected_pass in expected_outcomes)
        if (
            len(feedback) != len(expected_outcomes)
            or job.result.total_test_count != len(expected_outcomes)
            or job.result.passed_test_count != expected_passed_count
        ):
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        observed_outcomes = tuple((item.visible, item.passed) for item in feedback)
        if observed_outcomes != expected_outcomes:
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        visible_feedback = tuple(item for item in feedback if item.visible)
        hidden_feedback = tuple(item for item in feedback if not item.visible)
        if not visible_feedback or not hidden_feedback:
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        redaction = model_review_public_redaction_proof(exercise)
        checks: dict[str, object] = {
            "schema": {
                "prompt_schema": prompt.schema_version,
                "artifact_schema": artifact.schema_version,
                "rubric_schema": private.schema_version,
                "candidate_hash": candidate.candidate_hash,
            },
            "parser": {
                "template_id": template.template_id,
                "template_contract_hash": template.contract_hash,
                "code_hash": artifact.code_hash,
                "line_count": artifact.line_count,
            },
            "compile_or_typecheck": {
                "job_id": job.job_id,
                "runtime_id": job.runtime_id,
                "status": job.result.status.value,
                "diagnostic_code": job.result.diagnostic_code,
            },
            "visible_tests": {
                "expected": tuple(item[1] for item in expected_outcomes if item[0]),
                "observed": tuple(item.passed for item in visible_feedback),
                "count": len(visible_feedback),
            },
            "hidden_tests": {
                "expected": tuple(item[1] for item in expected_outcomes if not item[0]),
                "observed": tuple(item.passed for item in hidden_feedback),
                "count": len(hidden_feedback),
            },
            "finding_reachability": {
                "finding_ranges": tuple(
                    tuple((line.start_line, line.end_line) for line in item.accepted_line_ranges)
                    for item in private.expected_findings
                ),
                "proof_ids": tuple(
                    proof_id
                    for item in private.expected_findings
                    for proof_id in item.reachability_proof_ids
                ),
                "line_count": artifact.line_count,
            },
            "rubric_consistency": {
                "template_id": private.template_id,
                "template_version": private.template_version,
                "template_contract_hash": private.template_contract_hash,
                "rubric_hash": rubric.rubric_hash,
            },
            "coverage": coverage,
            "redaction": redaction,
        }
        receipt = ModelReviewValidationReceiptV1.model_validate(
            {
                "candidate_hash": candidate.candidate_hash,
                "validation_profile_version": candidate.validation_profile_version,
                "checks": [
                    {
                        "check_type": check_type,
                        "status": "passed",
                        "proof_hash": canonical_hash(
                            {
                                "validation_id": validation.validation_id,
                                "check_type": check_type,
                                "evidence": evidence,
                            }
                        ),
                    }
                    for check_type, evidence in checks.items()
                ],
            }
        )
        for item in receipt.checks:
            self._conn.execute(
                """
                INSERT INTO tutor_model_review_validation_checks (
                  validation_run_id, user_id, check_type, status,
                  execution_job_id, proof_hash, safe_code
                ) VALUES (%s, %s, %s, %s, %s, %s, 'model_review_check_passed')
                ON CONFLICT (validation_run_id, check_type) DO NOTHING
                """,
                (
                    validation.validation_id, validation.user_id, item.check_type, item.status,
                    job.job_id if item.check_type in {"compile_or_typecheck", "visible_tests", "hidden_tests"} else None,
                    item.proof_hash,
                ),
            )
        authority_hash = canonical_hash(
            {
                "validation_id": validation.validation_id,
                "candidate_hash": candidate.candidate_hash,
                "receipt_hash": receipt.receipt_hash,
                "job_id": job.job_id,
                "job_result_hash": canonical_hash(job.result.model_dump(mode="json")),
                "template_contract_hash": template.contract_hash,
            }
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_model_review_validation_runs
            SET state = 'verified', authority_hash = %s,
                check_summary_code = 'all_checks_passed',
                safe_summary = 'Model review candidate passed controlled validation.',
                terminal_at = %s
            WHERE id = %s AND user_id = %s AND state IN ('pending', 'running')
            RETURNING id
            """,
            (authority_hash, now, validation.validation_id, validation.user_id),
        ).fetchone()
        if updated is None:
            current = self.read_validation(validation_id=validation.validation_id, user_id=validation.user_id)
            if current.state != "verified" or current.authority_hash != authority_hash:
                raise PracticeIdempotencyConflict("model review validation terminal result conflicts")
        self._conn.execute(
            "UPDATE tutor_model_review_candidates SET state = 'verified' WHERE id = %s AND state = 'validating'",
            (candidate.candidate_id,),
        )
        return authority_hash, receipt.receipt_hash

    def attach_action_receipt(self, *, validation_id: str, user_id: str, action_receipt_hash: str) -> None:
        self._conn.execute(
            """
            UPDATE tutor_model_review_validation_runs SET action_receipt_hash = %s
            WHERE id = %s AND user_id = %s AND state = 'verified' AND action_receipt_hash IS NULL
            """,
            (action_receipt_hash, validation_id, user_id),
        )

    def publish(
        self,
        *,
        run: ModelReviewAuthoringRunRecord,
        candidate: ModelReviewCandidateRecord,
        validation: ModelReviewValidationRecord,
        now: datetime,
    ) -> str:
        if validation.state != "verified" or validation.authority_hash is None:
            raise ModelReviewRepositoryError("MODEL_REVIEW_VALIDATION_FAILED")
        current = self._conn.execute(
            """
            SELECT tracks.version AS track_version, active.revision_id AS plan_revision_id,
                   progress.version AS progress_version, assignments.assignment_version,
                   assignments.status AS assignment_status
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON active.track_id = tracks.id AND active.user_id = tracks.user_id
            JOIN tutor_track_node_progress AS progress
              ON progress.track_id = tracks.id AND progress.user_id = tracks.user_id
             AND progress.knowledge_key = %s
            JOIN tutor_lesson_assignments AS assignments
              ON assignments.id = %s AND assignments.user_id = tracks.user_id
            WHERE tracks.id = %s AND tracks.user_id = %s
            FOR UPDATE OF tracks, progress, assignments
            """,
            (run.knowledge_key, run.lesson_assignment_id, run.track_id, run.user_id),
        ).fetchone()
        if (
            current is None
            or _int(current["track_version"]) != run.expected_track_version
            or str(current["plan_revision_id"]) != run.plan_revision_id
            or _int(current["progress_version"]) != run.expected_progress_version
            or _int(current["assignment_version"]) != run.expected_assignment_version
            or str(current["assignment_status"]) != "active"
        ):
            raise PracticeVersionConflict("model review publication scope is stale")
        public = dict(candidate.public_payload)
        private = dict(candidate.private_payload)
        exercise = ExerciseVersion(
            language_id=str(public["language_id"]),
            exercise_key=str(public["exercise_key"]),
            exercise_type=ExerciseType(str(public["exercise_type"])),
            version=str(public["version"]),
            source_kind=ExerciseSourceKind(str(public["source_kind"])),
            title=str(public["title"]),
            learner_prompt=_mapping(public.get("learner_prompt")),
            starter_artifact=_mapping(public.get("starter_artifact")),
            required_capabilities=tuple(str(item) for item in _sequence(public.get("required_capabilities"))),
            runtime_profile_id=str(public["runtime_profile_id"]) if public.get("runtime_profile_id") else None,
            execution_required=bool(public["execution_required"]),
            public_feedback_policy_version=str(public["public_feedback_policy_version"]),
        )
        rubric = ExercisePrivateRubric(
            rubric_version=str(private["rubric_version"]),
            private_test_bundle=tuple(_mapping(item) for item in _sequence(private.get("private_test_bundle"))),
            reference_answer=_mapping(private.get("reference_answer")),
            score_policy=_mapping(private.get("score_policy")),
        )
        if (
            exercise.language_id != run.language_id
            or exercise.required_capabilities != run.required_capabilities
            or exercise.exercise_type is not ExerciseType.MODEL_CODE_REVIEW
            or exercise.source_kind is not ExerciseSourceKind.REGISTERED_AUTHOR
            or publication_candidate_hash(exercise, rubric) != candidate.candidate_hash
            or rubric.rubric_hash != str(private.get("rubric_hash") or "")
        ):
            raise PracticeVersionConflict("model review publication candidate identity is stale")
        validate_controlled_model_review_candidate(exercise=exercise, rubric=rubric)
        checks = self._conn.execute(
            """
            SELECT check_type, status, proof_hash
            FROM tutor_model_review_validation_checks
            WHERE validation_run_id = %s AND user_id = %s ORDER BY check_type
            """,
            (validation.validation_id, run.user_id),
        ).fetchall()
        receipt = ModelReviewValidationReceiptV1.model_validate(
            {
                "candidate_hash": candidate.candidate_hash,
                "validation_profile_version": candidate.validation_profile_version,
                "checks": [dict(item) for item in checks],
            }
        )
        require_exercise_quality(exercise, rubric, model_review_validation=receipt)
        version_row = self._conn.execute(
            """
            INSERT INTO tutor_exercise_versions (
              language_id, exercise_key, exercise_type, version, source_kind, title,
              learner_prompt_json, starter_artifact_json, required_capabilities_json,
              runtime_profile_key, execution_required, public_feedback_policy_version,
              validation_status, content_hash, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                      NULL, false, %s, 'ready', %s, %s)
            ON CONFLICT (exercise_key, version) DO NOTHING RETURNING id
            """,
            (
                exercise.language_id, exercise.exercise_key, exercise.exercise_type.value,
                exercise.version, exercise.source_kind.value, exercise.title,
                _json(exercise.learner_prompt), _json(exercise.starter_artifact),
                _json(exercise.required_capabilities), exercise.public_feedback_policy_version,
                exercise.content_hash, now,
            ),
        ).fetchone()
        if version_row is None:
            version_row = self._conn.execute(
                "SELECT id, content_hash FROM tutor_exercise_versions WHERE exercise_key = %s AND version = %s",
                (exercise.exercise_key, exercise.version),
            ).fetchone()
            if version_row is None or str(version_row["content_hash"]) != exercise.content_hash:
                raise PracticeIdempotencyConflict("model review exercise publication conflicts")
        exercise_version_id = str(version_row["id"])
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_private_rubrics (
              exercise_version_id, rubric_version, private_test_bundle_json,
              reference_answer_json, score_policy_json, rubric_hash, published_at
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (exercise_version_id) DO NOTHING
            """,
            (
                exercise_version_id, rubric.rubric_version, _json(rubric.private_test_bundle),
                _json(rubric.reference_answer), _json(rubric.score_policy), rubric.rubric_hash, now,
            ),
        )
        slot = self._conn.execute("SELECT * FROM tutor_lesson_gate_slots WHERE id = %s FOR UPDATE", (run.slot_id,)).fetchone()
        if slot is None:
            raise PracticeNotFound("model review Gate slot was not found")
        slot_hash = canonical_hash(
            {
                "gate_kind": str(slot["gate_kind"]),
                "assessment_contract_version": str(slot["assessment_contract_version"]),
                "required_capabilities": _string_list(slot.get("required_capabilities_json")),
                "learner_prompt_hash": str(slot["learner_prompt_hash"]),
            }
        )
        binding = LessonGateBinding(
            gate_key=run.gate_key,
            exercise_key=exercise.exercise_key,
            exercise_version=exercise.version,
            requirement_kind=_requirement_kind(str(slot["gate_kind"])),
            pass_policy_version=MODEL_REVIEW_PASS_POLICY_VERSION,
            pass_threshold=_float(rubric.score_policy.get("threshold") or 0.8),
            execution_requirement=ExecutionRequirement.FORBIDDEN,
            slot_contract_hash=slot_hash,
        )
        binding_row = self._conn.execute(
            """
            INSERT INTO tutor_lesson_gate_bindings (
              slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
              exercise_version_id, requirement_kind, pass_policy_version,
              pass_threshold, execution_requirement, slot_contract_hash,
              binding_contract_hash, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (document_id, gate_key) DO NOTHING RETURNING id
            """,
            (
                run.slot_id, run.document_id, run.user_id, run.track_id, run.knowledge_key,
                run.gate_key, exercise_version_id, binding.requirement_kind.value,
                binding.pass_policy_version, binding.pass_threshold,
                binding.execution_requirement.value, binding.slot_contract_hash,
                binding.binding_contract_hash, now,
            ),
        ).fetchone()
        if binding_row is None:
            binding_row = self._conn.execute(
                "SELECT id, binding_contract_hash FROM tutor_lesson_gate_bindings WHERE document_id = %s AND gate_key = %s",
                (run.document_id, run.gate_key),
            ).fetchone()
            if binding_row is None or str(binding_row["binding_contract_hash"]) != binding.binding_contract_hash:
                raise PracticeIdempotencyConflict("model review Gate binding conflicts")
        gate_binding_id = str(binding_row["id"])
        self._conn.execute(
            """
            INSERT INTO tutor_lesson_gate_states (
              user_id, track_id, knowledge_key, lesson_assignment_id,
              document_id, gate_binding_id, state
            ) VALUES (%s, %s, %s, %s, %s, %s, 'available')
            ON CONFLICT (lesson_assignment_id, gate_binding_id) DO NOTHING
            """,
            (run.user_id, run.track_id, run.knowledge_key, run.lesson_assignment_id, run.document_id, gate_binding_id),
        )
        publication = self._conn.execute(
            """
            INSERT INTO tutor_model_review_publications (
              authoring_run_id, candidate_id, validation_run_id, user_id, track_id,
              knowledge_key, lesson_assignment_id, gate_binding_id,
              exercise_version_id, validation_authority_hash, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (candidate_id) DO NOTHING RETURNING id
            """,
            (
                run.run_id, candidate.candidate_id, validation.validation_id, run.user_id,
                run.track_id, run.knowledge_key, run.lesson_assignment_id, gate_binding_id,
                exercise_version_id, validation.authority_hash, now,
            ),
        ).fetchone()
        if publication is None:
            publication = self._conn.execute(
                "SELECT id FROM tutor_model_review_publications WHERE candidate_id = %s",
                (candidate.candidate_id,),
            ).fetchone()
        if publication is None:
            raise RuntimeError("model review publication insert failed")
        self._conn.execute(
            "UPDATE tutor_model_review_candidates SET state = 'published' WHERE id = %s AND state = 'verified'",
            (candidate.candidate_id,),
        )
        self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs
            SET state = 'completed', publication_id = %s, terminal_at = %s,
                lease_owner_id = NULL, lease_expires_at = NULL
            WHERE id = %s AND state = 'validating'
            """,
            (publication["id"], now, run.run_id),
        )
        self.finish_internal_run(run_id=run.internal_run_id, user_id=run.user_id, outcome="completed", code=None, now=now)
        return str(publication["id"])

    def fail(self, *, run_id: str, code: str, message: str, now: datetime) -> None:
        row = self._conn.execute(
            """
            UPDATE tutor_model_review_authoring_runs
            SET state = 'failed', failure_code = %s, failure_message = %s,
                terminal_at = %s, lease_owner_id = NULL, lease_expires_at = NULL
            WHERE id = %s AND state NOT IN ('completed', 'failed', 'cancelled')
            RETURNING user_id, internal_run_id, candidate_id, validation_run_id
            """,
            (code, message[:320], now, run_id),
        ).fetchone()
        if row is None:
            return
        if row.get("candidate_id"):
            self._conn.execute(
                "UPDATE tutor_model_review_candidates SET state = 'rejected' WHERE id = %s AND state IN ('draft', 'validating', 'verified')",
                (row["candidate_id"],),
            )
        if row.get("validation_run_id"):
            self._conn.execute(
                """
                UPDATE tutor_model_review_validation_runs
                SET state = 'failed', failure_code = %s, safe_summary = %s, terminal_at = %s
                WHERE id = %s AND state IN ('pending', 'running')
                """,
                (code, message[:320], now, row["validation_run_id"]),
            )
        self.finish_internal_run(
            run_id=str(row["internal_run_id"]) if row.get("internal_run_id") else None,
            user_id=str(row["user_id"]), outcome="failed", code=code.lower(), now=now,
        )

    def append_learner_evidence(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        expected_gate_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT states.id AS gate_state_id, states.version AS gate_version,
                   states.lesson_assignment_id, states.gate_binding_id,
                   publications.id AS publication_id
            FROM tutor_lesson_gate_states AS states
            JOIN tutor_lesson_gate_bindings AS bindings ON bindings.id = states.gate_binding_id
            JOIN tutor_exercise_versions AS versions ON versions.id = bindings.exercise_version_id
            JOIN tutor_model_review_publications AS publications
              ON publications.user_id = states.user_id
             AND publications.lesson_assignment_id = states.lesson_assignment_id
             AND publications.gate_binding_id = states.gate_binding_id
            WHERE states.user_id = %s AND states.track_id = %s AND states.knowledge_key = %s
              AND bindings.gate_key = %s AND versions.exercise_type = 'model_code_review'
            FOR UPDATE OF states
            """,
            (user_id, track_id, knowledge_key, gate_key),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("model review evidence was not found")
        if _int(row["gate_version"]) != expected_gate_version:
            raise PracticeVersionConflict("model review evidence Gate version changed")
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_model_review_evidence_receipts
            WHERE user_id = %s AND gate_binding_id = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (user_id, row["gate_binding_id"], idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise PracticeIdempotencyConflict("model review evidence idempotency key conflicts")
            result = dict(existing)
            result["gate_version"] = expected_gate_version
            result["idempotent_replayed"] = True
            return result
        evidence = self.learner_safe_evidence(
            publication_id=str(row["publication_id"]), user_id=user_id
        )
        evidence_hash = canonical_hash(evidence)
        receipt = self._conn.execute(
            """
            INSERT INTO tutor_model_review_evidence_receipts (
              publication_id, user_id, lesson_assignment_id, gate_binding_id,
              idempotency_key, request_hash, evidence_json, evidence_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                row["publication_id"], user_id, row["lesson_assignment_id"],
                row["gate_binding_id"], idempotency_key, request_hash,
                _json(evidence), evidence_hash, now,
            ),
        ).fetchone()
        updated = self._conn.execute(
            """
            UPDATE tutor_lesson_gate_states SET version = version + 1
            WHERE id = %s AND version = %s RETURNING version
            """,
            (row["gate_state_id"], expected_gate_version),
        ).fetchone()
        if receipt is None or updated is None:
            raise PracticeVersionConflict("model review evidence Gate state changed")
        result = dict(receipt)
        result["gate_version"] = _int(updated["version"])
        result["idempotent_replayed"] = False
        return result

    def learner_safe_evidence(self, *, publication_id: str, user_id: str) -> dict[str, object]:
        rows = self._conn.execute(
            """
            SELECT checks.check_type, checks.status, checks.safe_code
            FROM tutor_model_review_publications AS publications
            JOIN tutor_model_review_validation_checks AS checks
              ON checks.validation_run_id = publications.validation_run_id
             AND checks.user_id = publications.user_id
            WHERE publications.id = %s AND publications.user_id = %s
            ORDER BY checks.check_type
            """,
            (publication_id, user_id),
        ).fetchall()
        if not rows:
            raise PracticeNotFound("model review evidence was not found")
        visible = [
            {
                "check_type": str(row["check_type"]),
                "status": str(row["status"]),
                "safe_code": str(row["safe_code"]),
            }
            for row in rows
            if str(row["check_type"])
            in {"parser", "compile_or_typecheck", "visible_tests", "hidden_tests", "coverage"}
        ]
        return {
            "schema_version": "model_code_review_visible_evidence_v1",
            "execution_claim": "prepublication_only",
            "checks": visible,
        }

    def finish_internal_run(
        self,
        *,
        run_id: str | None,
        user_id: str,
        outcome: Literal["completed", "failed"],
        code: str | None,
        now: datetime,
    ) -> None:
        if run_id is None:
            return
        self._conn.execute(
            """
            UPDATE tutor_runs
            SET status = %s, terminal_outcome = %s, terminal_diagnostic_code = %s,
                terminal_at = %s, active_lease_owner_id = NULL, active_lease_expires_at = NULL
            WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
            """,
            (outcome, outcome, code, now, run_id, user_id),
        )
        self._conn.execute(
            """
            UPDATE tutor_conversations SET status = 'closed'
            WHERE id = (SELECT conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s)
            """,
            (run_id, user_id),
        )


def _authoring(row: Mapping[str, object]) -> ModelReviewAuthoringRunRecord:
    return ModelReviewAuthoringRunRecord(
        run_id=str(row["id"]), user_id=str(row["user_id"]), track_id=str(row["track_id"]),
        knowledge_key=str(row["knowledge_key"]), plan_revision_id=str(row["plan_revision_id"]),
        lesson_assignment_id=str(row["lesson_assignment_id"]), document_id=str(row["document_id"]),
        slot_id=str(row["slot_id"]), gate_key=str(row["gate_key"]),
        expected_track_version=_int(row["expected_track_version"]),
        expected_progress_version=_int(row["expected_progress_version"]),
        expected_assignment_version=_int(row["expected_assignment_version"]),
        language_id=str(row["language_id"]),
        required_capabilities=tuple(_string_list(row.get("required_capabilities_json"))),
        mastery_level=str(row["mastery_level"]), mastery_confidence=_float(row["mastery_confidence"]),
        validation_profile_version=str(row["validation_profile_version"]), request_hash=str(row["request_hash"]),
        state=str(row["state"]), attempt_count=_int(row.get("attempt_count")),
        lease_generation=_int(row.get("lease_generation")),
        internal_conversation_id=str(row["internal_conversation_id"]) if row.get("internal_conversation_id") else None,
        internal_run_id=str(row["internal_run_id"]) if row.get("internal_run_id") else None,
        candidate_id=str(row["candidate_id"]) if row.get("candidate_id") else None,
        validation_run_id=str(row["validation_run_id"]) if row.get("validation_run_id") else None,
        publication_id=str(row["publication_id"]) if row.get("publication_id") else None,
        failure_code=str(row["failure_code"]) if row.get("failure_code") else None,
        failure_message=str(row["failure_message"]) if row.get("failure_message") else None,
    )


def _candidate(row: Mapping[str, object]) -> ModelReviewCandidateRecord:
    return ModelReviewCandidateRecord(
        candidate_id=str(row["id"]), authoring_run_id=str(row["authoring_run_id"]),
        user_id=str(row["user_id"]), track_id=str(row["track_id"]), knowledge_key=str(row["knowledge_key"]),
        public_payload=_mapping(row.get("public_payload_json")), private_payload=_mapping(row.get("private_payload_json")),
        public_hash=str(row["public_hash"]), private_hash=str(row["private_hash"]),
        candidate_hash=str(row["candidate_hash"]), validation_profile_version=str(row["validation_profile_version"]),
        state=str(row["state"]),
    )


def _validation(row: Mapping[str, object]) -> ModelReviewValidationRecord:
    return ModelReviewValidationRecord(
        validation_id=str(row["id"]), authoring_run_id=str(row["authoring_run_id"]),
        candidate_id=str(row["candidate_id"]), user_id=str(row["user_id"]), track_id=str(row["track_id"]),
        validation_profile_version=str(row["validation_profile_version"]), candidate_hash=str(row["candidate_hash"]),
        state=str(row["state"]), action_invocation_id=str(row["action_invocation_id"]) if row.get("action_invocation_id") else None,
        authority_hash=str(row["authority_hash"]) if row.get("authority_hash") else None,
        action_receipt_hash=str(row["action_receipt_hash"]) if row.get("action_receipt_hash") else None,
    )


def _job(row: Mapping[str, object]) -> ExecutionJobV1:
    raw_owner = str(row.get("owner_kind") or "tutor_effect")
    owner_kind: Literal["tutor_effect", "exercise_attempt", "model_review_validation"] = (
        "exercise_attempt" if raw_owner == "exercise_attempt"
        else "model_review_validation" if raw_owner == "model_review_validation"
        else "tutor_effect"
    )
    raw_result = row.get("result_json")
    return ExecutionJobV1(
        job_id=str(row["id"]), intent_proof_id=str(row["intent_id"]), user_id=str(row["user_id"]),
        runtime_id=str(row["runtime_id"]), lock_fingerprint=str(row["lock_fingerprint"]),
        state=ExecutionJobState(str(row["state"])), owner_kind=owner_kind,
        effect_id=str(row["effect_key"]) if row.get("effect_key") else None,
        conversation_id=str(row["conversation_id"]) if row.get("conversation_id") else None,
        run_id=str(row["run_id"]) if row.get("run_id") else None,
        exercise_attempt_id=str(row["exercise_attempt_id"]) if row.get("exercise_attempt_id") else None,
        model_review_validation_id=str(row["model_review_validation_id"]) if row.get("model_review_validation_id") else None,
        lease_owner_id=str(row["lease_owner_id"]) if row.get("lease_owner_id") else None,
        lease_generation=_int(row.get("lease_generation")),
        lease_expires_at=_datetime(row.get("lease_expires_at")),
        launch_token=str(row["launch_token"]) if row.get("launch_token") else None,
        launch_generation=_int(row.get("launch_generation")),
        cancellation_requested_at=_datetime(row.get("cancellation_requested_at")),
        result=SafeExecutionResultV1.model_validate(raw_result) if isinstance(raw_result, Mapping) else None,
        safe_diagnostic_code=str(row["safe_diagnostic_code"]) if row.get("safe_diagnostic_code") else None,
    )


def _candidate_material(
    candidate: ModelReviewCandidateRecord,
) -> tuple[ExerciseVersion, ExercisePrivateRubric]:
    public = dict(candidate.public_payload)
    private = dict(candidate.private_payload)
    exercise = ExerciseVersion(
        language_id=str(public["language_id"]),
        exercise_key=str(public["exercise_key"]),
        exercise_type=ExerciseType(str(public["exercise_type"])),
        version=str(public["version"]),
        source_kind=ExerciseSourceKind(str(public["source_kind"])),
        title=str(public["title"]),
        learner_prompt=_mapping(public.get("learner_prompt")),
        starter_artifact=_mapping(public.get("starter_artifact")),
        required_capabilities=tuple(str(item) for item in _sequence(public.get("required_capabilities"))),
        runtime_profile_id=str(public["runtime_profile_id"]) if public.get("runtime_profile_id") else None,
        execution_required=bool(public["execution_required"]),
        public_feedback_policy_version=str(public["public_feedback_policy_version"]),
    )
    rubric = ExercisePrivateRubric(
        rubric_version=str(private["rubric_version"]),
        private_test_bundle=tuple(_mapping(item) for item in _sequence(private.get("private_test_bundle"))),
        reference_answer=_mapping(private.get("reference_answer")),
        score_policy=_mapping(private.get("score_policy")),
    )
    if (
        exercise.content_hash != str(public.get("content_hash") or exercise.content_hash)
        or rubric.rubric_hash != str(private.get("rubric_hash") or "")
        or publication_candidate_hash(exercise, rubric) != candidate.candidate_hash
    ):
        raise PracticeVersionConflict("model review candidate material is stale")
    return exercise, rubric


def _runtime_id(public_payload: Mapping[str, object]) -> str:
    language = str(_mapping(public_payload.get("starter_artifact")).get("language_id") or "").lower()
    value = {"python": "python-stdout-v1", "javascript": "node-typescript-v1", "typescript": "node-typescript-v1", "sql": "sqlite-query-v1"}.get(language)
    if value is None:
        raise ExecutionSubmissionError("trusted_runtime_unsupported")
    return value


def _mapping(value: object) -> dict[str, object]:
    return {str(key): item for key, item in value.items()} if isinstance(value, Mapping) else {}


def _sequence(value: object) -> Sequence[object]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


def _reference_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _datetime(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
