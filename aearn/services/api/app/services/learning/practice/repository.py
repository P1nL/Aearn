"""PostgreSQL authority for Lesson Gate exercises and append-only Attempts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import (
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
)
from app.services.learning.practice.contracts import (
    ExecutionRequirement,
    ExerciseAttemptResult,
    ExerciseAttemptType,
    ExerciseType,
    GateRequirementKind,
    LessonGateBinding,
    canonical_hash,
    canonical_submission_hash,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture, fixture_for_language
from app.services.learning.practice.policies import GATE_PASS_POLICY_VERSION, HINT_POLICY_VERSION
from app.services.learning.track_repository import PostgresLearningTrackRepository


class PracticeRepositoryError(ValueError):
    pass


class PracticeNotFound(PracticeRepositoryError):
    pass


class PracticeNotReady(PracticeRepositoryError):
    pass


class PracticeVersionConflict(PracticeRepositoryError):
    pass


class PracticeIdempotencyConflict(PracticeRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class GateScope:
    user_id: str
    track_id: str
    language_id: str
    track_version: int
    plan_revision_id: str
    knowledge_key: str
    progress_status: str
    progress_version: int
    assignment_id: str
    assignment_version: int
    assignment_started_at: datetime | None
    document_id: str


class PostgresExerciseGateRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def read_scope(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        for_update: bool = False,
    ) -> GateScope:
        lock = " FOR UPDATE OF tracks, progress, assignments" if for_update else ""
        row = self._conn.execute(
            """
            SELECT tracks.id AS track_id, tracks.user_id, tracks.language_id,
                   tracks.version AS track_version, active.revision_id AS plan_revision_id,
                   progress.status AS progress_status, progress.version AS progress_version,
                   assignments.id AS assignment_id, assignments.assignment_version,
                   assignments.started_at AS assignment_started_at,
                   assignments.document_id
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id) = (tracks.id, tracks.user_id)
             AND progress.knowledge_key = %s
            JOIN tutor_lesson_assignments AS assignments
              ON (assignments.track_id, assignments.user_id, assignments.knowledge_key) =
                 (tracks.id, tracks.user_id, progress.knowledge_key)
             AND assignments.status = 'active'
            WHERE tracks.id = %s AND tracks.user_id = %s
            """ + lock,
            (knowledge_key, track_id, user_id),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("Lesson Gate scope was not found")
        return GateScope(
            user_id=str(row["user_id"]),
            track_id=str(row["track_id"]),
            language_id=str(row["language_id"]),
            track_version=_int(row["track_version"]),
            plan_revision_id=str(row["plan_revision_id"]),
            knowledge_key=knowledge_key,
            progress_status=str(row["progress_status"]),
            progress_version=_int(row["progress_version"]),
            assignment_id=str(row["assignment_id"]),
            assignment_version=_int(row["assignment_version"]),
            assignment_started_at=_datetime_or_none(row.get("assignment_started_at")),
            document_id=str(row["document_id"]),
        )

    def ensure_curated_fixture(self, fixture: CuratedExerciseFixture, *, now: datetime) -> str:
        exercise = fixture.exercise
        row = self._conn.execute(
            """
            INSERT INTO tutor_exercise_versions (
              language_id, exercise_key, exercise_type, version, source_kind, title,
              learner_prompt_json, starter_artifact_json, required_capabilities_json,
              runtime_profile_key, execution_required, public_feedback_policy_version,
              validation_status, content_hash, published_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb,
                      %s, %s, %s, %s, %s, %s)
            ON CONFLICT (exercise_key, version) DO NOTHING
            RETURNING id
            """,
            (
                exercise.language_id,
                exercise.exercise_key,
                exercise.exercise_type.value,
                exercise.version,
                exercise.source_kind.value,
                exercise.title,
                _json(exercise.learner_prompt),
                _json(exercise.starter_artifact),
                _json(list(exercise.required_capabilities)),
                exercise.runtime_profile_id,
                exercise.execution_required,
                exercise.public_feedback_policy_version,
                exercise.validation_status.value,
                exercise.content_hash,
                now,
            ),
        ).fetchone()
        if row is None:
            row = self._conn.execute(
                "SELECT id, content_hash FROM tutor_exercise_versions WHERE exercise_key = %s AND version = %s",
                (exercise.exercise_key, exercise.version),
            ).fetchone()
            if row is None or str(row["content_hash"]) != exercise.content_hash:
                raise PracticeIdempotencyConflict("curated exercise identity conflicts with stored content")
        exercise_version_id = str(row["id"])
        rubric = fixture.rubric
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_exercise_private_rubrics (
              exercise_version_id, rubric_version, private_test_bundle_json,
              reference_answer_json, score_policy_json, rubric_hash, published_at
            ) VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
            ON CONFLICT (exercise_version_id) DO NOTHING
            RETURNING id
            """,
            (
                exercise_version_id,
                rubric.rubric_version,
                _json([dict(item) for item in rubric.private_test_bundle]),
                _json(rubric.reference_answer),
                _json(rubric.score_policy),
                rubric.rubric_hash,
                now,
            ),
        ).fetchone()
        if inserted is None:
            stored = self._conn.execute(
                "SELECT rubric_hash FROM tutor_exercise_private_rubrics WHERE exercise_version_id = %s",
                (exercise_version_id,),
            ).fetchone()
            if stored is None or str(stored["rubric_hash"]) != rubric.rubric_hash:
                raise PracticeIdempotencyConflict("curated rubric identity conflicts with stored content")
        return exercise_version_id

    def prepare_gates(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        expected_track_version: int,
        expected_progress_version: int,
        now: datetime,
    ) -> tuple[dict[str, object], ...]:
        scope = self.read_scope(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            for_update=True,
        )
        if scope.progress_status == "locked":
            raise PracticeNotReady("Lesson is locked")
        if scope.track_version != expected_track_version or scope.progress_version != expected_progress_version:
            raise PracticeVersionConflict("LearningTrack or progress changed")
        fixture = fixture_for_language(scope.language_id)
        if fixture is None:
            return ()
        exercise_version_id = self.ensure_curated_fixture(fixture, now=now)
        slots = self._conn.execute(
            "SELECT * FROM tutor_lesson_gate_slots WHERE document_id = %s ORDER BY block_id, gate_key",
            (scope.document_id,),
        ).fetchall()
        for slot in slots:
            slot_hash = canonical_hash(
                {
                    "gate_kind": str(slot["gate_kind"]),
                    "assessment_contract_version": str(slot["assessment_contract_version"]),
                    "required_capabilities": _string_list(slot.get("required_capabilities_json")),
                    "learner_prompt_hash": str(slot["learner_prompt_hash"]),
                }
            )
            binding = LessonGateBinding(
                gate_key=str(slot["gate_key"]),
                exercise_key=fixture.exercise.exercise_key,
                exercise_version=fixture.exercise.version,
                requirement_kind=_requirement_kind(str(slot["gate_kind"])),
                pass_policy_version=GATE_PASS_POLICY_VERSION,
                pass_threshold=0.8,
                execution_requirement=ExecutionRequirement.REQUIRED,
                slot_contract_hash=slot_hash,
            )
            inserted = self._conn.execute(
                """
                INSERT INTO tutor_lesson_gate_bindings (
                  slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
                  exercise_version_id, requirement_kind, pass_policy_version,
                  pass_threshold, execution_requirement, slot_contract_hash,
                  binding_contract_hash, published_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id, gate_key) DO NOTHING
                RETURNING id
                """,
                (
                    slot["id"],
                    scope.document_id,
                    user_id,
                    track_id,
                    knowledge_key,
                    binding.gate_key,
                    exercise_version_id,
                    binding.requirement_kind.value,
                    binding.pass_policy_version,
                    binding.pass_threshold,
                    binding.execution_requirement.value,
                    binding.slot_contract_hash,
                    binding.binding_contract_hash,
                    now,
                ),
            ).fetchone()
            if inserted is None:
                inserted = self._conn.execute(
                    """
                    SELECT id, binding_contract_hash FROM tutor_lesson_gate_bindings
                    WHERE document_id = %s AND gate_key = %s
                    """,
                    (scope.document_id, binding.gate_key),
                ).fetchone()
                if inserted is None or str(inserted["binding_contract_hash"]) != binding.binding_contract_hash:
                    raise PracticeIdempotencyConflict("Lesson Gate binding conflicts with frozen authority")
            self._conn.execute(
                """
                INSERT INTO tutor_lesson_gate_states (
                  user_id, track_id, knowledge_key, lesson_assignment_id,
                  document_id, gate_binding_id, state
                ) VALUES (%s, %s, %s, %s, %s, %s, 'available')
                ON CONFLICT (lesson_assignment_id, gate_binding_id) DO NOTHING
                """,
                (user_id, track_id, knowledge_key, scope.assignment_id, scope.document_id, inserted["id"]),
            )
        return self.read_gates(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key)

    def read_gates(self, *, user_id: str, track_id: str, knowledge_key: str) -> tuple[dict[str, object], ...]:
        scope = self.read_scope(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key)
        rows = self._conn.execute(
            """
            SELECT assignments.id AS assignment_id, assignments.user_id,
                   slots.gate_key, slots.gate_kind, slots.assessment_contract_version,
                   slots.required_capabilities_json AS slot_capabilities_json,
                   slots.learner_prompt,
                   bindings.id AS binding_id, bindings.requirement_kind,
                   bindings.pass_policy_version, bindings.pass_threshold,
                   bindings.execution_requirement, bindings.binding_contract_hash,
                   versions.id AS exercise_version_id, versions.language_id,
                   versions.exercise_key, versions.exercise_type, versions.version AS exercise_version,
                   versions.title AS exercise_title, versions.learner_prompt_json,
                   versions.starter_artifact_json, versions.required_capabilities_json,
                   versions.runtime_profile_key, versions.execution_required,
                   versions.content_hash AS exercise_content_hash,
                   states.id AS gate_state_id, states.state AS gate_state,
                   states.attempt_count, states.best_score, states.latest_attempt_id,
                   states.passing_attempt_id, states.version AS gate_version, states.passed_at,
                   attempts.attempt_type AS latest_attempt_type,
                   attempts.submission_hash AS latest_submission_hash,
                   results.outcome AS latest_outcome, results.score AS latest_score,
                   results.safe_feedback_json AS latest_safe_feedback_json,
                   results.terminal_at AS latest_terminal_at
            FROM tutor_lesson_assignments AS assignments
            JOIN tutor_lesson_gate_slots AS slots ON slots.document_id = assignments.document_id
            LEFT JOIN tutor_lesson_gate_bindings AS bindings
              ON (bindings.document_id, bindings.gate_key) = (slots.document_id, slots.gate_key)
            LEFT JOIN tutor_exercise_versions AS versions ON versions.id = bindings.exercise_version_id
            LEFT JOIN tutor_lesson_gate_states AS states
              ON states.lesson_assignment_id = assignments.id AND states.gate_binding_id = bindings.id
            LEFT JOIN tutor_exercise_attempts AS attempts ON attempts.id = states.latest_attempt_id
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE assignments.id = %s AND assignments.status = 'active'
            ORDER BY slots.block_id, slots.gate_key
            """,
            (scope.assignment_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def read_gate(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        for_update: bool = False,
    ) -> dict[str, object]:
        lock = " FOR UPDATE OF tracks, progress, assignments, states" if for_update else ""
        row = self._conn.execute(
            """
            SELECT tracks.version AS track_version, active.revision_id AS plan_revision_id,
                   progress.status AS progress_status, progress.version AS progress_version,
                   assignments.id AS assignment_id, assignments.assignment_version,
                   assignments.started_at AS assignment_started_at,
                   assignments.document_id, slots.gate_key, slots.gate_kind,
                   slots.assessment_contract_version, slots.required_capabilities_json AS slot_capabilities_json,
                   slots.learner_prompt, bindings.id AS binding_id, bindings.requirement_kind,
                   bindings.pass_policy_version, bindings.pass_threshold,
                   bindings.execution_requirement, bindings.binding_contract_hash,
                   versions.id AS exercise_version_id, versions.language_id,
                   versions.exercise_key, versions.exercise_type, versions.version AS exercise_version,
                   versions.title AS exercise_title, versions.learner_prompt_json,
                   versions.starter_artifact_json, versions.required_capabilities_json,
                   versions.runtime_profile_key, versions.execution_required,
                   versions.content_hash AS exercise_content_hash,
                   states.id AS gate_state_id, states.state AS gate_state,
                   states.attempt_count, states.best_score, states.latest_attempt_id,
                   states.passing_attempt_id, states.version AS gate_version, states.passed_at
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id) = (tracks.id, tracks.user_id)
             AND progress.knowledge_key = %s
            JOIN tutor_lesson_assignments AS assignments
              ON (assignments.track_id, assignments.user_id, assignments.knowledge_key) =
                 (tracks.id, tracks.user_id, progress.knowledge_key)
             AND assignments.status = 'active'
            JOIN tutor_lesson_gate_slots AS slots ON slots.document_id = assignments.document_id
            JOIN tutor_lesson_gate_bindings AS bindings
              ON (bindings.document_id, bindings.gate_key) = (slots.document_id, slots.gate_key)
            JOIN tutor_exercise_versions AS versions ON versions.id = bindings.exercise_version_id
            JOIN tutor_lesson_gate_states AS states
              ON states.lesson_assignment_id = assignments.id AND states.gate_binding_id = bindings.id
            WHERE tracks.id = %s AND tracks.user_id = %s AND slots.gate_key = %s
            """ + lock,
            (knowledge_key, track_id, user_id, gate_key),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("Lesson Gate was not found")
        return dict(row)

    def append_hint(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        expected_gate_version: int,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object]:
        gate = self.read_gate(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            for_update=True,
        )
        if _int(gate["gate_version"]) != expected_gate_version:
            raise PracticeVersionConflict("Lesson Gate version changed")
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_exercise_hint_receipts
            WHERE user_id = %s AND lesson_assignment_id = %s
              AND gate_binding_id = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (user_id, gate["assignment_id"], gate["binding_id"], idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise PracticeIdempotencyConflict("hint idempotency key conflicts with stored request")
            replay = dict(existing)
            replay["idempotent_replayed"] = True
            return replay
        count_row = self._conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_exercise_hint_receipts
            WHERE user_id = %s AND lesson_assignment_id = %s AND gate_binding_id = %s
            """,
            (user_id, gate["assignment_id"], gate["binding_id"]),
        ).fetchone()
        level = min(3, _int(count_row["count"] if count_row else 0) + 1)
        hint = _safe_hint(level=level, gate=gate)
        row = self._conn.execute(
            """
            INSERT INTO tutor_exercise_hint_receipts (
              user_id, track_id, knowledge_key, lesson_assignment_id,
              gate_binding_id, hint_level, hint_policy_version, safe_hint_json,
              idempotency_key, request_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                track_id,
                knowledge_key,
                gate["assignment_id"],
                gate["binding_id"],
                level,
                HINT_POLICY_VERSION,
                _json(hint),
                idempotency_key,
                request_hash,
            ),
        ).fetchone()
        updated = self._conn.execute(
            """
            UPDATE tutor_lesson_gate_states SET version = version + 1
            WHERE id = %s AND version = %s RETURNING version
            """,
            (gate["gate_state_id"], expected_gate_version),
        ).fetchone()
        if row is None or updated is None:
            raise PracticeVersionConflict("Lesson Gate hint state changed")
        result = dict(row)
        result["gate_version"] = _int(updated["version"])
        result["idempotent_replayed"] = False
        return result

    def create_gate_attempt(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
        gate_key: str,
        attempt_type: ExerciseAttemptType,
        submission: str,
        expected_track_version: int,
        expected_progress_version: int,
        expected_assignment_version: int,
        expected_gate_version: int,
        idempotency_key: str,
        request_hash: str,
        now: datetime,
    ) -> dict[str, object]:
        if attempt_type not in {ExerciseAttemptType.RUN, ExerciseAttemptType.SUBMIT}:
            raise PracticeRepositoryError("Gate Attempt type is invalid")
        gate = self.read_gate(
            user_id=user_id,
            track_id=track_id,
            knowledge_key=knowledge_key,
            gate_key=gate_key,
            for_update=True,
        )
        if str(gate["progress_status"]) == "locked" or gate.get("assignment_started_at") is None:
            raise PracticeNotReady("Lesson must be started before attempting a Gate")
        if (
            _int(gate["track_version"]) != expected_track_version
            or _int(gate["progress_version"]) != expected_progress_version
            or _int(gate["assignment_version"]) != expected_assignment_version
            or _int(gate["gate_version"]) != expected_gate_version
        ):
            raise PracticeVersionConflict("Gate Attempt scope version changed")
        if str(gate["gate_state"]) == "passed":
            raise PracticeNotReady("Passed Gate does not accept new Attempts")
        normalized = str(submission).replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip() or len(normalized) > 48_000:
            raise PracticeRepositoryError("submission must contain 1..48000 characters")
        existing = self._conn.execute(
            """
            SELECT attempts.*, submissions.id AS submission_id
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions ON submissions.attempt_id = attempts.id
            WHERE attempts.user_id = %s AND attempts.attempt_type = %s AND attempts.idempotency_key = %s
            FOR UPDATE OF attempts
            """,
            (user_id, attempt_type.value, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise PracticeIdempotencyConflict("Attempt idempotency key conflicts with stored request")
            replay = dict(existing)
            replay["idempotent_replayed"] = True
            return replay
        hint_row = self._conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_exercise_hint_receipts
            WHERE user_id = %s AND lesson_assignment_id = %s AND gate_binding_id = %s
            """,
            (user_id, gate["assignment_id"], gate["binding_id"]),
        ).fetchone()
        hint_count = _int(hint_row["count"] if hint_row else 0)
        evidence_row = self._conn.execute(
            """
            SELECT count(*)::int AS count FROM tutor_model_review_evidence_receipts
            WHERE user_id = %s AND lesson_assignment_id = %s AND gate_binding_id = %s
            """,
            (user_id, gate["assignment_id"], gate["binding_id"]),
        ).fetchone()
        evidence_count = _int(evidence_row["count"] if evidence_row else 0)
        assistance_kind = (
            "hinted" if hint_count else "validation_evidence_viewed" if evidence_count else "independent"
        )
        independence = "hinted" if assistance_kind != "independent" else "independent"
        hint_state_hash = canonical_hash(
            {
                "hint_count": hint_count,
                "evidence_count": evidence_count,
                "assistance_kind": assistance_kind,
                "policy_version": HINT_POLICY_VERSION,
            }
        )
        attempt_id = str(uuid4())
        submission_id = str(uuid4())
        submission_hash = canonical_submission_hash(normalized)
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempts (
              id, attempt_type, user_id, track_id, plan_revision_id,
              expected_track_version, expected_progress_version, knowledge_key,
              lesson_assignment_id, document_id, gate_binding_id,
              exercise_version_id, submission_hash, hint_state_hash, independence,
              assistance_kind, idempotency_key, request_hash, accepted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                attempt_id,
                attempt_type.value,
                user_id,
                track_id,
                gate["plan_revision_id"],
                expected_track_version,
                expected_progress_version,
                knowledge_key,
                gate["assignment_id"],
                gate["document_id"],
                gate["binding_id"],
                gate["exercise_version_id"],
                submission_hash,
                hint_state_hash,
                independence,
                assistance_kind,
                idempotency_key,
                request_hash,
                now,
            ),
        )
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_submissions (
              id, attempt_id, user_id, exercise_version_id,
              submission_kind, content_text, content_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                submission_id,
                attempt_id,
                user_id,
                gate["exercise_version_id"],
                _submission_kind(str(gate["exercise_type"])),
                normalized,
                submission_hash,
            ),
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_lesson_gate_states
            SET state = 'in_progress', attempt_count = attempt_count + 1,
                latest_attempt_id = %s, version = version + 1
            WHERE id = %s AND version = %s RETURNING version
            """,
            (attempt_id, gate["gate_state_id"], expected_gate_version),
        ).fetchone()
        if updated is None:
            raise PracticeVersionConflict("Gate state changed while accepting Attempt")
        return {
            "id": attempt_id,
            "attempt_type": attempt_type.value,
            "user_id": user_id,
            "track_id": track_id,
            "knowledge_key": knowledge_key,
            "exercise_version_id": str(gate["exercise_version_id"]),
            "submission_id": submission_id,
            "submission_hash": submission_hash,
            "independence": independence,
            "assistance_kind": assistance_kind,
            "accepted_at": now,
            "gate_version": _int(updated["version"]),
            "runtime_profile_key": gate.get("runtime_profile_key"),
            "required_capabilities_json": gate.get("required_capabilities_json"),
            "pass_threshold": _float(gate["pass_threshold"]),
            "exercise_type": str(gate["exercise_type"]),
            "idempotent_replayed": False,
        }

    def read_attempt(self, *, user_id: str, attempt_id: str, for_update: bool = False) -> dict[str, object]:
        lock = " FOR UPDATE OF attempts" if for_update else ""
        row = self._conn.execute(
            """
            SELECT attempts.*, results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json, results.policy_version AS result_policy_version,
                   results.result_hash, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state,
                   jobs.safe_diagnostic_code AS execution_diagnostic_code
            FROM tutor_exercise_attempts AS attempts
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE attempts.id = %s AND attempts.user_id = %s
            """ + lock,
            (attempt_id, user_id),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("exercise Attempt was not found")
        return dict(row)

    def finalize_gate_attempt(
        self,
        *,
        user_id: str,
        attempt_id: str,
        result: ExerciseAttemptResult,
        now: datetime,
    ) -> dict[str, object]:
        attempt = self.read_attempt(user_id=user_id, attempt_id=attempt_id, for_update=True)
        if attempt.get("result_hash") is not None:
            if str(attempt["result_hash"]) != result.result_hash:
                raise PracticeIdempotencyConflict("Attempt result conflicts with stored terminal result")
            attempt["idempotent_replayed"] = True
            return attempt
        self._conn.execute(
            """
            INSERT INTO tutor_exercise_attempt_results (
              attempt_id, user_id, outcome, score, safe_feedback_json,
              capability_scores_json, execution_receipt_hash, policy_version,
              result_hash, terminal_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                attempt_id,
                user_id,
                result.outcome.value,
                result.score,
                _json(result.safe_feedback),
                _json(result.capability_scores),
                result.execution_receipt_hash,
                result.policy_version,
                result.result_hash,
                result.terminal_at,
            ),
        )
        if str(attempt["attempt_type"]) == ExerciseAttemptType.RUN.value:
            return self.read_attempt(user_id=user_id, attempt_id=attempt_id)
        track = self._conn.execute(
            "SELECT version FROM tutor_learning_tracks WHERE id = %s AND user_id = %s FOR UPDATE",
            (attempt["track_id"], user_id),
        ).fetchone()
        progress = self._conn.execute(
            """
            SELECT status, version FROM tutor_track_node_progress
            WHERE track_id = %s AND user_id = %s AND knowledge_key = %s FOR UPDATE
            """,
            (attempt["track_id"], user_id, attempt["knowledge_key"]),
        ).fetchone()
        assignment = self._conn.execute(
            """
            SELECT id, status, document_id FROM tutor_lesson_assignments
            WHERE id = %s AND user_id = %s AND track_id = %s AND knowledge_key = %s FOR UPDATE
            """,
            (attempt["lesson_assignment_id"], user_id, attempt["track_id"], attempt["knowledge_key"]),
        ).fetchone()
        if (
            track is None
            or progress is None
            or assignment is None
            or str(assignment["status"]) != "active"
            or str(assignment["document_id"]) != str(attempt["document_id"])
            or _int(track["version"]) != _int(attempt["expected_track_version"])
            or _int(progress["version"]) != _int(attempt["expected_progress_version"])
        ):
            stale = self.read_attempt(user_id=user_id, attempt_id=attempt_id)
            stale["projected"] = False
            stale["projection_code"] = "LESSON_GATE_VERSION_CONFLICT"
            return stale
        gate = self._conn.execute(
            """
            SELECT states.*, bindings.requirement_kind, bindings.pass_threshold
            FROM tutor_lesson_gate_states AS states
            JOIN tutor_lesson_gate_bindings AS bindings ON bindings.id = states.gate_binding_id
            WHERE states.lesson_assignment_id = %s AND states.gate_binding_id = %s
              AND states.user_id = %s AND states.track_id = %s AND states.knowledge_key = %s
            FOR UPDATE OF states
            """,
            (
                attempt["lesson_assignment_id"],
                attempt["gate_binding_id"],
                user_id,
                attempt["track_id"],
                attempt["knowledge_key"],
            ),
        ).fetchone()
        if gate is None:
            raise PracticeNotFound("Gate state was not found during finalization")
        passed = result.outcome.value == "passed" and result.score >= _float(gate["pass_threshold"])
        evidence = MasteryEvidence(
            evidence_id=str(uuid4()),
            knowledge_key=str(attempt["knowledge_key"]),
            evidence_kind=MasteryEvidenceKind.GATE,
            source_receipt_id=attempt_id,
            source_receipt_hash=result.result_hash,
            independence=MasteryIndependence(str(attempt["independence"])),
            score=result.score,
            hint_count=0 if str(attempt["independence"]) == "independent" else 1,
            attempt_count=_int(gate["attempt_count"]),
            summary={
                "strengths": list(result.capability_scores) if passed else [],
                "weaknesses": [] if passed else list(result.capability_scores),
            },
            created_at=now,
        )
        _, mastery, _ = PostgresLearningTrackRepository(self._conn).append_mastery_evidence(
            user_id=user_id,
            track_id=str(attempt["track_id"]),
            evidence=evidence,
        )
        updated_gate = self._conn.execute(
            """
            UPDATE tutor_lesson_gate_states
            SET state = %s, best_score = GREATEST(best_score, %s), latest_attempt_id = %s,
                passing_attempt_id = CASE WHEN %s THEN %s ELSE passing_attempt_id END,
                passed_at = CASE WHEN %s THEN %s ELSE NULL END,
                version = version + 1
            WHERE id = %s RETURNING *
            """,
            (
                "passed" if passed else "remediation_required",
                result.score,
                attempt_id,
                passed,
                attempt_id,
                passed,
                now,
                gate["id"],
            ),
        ).fetchone()
        route_changed = False
        if passed and str(gate["requirement_kind"]) == GateRequirementKind.REQUIRED.value:
            remaining = self._conn.execute(
                """
                SELECT count(*)::int AS count
                FROM tutor_lesson_gate_states AS states
                JOIN tutor_lesson_gate_bindings AS bindings ON bindings.id = states.gate_binding_id
                WHERE states.lesson_assignment_id = %s
                  AND bindings.requirement_kind = 'required'
                  AND states.state <> 'passed'
                """,
                (attempt["lesson_assignment_id"],),
            ).fetchone()
            if _int(remaining["count"] if remaining else 0) == 0:
                self._conn.execute(
                    """
                    UPDATE tutor_track_node_progress
                    SET status = 'completed', started_at = COALESCE(started_at, %s),
                        completed_at = COALESCE(completed_at, %s), version = version + 1
                    WHERE track_id = %s AND user_id = %s AND knowledge_key = %s
                      AND status IN ('available', 'in_progress')
                    """,
                    (now, now, attempt["track_id"], user_id, attempt["knowledge_key"]),
                )
                self._unlock_available_nodes(
                    user_id=user_id,
                    track_id=str(attempt["track_id"]),
                    plan_revision_id=str(attempt["plan_revision_id"]),
                )
                self._advance_track(
                    user_id=user_id,
                    track_id=str(attempt["track_id"]),
                    completed_key=str(attempt["knowledge_key"]),
                    now=now,
                )
                route_changed = True
        projected = self.read_attempt(user_id=user_id, attempt_id=attempt_id)
        projected.update(
            projected=True,
            route_changed=route_changed,
            gate_state=dict(updated_gate) if updated_gate else None,
            mastery={
                "confidence": mastery.confidence,
                "mastery_level": mastery.mastery_level.value,
                "evidence_count": mastery.evidence_count,
                "observation_count": mastery.observation_count,
            },
            idempotent_replayed=False,
        )
        return projected

    def _unlock_available_nodes(self, *, user_id: str, track_id: str, plan_revision_id: str) -> None:
        rows = self._conn.execute(
            """
            SELECT nodes.knowledge_key, nodes.prerequisite_keys_json,
                   progress.status, modules.order_index AS module_order, nodes.order_index AS node_order
            FROM tutor_track_plan_nodes AS nodes
            JOIN tutor_track_plan_modules AS modules ON modules.id = nodes.module_id
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (nodes.track_id, nodes.user_id, nodes.knowledge_key)
            WHERE nodes.revision_id = %s AND nodes.track_id = %s AND nodes.user_id = %s
            ORDER BY modules.order_index, nodes.order_index
            """,
            (plan_revision_id, track_id, user_id),
        ).fetchall()
        statuses = {str(row["knowledge_key"]): str(row["status"]) for row in rows}
        satisfied = {"completed", "diagnostic_skipped"}
        for row in rows:
            key = str(row["knowledge_key"])
            if statuses[key] != "locked":
                continue
            prerequisites = _string_list(row.get("prerequisite_keys_json"))
            if all(statuses.get(item) in satisfied for item in prerequisites):
                self._conn.execute(
                    """
                    UPDATE tutor_track_node_progress SET status = 'available', version = version + 1
                    WHERE track_id = %s AND user_id = %s AND knowledge_key = %s AND status = 'locked'
                    """,
                    (track_id, user_id, key),
                )
                statuses[key] = "available"

    def _advance_track(self, *, user_id: str, track_id: str, completed_key: str, now: datetime) -> None:
        next_row = self._conn.execute(
            """
            SELECT progress.knowledge_key
            FROM tutor_track_active_plans AS active
            JOIN tutor_track_plan_nodes AS nodes ON nodes.revision_id = active.revision_id
            JOIN tutor_track_plan_modules AS modules ON modules.id = nodes.module_id
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (nodes.track_id, nodes.user_id, nodes.knowledge_key)
            WHERE active.track_id = %s AND active.user_id = %s
              AND progress.status IN ('available', 'in_progress')
            ORDER BY modules.order_index, nodes.order_index LIMIT 1
            """,
            (track_id, user_id),
        ).fetchone()
        self._conn.execute(
            """
            UPDATE tutor_learning_tracks
            SET current_knowledge_key = %s, last_learned_at = %s, version = version + 1
            WHERE id = %s AND user_id = %s
            """,
            (str(next_row["knowledge_key"]) if next_row else completed_key, now, track_id, user_id),
        )


def _requirement_kind(gate_kind: str) -> GateRequirementKind:
    return {
        "knowledge_check": GateRequirementKind.REQUIRED,
        "guided_practice": GateRequirementKind.RECOMMENDED,
        "independent_practice": GateRequirementKind.DIAGNOSTIC,
    }[gate_kind]


def _submission_kind(exercise_type: str) -> str:
    if exercise_type == ExerciseType.SQL_QUERY.value:
        return "sql"
    if exercise_type in {ExerciseType.STATIC_CODE_REASONING.value, ExerciseType.MODEL_CODE_REVIEW.value}:
        return "structured_answer"
    return "code"


def _safe_hint(*, level: int, gate: Mapping[str, object]) -> dict[str, object]:
    capabilities = _string_list(gate.get("required_capabilities_json"))
    messages = {
        1: "先写出这段代码应该产生的一个最小结果，再检查对应变量或表达式。",
        2: "把问题缩小到一个输入和一个输出，逐行核对类型、名称与返回值。",
        3: "使用当前练习的 starter 重新开始，只保留满足核心能力的最小改动。",
    }
    return {
        "level": level,
        "message": messages[level],
        "capabilities": capabilities[:4],
        "reveals_answer": False,
    }


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_hash(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    return int(str(value or 0))


def _float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    return float(str(value or 0))


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list | tuple) else []


def _datetime_or_none(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None
