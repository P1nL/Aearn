"""PostgreSQL authority for track-scoped spaced-review schedules."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import uuid4

from psycopg import Connection

from app.services.learning.contracts import MasteryEvidence, MasteryEvidenceKind, MasteryIndependence
from app.services.learning.reviews.contracts import (
    REVIEW_POLICY_VERSION,
    ReviewCardState,
    ReviewRating,
    ReviewRiskLevel,
    ReviewScheduleSnapshot,
)
from app.services.learning.reviews.persistence import (
    ReviewNotFound,
    ReviewVersionConflict,
    as_datetime,
    as_float,
    as_int,
    content_hash,
    json_text,
    string_list,
    utc,
)
from app.services.learning.reviews.scheduler import current_risk, seed_schedule_from_evidence


class PostgresReviewScheduleRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def seed_from_evidence(
        self,
        *,
        user_id: str,
        track_id: str,
        evidence: MasteryEvidence,
        now: datetime | None = None,
    ) -> bool:
        if evidence.evidence_kind in {MasteryEvidenceKind.REVIEW, MasteryEvidenceKind.MODULE_DIAGNOSTIC}:
            return False
        current = utc(now or evidence.created_at)
        active = self._active_scope(user_id=user_id, track_id=track_id, knowledge_key=evidence.knowledge_key)
        schedule = seed_schedule_from_evidence(evidence=evidence, now=current)
        inserted = self._conn.execute(
            """
            INSERT INTO tutor_review_schedule_states (
              user_id, track_id, knowledge_key, source_plan_revision_id, status,
              card_state, stability, difficulty, due_at, review_count, lapse_count,
              last_rating, risk_level, scheduler_version
            ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s, 0, 0, NULL, %s, %s)
            ON CONFLICT (track_id, knowledge_key) DO NOTHING RETURNING *
            """,
            (
                user_id, track_id, evidence.knowledge_key, active["plan_revision_id"],
                schedule.card_state.value, schedule.stability, schedule.difficulty,
                schedule.due_at, schedule.risk_level.value, schedule.scheduler_version,
            ),
        ).fetchone()
        if inserted is None:
            return False
        self.insert_event(
            schedule_row=inserted,
            source_kind="mastery_seed",
            source_receipt_id=evidence.source_receipt_id,
            reason_codes=("trusted_mastery_seed",),
            previous={},
            next_state=schedule_payload(schedule),
            now=current,
        )
        return True

    def seed_diagnostic_skip(
        self,
        *,
        user_id: str,
        track_id: str,
        knowledge_keys: Sequence[str],
        source_receipt_id: str,
        now: datetime,
    ) -> int:
        created = 0
        for key in knowledge_keys:
            evidence = MasteryEvidence(
                evidence_id=str(uuid4()),
                knowledge_key=key,
                evidence_kind=MasteryEvidenceKind.MODULE_DIAGNOSTIC,
                source_receipt_id=f"{source_receipt_id}:{key}",
                source_receipt_hash=content_hash({"source": source_receipt_id, "knowledge_key": key}),
                independence=MasteryIndependence.INDEPENDENT,
                score=1.0,
                hint_count=0,
                attempt_count=1,
                summary={"kind": "diagnostic_skipped_module"},
                created_at=now,
            )
            active = self._active_scope(user_id=user_id, track_id=track_id, knowledge_key=key)
            schedule = seed_schedule_from_evidence(evidence=evidence, now=now)
            row = self._conn.execute(
                """
                INSERT INTO tutor_review_schedule_states (
                  user_id, track_id, knowledge_key, source_plan_revision_id, status,
                  card_state, stability, difficulty, due_at, review_count, lapse_count,
                  last_rating, risk_level, scheduler_version
                ) VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s, 0, 0, NULL, %s, %s)
                ON CONFLICT (track_id, knowledge_key) DO NOTHING RETURNING *
                """,
                (
                    user_id, track_id, key, active["plan_revision_id"], schedule.card_state.value,
                    schedule.stability, schedule.difficulty, schedule.due_at,
                    schedule.risk_level.value, schedule.scheduler_version,
                ),
            ).fetchone()
            if row is None:
                continue
            self.insert_event(
                schedule_row=row,
                source_kind="diagnostic_skip",
                source_receipt_id=source_receipt_id,
                reason_codes=("diagnostic_skip_low_frequency",),
                previous={},
                next_state=schedule_payload(schedule),
                now=now,
            )
            created += 1
        return created

    def read(self, *, user_id: str, track_id: str, knowledge_key: str, for_update: bool = False) -> dict[str, object]:
        lock = " FOR UPDATE" if for_update else ""
        row = self._conn.execute(
            """
            SELECT * FROM tutor_review_schedule_states
            WHERE user_id = %s AND track_id = %s AND knowledge_key = %s
            """ + lock,
            (user_id, track_id, knowledge_key),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("review schedule was not found")
        return dict(row)

    def read_queue(self, *, user_id: str, track_id: str, now: datetime) -> dict[str, object]:
        track = self._track_scope(user_id=user_id, track_id=track_id)
        rows = self._conn.execute(
            """
            SELECT schedules.*, nodes.title, nodes.required_capabilities_json,
                   mastery.confidence, mastery.mastery_level
            FROM tutor_review_schedule_states AS schedules
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (schedules.track_id, schedules.user_id)
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id, nodes.knowledge_key) =
                 (active.revision_id, schedules.track_id, schedules.user_id, schedules.knowledge_key)
            LEFT JOIN tutor_mastery_states AS mastery
              ON (mastery.track_id, mastery.user_id, mastery.knowledge_key) =
                 (schedules.track_id, schedules.user_id, schedules.knowledge_key)
            WHERE schedules.user_id = %s AND schedules.track_id = %s
              AND schedules.status = 'active'
              AND (schedules.due_at <= %s OR schedules.risk_level = 'critical')
            ORDER BY schedules.due_at, schedules.knowledge_key
            """,
            (user_id, track_id, now),
        ).fetchall()
        prerequisites = self.current_prerequisites(
            user_id=user_id,
            track_id=track_id,
            revision_id=str(track["plan_revision_id"]),
            current_key=str(track.get("current_knowledge_key") or ""),
        )
        items: list[dict[str, object]] = []
        for row in rows:
            schedule = schedule_from_row(row)
            risk = current_risk(schedule=schedule, now=now)
            critical_gate = schedule.knowledge_key in prerequisites and risk is ReviewRiskLevel.CRITICAL
            items.append(
                {
                    "schedule_id": str(row["id"]),
                    "knowledge_key": schedule.knowledge_key,
                    "title": str(row["title"]),
                    "due_at": schedule.due_at,
                    "risk_level": risk.value,
                    "critical_prerequisite_gate": critical_gate,
                    "mastery": {
                        "confidence": as_float(row.get("confidence")),
                        "mastery_level": str(row.get("mastery_level") or "unseen"),
                    },
                    "required_capabilities": string_list(row.get("required_capabilities_json")),
                    "schedule_version": as_int(row["version"]),
                }
            )
        return {
            "track_id": track_id,
            "as_of": utc(now),
            "due_count": len(items),
            "items": items,
            "critical_prerequisite_gate": next(
                (item for item in items if item["critical_prerequisite_gate"]), None
            ),
        }

    def update_after_review(
        self,
        *,
        schedule_row: Mapping[str, object],
        next_schedule: ReviewScheduleSnapshot,
        now: datetime,
    ) -> dict[str, object]:
        updated = self._conn.execute(
            """
            UPDATE tutor_review_schedule_states
            SET card_state = %s, stability = %s, difficulty = %s, due_at = %s,
                last_review_at = %s, review_count = %s, lapse_count = %s,
                last_rating = %s, risk_level = %s, scheduler_version = %s,
                version = version + 1
            WHERE id = %s AND version = %s RETURNING *
            """,
            (
                next_schedule.card_state.value, next_schedule.stability,
                next_schedule.difficulty, next_schedule.due_at, now,
                next_schedule.review_count, next_schedule.lapse_count,
                next_schedule.last_rating.value if next_schedule.last_rating else None,
                next_schedule.risk_level.value, next_schedule.scheduler_version,
                schedule_row["id"], schedule_row["version"],
            ),
        ).fetchone()
        if updated is None:
            raise ReviewVersionConflict("review schedule changed")
        return dict(updated)

    def migrate_plan(
        self,
        *,
        user_id: str,
        track_id: str,
        to_revision_id: str,
        retained_keys: Sequence[str],
        removed_keys: Sequence[str],
        migration_id: str,
        now: datetime,
    ) -> None:
        for key in retained_keys:
            row = self._conn.execute(
                """SELECT * FROM tutor_review_schedule_states
                WHERE user_id = %s AND track_id = %s AND knowledge_key = %s FOR UPDATE""",
                (user_id, track_id, key),
            ).fetchone()
            if row is None:
                continue
            previous = schedule_payload(schedule_from_row(row))
            next_card = "review" if str(row["status"]) == "suspended" else str(row["card_state"])
            updated = self._conn.execute(
                """
                UPDATE tutor_review_schedule_states
                SET source_plan_revision_id = %s, status = 'active', card_state = %s,
                    due_at = CASE WHEN status = 'suspended' THEN %s ELSE due_at END,
                    risk_level = CASE WHEN status = 'suspended' THEN 'normal' ELSE risk_level END,
                    version = version + 1
                WHERE id = %s RETURNING *
                """,
                (to_revision_id, next_card, now, row["id"]),
            ).fetchone()
            assert updated is not None
            self.insert_event(
                schedule_row=updated,
                source_kind="plan_migration",
                source_receipt_id=f"{migration_id}:retained:{key}",
                reason_codes=("stable_knowledge_key_retained",),
                previous=previous,
                next_state=schedule_payload(schedule_from_row(updated)),
                now=now,
            )
        for key in removed_keys:
            row = self._conn.execute(
                """SELECT * FROM tutor_review_schedule_states
                WHERE user_id = %s AND track_id = %s AND knowledge_key = %s AND status = 'active' FOR UPDATE""",
                (user_id, track_id, key),
            ).fetchone()
            if row is None:
                continue
            previous = schedule_payload(schedule_from_row(row))
            updated = self._conn.execute(
                """
                UPDATE tutor_review_schedule_states
                SET source_plan_revision_id = %s, status = 'suspended', card_state = 'suspended',
                    risk_level = 'low', version = version + 1
                WHERE id = %s RETURNING *
                """,
                (to_revision_id, row["id"]),
            ).fetchone()
            assert updated is not None
            self.insert_event(
                schedule_row=updated,
                source_kind="plan_migration",
                source_receipt_id=f"{migration_id}:removed:{key}",
                reason_codes=("knowledge_key_removed",),
                previous=previous,
                next_state=schedule_payload(schedule_from_row(updated)),
                now=now,
            )

    def insert_event(
        self,
        *,
        schedule_row: Mapping[str, object],
        source_kind: str,
        source_receipt_id: str,
        reason_codes: Sequence[str],
        previous: Mapping[str, object],
        next_state: Mapping[str, object],
        now: datetime,
    ) -> str:
        event_id = str(uuid4())
        payload = {
            "schedule_id": str(schedule_row["id"]),
            "source_kind": source_kind,
            "source_receipt_id": source_receipt_id,
            "reason_codes": list(reason_codes),
            "previous": dict(previous),
            "next": dict(next_state),
            "scheduler_version": REVIEW_POLICY_VERSION,
        }
        self._conn.execute(
            """
            INSERT INTO tutor_review_schedule_events (
              id, schedule_id, user_id, track_id, knowledge_key, source_kind,
              source_receipt_id, reason_codes_json, previous_state_json,
              next_state_json, event_hash, scheduler_version, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
            """,
            (
                event_id, schedule_row["id"], schedule_row["user_id"], schedule_row["track_id"],
                schedule_row["knowledge_key"], source_kind, source_receipt_id,
                json_text(list(reason_codes)), json_text(previous), json_text(next_state),
                content_hash(payload), REVIEW_POLICY_VERSION, now,
            ),
        )
        return event_id

    def current_prerequisites(
        self,
        *,
        user_id: str,
        track_id: str,
        revision_id: str,
        current_key: str,
    ) -> set[str]:
        if not current_key:
            return set()
        rows = self._conn.execute(
            """SELECT knowledge_key, prerequisite_keys_json FROM tutor_track_plan_nodes
            WHERE revision_id = %s AND track_id = %s AND user_id = %s""",
            (revision_id, track_id, user_id),
        ).fetchall()
        graph = {str(row["knowledge_key"]): string_list(row.get("prerequisite_keys_json")) for row in rows}
        found: set[str] = set()
        pending = list(graph.get(current_key, ()))
        while pending:
            key = pending.pop()
            if key in found:
                continue
            found.add(key)
            pending.extend(graph.get(key, ()))
        return found

    def _track_scope(self, *, user_id: str, track_id: str) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT tracks.*, active.revision_id AS plan_revision_id
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            WHERE tracks.id = %s AND tracks.user_id = %s
            """,
            (track_id, user_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("LearningTrack was not found")
        return dict(row)

    def _active_scope(self, *, user_id: str, track_id: str, knowledge_key: str) -> dict[str, object]:
        row = self._conn.execute(
            """
            SELECT tracks.language_id, tracks.version AS track_version,
                   active.revision_id AS plan_revision_id,
                   nodes.required_capabilities_json
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active
              ON (active.track_id, active.user_id) = (tracks.id, tracks.user_id)
            JOIN tutor_track_plan_nodes AS nodes
              ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
                 (active.revision_id, tracks.id, tracks.user_id)
             AND nodes.knowledge_key = %s
            WHERE tracks.id = %s AND tracks.user_id = %s
            """,
            (knowledge_key, track_id, user_id),
        ).fetchone()
        if row is None:
            raise ReviewNotFound("active review knowledge node was not found")
        return dict(row)


def schedule_from_row(row: Mapping[str, object]) -> ReviewScheduleSnapshot:
    rating = row.get("last_rating")
    return ReviewScheduleSnapshot(
        knowledge_key=str(row["knowledge_key"]),
        card_state=ReviewCardState(str(row["card_state"])),
        stability=as_float(row["stability"]),
        difficulty=as_float(row["difficulty"]),
        due_at=as_datetime(row["due_at"]),
        review_count=as_int(row["review_count"]),
        lapse_count=as_int(row["lapse_count"]),
        last_rating=ReviewRating(str(rating)) if rating else None,
        risk_level=ReviewRiskLevel(str(row["risk_level"])),
        scheduler_version=str(row["scheduler_version"]),
    )


def schedule_payload(schedule: ReviewScheduleSnapshot) -> dict[str, object]:
    return {
        "knowledge_key": schedule.knowledge_key,
        "card_state": schedule.card_state.value,
        "stability": schedule.stability,
        "difficulty": schedule.difficulty,
        "due_at": schedule.due_at.isoformat(),
        "review_count": schedule.review_count,
        "lapse_count": schedule.lapse_count,
        "last_rating": schedule.last_rating.value if schedule.last_rating else None,
        "risk_level": schedule.risk_level.value,
        "scheduler_version": schedule.scheduler_version,
    }
