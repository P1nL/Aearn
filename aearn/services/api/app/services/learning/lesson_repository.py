"""PostgreSQL authority for immutable LessonDocument artifacts."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import uuid4

from psycopg.types.json import Jsonb
from psycopg import Connection

from app.services.grounding.grounding_sources import SourceContentType, SourceTrustTier, SourceVersionKind
from app.services.learning.lesson_contracts import (
    ExerciseGateBlock,
    LessonDocumentDraft,
    LessonImpact,
    LessonSourceSnapshot,
    lesson_block_payload,
    parse_lesson_document_candidate,
)


class LessonRepositoryError(ValueError):
    pass


class LessonNotFound(LessonRepositoryError):
    pass


class LessonVersionConflict(LessonRepositoryError):
    pass


class LessonAssignmentConflict(LessonRepositoryError):
    pass


class LessonIdempotencyConflict(LessonRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class LessonScopeRecord:
    user_id: str
    track_id: str
    language_id: str
    goal_text: str
    target_level: str
    track_version: int
    active_plan_revision_id: str
    module_key: str
    module_diagnostic_allowed: bool
    knowledge_key: str
    node_title: str
    node_description: str
    required_capabilities: tuple[str, ...]
    progress_status: str
    progress_version: int
    mastery_level: str
    mastery_confidence: float


@dataclass(frozen=True, slots=True)
class LessonAuthoringRunRecord:
    run_id: str
    user_id: str
    track_id: str
    knowledge_key: str
    run_kind: str
    state: str
    idempotency_key: str
    request_hash: str
    expected_track_version: int
    expected_progress_version: int
    active_plan_revision_id: str
    profile_hash: str
    source_set_hash: str | None
    attempt_count: int
    lease_generation: int
    lease_owner: str | None
    lease_expires_at: datetime | None
    failure_code: str | None
    failure_message: str | None
    standard_document_id: str | None
    personalized_document_id: str | None
    assignment_id: str | None
    created_at: datetime
    updated_at: datetime
    terminal_at: datetime | None


@dataclass(frozen=True, slots=True)
class PublishedLesson:
    standard_document_id: str
    personalized_document_id: str
    assignment_id: str
    assignment_status: str


class PostgresLessonDocumentRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def read_scope(self, *, user_id: str, track_id: str, knowledge_key: str, for_update: bool = False) -> LessonScopeRecord:
        lock = " FOR UPDATE OF tracks, progress" if for_update else ""
        row = self._conn.execute(
            """
            SELECT tracks.user_id, tracks.id AS track_id, tracks.language_id,
                   tracks.goal_text, tracks.target_level, tracks.version AS track_version,
                   active.revision_id AS active_plan_revision_id,
                   modules.module_key,
                   (
                     modules.is_skippable
                     AND nodes.order_index = 0
                     AND tracks.current_knowledge_key = nodes.knowledge_key
                     AND NOT EXISTS (
                       SELECT 1
                       FROM tutor_track_plan_nodes AS module_nodes
                       JOIN tutor_track_node_progress AS module_progress
                         ON (module_progress.track_id, module_progress.user_id, module_progress.knowledge_key) =
                            (module_nodes.track_id, module_nodes.user_id, module_nodes.knowledge_key)
                       WHERE module_nodes.module_id = modules.id
                         AND module_nodes.revision_id = modules.revision_id
                         AND module_nodes.track_id = modules.track_id
                         AND module_nodes.user_id = modules.user_id
                         AND module_progress.status IN ('completed', 'review_due', 'diagnostic_skipped')
                     )
                   ) AS module_diagnostic_allowed,
                   nodes.knowledge_key, nodes.title AS node_title, nodes.description AS node_description,
                   nodes.required_capabilities_json, progress.status AS progress_status,
                   progress.version AS progress_version, mastery.mastery_level,
                   mastery.confidence AS mastery_confidence
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
                 (active.revision_id, active.track_id, active.user_id)
            JOIN tutor_track_plan_modules AS modules
              ON (modules.id, modules.revision_id, modules.track_id, modules.user_id) =
                 (nodes.module_id, nodes.revision_id, nodes.track_id, nodes.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (nodes.track_id, nodes.user_id, nodes.knowledge_key)
            LEFT JOIN tutor_mastery_states AS mastery
              ON (mastery.track_id, mastery.user_id, mastery.knowledge_key) =
                 (progress.track_id, progress.user_id, progress.knowledge_key)
            WHERE tracks.id = %s AND tracks.user_id = %s AND nodes.knowledge_key = %s
            """ + lock,
            (track_id, user_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise LessonNotFound("Lesson scope was not found")
        return LessonScopeRecord(
            user_id=str(row["user_id"]), track_id=str(row["track_id"]), language_id=str(row["language_id"]),
            goal_text=str(row["goal_text"]), target_level=str(row["target_level"]), track_version=_int(row["track_version"]),
            active_plan_revision_id=str(row["active_plan_revision_id"]), module_key=str(row["module_key"]),
            module_diagnostic_allowed=bool(row["module_diagnostic_allowed"]), knowledge_key=str(row["knowledge_key"]),
            node_title=str(row["node_title"]), node_description=str(row["node_description"]),
            required_capabilities=_string_tuple(row.get("required_capabilities_json")),
            progress_status=str(row["progress_status"]), progress_version=_int(row["progress_version"]),
            mastery_level=str(row.get("mastery_level") or "unseen"), mastery_confidence=_float(row.get("mastery_confidence")),
        )

    def create_or_replay_authoring_run(
        self, *, scope: LessonScopeRecord, run_kind: str, idempotency_key: str,
        request_hash: str, profile_hash: str,
    ) -> tuple[LessonAuthoringRunRecord, bool]:
        existing = self._conn.execute(
            "SELECT * FROM tutor_lesson_authoring_runs WHERE user_id = %s AND run_kind = %s AND idempotency_key = %s FOR UPDATE",
            (scope.user_id, run_kind, idempotency_key),
        ).fetchone()
        if existing is not None:
            if str(existing["request_hash"]) != request_hash:
                raise LessonIdempotencyConflict("Lesson authoring idempotency request conflicts")
            return _run_from_row(existing), True
        row = self._conn.execute(
            """
            INSERT INTO tutor_lesson_authoring_runs (
              id, user_id, track_id, knowledge_key, run_kind, state, idempotency_key,
              request_hash, expected_track_version, expected_progress_version,
              active_plan_revision_id, profile_hash
            ) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (str(uuid4()), scope.user_id, scope.track_id, scope.knowledge_key, run_kind,
             idempotency_key, request_hash, scope.track_version, scope.progress_version,
             scope.active_plan_revision_id, profile_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError("Lesson authoring run insert returned no row")
        return _run_from_row(row), False

    def read_authoring_run(self, *, run_id: str, user_id: str | None = None, for_update: bool = False) -> LessonAuthoringRunRecord:
        user_clause = " AND user_id = %s" if user_id is not None else ""
        params: tuple[object, ...] = (run_id, user_id) if user_id is not None else (run_id,)
        row = self._conn.execute("SELECT * FROM tutor_lesson_authoring_runs WHERE id = %s" + user_clause + (" FOR UPDATE" if for_update else ""), params).fetchone()
        if row is None:
            raise LessonNotFound("Lesson authoring run was not found")
        return _run_from_row(row)

    def claim_authoring_run(self, *, run_id: str, owner: str, now: datetime, lease_seconds: int = 120) -> LessonAuthoringRunRecord | None:
        row = self._conn.execute("SELECT * FROM tutor_lesson_authoring_runs WHERE id = %s FOR UPDATE", (run_id,)).fetchone()
        if row is None or str(row["state"]) in {"completed", "failed", "cancelled"}:
            return None
        expires = _optional_datetime(row.get("lease_expires_at"))
        if str(row["state"]) in {"claimed", "running"} and expires is not None and expires > now:
            return None
        claimed = self._conn.execute(
            """
            UPDATE tutor_lesson_authoring_runs
            SET state = 'claimed', attempt_count = attempt_count + 1,
                lease_generation = lease_generation + 1, lease_owner = %s,
                lease_expires_at = %s, failure_code = NULL, failure_message = NULL
            WHERE id = %s RETURNING *
            """,
            (owner, now + timedelta(seconds=max(30, lease_seconds)), run_id),
        ).fetchone()
        return _run_from_row(claimed) if claimed is not None else None

    def mark_authoring_running(self, *, run_id: str, lease_generation: int) -> LessonAuthoringRunRecord:
        row = self._conn.execute(
            "UPDATE tutor_lesson_authoring_runs SET state = 'running' WHERE id = %s AND state = 'claimed' AND lease_generation = %s RETURNING *",
            (run_id, lease_generation),
        ).fetchone()
        if row is None:
            raise LessonVersionConflict("Lesson authoring lease changed")
        return _run_from_row(row)

    def set_authoring_source_set(self, *, run_id: str, lease_generation: int, source_set_hash: str) -> None:
        row = self._conn.execute(
            "UPDATE tutor_lesson_authoring_runs SET source_set_hash = %s WHERE id = %s AND state = 'running' AND lease_generation = %s RETURNING id",
            (source_set_hash, run_id, lease_generation),
        ).fetchone()
        if row is None:
            raise LessonVersionConflict("Lesson authoring lease changed")

    def assert_authoring_current(self, *, run: LessonAuthoringRunRecord) -> None:
        current = self.read_authoring_run(run_id=run.run_id, for_update=True)
        if current.state != "running" or current.lease_generation != run.lease_generation:
            raise LessonVersionConflict("Lesson authoring lease changed")
        scope = self.read_scope(user_id=run.user_id, track_id=run.track_id, knowledge_key=run.knowledge_key)
        if (scope.track_version != run.expected_track_version
                or scope.progress_version != run.expected_progress_version
                or scope.active_plan_revision_id != run.active_plan_revision_id):
            raise LessonVersionConflict("Lesson authoring scope changed")

    def record_authoring_attempt(
        self, *, run: LessonAuthoringRunRecord, attempt_index: int, provider: str, model: str, protocol: str,
        outcome: str, diagnostic_code: str | None, usage: Mapping[str, int] | None,
        request_hash: str, response_hash: str | None,
        diagnostic: Mapping[str, object] | None = None,
    ) -> None:
        from app.services.learning.lesson_authoring_feedback import validate_attempt_diagnostic
        current = self.read_authoring_run(run_id=run.run_id, for_update=True)
        if current.state != "running" or current.lease_generation != run.lease_generation:
            raise LessonVersionConflict("Lesson authoring lease changed")
        safe_diagnostic = validate_attempt_diagnostic(diagnostic or {})
        self._conn.execute(
            """
            INSERT INTO tutor_lesson_authoring_attempt_receipts (
              run_id, user_id, attempt_index, provider, model, protocol, outcome,
              diagnostic_code, usage_available, input_tokens, output_tokens,
              total_tokens, request_hash, response_hash, diagnostic_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, attempt_index) DO NOTHING
            """,
            (run.run_id, run.user_id, attempt_index, provider, model, protocol, outcome,
             diagnostic_code, usage is not None, usage.get("input_tokens") if usage else None,
             usage.get("output_tokens") if usage else None, usage.get("total_tokens") if usage else None,
             request_hash, response_hash, Jsonb(safe_diagnostic)),
        )
        self._conn.execute(
            "UPDATE tutor_lesson_authoring_runs SET attempt_count = GREATEST(attempt_count, %s) WHERE id = %s",
            (attempt_index, run.run_id),
        )

    def fail_authoring_run(self, *, run_id: str, lease_generation: int, failure_code: str, failure_message: str, now: datetime) -> None:
        row = self._conn.execute(
            """
            UPDATE tutor_lesson_authoring_runs
            SET state = 'failed', failure_code = %s, failure_message = %s,
                lease_owner = NULL, lease_expires_at = NULL, terminal_at = %s
            WHERE id = %s AND state IN ('claimed', 'running') AND lease_generation = %s
            RETURNING id
            """,
            (failure_code, failure_message[:500], now, run_id, lease_generation),
        ).fetchone()
        if row is None:
            raise LessonVersionConflict("Lesson authoring lease changed")

    def evidence_is_current(self, snapshots: Sequence[LessonSourceSnapshot]) -> bool:
        for snapshot in snapshots:
            row = self._conn.execute(
                "SELECT source_id, canonical_url, source_version_label, source_version_kind, document_content_hash, content_hash FROM grounding_chunks WHERE chunk_id = %s",
                (snapshot.grounding_chunk_id,),
            ).fetchone()
            if row is None or (str(row["source_id"]), str(row["canonical_url"]), str(row["source_version_label"]),
                str(row["source_version_kind"]), str(row["document_content_hash"]), str(row["content_hash"])) != (
                snapshot.source_id, snapshot.canonical_url, snapshot.source_version_label,
                snapshot.source_version_kind, snapshot.document_content_hash, snapshot.chunk_content_hash):
                return False
        return True

    def publish_authoring_result(
        self, *, run: LessonAuthoringRunRecord, standard_document: LessonDocumentDraft,
        personalized_document: LessonDocumentDraft, snapshots: tuple[LessonSourceSnapshot, ...],
        standard_quality: Mapping[str, object], personalized_quality: Mapping[str, object],
        standard_change_summary: Mapping[str, object], personalized_change_summary: Mapping[str, object],
        generator_version: str, policy_version: str, source_set_hash: str,
        impact: LessonImpact, now: datetime,
    ) -> PublishedLesson:
        current_run = self.read_authoring_run(run_id=run.run_id, for_update=True)
        if current_run.state != "running" or current_run.lease_generation != run.lease_generation:
            raise LessonVersionConflict("Lesson authoring lease changed")
        scope = self.read_scope(user_id=run.user_id, track_id=run.track_id, knowledge_key=run.knowledge_key, for_update=True)
        if (scope.track_version, scope.progress_version, scope.active_plan_revision_id) != (
            run.expected_track_version, run.expected_progress_version, run.active_plan_revision_id):
            raise LessonVersionConflict("LearningTrack changed during Lesson authoring")
        if current_run.source_set_hash != source_set_hash or not self.evidence_is_current(snapshots):
            raise LessonVersionConflict("Lesson source evidence changed during authoring")
        standard_id = self._insert_or_reuse_document(
            document_kind="standard", document=standard_document, snapshots=snapshots,
            user_id=None, track_id=None, active_plan_revision_id=None,
            standard_document_id=None, profile_hash=None, generator_version=generator_version,
            policy_version=policy_version, source_set_hash=source_set_hash,
            change_summary=standard_change_summary, quality_summary=standard_quality,
        )
        personalized_id = self._insert_or_reuse_document(
            document_kind="personalized", document=personalized_document, snapshots=snapshots,
            user_id=run.user_id, track_id=run.track_id,
            active_plan_revision_id=run.active_plan_revision_id, standard_document_id=standard_id,
            profile_hash=run.profile_hash, generator_version=generator_version,
            policy_version=policy_version, source_set_hash=source_set_hash,
            change_summary=personalized_change_summary, quality_summary=personalized_quality,
        )
        assignment_id, assignment_status = self._assign_document(
            run=run, document_id=personalized_id, document_hash=personalized_document.content_hash,
            impact=impact, now=now,
        )
        row = self._conn.execute(
            """
            UPDATE tutor_lesson_authoring_runs
            SET state = 'completed', standard_document_id = %s,
                personalized_document_id = %s, assignment_id = %s,
                lease_owner = NULL, lease_expires_at = NULL, terminal_at = %s
            WHERE id = %s AND state = 'running' AND lease_generation = %s
            RETURNING id
            """,
            (standard_id, personalized_id, assignment_id, now, run.run_id, run.lease_generation),
        ).fetchone()
        if row is None:
            raise LessonVersionConflict("Lesson authoring lease changed")
        return PublishedLesson(standard_id, personalized_id, assignment_id, assignment_status)

    def read_lesson_state(self, *, user_id: str, track_id: str, knowledge_key: str) -> dict[str, object]:
        scope = self.read_scope(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key)
        assignment = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'active'",
            (user_id, track_id, knowledge_key),
        ).fetchone()
        latest_run = self._conn.execute(
            "SELECT * FROM tutor_lesson_authoring_runs WHERE user_id = %s AND track_id = %s AND knowledge_key = %s ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id, track_id, knowledge_key),
        ).fetchone()
        proposed = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'proposed' ORDER BY assignment_version DESC LIMIT 1",
            (user_id, track_id, knowledge_key),
        ).fetchone()
        result: dict[str, object] = {
            "scope": scope, "assignment": None, "document": None, "sources": (),
            "proposed_assignment": dict(proposed) if proposed is not None else None,
            "latest_run": _run_from_row(latest_run) if latest_run is not None else None,
        }
        if assignment is not None:
            document_id = str(assignment["document_id"])
            result.update(
                assignment=dict(assignment), document=self.load_document(document_id=document_id),
                sources=self.load_source_snapshots(document_id=document_id),
            )
        return result

    def load_document(self, *, document_id: str) -> LessonDocumentDraft:
        row = self._conn.execute("SELECT * FROM tutor_lesson_documents WHERE id = %s", (document_id,)).fetchone()
        if row is None:
            raise LessonNotFound("LessonDocument was not found")
        document = parse_lesson_document_candidate({
            "schema_version": str(row["schema_version"]), "title": str(row["title"]),
            "language_id": str(row["language_id"]), "knowledge_key": str(row["knowledge_key"]),
            "content_standard_version": str(row["content_standard_version"]),
            "coverage_keys": list(row["coverage_keys_json"]) if isinstance(row["coverage_keys_json"], list | tuple) else [],
            "blocks": list(row["blocks_json"]) if isinstance(row["blocks_json"], list | tuple) else [],
        })
        if document.content_hash != str(row["content_hash"]):
            raise LessonRepositoryError("Stored LessonDocument hash does not match its canonical content")
        return document

    def load_source_snapshots(self, *, document_id: str) -> tuple[LessonSourceSnapshot, ...]:
        rows = self._conn.execute(
            "SELECT * FROM tutor_lesson_source_snapshots WHERE document_id = %s ORDER BY citation_id", (document_id,),
        ).fetchall()
        return tuple(_snapshot_from_row(row) for row in rows)

    def start_assignment(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int, expected_progress_version: int, now: datetime,
    ) -> dict[str, object]:
        scope = self.read_scope(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key, for_update=True)
        row = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE id = %s AND user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'active' FOR UPDATE",
            (assignment_id, user_id, track_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise LessonNotFound("Lesson assignment was not found")
        if _int(row["assignment_version"]) != expected_assignment_version:
            raise LessonAssignmentConflict("Lesson assignment version changed")
        if row.get("started_at") is not None:
            return dict(row)
        if scope.progress_version != expected_progress_version or scope.progress_status == "locked":
            raise LessonVersionConflict("Lesson progress changed")
        progress_status = "in_progress" if scope.progress_status == "available" else scope.progress_status
        progress = self._conn.execute(
            """
            UPDATE tutor_track_node_progress
            SET status = %s, started_at = COALESCE(started_at, %s), version = version + 1
            WHERE track_id = %s AND user_id = %s AND knowledge_key = %s AND version = %s
            RETURNING version
            """,
            (progress_status, now, track_id, user_id, knowledge_key, expected_progress_version),
        ).fetchone()
        if progress is None:
            raise LessonVersionConflict("Lesson progress changed")
        updated = self._conn.execute(
            "UPDATE tutor_lesson_assignments SET started_at = %s WHERE id = %s AND started_at IS NULL RETURNING *",
            (now, assignment_id),
        ).fetchone()
        if updated is None:
            raise LessonAssignmentConflict("Lesson assignment start changed")
        self._conn.execute(
            "UPDATE tutor_learning_tracks SET current_knowledge_key = %s, last_learned_at = %s WHERE id = %s AND user_id = %s",
            (knowledge_key, now, track_id, user_id),
        )
        result = dict(updated)
        result.update(progress_version=_int(progress["version"]), progress_status=progress_status)
        return result

    def activate_proposed_assignment(
        self, *, user_id: str, track_id: str, knowledge_key: str, assignment_id: str,
        expected_assignment_version: int, now: datetime,
    ) -> dict[str, object]:
        current = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'active' FOR UPDATE",
            (user_id, track_id, knowledge_key),
        ).fetchone()
        proposed = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE id = %s AND user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'proposed' FOR UPDATE",
            (assignment_id, user_id, track_id, knowledge_key),
        ).fetchone()
        if current is None or proposed is None:
            raise LessonNotFound("Lesson assignment migration was not found")
        if _int(proposed["assignment_version"]) != expected_assignment_version or str(proposed.get("predecessor_assignment_id")) != str(current["id"]):
            raise LessonAssignmentConflict("Lesson assignment migration is stale")
        self._conn.execute("UPDATE tutor_lesson_assignments SET status = 'superseded' WHERE id = %s", (current["id"],))
        activated = self._conn.execute(
            "UPDATE tutor_lesson_assignments SET status = 'active', activated_at = %s WHERE id = %s RETURNING *",
            (now, assignment_id),
        ).fetchone()
        if activated is None:
            raise LessonAssignmentConflict("Lesson assignment migration failed")
        return dict(activated)

    def _insert_or_reuse_document(
        self, *, document_kind: str, document: LessonDocumentDraft,
        snapshots: tuple[LessonSourceSnapshot, ...], user_id: str | None,
        track_id: str | None, active_plan_revision_id: str | None,
        standard_document_id: str | None, profile_hash: str | None,
        generator_version: str, policy_version: str, source_set_hash: str,
        change_summary: Mapping[str, object], quality_summary: Mapping[str, object],
    ) -> str:
        if document_kind == "standard":
            existing = self._conn.execute(
                """
                SELECT id FROM tutor_lesson_documents
                WHERE document_kind = 'standard' AND language_id = %s AND knowledge_key = %s
                  AND content_standard_version = %s AND generator_version = %s
                  AND policy_version = %s AND source_set_hash = %s AND content_hash = %s
                """,
                (document.language_id, document.knowledge_key, document.content_standard_version,
                 generator_version, policy_version, source_set_hash, document.content_hash),
            ).fetchone()
            predecessor = self._conn.execute(
                "SELECT id FROM tutor_lesson_documents WHERE document_kind = 'standard' AND language_id = %s AND knowledge_key = %s AND content_standard_version = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (document.language_id, document.knowledge_key, document.content_standard_version),
            ).fetchone()
        else:
            existing = self._conn.execute(
                """
                SELECT id FROM tutor_lesson_documents
                WHERE document_kind = 'personalized' AND user_id = %s AND track_id = %s
                  AND knowledge_key = %s AND standard_document_id = %s AND profile_hash = %s
                  AND generator_version = %s AND policy_version = %s
                  AND source_set_hash = %s AND content_hash = %s
                """,
                (user_id, track_id, document.knowledge_key, standard_document_id, profile_hash,
                 generator_version, policy_version, source_set_hash, document.content_hash),
            ).fetchone()
            predecessor = self._conn.execute(
                "SELECT id FROM tutor_lesson_documents WHERE document_kind = 'personalized' AND user_id = %s AND track_id = %s AND knowledge_key = %s ORDER BY created_at DESC, id DESC LIMIT 1",
                (user_id, track_id, document.knowledge_key),
            ).fetchone()
        if existing is not None:
            return str(existing["id"])
        document_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO tutor_lesson_documents (
              id, document_kind, user_id, track_id, knowledge_key, language_id,
              active_plan_revision_id, standard_document_id, predecessor_document_id,
              schema_version, content_standard_version, generator_version, policy_version,
              source_set_hash, profile_hash, title, coverage_keys_json, blocks_json,
              content_hash, change_summary_json, quality_summary_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s::jsonb)
            """,
            (document_id, document_kind, user_id, track_id, document.knowledge_key,
             document.language_id, active_plan_revision_id, standard_document_id,
             str(predecessor["id"]) if predecessor is not None else None,
             document.schema_version, document.content_standard_version,
             generator_version, policy_version, source_set_hash, profile_hash,
             document.title, _json(list(document.coverage_keys)),
             _json([lesson_block_payload(block) for block in document.blocks]),
             document.content_hash, _json(dict(change_summary)), _json(dict(quality_summary))),
        )
        self._insert_document_children(document_id=document_id, document=document, snapshots=snapshots, user_id=user_id, track_id=track_id)
        return document_id

    def _insert_document_children(
        self, *, document_id: str, document: LessonDocumentDraft,
        snapshots: tuple[LessonSourceSnapshot, ...], user_id: str | None, track_id: str | None,
    ) -> None:
        for snapshot in snapshots:
            self._conn.execute(
                """
                INSERT INTO tutor_lesson_source_snapshots (
                  document_id, user_id, track_id, knowledge_key, citation_id,
                  source_id, display_name, provider, trust_tier, source_type,
                  source_version_label, source_version_kind, canonical_url,
                  section_path_json, grounding_chunk_id, document_content_hash,
                  chunk_content_hash, fetched_at, snapshotted_at, evidence_excerpt
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                """,
                (document_id, user_id, track_id, document.knowledge_key, snapshot.citation_id,
                 snapshot.source_id, snapshot.display_name, snapshot.provider, snapshot.trust_tier,
                 snapshot.source_type, snapshot.source_version_label, snapshot.source_version_kind,
                 snapshot.canonical_url, _json(list(snapshot.section_path)), snapshot.grounding_chunk_id,
                 snapshot.document_content_hash, snapshot.chunk_content_hash, snapshot.fetched_at,
                 snapshot.snapshotted_at, snapshot.evidence_excerpt),
            )
        for block in document.blocks:
            for citation_id in block.citation_ids:
                self._conn.execute(
                    "INSERT INTO tutor_lesson_block_citations (document_id, user_id, track_id, knowledge_key, block_id, citation_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (document_id, user_id, track_id, document.knowledge_key, block.block_id, citation_id),
                )
            if isinstance(block, ExerciseGateBlock):
                self._conn.execute(
                    """
                    INSERT INTO tutor_lesson_gate_slots (
                      document_id, user_id, track_id, knowledge_key, block_id, gate_key,
                      gate_kind, assessment_contract_version, required_capabilities_json,
                      learner_prompt_hash, learner_prompt
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (document_id, user_id, track_id, document.knowledge_key, block.block_id,
                     block.gate_key, block.gate_kind, block.assessment_contract_version,
                     _json(list(block.required_capabilities)), hashlib.sha256(block.learner_prompt.encode("utf-8")).hexdigest(),
                     block.learner_prompt),
                )

    def _assign_document(
        self, *, run: LessonAuthoringRunRecord, document_id: str,
        document_hash: str, impact: LessonImpact, now: datetime,
    ) -> tuple[str, str]:
        current = self._conn.execute(
            "SELECT * FROM tutor_lesson_assignments WHERE user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'active' FOR UPDATE",
            (run.user_id, run.track_id, run.knowledge_key),
        ).fetchone()
        if current is not None and str(current["document_id"]) == document_id:
            return str(current["id"]), "active"
        predecessor_id = str(current["id"]) if current is not None else None
        assignment_version = 1 if current is None else _int(current["assignment_version"]) + 1
        status = "proposed" if current is not None and current.get("started_at") is not None else "active"
        if current is not None and status == "active":
            self._conn.execute("UPDATE tutor_lesson_assignments SET status = 'superseded' WHERE id = %s", (current["id"],))
        assignment_id = str(uuid4())
        self._conn.execute(
            """
            INSERT INTO tutor_lesson_assignments (
              id, user_id, track_id, knowledge_key, document_id, source_plan_revision_id,
              predecessor_assignment_id, assignment_version, status, impact_json,
              expected_progress_version, content_hash, activated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            """,
            (assignment_id, run.user_id, run.track_id, run.knowledge_key, document_id,
             run.active_plan_revision_id, predecessor_id, assignment_version, status,
             _json(impact.as_dict()), run.expected_progress_version, document_hash,
             now if status == "active" else None),
        )
        return assignment_id, status


def _run_from_row(row: Mapping[str, object]) -> LessonAuthoringRunRecord:
    return LessonAuthoringRunRecord(
        run_id=str(row["id"]), user_id=str(row["user_id"]), track_id=str(row["track_id"]),
        knowledge_key=str(row["knowledge_key"]), run_kind=str(row["run_kind"]), state=str(row["state"]),
        idempotency_key=str(row["idempotency_key"]), request_hash=str(row["request_hash"]),
        expected_track_version=_int(row["expected_track_version"]),
        expected_progress_version=_int(row["expected_progress_version"]),
        active_plan_revision_id=str(row["active_plan_revision_id"]), profile_hash=str(row["profile_hash"]),
        source_set_hash=_optional_str(row.get("source_set_hash")), attempt_count=_int(row["attempt_count"]),
        lease_generation=_int(row["lease_generation"]), lease_owner=_optional_str(row.get("lease_owner")),
        lease_expires_at=_optional_datetime(row.get("lease_expires_at")), failure_code=_optional_str(row.get("failure_code")),
        failure_message=_optional_str(row.get("failure_message")), standard_document_id=_optional_str(row.get("standard_document_id")),
        personalized_document_id=_optional_str(row.get("personalized_document_id")), assignment_id=_optional_str(row.get("assignment_id")),
        created_at=_datetime(row["created_at"]), updated_at=_datetime(row["updated_at"]),
        terminal_at=_optional_datetime(row.get("terminal_at")),
    )


def _snapshot_from_row(row: Mapping[str, object]) -> LessonSourceSnapshot:
    section = row.get("section_path_json")
    return LessonSourceSnapshot(
        citation_id=str(row["citation_id"]), source_id=str(row["source_id"]),
        display_name=str(row["display_name"]), provider=str(row["provider"]),
        trust_tier=cast(SourceTrustTier, str(row["trust_tier"])), source_type=cast(SourceContentType, str(row["source_type"])),
        source_version_label=str(row["source_version_label"]), source_version_kind=cast(SourceVersionKind, str(row["source_version_kind"])),
        canonical_url=str(row["canonical_url"]),
        section_path=tuple(str(item) for item in section) if isinstance(section, list | tuple) else (),
        grounding_chunk_id=str(row["grounding_chunk_id"]), document_content_hash=str(row["document_content_hash"]),
        chunk_content_hash=str(row["chunk_content_hash"]), fetched_at=_datetime(row["fetched_at"]),
        snapshotted_at=_datetime(row["snapshotted_at"]), evidence_excerpt=str(row["evidence_excerpt"]),
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return int(str(value or 0))


def _float(value: object) -> float:
    return 0.0 if value is None else float(str(value))


def _datetime(value: object) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)
