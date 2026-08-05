"""Explicit PostgreSQL repository for the track-scoped learning domain."""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import (
    LearningPlan,
    LearningPlanModule,
    LearningPlanNode,
    LearningScope,
    LearningScopeKind,
    LearningTaskKind,
    MasteryEvidence,
    MasteryEvidenceKind,
    MasteryIndependence,
    NodeProgressStatus,
    PlanImpact,
    calculate_plan_impact,
    canonical_plan_payload,
)
from app.services.learning.mastery import MasteryProjector, MasteryProjection


class LearningTrackRepositoryError(ValueError):
    pass


class LearningTrackNotFound(LearningTrackRepositoryError):
    pass


class LearningPlanVersionConflict(LearningTrackRepositoryError):
    pass


class LearningPlanActivationInvalid(LearningTrackRepositoryError):
    pass


class LearningScopeConflict(LearningTrackRepositoryError):
    pass


class LearningIdempotencyConflict(LearningTrackRepositoryError):
    pass


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    run_id: str
    user_id: str
    conversation_id: str
    scope_kind: LearningScopeKind
    learning_track_id: str | None
    task_kind: LearningTaskKind
    knowledge_key: str | None
    scope_version: int


class PostgresLearningTrackRepository:
    """Transaction-bound SQL adapter. The service owns the outer transaction."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def create_track(
        self,
        *,
        user_id: str,
        language_id: str,
        goal_text: str,
        target_level: str,
        plan: LearningPlan,
        conversation_id: str | None = None,
    ) -> str:
        track_id = str(uuid4())
        revision_id = str(uuid4())
        initial_key = next((node.knowledge_key for node in plan.nodes if not node.prerequisite_keys), None)
        row = self._conn.execute(
            """
            INSERT INTO tutor_learning_tracks (
              id, user_id, language_id, goal_text, target_level, status, version
            )
            SELECT %s, users.id, %s, %s, %s, 'active', 1
            FROM users WHERE users.id = %s AND users.deleted_at IS NULL
            RETURNING id
            """,
            (track_id, language_id, goal_text, target_level, user_id),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("learner not found")
        self._insert_revision(
            revision_id=revision_id,
            track_id=track_id,
            user_id=user_id,
            predecessor_revision_id=None,
            status="active",
            plan=plan,
            activated_at=datetime.now(UTC),
        )
        self._conn.execute(
            "INSERT INTO tutor_track_active_plans (track_id, user_id, revision_id) VALUES (%s, %s, %s)",
            (track_id, user_id, revision_id),
        )
        self._insert_plan_structure(revision_id=revision_id, track_id=track_id, user_id=user_id, plan=plan)
        self._insert_initial_progress(revision_id=revision_id, track_id=track_id, user_id=user_id, plan=plan)
        if initial_key is not None:
            self._conn.execute(
                "UPDATE tutor_learning_tracks SET current_knowledge_key = %s WHERE id = %s AND user_id = %s",
                (initial_key, track_id, user_id),
            )
        if conversation_id is not None:
            self.bind_conversation_scope(
                user_id=user_id,
                conversation_id=conversation_id,
                scope=LearningScope(
                    scope_kind=LearningScopeKind.LEARNING_TRACK,
                    learning_track_id=track_id,
                    task_kind=LearningTaskKind.LESSON_TEACHING,
                ),
            )
        return track_id

    def list_tracks(self, *, user_id: str) -> tuple[dict[str, object], ...]:
        rows = self._conn.execute(self._TRACK_READ_SQL + " WHERE tracks.user_id = %s" + self._TRACK_GROUP_SQL + " ORDER BY tracks.updated_at DESC, tracks.id DESC", (user_id,)).fetchall()
        return tuple(dict(row) for row in rows)

    def read_track(self, *, user_id: str, track_id: str, for_update: bool = False) -> dict[str, object]:
        lock = " FOR UPDATE OF tracks" if for_update else ""
        row = self._conn.execute(
            self._TRACK_READ_SQL + " WHERE tracks.id = %s AND tracks.user_id = %s" + self._TRACK_GROUP_SQL + lock,
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("learning track not found")
        return dict(row)

    def read_roadmap(self, *, user_id: str, track_id: str) -> dict[str, object]:
        track = self.read_track(user_id=user_id, track_id=track_id)
        rows = self._conn.execute(
            """
            SELECT modules.id AS module_id, modules.module_key, modules.title AS module_title,
                   modules.description AS module_description, modules.order_index AS module_order,
                   modules.is_core AS module_is_core, modules.is_skippable,
                   nodes.id AS node_id, nodes.knowledge_key, nodes.title AS node_title,
                   nodes.description AS node_description, nodes.order_index AS node_order,
                   nodes.is_core AS node_is_core, nodes.prerequisite_keys_json,
                   nodes.required_capabilities_json, progress.status AS progress_status,
                   progress.version AS progress_version, mastery.mastery_level,
                   mastery.confidence AS mastery_confidence
            FROM tutor_track_plan_modules AS modules
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.module_id, nodes.revision_id, nodes.track_id, nodes.user_id) =
                 (modules.id, modules.revision_id, modules.track_id, modules.user_id)
            JOIN tutor_track_node_progress AS progress
              ON (progress.track_id, progress.user_id, progress.knowledge_key) =
                 (nodes.track_id, nodes.user_id, nodes.knowledge_key)
            LEFT JOIN tutor_mastery_states AS mastery
              ON (mastery.track_id, mastery.user_id, mastery.knowledge_key) =
                 (progress.track_id, progress.user_id, progress.knowledge_key)
            WHERE modules.revision_id = %s AND modules.track_id = %s AND modules.user_id = %s
            ORDER BY modules.order_index, nodes.order_index
            """,
            (track["active_revision_id"], track_id, user_id),
        ).fetchall()
        modules: list[dict[str, object]] = []
        by_id: dict[str, dict[str, object]] = {}
        for row in rows:
            module_id = str(row["module_id"])
            module = by_id.get(module_id)
            if module is None:
                module = {
                    "module_id": module_id,
                    "module_key": str(row["module_key"]),
                    "title": str(row["module_title"]),
                    "description": str(row["module_description"]),
                    "order_index": _int(row["module_order"]),
                    "is_core": bool(row["module_is_core"]),
                    "is_skippable": bool(row["is_skippable"]),
                    "nodes": [],
                }
                modules.append(module)
                by_id[module_id] = module
            node_list = module["nodes"]
            assert isinstance(node_list, list)
            node_list.append({
                "node_id": str(row["node_id"]),
                "knowledge_key": str(row["knowledge_key"]),
                "title": str(row["node_title"]),
                "description": str(row["node_description"]),
                "order_index": _int(row["node_order"]),
                "is_core": bool(row["node_is_core"]),
                "prerequisite_keys": _string_list(row.get("prerequisite_keys_json")),
                "required_capabilities": _string_list(row.get("required_capabilities_json")),
                "progress_status": str(row["progress_status"]),
                "progress_version": _int(row["progress_version"]),
                "mastery_level": str(row.get("mastery_level") or "unseen"),
                "mastery_confidence": _float(row.get("mastery_confidence")),
            })
        return {
            "track_id": track_id,
            "active_revision_id": str(track["active_revision_id"]),
            "title": str(track["active_plan_title"]),
            "target_level": str(track["target_level"]),
            "modules": modules,
        }

    def list_revisions(self, *, user_id: str, track_id: str) -> tuple[dict[str, object], ...]:
        self._assert_track(user_id=user_id, track_id=track_id)
        rows = self._conn.execute(
            """
            SELECT revisions.id AS revision_id, revisions.predecessor_revision_id,
                   revisions.status, revisions.title, revisions.target_level,
                   revisions.generator_version, revisions.policy_version,
                   revisions.change_reason, revisions.content_hash,
                   revisions.created_at, revisions.activated_at, migrations.impact_json
            FROM tutor_track_plan_revisions AS revisions
            LEFT JOIN tutor_track_plan_migrations AS migrations
              ON (migrations.to_revision_id, migrations.track_id, migrations.user_id) =
                 (revisions.id, revisions.track_id, revisions.user_id)
            WHERE revisions.track_id = %s AND revisions.user_id = %s
            ORDER BY revisions.created_at DESC, revisions.id DESC
            """,
            (track_id, user_id),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    _TRACK_READ_SQL = """
        SELECT tracks.*, active.revision_id AS active_revision_id,
               revisions.title AS active_plan_title,
               current_node.title AS current_knowledge_title,
               count(progress.knowledge_key)::int AS progress_total,
               count(*) FILTER (WHERE progress.status IN ('completed', 'diagnostic_skipped'))::int AS progress_completed,
               count(*) FILTER (WHERE progress.status = 'in_progress')::int AS progress_in_progress,
               count(*) FILTER (WHERE progress.status = 'review_due')::int AS progress_review_due
        FROM tutor_learning_tracks AS tracks
        JOIN tutor_track_active_plans AS active
          ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
        JOIN tutor_track_plan_revisions AS revisions
          ON (revisions.id, revisions.track_id, revisions.user_id) =
             (active.revision_id, active.track_id, active.user_id)
        LEFT JOIN tutor_track_plan_nodes AS current_node
          ON current_node.revision_id = active.revision_id
         AND current_node.track_id = tracks.id
         AND current_node.user_id = tracks.user_id
         AND current_node.knowledge_key = tracks.current_knowledge_key
        LEFT JOIN tutor_track_plan_nodes AS active_node
          ON active_node.revision_id = active.revision_id
         AND active_node.track_id = tracks.id
         AND active_node.user_id = tracks.user_id
        LEFT JOIN tutor_track_node_progress AS progress
          ON (progress.track_id, progress.user_id, progress.knowledge_key) =
             (active_node.track_id, active_node.user_id, active_node.knowledge_key)
    """
    _TRACK_GROUP_SQL = " GROUP BY tracks.id, active.revision_id, revisions.title, current_node.title"

    def propose_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        expected_track_version: int,
        plan: LearningPlan,
        idempotency_key: str,
        request_hash: str,
    ) -> tuple[str, PlanImpact, int]:
        track = self._lock_track(user_id=user_id, track_id=track_id)
        if str(track["status"]) == "archived":
            raise LearningPlanActivationInvalid("archived tracks cannot receive plan proposals")
        current_version = _int(track["version"])
        if current_version != expected_track_version:
            raise LearningPlanVersionConflict("learning track version changed")
        active = self._active_revision(user_id=user_id, track_id=track_id)
        current_plan = _plan_from_row(active)
        progress_rows = self._conn.execute(
            "SELECT knowledge_key FROM tutor_track_node_progress WHERE track_id = %s AND user_id = %s",
            (track_id, user_id),
        ).fetchall()
        impact = calculate_plan_impact(
            current_plan,
            plan,
            progress_keys={str(row["knowledge_key"]) for row in progress_rows},
        )
        revision_id = str(uuid4())
        next_version = current_version + 1
        self._insert_revision(
            revision_id=revision_id,
            track_id=track_id,
            user_id=user_id,
            predecessor_revision_id=str(active["id"]),
            status="proposed",
            plan=plan,
            activated_at=None,
        )
        self._insert_plan_structure(revision_id=revision_id, track_id=track_id, user_id=user_id, plan=plan)
        self._conn.execute(
            """
            INSERT INTO tutor_track_plan_migrations (
              track_id, user_id, from_revision_id, to_revision_id, status,
              impact_json, expected_track_version, idempotency_key, request_hash
            ) VALUES (%s, %s, %s, %s, 'proposed', %s::jsonb, %s, %s, %s)
            """,
            (
                track_id, user_id, active["id"], revision_id, _json(impact.as_dict()),
                next_version, idempotency_key, request_hash,
            ),
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_learning_tracks SET version = version + 1
            WHERE id = %s AND user_id = %s AND version = %s RETURNING version
            """,
            (track_id, user_id, current_version),
        ).fetchone()
        if updated is None:
            raise LearningPlanVersionConflict("learning track version changed")
        return revision_id, impact, _int(updated["version"])

    def activate_revision(
        self,
        *,
        user_id: str,
        track_id: str,
        revision_id: str,
        expected_track_version: int,
    ) -> int:
        track = self._lock_track(user_id=user_id, track_id=track_id)
        current_version = _int(track["version"])
        if current_version != expected_track_version:
            raise LearningPlanVersionConflict("learning track version changed")
        active = self._active_revision(user_id=user_id, track_id=track_id)
        candidate = self._conn.execute(
            "SELECT * FROM tutor_track_plan_revisions WHERE id = %s AND track_id = %s AND user_id = %s FOR UPDATE",
            (revision_id, track_id, user_id),
        ).fetchone()
        if candidate is None:
            raise LearningTrackNotFound("learning plan revision not found")
        if (
            str(candidate["status"]) != "proposed"
            or str(candidate.get("predecessor_revision_id") or "") != str(active["id"])
        ):
            raise LearningPlanActivationInvalid("plan revision is not the direct proposed successor")
        migration = self._conn.execute(
            "SELECT * FROM tutor_track_plan_migrations WHERE track_id = %s AND user_id = %s AND to_revision_id = %s FOR UPDATE",
            (track_id, user_id, revision_id),
        ).fetchone()
        if migration is None or str(migration["status"]) != "proposed" or _int(migration["expected_track_version"]) != current_version:
            raise LearningPlanActivationInvalid("plan migration is no longer activatable")
        now = datetime.now(UTC)
        self._conn.execute("UPDATE tutor_track_plan_revisions SET status = 'superseded' WHERE id = %s", (active["id"],))
        self._conn.execute(
            "UPDATE tutor_track_plan_revisions SET status = 'active', activated_at = %s WHERE id = %s",
            (now, revision_id),
        )
        self._conn.execute(
            "UPDATE tutor_track_active_plans SET revision_id = %s WHERE track_id = %s AND user_id = %s",
            (revision_id, track_id, user_id),
        )
        candidate_plan = _plan_from_row(candidate)
        retained_rows = self._conn.execute(
            "SELECT knowledge_key, status FROM tutor_track_node_progress WHERE track_id = %s AND user_id = %s",
            (track_id, user_id),
        ).fetchall()
        retained_statuses = {str(row["knowledge_key"]): str(row["status"]) for row in retained_rows}
        satisfied_statuses = {NodeProgressStatus.COMPLETED.value, NodeProgressStatus.DIAGNOSTIC_SKIPPED.value}
        for node in candidate_plan.nodes:
            prerequisites_satisfied = all(
                retained_statuses.get(prerequisite) in satisfied_statuses
                for prerequisite in node.prerequisite_keys
            )
            initial = NodeProgressStatus.AVAILABLE if prerequisites_satisfied else NodeProgressStatus.LOCKED
            self._conn.execute(
                """
                INSERT INTO tutor_track_node_progress (
                  track_id, user_id, knowledge_key, status, source_plan_revision_id
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (track_id, knowledge_key) DO NOTHING
                """,
                (track_id, user_id, node.knowledge_key, initial.value, revision_id),
            )
            self._conn.execute(
                """
                INSERT INTO tutor_mastery_states (
                  track_id, user_id, knowledge_key, confidence, mastery_level,
                  strengths_json, weaknesses_json, evidence_count, last_evidence_id,
                  projector_version, version
                ) VALUES (%s, %s, %s, 0, 'unseen', '[]'::jsonb, '[]'::jsonb, 0, NULL, 'learning_mastery_v1', 1)
                ON CONFLICT (track_id, knowledge_key) DO NOTHING
                """,
                (track_id, user_id, node.knowledge_key),
            )
        candidate_keys = {node.knowledge_key for node in candidate_plan.nodes}
        current_key = str(track.get("current_knowledge_key") or "")
        if current_key not in candidate_keys:
            current_key = next((node.knowledge_key for node in candidate_plan.nodes if not node.prerequisite_keys), candidate_plan.nodes[0].knowledge_key)
        self._conn.execute(
            "UPDATE tutor_track_plan_migrations SET status = 'applied', confirmed_at = %s, applied_at = %s WHERE id = %s",
            (now, now, migration["id"]),
        )
        updated = self._conn.execute(
            """
            UPDATE tutor_learning_tracks
            SET version = version + 1, current_knowledge_key = %s, target_level = %s
            WHERE id = %s AND user_id = %s AND version = %s RETURNING version
            """,
            (current_key, candidate_plan.target_level, track_id, user_id, current_version),
        ).fetchone()
        if updated is None:
            raise LearningPlanVersionConflict("learning track version changed")
        return _int(updated["version"])

    def bind_conversation_scope(
        self,
        *,
        user_id: str,
        conversation_id: str,
        scope: LearningScope,
        allowed_foreground_run_id: str | None = None,
    ) -> int:
        conversation = self._conn.execute(
            """
            SELECT id FROM tutor_conversations
            WHERE id = %s AND user_id = %s AND visibility = 'learner'
              AND kind = 'interactive' AND status = 'active' FOR UPDATE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if conversation is None:
            raise LearningTrackNotFound("Tutor conversation not found")
        active = self._conn.execute(
            """
            SELECT id FROM tutor_runs
            WHERE conversation_id = %s AND user_id = %s AND origin = 'interactive'
              AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
            FOR UPDATE
            """,
            (conversation_id, user_id),
        ).fetchone()
        if active is not None and str(active["id"]) != str(allowed_foreground_run_id or ""):
            raise LearningScopeConflict("conversation scope cannot change during an active foreground run")
        self._assert_scope_target(user_id=user_id, scope=scope)
        existing = self._conn.execute(
            "SELECT * FROM tutor_conversation_learning_scopes WHERE conversation_id = %s AND user_id = %s FOR UPDATE",
            (conversation_id, user_id),
        ).fetchone()
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO tutor_conversation_learning_scopes (
                  conversation_id, user_id, scope_kind, learning_track_id, version
                ) VALUES (%s, %s, %s, %s, 1)
                """,
                (conversation_id, user_id, scope.scope_kind.value, scope.learning_track_id),
            )
            return 1
        same = str(existing["scope_kind"]) == scope.scope_kind.value and _optional_str(existing.get("learning_track_id")) == scope.learning_track_id
        if same:
            return _int(existing["version"])
        updated = self._conn.execute(
            """
            UPDATE tutor_conversation_learning_scopes
            SET scope_kind = %s, learning_track_id = %s, version = version + 1
            WHERE conversation_id = %s AND user_id = %s RETURNING version
            """,
            (scope.scope_kind.value, scope.learning_track_id, conversation_id, user_id),
        ).fetchone()
        if updated is None:
            raise LearningScopeConflict("conversation scope update failed")
        return _int(updated["version"])

    def snapshot_run_scope(
        self,
        *,
        user_id: str,
        run_id: str,
        explicit_scope: LearningScope | None = None,
    ) -> ScopeSnapshot:
        run = self._conn.execute(
            "SELECT id, conversation_id FROM tutor_runs WHERE id = %s AND user_id = %s AND origin = 'interactive' FOR UPDATE",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise LearningTrackNotFound("Tutor run not found")
        conversation_id = str(run["conversation_id"])
        if explicit_scope is not None:
            scope_version = self.bind_conversation_scope(
                user_id=user_id,
                conversation_id=conversation_id,
                scope=explicit_scope,
                allowed_foreground_run_id=run_id,
            )
            scope = explicit_scope
        else:
            row = self._conn.execute(
                "SELECT scope_kind, learning_track_id, version FROM tutor_conversation_learning_scopes WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            ).fetchone()
            if row is None:
                scope = LearningScope()
                scope_version = 0
            else:
                scope = LearningScope(
                    scope_kind=LearningScopeKind(str(row["scope_kind"])),
                    learning_track_id=_optional_str(row.get("learning_track_id")),
                )
                scope_version = _int(row["version"])
        self._assert_scope_target(user_id=user_id, scope=scope)
        expected = ScopeSnapshot(
            run_id=run_id,
            user_id=user_id,
            conversation_id=conversation_id,
            scope_kind=scope.scope_kind,
            learning_track_id=scope.learning_track_id,
            task_kind=scope.task_kind or LearningTaskKind.GENERAL_TUTOR,
            knowledge_key=scope.knowledge_key,
            scope_version=scope_version,
        )
        existing = self._conn.execute(
            "SELECT * FROM tutor_run_learning_scopes WHERE run_id = %s AND user_id = %s",
            (run_id, user_id),
        ).fetchone()
        if existing is not None:
            snapshot = _scope_snapshot_from_row(existing)
            if snapshot != expected:
                raise LearningScopeConflict("run scope snapshot is immutable")
            return snapshot
        self._conn.execute(
            """
            INSERT INTO tutor_run_learning_scopes (
              run_id, user_id, conversation_id, scope_kind, learning_track_id,
              task_kind, knowledge_key, scope_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id, user_id, conversation_id, scope.scope_kind.value, scope.learning_track_id,
                (scope.task_kind or LearningTaskKind.GENERAL_TUTOR).value, scope.knowledge_key, scope_version,
            ),
        )
        return expected

    def read_run_scope(self, *, user_id: str, run_id: str) -> ScopeSnapshot:
        row = self._conn.execute(
            """
            SELECT scopes.*, runs.conversation_id AS run_conversation_id
            FROM tutor_runs AS runs LEFT JOIN tutor_run_learning_scopes AS scopes ON scopes.run_id = runs.id
            WHERE runs.id = %s AND runs.user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("Tutor run not found")
        if row.get("scope_kind") is None:
            return ScopeSnapshot(
                run_id=run_id, user_id=user_id, conversation_id=str(row["run_conversation_id"]),
                scope_kind=LearningScopeKind.GENERAL, learning_track_id=None,
                task_kind=LearningTaskKind.GENERAL_TUTOR, knowledge_key=None, scope_version=0,
            )
        return _scope_snapshot_from_row(row)

    def append_mastery_evidence(
        self,
        *,
        user_id: str,
        track_id: str,
        evidence: MasteryEvidence,
        projector: MasteryProjector | None = None,
    ) -> tuple[str, MasteryProjection, bool]:
        self._assert_progress(user_id=user_id, track_id=track_id, knowledge_key=evidence.knowledge_key)
        existing = self._conn.execute(
            """
            SELECT * FROM tutor_mastery_evidence
            WHERE track_id = %s AND evidence_kind = %s AND source_receipt_id = %s FOR UPDATE
            """,
            (track_id, evidence.evidence_kind.value, evidence.source_receipt_id),
        ).fetchone()
        replayed = existing is not None
        evidence_id = evidence.evidence_id
        if existing is not None:
            existing_summary = (
                dict(existing["evidence_summary_json"])
                if isinstance(existing["evidence_summary_json"], Mapping)
                else {}
            )
            if (
                str(existing["user_id"]) != user_id
                or str(existing["knowledge_key"]) != evidence.knowledge_key
                or str(existing["source_receipt_hash"]) != evidence.source_receipt_hash
                or str(existing["independence"]) != evidence.independence.value
                or _float(existing["score"]) != evidence.score
                or _int(existing["hint_count"]) != evidence.hint_count
                or _int(existing["attempt_count"]) != evidence.attempt_count
                or existing_summary != dict(evidence.summary)
            ):
                raise LearningIdempotencyConflict("mastery evidence receipt conflicts with stored evidence")
            evidence_id = str(existing["id"])
            stored = self._load_mastery_evidence(
                user_id=user_id,
                track_id=track_id,
                knowledge_key=evidence.knowledge_key,
            )
            projection = (projector or MasteryProjector()).project(
                knowledge_key=evidence.knowledge_key,
                evidence=stored,
            )
            return evidence_id, projection, True
        else:
            self._conn.execute(
                """
                INSERT INTO tutor_mastery_evidence (
                  id, track_id, user_id, knowledge_key, evidence_kind,
                  source_receipt_id, source_receipt_hash, independence, score,
                  hint_count, attempt_count, evidence_summary_json, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    evidence_id, track_id, user_id, evidence.knowledge_key, evidence.evidence_kind.value,
                    evidence.source_receipt_id, evidence.source_receipt_hash, evidence.independence.value,
                    evidence.score, evidence.hint_count, evidence.attempt_count,
                    _json(dict(evidence.summary)), evidence.created_at,
                ),
            )
        stored = self._load_mastery_evidence(user_id=user_id, track_id=track_id, knowledge_key=evidence.knowledge_key)
        projection = (projector or MasteryProjector()).project(knowledge_key=evidence.knowledge_key, evidence=stored)
        self._upsert_mastery_projection(user_id=user_id, track_id=track_id, projection=projection)
        return evidence_id, projection, replayed

    def _insert_revision(
        self,
        *,
        revision_id: str,
        track_id: str,
        user_id: str,
        predecessor_revision_id: str | None,
        status: str,
        plan: LearningPlan,
        activated_at: datetime | None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_track_plan_revisions (
              id, track_id, user_id, predecessor_revision_id, status, title,
              target_level, plan_json, generator_version, policy_version,
              change_reason, content_hash, activated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
            """,
            (
                revision_id, track_id, user_id, predecessor_revision_id, status,
                plan.title, plan.target_level, _json(canonical_plan_payload(plan)),
                plan.generator_version, plan.policy_version, plan.change_reason,
                plan.content_hash, activated_at,
            ),
        )

    def _insert_plan_structure(
        self,
        *,
        revision_id: str,
        track_id: str,
        user_id: str,
        plan: LearningPlan,
    ) -> None:
        for module in plan.modules:
            module_id = str(uuid4())
            self._conn.execute(
                """
                INSERT INTO tutor_track_plan_modules (
                  id, revision_id, track_id, user_id, module_key, title,
                  description, order_index, is_core, is_skippable
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    module_id, revision_id, track_id, user_id, module.module_key,
                    module.title, module.description, module.order_index, module.is_core, module.is_skippable,
                ),
            )
            for node in module.nodes:
                self._conn.execute(
                    """
                    INSERT INTO tutor_track_plan_nodes (
                      module_id, revision_id, track_id, user_id, knowledge_key,
                      title, description, order_index, is_core,
                      prerequisite_keys_json, required_capabilities_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                    """,
                    (
                        module_id, revision_id, track_id, user_id, node.knowledge_key,
                        node.title, node.description, node.order_index, node.is_core,
                        _json(list(node.prerequisite_keys)), _json(list(node.required_capabilities)),
                    ),
                )

    def _insert_initial_progress(
        self,
        *,
        revision_id: str,
        track_id: str,
        user_id: str,
        plan: LearningPlan,
    ) -> None:
        for node in plan.nodes:
            status = NodeProgressStatus.AVAILABLE if not node.prerequisite_keys else NodeProgressStatus.LOCKED
            self._conn.execute(
                """
                INSERT INTO tutor_track_node_progress (
                  track_id, user_id, knowledge_key, status, source_plan_revision_id
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (track_id, user_id, node.knowledge_key, status.value, revision_id),
            )
            self._conn.execute(
                """
                INSERT INTO tutor_mastery_states (
                  track_id, user_id, knowledge_key, confidence, mastery_level,
                  strengths_json, weaknesses_json, evidence_count, last_evidence_id,
                  projector_version, version
                ) VALUES (%s, %s, %s, 0, 'unseen', '[]'::jsonb, '[]'::jsonb, 0, NULL, 'learning_mastery_v1', 1)
                """,
                (track_id, user_id, node.knowledge_key),
            )

    def _lock_track(self, *, user_id: str, track_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_learning_tracks WHERE id = %s AND user_id = %s FOR UPDATE",
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("learning track not found")
        return row

    def _assert_track(self, *, user_id: str, track_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM tutor_learning_tracks WHERE id = %s AND user_id = %s",
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("learning track not found")

    def _active_revision(self, *, user_id: str, track_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            """
            SELECT revisions.*
            FROM tutor_track_active_plans AS active
            JOIN tutor_track_plan_revisions AS revisions
              ON (revisions.id, revisions.track_id, revisions.user_id) =
                 (active.revision_id, active.track_id, active.user_id)
            WHERE active.track_id = %s AND active.user_id = %s FOR UPDATE OF active, revisions
            """,
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise LearningPlanActivationInvalid("active learning plan is missing")
        return row

    def _assert_scope_target(self, *, user_id: str, scope: LearningScope) -> None:
        if scope.scope_kind is not LearningScopeKind.LEARNING_TRACK:
            return
        assert scope.learning_track_id is not None
        self._assert_track(user_id=user_id, track_id=scope.learning_track_id)
        if scope.knowledge_key is not None:
            active_node = self._conn.execute(
                """
                SELECT 1
                FROM tutor_track_active_plans AS active
                JOIN tutor_track_plan_nodes AS nodes
                  ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
                     (active.revision_id, active.track_id, active.user_id)
                WHERE active.track_id = %s AND active.user_id = %s
                  AND nodes.knowledge_key = %s
                """,
                (scope.learning_track_id, user_id, scope.knowledge_key),
            ).fetchone()
            if active_node is None:
                raise LearningTrackNotFound("learning track knowledge node not found in the active plan")
            self._assert_progress(
                user_id=user_id,
                track_id=scope.learning_track_id,
                knowledge_key=scope.knowledge_key,
            )

    def _assert_progress(self, *, user_id: str, track_id: str, knowledge_key: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM tutor_track_node_progress WHERE track_id = %s AND user_id = %s AND knowledge_key = %s",
            (track_id, user_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise LearningTrackNotFound("learning track knowledge node not found")

    def _load_mastery_evidence(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_key: str,
    ) -> tuple[MasteryEvidence, ...]:
        rows = self._conn.execute(
            """
            SELECT * FROM tutor_mastery_evidence
            WHERE track_id = %s AND user_id = %s AND knowledge_key = %s
            ORDER BY created_at, id
            """,
            (track_id, user_id, knowledge_key),
        ).fetchall()
        return tuple(
            MasteryEvidence(
                evidence_id=str(row["id"]),
                knowledge_key=str(row["knowledge_key"]),
                evidence_kind=MasteryEvidenceKind(str(row["evidence_kind"])),
                source_receipt_id=str(row["source_receipt_id"]),
                source_receipt_hash=str(row["source_receipt_hash"]),
                independence=MasteryIndependence(str(row["independence"])),
                score=_float(row["score"]),
                hint_count=_int(row["hint_count"]),
                attempt_count=_int(row["attempt_count"]),
                summary=dict(row["evidence_summary_json"]) if isinstance(row["evidence_summary_json"], Mapping) else {},
                created_at=_datetime(row["created_at"]),
            )
            for row in rows
        )

    def _upsert_mastery_projection(
        self,
        *,
        user_id: str,
        track_id: str,
        projection: MasteryProjection,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO tutor_mastery_states (
              track_id, user_id, knowledge_key, confidence, mastery_level,
              strengths_json, weaknesses_json, evidence_count, last_evidence_id,
              projector_version, version
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, 1)
            ON CONFLICT (track_id, knowledge_key) DO UPDATE SET
              user_id = EXCLUDED.user_id,
              confidence = EXCLUDED.confidence,
              mastery_level = EXCLUDED.mastery_level,
              strengths_json = EXCLUDED.strengths_json,
              weaknesses_json = EXCLUDED.weaknesses_json,
              evidence_count = EXCLUDED.evidence_count,
              last_evidence_id = EXCLUDED.last_evidence_id,
              projector_version = EXCLUDED.projector_version,
              version = tutor_mastery_states.version + 1
            """,
            (
                track_id, user_id, projection.knowledge_key, projection.confidence,
                projection.mastery_level.value, _json(list(projection.strengths)),
                _json(list(projection.weaknesses)), projection.evidence_count,
                projection.last_evidence_id, projection.projector_version,
            ),
        )


def _plan_from_row(row: Mapping[str, object]) -> LearningPlan:
    payload = row.get("plan_json")
    if not isinstance(payload, Mapping):
        raise LearningPlanActivationInvalid("stored learning plan is invalid")
    raw_modules = payload.get("modules")
    if not isinstance(raw_modules, list | tuple):
        raise LearningPlanActivationInvalid("stored learning plan modules are invalid")
    modules: list[LearningPlanModule] = []
    for raw_module in raw_modules:
        if not isinstance(raw_module, Mapping):
            raise LearningPlanActivationInvalid("stored learning plan module is invalid")
        raw_nodes = raw_module.get("nodes")
        if not isinstance(raw_nodes, list | tuple):
            raise LearningPlanActivationInvalid("stored learning plan nodes are invalid")
        nodes = tuple(
            LearningPlanNode(
                knowledge_key=str(raw_node["knowledge_key"]),
                title=str(raw_node["title"]),
                description=str(raw_node.get("description") or ""),
                order_index=_int(raw_node["order_index"]),
                is_core=bool(raw_node.get("is_core", True)),
                prerequisite_keys=tuple(_string_list(raw_node.get("prerequisite_keys"))),
                required_capabilities=tuple(_string_list(raw_node.get("required_capabilities"))),
            )
            for raw_node in raw_nodes if isinstance(raw_node, Mapping)
        )
        modules.append(
            LearningPlanModule(
                module_key=str(raw_module["module_key"]),
                title=str(raw_module["title"]),
                description=str(raw_module.get("description") or ""),
                order_index=_int(raw_module["order_index"]),
                is_core=bool(raw_module.get("is_core", True)),
                is_skippable=bool(raw_module.get("is_skippable", False)),
                nodes=nodes,
            )
        )
    return LearningPlan(
        title=str(row["title"]),
        target_level=str(row["target_level"]),
        generator_version=str(row["generator_version"]),
        policy_version=str(row["policy_version"]),
        change_reason=str(row["change_reason"]),
        modules=tuple(modules),
    )


def _scope_snapshot_from_row(row: Mapping[str, object]) -> ScopeSnapshot:
    return ScopeSnapshot(
        run_id=str(row["run_id"]),
        user_id=str(row["user_id"]),
        conversation_id=str(row["conversation_id"]),
        scope_kind=LearningScopeKind(str(row["scope_kind"])),
        learning_track_id=_optional_str(row.get("learning_track_id")),
        task_kind=LearningTaskKind(str(row["task_kind"])),
        knowledge_key=_optional_str(row.get("knowledge_key")),
        scope_version=_int(row["scope_version"]),
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float | str | bytes | bytearray):
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    return 0


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, Decimal | int | float | str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise LearningTrackRepositoryError("stored timestamp is invalid")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list | tuple) else []


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None
