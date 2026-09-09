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
    ExerciseAttemptResult,
    ExerciseAttemptType,
    ExercisePrivateRubric,
    ExerciseType,
    ExerciseVersion,
    GateRequirementKind,
    LessonGateBinding,
    canonical_hash,
    canonical_submission_hash,
)
from app.services.learning.practice.fixtures import CuratedExerciseFixture, fixture_for_language
from app.services.learning.practice.gate_selection import (
    KNOWLEDGE_CHECK_GATE_CONTRACT,
    LEGACY_GATE_CONTRACT,
    MODEL_REVIEW_GATE_CONTRACT,
    GateSelectionUnavailable,
    execution_requirement_for,
    gate_binding_compatibility,
    gate_slot_is_compatible,
    select_published_knowledge_check,
)
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
    node_capabilities: tuple[str, ...]


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
                   assignments.document_id,
                   nodes.required_capabilities_json AS node_capabilities_json
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id) = (tracks.id, tracks.user_id)
             AND progress.knowledge_key = %s
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id, nodes.knowledge_key) =
                 (active.revision_id, tracks.id, tracks.user_id, progress.knowledge_key)
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
            node_capabilities=tuple(_string_list(row.get("node_capabilities_json"))),
        )

    def ensure_curated_fixture(self, fixture: CuratedExerciseFixture, *, now: datetime) -> str:
        return self.ensure_exercise_authority(
            fixture.exercise,
            fixture.rubric,
            now=now,
        )

    def ensure_exercise_authority(
        self,
        exercise: ExerciseVersion,
        rubric: ExercisePrivateRubric,
        *,
        now: datetime,
    ) -> str:
        """Materialize or replay one exact immutable ExerciseVersion and rubric."""

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
        gate_key: str | None = None,
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
        slots = self._conn.execute(
            """
            SELECT * FROM tutor_lesson_gate_slots
            WHERE document_id = %s AND (%s::text IS NULL OR gate_key = %s)
            ORDER BY block_id, gate_key
            """,
            (scope.document_id, gate_key, gate_key),
        ).fetchall()
        if gate_key is not None and not slots:
            raise PracticeNotFound("Lesson Gate slot was not found")
        for slot in slots:
            existing = self._conn.execute(
                """
                SELECT id FROM tutor_lesson_gate_bindings
                WHERE document_id = %s AND gate_key = %s
                """,
                (scope.document_id, slot["gate_key"]),
            ).fetchone()
            if existing is not None:
                # Bindings are immutable historical authority. Compatibility is enforced
                # at projection/action time; preparation never rewrites or deletes them.
                continue
            assessment = str(slot["assessment_contract_version"])
            slot_capabilities = tuple(_string_list(slot.get("required_capabilities_json")))
            slot_scope = dict(slot)
            slot_scope.update(
                node_capabilities_json=list(scope.node_capabilities),
                scope_language_id=scope.language_id,
                scope_knowledge_key=scope.knowledge_key,
            )
            if not gate_slot_is_compatible(slot_scope):
                continue
            if assessment == MODEL_REVIEW_GATE_CONTRACT:
                # The dedicated authoring repository is the sole publication path.
                continue
            if assessment == KNOWLEDGE_CHECK_GATE_CONTRACT:
                if str(slot["gate_kind"]) != "knowledge_check":
                    continue
                try:
                    selection = select_published_knowledge_check(
                        self._conn,
                        language_id=scope.language_id,
                        knowledge_key=scope.knowledge_key,
                        required_capabilities=slot_capabilities,
                        available_capabilities=scope.node_capabilities,
                    )
                except GateSelectionUnavailable:
                    continue
                exercise_version_id = selection.exercise_version_id
                exercise_key = selection.exercise_key
                exercise_version = selection.exercise_version
                execution_required = selection.execution_required
                pass_threshold = selection.pass_threshold
            elif assessment == LEGACY_GATE_CONTRACT:
                fixture = fixture_for_language(scope.language_id)
                if (
                    fixture is None
                    or fixture.exercise.required_capabilities != slot_capabilities
                ):
                    continue
                exercise_version_id = self.ensure_curated_fixture(fixture, now=now)
                exercise_key = fixture.exercise.exercise_key
                exercise_version = fixture.exercise.version
                execution_required = fixture.exercise.execution_required
                pass_threshold = 0.8
            else:
                # Unknown assessment contracts are never mapped optimistically.
                continue
            slot_hash = canonical_hash(
                {
                    "gate_kind": str(slot["gate_kind"]),
                    "assessment_contract_version": assessment,
                    "required_capabilities": list(slot_capabilities),
                    "learner_prompt_hash": str(slot["learner_prompt_hash"]),
                }
            )
            binding = LessonGateBinding(
                gate_key=str(slot["gate_key"]),
                exercise_key=exercise_key,
                exercise_version=exercise_version,
                requirement_kind=_requirement_kind(str(slot["gate_kind"])),
                pass_policy_version=GATE_PASS_POLICY_VERSION,
                pass_threshold=pass_threshold,
                execution_requirement=execution_requirement_for(execution_required),
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
                # A concurrent immutable winner is left intact and checked on read.
                continue
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
                   slots.learner_prompt, slots.learner_prompt_hash,
                   bindings.id AS binding_id, bindings.knowledge_key AS binding_knowledge_key,
                   bindings.requirement_kind,
                   bindings.pass_policy_version, bindings.pass_threshold,
                   bindings.execution_requirement, bindings.binding_contract_hash,
                   versions.id AS exercise_version_id,
                   versions.language_id AS language_id,
                   versions.language_id AS exercise_language_id,
                   versions.exercise_key, versions.exercise_type, versions.version AS exercise_version,
                   versions.source_kind, versions.title AS exercise_title,
                   versions.learner_prompt_json, versions.starter_artifact_json,
                   versions.required_capabilities_json,
                   versions.required_capabilities_json AS exercise_capabilities_json,
                   versions.runtime_profile_key, versions.execution_required,
                   versions.content_hash AS exercise_content_hash,
                   rubrics.rubric_hash AS stored_rubric_hash,
                   rubrics.reference_answer_json,
                   rubrics.score_policy_json,
                   materializations.version_id AS materialization_version_id,
                   materializations.item_handle AS materialization_handle,
                   materializations.content_hash AS materialization_content_hash,
                   materializations.exercise_version_id AS materialization_exercise_version_id,
                   materializations.exercise_key AS materialization_exercise_key,
                   materializations.exercise_version AS materialization_exercise_version,
                   materializations.exercise_content_hash AS materialization_exercise_content_hash,
                   materializations.rubric_hash AS materialization_rubric_hash,
                   items.handle AS item_handle, items.item_kind, items.purpose AS item_purpose,
                   items.knowledge_key AS item_knowledge_key,
                   items.language_id AS item_language_id,
                   items.required_capabilities_json AS item_capabilities_json,
                   items.content_hash AS item_content_hash,
                   item_public.public_json AS item_public_json,
                   publication.state AS latest_publication_state,
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
            LEFT JOIN tutor_exercise_private_rubrics AS rubrics
              ON rubrics.exercise_version_id = versions.id
            LEFT JOIN tutor_learning_item_practice_materializations AS materializations
              ON materializations.exercise_version_id = versions.id
            LEFT JOIN tutor_learning_item_versions AS items
              ON items.id = materializations.version_id
            LEFT JOIN tutor_learning_item_public_contents AS item_public
              ON item_public.version_id = items.id
            LEFT JOIN LATERAL (
              SELECT events.state
              FROM tutor_learning_item_publication_events AS events
              WHERE events.version_id = items.id
              ORDER BY events.state_version DESC LIMIT 1
            ) AS publication ON true
            LEFT JOIN tutor_lesson_gate_states AS states
              ON states.lesson_assignment_id = assignments.id AND states.gate_binding_id = bindings.id
            LEFT JOIN tutor_exercise_attempts AS attempts ON attempts.id = states.latest_attempt_id
            LEFT JOIN tutor_exercise_attempt_results AS results ON results.attempt_id = attempts.id
            WHERE assignments.id = %s AND assignments.status = 'active'
            ORDER BY slots.block_id, slots.gate_key
            """,
            (scope.assignment_id,),
        ).fetchall()
        projected: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item.update(
                scope_language_id=scope.language_id,
                scope_knowledge_key=scope.knowledge_key,
                node_capabilities_json=list(scope.node_capabilities),
            )
            projected.append(item)
        return tuple(projected)

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
            SELECT tracks.version AS track_version, tracks.language_id AS scope_language_id,
                   active.revision_id AS plan_revision_id,
                   progress.knowledge_key AS scope_knowledge_key,
                   progress.status AS progress_status, progress.version AS progress_version,
                   nodes.required_capabilities_json AS node_capabilities_json,
                   assignments.id AS assignment_id, assignments.assignment_version,
                   assignments.started_at AS assignment_started_at,
                   assignments.document_id, slots.gate_key, slots.gate_kind,
                   slots.assessment_contract_version,
                   slots.required_capabilities_json AS slot_capabilities_json,
                   slots.learner_prompt, slots.learner_prompt_hash,
                   bindings.id AS binding_id,
                   bindings.knowledge_key AS binding_knowledge_key,
                   bindings.requirement_kind,
                   bindings.pass_policy_version, bindings.pass_threshold,
                   bindings.execution_requirement, bindings.binding_contract_hash,
                   versions.id AS exercise_version_id,
                   versions.language_id AS language_id,
                   versions.language_id AS exercise_language_id,
                   versions.exercise_key, versions.exercise_type, versions.version AS exercise_version,
                   versions.source_kind, versions.title AS exercise_title,
                   versions.learner_prompt_json, versions.starter_artifact_json,
                   versions.required_capabilities_json,
                   versions.required_capabilities_json AS exercise_capabilities_json,
                   versions.runtime_profile_key, versions.execution_required,
                   versions.content_hash AS exercise_content_hash,
                   rubrics.rubric_hash AS stored_rubric_hash,
                   rubrics.reference_answer_json,
                   rubrics.score_policy_json,
                   materializations.version_id AS materialization_version_id,
                   materializations.item_handle AS materialization_handle,
                   materializations.content_hash AS materialization_content_hash,
                   materializations.exercise_version_id AS materialization_exercise_version_id,
                   materializations.exercise_key AS materialization_exercise_key,
                   materializations.exercise_version AS materialization_exercise_version,
                   materializations.exercise_content_hash AS materialization_exercise_content_hash,
                   materializations.rubric_hash AS materialization_rubric_hash,
                   items.handle AS item_handle, items.item_kind, items.purpose AS item_purpose,
                   items.knowledge_key AS item_knowledge_key,
                   items.language_id AS item_language_id,
                   items.required_capabilities_json AS item_capabilities_json,
                   items.content_hash AS item_content_hash,
                   item_public.public_json AS item_public_json,
                   publication.state AS latest_publication_state,
                   states.id AS gate_state_id, states.state AS gate_state,
                   states.attempt_count, states.best_score, states.latest_attempt_id,
                   states.passing_attempt_id, states.version AS gate_version, states.passed_at
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id) = (tracks.id, tracks.user_id)
             AND progress.knowledge_key = %s
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id, nodes.knowledge_key) =
                 (active.revision_id, tracks.id, tracks.user_id, progress.knowledge_key)
            JOIN tutor_lesson_assignments AS assignments
              ON (assignments.track_id, assignments.user_id, assignments.knowledge_key) =
                 (tracks.id, tracks.user_id, progress.knowledge_key)
             AND assignments.status = 'active'
            JOIN tutor_lesson_gate_slots AS slots ON slots.document_id = assignments.document_id
            JOIN tutor_lesson_gate_bindings AS bindings
              ON (bindings.document_id, bindings.gate_key) = (slots.document_id, slots.gate_key)
            JOIN tutor_exercise_versions AS versions ON versions.id = bindings.exercise_version_id
            JOIN tutor_exercise_private_rubrics AS rubrics
              ON rubrics.exercise_version_id = versions.id
            LEFT JOIN tutor_learning_item_practice_materializations AS materializations
              ON materializations.exercise_version_id = versions.id
            LEFT JOIN tutor_learning_item_versions AS items
              ON items.id = materializations.version_id
            LEFT JOIN tutor_learning_item_public_contents AS item_public
              ON item_public.version_id = items.id
            LEFT JOIN LATERAL (
              SELECT events.state
              FROM tutor_learning_item_publication_events AS events
              WHERE events.version_id = items.id
              ORDER BY events.state_version DESC LIMIT 1
            ) AS publication ON true
            JOIN tutor_lesson_gate_states AS states
              ON states.lesson_assignment_id = assignments.id AND states.gate_binding_id = bindings.id
            WHERE tracks.id = %s AND tracks.user_id = %s AND slots.gate_key = %s
            """ + lock,
            (knowledge_key, track_id, user_id, gate_key),
        ).fetchone()
        if row is None:
            raise PracticeNotFound("Lesson Gate was not found")
        gate = dict(row)
        if for_update and gate.get("materialization_version_id") is not None:
            version_id = str(gate["materialization_version_id"])
            locked = self._conn.execute(
                "SELECT id FROM tutor_learning_item_versions WHERE id = %s FOR UPDATE",
                (version_id,),
            ).fetchone()
            publication = None
            if locked is not None:
                publication = self._conn.execute(
                    """
                    SELECT state
                    FROM tutor_learning_item_publication_events
                    WHERE version_id = %s
                    ORDER BY state_version DESC
                    LIMIT 1
                    """,
                    (version_id,),
                ).fetchone()
            gate["latest_publication_state"] = (
                str(publication["state"]) if publication is not None else None
            )
        return gate

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
            replay["gate_version"] = expected_gate_version + 1
            replay["idempotent_replayed"] = True
            return replay
        if _int(gate["gate_version"]) != expected_gate_version:
            raise PracticeVersionConflict("Lesson Gate version changed")
        if not gate_binding_compatibility(gate).actionable:
            raise PracticeNotReady("Gate binding is incompatible with its assessment contract")
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

    def replay_gate_attempt(
        self,
        *,
        user_id: str,
        attempt_type: ExerciseAttemptType,
        idempotency_key: str,
        request_hash: str,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT attempts.*, submissions.id AS submission_id,
                   results.outcome, results.score, results.safe_feedback_json,
                   results.capability_scores_json,
                   results.result_hash, results.terminal_at,
                   links.execution_job_id, jobs.state AS execution_job_state
            FROM tutor_exercise_attempts AS attempts
            JOIN tutor_exercise_attempt_submissions AS submissions
              ON submissions.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id = attempts.id
            LEFT JOIN tutor_exercise_execution_links AS links
              ON links.attempt_id = attempts.id
            LEFT JOIN tutor_execution_jobs AS jobs ON jobs.id = links.execution_job_id
            WHERE attempts.user_id = %s AND attempts.attempt_type = %s
              AND attempts.idempotency_key = %s
            FOR UPDATE OF attempts
            """,
            (user_id, attempt_type.value, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if str(row["request_hash"]) != request_hash:
            raise PracticeIdempotencyConflict(
                "Attempt idempotency key conflicts with stored request"
            )
        replay = dict(row)
        replay["idempotent_replayed"] = True
        return replay

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
        replay = self.replay_gate_attempt(
            user_id=user_id,
            attempt_type=attempt_type,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
        )
        if replay is not None:
            return replay
        if str(gate["progress_status"]) == "locked" or gate.get("assignment_started_at") is None:
            raise PracticeNotReady("Lesson must be started before attempting a Gate")
        if (
            _int(gate["track_version"]) != expected_track_version
            or _int(gate["progress_version"]) != expected_progress_version
            or _int(gate["assignment_version"]) != expected_assignment_version
            or _int(gate["gate_version"]) != expected_gate_version
        ):
            raise PracticeVersionConflict("Gate Attempt scope version changed")
        normalized = str(submission).replace("\r\n", "\n").replace("\r", "\n")
        if not normalized.strip() or len(normalized) > 48_000:
            raise PracticeRepositoryError("submission must contain 1..48000 characters")
        if not gate_binding_compatibility(gate).actionable:
            raise PracticeNotReady("Gate binding is incompatible with its assessment contract")
        if str(gate["gate_state"]) == "passed":
            raise PracticeNotReady("Passed Gate does not accept new Attempts")
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
