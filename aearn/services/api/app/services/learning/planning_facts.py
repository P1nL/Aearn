"""Server-authoritative planning intake facts and question-state lineage."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from psycopg import Connection

from app.agents.harness.contracts import (
    TUTOR_PLANNING_QUESTION_KEYS,
    TutorContextSelection,
    TutorContextSource,
    TutorContinuationKind,
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorRunSnapshot,
)
from app.services.learning.planning_intent import (
    PLANNING_LANGUAGE_INTENT_POLICY_VERSION,
    PlanningIntentResolver,
)


PLANNING_FACT_POLICY_VERSION = "planning-intake-facts-v1"
PLANNING_SNAPSHOT_SCHEMA_VERSION = "authoritative-context-snapshot-v1"


class PlanningFactField(StrEnum):
    LANGUAGE_ID = "language_id"
    GOAL_TEXT = "goal_text"
    TARGET_LEVEL = "target_level"
    WEEKLY_MINUTES = "weekly_minutes"
    EXPERIENCE_LEVEL = "experience_level"
    TEACHING_PREFERENCES = "teaching_preferences"
    PACE_CONSTRAINTS = "pace_constraints"


PLANNING_DIRECTION_SWITCH_REOPEN_FIELDS: tuple[PlanningFactField, ...] = (
    PlanningFactField.LANGUAGE_ID,
    PlanningFactField.GOAL_TEXT,
    PlanningFactField.TARGET_LEVEL,
    PlanningFactField.EXPERIENCE_LEVEL,
)


if frozenset(item.value for item in PlanningFactField) != TUTOR_PLANNING_QUESTION_KEYS:
    raise RuntimeError("planning fact fields must match Tutor planning question keys")


class PlanningFactState(StrEnum):
    ANSWERED_UNCONFIRMED = "answered_unconfirmed"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"


class PlanningQuestionState(StrEnum):
    UNASKED = "unasked"
    ASKED = "asked"
    ANSWERED_UNCONFIRMED = "answered_unconfirmed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    REOPENED = "reopened"
    WITHDRAWN = "withdrawn"


_REQUIRED_PROFILE_FIELDS = frozenset(PlanningFactField)
_EXPERIENCE_LEVELS = frozenset({"new", "beginner", "intermediate", "advanced"})
_WEEKLY_ARABIC = re.compile(
    r"(?:每周|每週|每星期|weekly|per\s+week)[^\d]{0,18}(\d+(?:\.\d+)?)\s*"
    r"(小时|小時|个小时|個小時|hours?|hrs?|h|分钟|分鐘|minutes?|mins?|min)",
    re.IGNORECASE,
)
_WEEKLY_ARABIC_REVERSED = re.compile(
    r"(\d+(?:\.\d+)?)\s*(小时|小時|个小时|個小時|hours?|hrs?|h|分钟|分鐘|minutes?|mins?|min)"
    r"[^\d]{0,18}(?:每周|每週|每星期|weekly|per\s+week)",
    re.IGNORECASE,
)
_WEEKLY_CHINESE = re.compile(
    r"(?:每周|每週|每星期)[^零一二两兩三四五六七八九十百]{0,12}"
    r"([零一二两兩三四五六七八九十百]+)\s*(小时|小時|个小时|個小時|分钟|分鐘)"
)


@dataclass(frozen=True, slots=True)
class PlanningFact:
    fact_id: str
    session_id: str
    field_key: PlanningFactField
    value: object
    value_hash: str
    revision: int
    state: PlanningFactState
    source_message_id: str
    source_run_id: str
    source_input_revision: int
    supersedes_fact_id: str | None
    policy_version: str = PLANNING_FACT_POLICY_VERSION

    def as_public_dict(self) -> dict[str, object]:
        return {
            "field_key": self.field_key.value,
            "value": self.value,
            "revision": self.revision,
            "status": self.state.value,
        }

    def as_context_source(self) -> TutorContextSource:
        return TutorContextSource(
            source_id=f"planning-fact:{self.field_key.value}:{self.fact_id}",
            content={
                "kind": "confirmed_planning_fact",
                "field_key": self.field_key.value,
                "profile_field": (
                    "pace_summary" if self.field_key is PlanningFactField.PACE_CONSTRAINTS else self.field_key.value
                ),
                "profile_value_policy": "copy_exact",
                "value": self.value,
                "fact_revision": self.revision,
                "policy_version": self.policy_version,
            },
        )


@dataclass(frozen=True, slots=True)
class AuthoritativeContextSnapshot:
    schema_version: str
    run_id: str
    conversation_id: str
    input_revision: int
    planning_session_id: str | None
    fact_revision: int
    facts_fingerprint: str
    required_facts: tuple[TutorContextSource, ...]
    question_states: tuple[tuple[str, str], ...]
    snapshot_hash: str
    action_receipts: tuple[TutorContextSource, ...] = ()
    confirmed_question_reasked_count: int = 0


class PlanningFactError(ValueError):
    pass


class PostgresPlanningFactRepository:
    """Append-only planning fact and question event authority."""

    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def record_input(
        self,
        *,
        user_id: str,
        run_id: str,
        conversation_id: str,
        message_id: str,
        input_revision: int,
        content: str,
        explicit_facts: Mapping[str, object] | None = None,
        reopen_fields: Sequence[str] = (),
        intent_resolution_enabled: bool = True,
    ) -> dict[str, object] | None:
        session = self._active_session_for_input(
            user_id=user_id,
            run_id=run_id,
            conversation_id=conversation_id,
            message_id=message_id,
            input_revision=input_revision,
            for_update=True,
        )
        if session is None:
            return None

        explicit = {
            PlanningFactField(str(key)): value
            for key, value in (explicit_facts or {}).items()
            if value is not None
        }
        reopened = {PlanningFactField(str(field)) for field in reopen_fields}
        extracted = extract_planning_facts(content)
        current_language = self._current_fact_row(
            session_id=str(session["id"]),
            field=PlanningFactField.LANGUAGE_ID,
        )
        language_intent = PlanningIntentResolver(self._conn).resolve(
            content,
            confirmed_language_id=(
                None
                if PlanningFactField.LANGUAGE_ID in reopened or current_language is None
                else str(current_language["value_json"])
            ),
            enabled=intent_resolution_enabled,
        )
        auto_language = language_intent.auto_confirm_language_id
        intent_policy_fields: set[PlanningFactField] = set()
        if auto_language is not None and (
            current_language is None
            or str(current_language["value_json"]) == auto_language
            or PlanningFactField.LANGUAGE_ID in reopened
        ):
            extracted[PlanningFactField.LANGUAGE_ID] = auto_language
            intent_policy_fields.add(PlanningFactField.LANGUAGE_ID)
        merged: dict[PlanningFactField, tuple[object, str, str]] = {
            field: (
                value,
                "deterministic_input",
                PLANNING_LANGUAGE_INTENT_POLICY_VERSION
                if field in intent_policy_fields
                else PLANNING_FACT_POLICY_VERSION,
            )
            for field, value in extracted.items()
        }
        merged.update(
            {
                field: (value, "explicit_input", PLANNING_FACT_POLICY_VERSION)
                for field, value in explicit.items()
            }
        )

        changed = False
        self._conn.execute(
            """
            UPDATE tutor_learning_plan_sessions
            SET facts_policy_version = COALESCE(facts_policy_version, %s)
            WHERE id = %s AND user_id = %s
            """,
            (PLANNING_FACT_POLICY_VERSION, session["id"], user_id),
        )

        for raw_field in reopen_fields:
            field = PlanningFactField(str(raw_field))
            self._append_question_event(
                session=session,
                field=field,
                status=PlanningQuestionState.REOPENED,
                source_run_id=run_id,
                source_message_id=message_id,
                source_input_revision=input_revision,
                fact_id=None,
                reason_code="learner_reopened",
            )
            changed = True

        prior_question_states = self.current_question_states(
            user_id=user_id,
            session_id=str(session["id"]),
        )
        if not merged:
            for field, state in prior_question_states.items():
                if state is PlanningQuestionState.ASKED:
                    self._append_question_event(
                        session=session,
                        field=field,
                        status=PlanningQuestionState.ANSWERED_UNCONFIRMED,
                        source_run_id=run_id,
                        source_message_id=message_id,
                        source_input_revision=input_revision,
                        fact_id=None,
                        reason_code="learner_answer_needs_confirmation",
                    )
                    changed = True

        for field, (raw_value, source_kind, policy_version) in merged.items():
            value = normalize_planning_fact(field, raw_value)
            value_hash = planning_fact_value_hash(field, value, policy_version=policy_version)
            current = self._current_fact_row(session_id=str(session["id"]), field=field)
            if current is not None and str(current["value_hash"]) == value_hash:
                self._append_question_event(
                    session=session,
                    field=field,
                    status=PlanningQuestionState.CONFIRMED,
                    source_run_id=run_id,
                    source_message_id=message_id,
                    source_input_revision=input_revision,
                    fact_id=str(current["id"]),
                    reason_code="confirmed_replay",
                )
                continue
            revision = _integer(current["revision"], label="fact revision") + 1 if current is not None else 1
            if current is not None:
                self._append_question_event(
                    session=session,
                    field=field,
                    status=PlanningQuestionState.SUPERSEDED,
                    source_run_id=run_id,
                    source_message_id=message_id,
                    source_input_revision=input_revision,
                    fact_id=str(current["id"]),
                    reason_code="fact_superseded",
                )
            fact_id = str(uuid4())
            row = self._conn.execute(
                """
                INSERT INTO tutor_planning_intake_facts (
                  id, session_id, user_id, conversation_id, field_key, value_json,
                  value_hash, revision, state, source_kind, source_message_id,
                  source_run_id, source_input_revision, supersedes_fact_id, policy_version
                ) VALUES (
                  %s, %s, %s, %s, %s, %s::jsonb,
                  %s, %s, 'confirmed', %s, %s,
                  %s, %s, %s, %s
                )
                ON CONFLICT (session_id, field_key, source_run_id, source_input_revision, value_hash)
                DO NOTHING
                RETURNING id
                """,
                (
                    fact_id,
                    session["id"],
                    user_id,
                    conversation_id,
                    field.value,
                    _json(value),
                    value_hash,
                    revision,
                    source_kind,
                    message_id,
                    run_id,
                    input_revision,
                    str(current["id"]) if current is not None else None,
                    policy_version,
                ),
            ).fetchone()
            if row is None:
                replay = self._conn.execute(
                    """
                    SELECT id FROM tutor_planning_intake_facts
                    WHERE session_id = %s AND field_key = %s AND source_run_id = %s
                      AND source_input_revision = %s AND value_hash = %s
                    """,
                    (session["id"], field.value, run_id, input_revision, value_hash),
                ).fetchone()
                if replay is None:
                    raise PlanningFactError("planning fact idempotent insert failed")
                fact_id = str(replay["id"])
            changed = True
            self._append_question_event(
                session=session,
                field=field,
                status=PlanningQuestionState.CONFIRMED,
                source_run_id=run_id,
                source_message_id=message_id,
                source_input_revision=input_revision,
                fact_id=fact_id,
                reason_code="learner_confirmed",
            )
        if changed:
            self._conn.execute(
                """
                UPDATE tutor_learning_plan_sessions
                SET version = version + 1
                WHERE id = %s AND user_id = %s AND status IN ('collecting', 'draft_ready')
                """,
                (session["id"], user_id),
            )
        return self.public_projection(user_id=user_id, session_id=str(session["id"]))

    def current_facts(self, *, user_id: str, session_id: str) -> tuple[PlanningFact, ...]:
        rows = self._conn.execute(
            """
            SELECT facts.*
            FROM tutor_planning_intake_facts AS facts
            WHERE facts.session_id = %s AND facts.user_id = %s
              AND facts.state = 'confirmed'
              AND NOT EXISTS (
                SELECT 1 FROM tutor_planning_intake_facts AS successor
                WHERE successor.supersedes_fact_id = facts.id
              )
            ORDER BY facts.field_key
            """,
            (session_id, user_id),
        ).fetchall()
        facts = tuple(_fact_from_row(row) for row in rows)
        question_states = self.current_question_states(user_id=user_id, session_id=session_id)
        return tuple(
            fact
            for fact in facts
            if question_states.get(fact.field_key, PlanningQuestionState.CONFIRMED)
            is PlanningQuestionState.CONFIRMED
        )

    def current_facts_for_run(self, *, user_id: str, run_id: str) -> tuple[PlanningFact, ...]:
        session = self._active_session_for_run(user_id=user_id, run_id=run_id)
        if session is None:
            return ()
        return self.current_facts(user_id=user_id, session_id=str(session["id"]))

    def facts_fingerprint(self, facts: Sequence[PlanningFact]) -> str:
        return planning_facts_fingerprint(facts)

    def profile_fact_state(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> tuple[dict[PlanningFactField, object], str, int, tuple[PlanningFactField, ...]]:
        facts = self.current_facts(user_id=user_id, session_id=session_id)
        question_states = self.current_question_states(user_id=user_id, session_id=session_id)
        authoritative = tuple(
            fact
            for fact in facts
            if question_states.get(fact.field_key) is not PlanningQuestionState.REOPENED
        )
        values = {fact.field_key: fact.value for fact in authoritative}
        missing = tuple(sorted(_REQUIRED_PROFILE_FIELDS - set(values), key=lambda item: item.value))
        revision = sum(fact.revision for fact in authoritative)
        return values, self.facts_fingerprint(authoritative), revision, missing

    def missing_fields_for_run(
        self,
        *,
        user_id: str,
        run_id: str,
    ) -> tuple[PlanningFactField, ...]:
        session = self._active_session_for_run(user_id=user_id, run_id=run_id)
        if session is None:
            return ()
        return self.profile_fact_state(
            user_id=user_id,
            session_id=str(session["id"]),
        )[3]

    def validate_profile(
        self,
        *,
        user_id: str,
        session_id: str,
        profile: Mapping[str, object],
        require_complete: bool,
    ) -> tuple[str, int]:
        values, fingerprint, revision, missing = self.profile_fact_state(
            user_id=user_id,
            session_id=session_id,
        )
        if require_complete and missing:
            raise PlanningFactError(
                "missing confirmed planning facts: " + ",".join(field.value for field in missing)
            )
        profile_mapping = {
            PlanningFactField.LANGUAGE_ID: profile.get("language_id"),
            PlanningFactField.GOAL_TEXT: profile.get("goal_text"),
            PlanningFactField.TARGET_LEVEL: profile.get("target_level"),
            PlanningFactField.WEEKLY_MINUTES: profile.get("weekly_minutes"),
            PlanningFactField.EXPERIENCE_LEVEL: profile.get("experience_level"),
            PlanningFactField.TEACHING_PREFERENCES: profile.get("teaching_preferences"),
            PlanningFactField.PACE_CONSTRAINTS: profile.get("pace_summary"),
        }
        for field, expected in values.items():
            if normalize_planning_fact(field, profile_mapping[field]) != expected:
                raise PlanningFactError(f"plan profile conflicts with confirmed fact {field.value}")
        return fingerprint, revision

    def public_projection(self, *, user_id: str, session_id: str) -> dict[str, object]:
        facts = self.current_facts(user_id=user_id, session_id=session_id)
        fact_by_field = {fact.field_key: fact for fact in facts}
        question_states = self.current_question_states(user_id=user_id, session_id=session_id)
        return {
            "schema_version": PLANNING_SNAPSHOT_SCHEMA_VERSION,
            "facts": [fact.as_public_dict() for fact in facts],
            "questions": [
                {
                    "question_key": field.value,
                    "field_key": field.value,
                    "status": (
                        PlanningQuestionState.CONFIRMED.value
                        if field in fact_by_field and question_states.get(field) is not PlanningQuestionState.REOPENED
                        else question_states.get(field, PlanningQuestionState.UNASKED).value
                    ),
                }
                for field in PlanningFactField
            ],
            "fact_revision": sum(fact.revision for fact in facts),
        }

    def current_question_states(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[PlanningFactField, PlanningQuestionState]:
        rows = self._conn.execute(
            """
            WITH RECURSIVE question_chain AS (
              SELECT events.id, events.field_key, events.status, events.previous_event_id,
                     events.created_at, 0 AS ancestor_depth
              FROM tutor_planning_question_events AS events
              WHERE events.session_id = %s AND events.user_id = %s
                AND NOT EXISTS (
                  SELECT 1
                  FROM tutor_planning_question_events AS successor
                  WHERE successor.previous_event_id = events.id
                )
              UNION ALL
              SELECT predecessor.id, predecessor.field_key, predecessor.status,
                     predecessor.previous_event_id, predecessor.created_at,
                     chain.ancestor_depth + 1
              FROM tutor_planning_question_events AS predecessor
              JOIN question_chain AS chain ON chain.previous_event_id = predecessor.id
            )
            SELECT DISTINCT ON (field_key) field_key, status
            FROM question_chain
            WHERE status <> 'reasked_blocked'
            ORDER BY field_key, ancestor_depth, created_at DESC, id DESC
            """,
            (session_id, user_id),
        ).fetchall()
        return {
            PlanningFactField(str(row["field_key"])): PlanningQuestionState(str(row["status"]))
            for row in rows
        }

    def project_snapshot(
        self,
        *,
        run: TutorRunSnapshot,
        input_revision: int,
        action_receipts: Sequence[TutorContextSource] = (),
    ) -> AuthoritativeContextSnapshot:
        session = self._active_session_for_run(user_id=run.user_id, run_id=run.run_id)
        if session is None:
            return build_authoritative_context_snapshot(
                run=run,
                input_revision=input_revision,
                planning_session_id=None,
                facts=(),
                question_states={},
                action_receipts=action_receipts,
            )
        session_id = str(session["id"])
        facts = self.current_facts(user_id=run.user_id, session_id=session_id)
        question_states = self.current_question_states(
            user_id=run.user_id,
            session_id=session_id,
        )
        return build_authoritative_context_snapshot(
            run=run,
            input_revision=input_revision,
            planning_session_id=session_id,
            facts=facts,
            question_states=question_states,
            action_receipts=action_receipts,
            confirmed_question_reasked_count=self._confirmed_question_reasked_count(
                user_id=run.user_id,
                session_id=session_id,
            ),
        )

    def _confirmed_question_reasked_count(self, *, user_id: str, session_id: str) -> int:
        row = self._conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_planning_question_events
            WHERE session_id = %s AND user_id = %s AND status = 'reasked_blocked'
            """,
            (session_id, user_id),
        ).fetchone()
        return _integer(row["count"], label="reasked count") if row is not None else 0

    def message_semantics_for_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> tuple[frozenset[str], frozenset[str]]:
        covered = frozenset(fact.source_message_id for fact in self.current_facts(user_id=user_id, session_id=session_id))
        blocked_rows = self._conn.execute(
            """
            SELECT facts.source_message_id::text AS message_id
            FROM tutor_planning_intake_facts AS facts
            WHERE facts.session_id = %s AND facts.user_id = %s
              AND facts.state = 'answered_unconfirmed'
              AND NOT EXISTS (
                SELECT 1 FROM tutor_planning_intake_facts AS successor
                WHERE successor.supersedes_fact_id = facts.id
              )
            UNION
            SELECT events.source_message_id::text AS message_id
            FROM tutor_planning_question_events AS events
            WHERE events.session_id = %s AND events.user_id = %s
              AND events.source_message_id IS NOT NULL
              AND events.status IN ('answered_unconfirmed', 'reopened')
              AND NOT EXISTS (
                SELECT 1 FROM tutor_planning_question_events AS successor
                WHERE successor.previous_event_id = events.id
              )
            """,
            (session_id, user_id, session_id, user_id),
        ).fetchall()
        blocked = frozenset(str(row["message_id"]) for row in blocked_rows)
        return covered, blocked

    def question_is_confirmed_for_run(
        self,
        *,
        user_id: str,
        run_id: str,
        field: PlanningFactField,
    ) -> bool:
        session = self._active_session_for_run(user_id=user_id, run_id=run_id)
        if session is None:
            return False
        states = self.current_question_states(user_id=user_id, session_id=str(session["id"]))
        if states.get(field) is PlanningQuestionState.REOPENED:
            return False
        return any(
            fact.field_key is field
            for fact in self.current_facts(user_id=user_id, session_id=str(session["id"]))
        )

    def record_question_asked(
        self,
        *,
        run: TutorRunSnapshot,
        field: PlanningFactField,
    ) -> None:
        session = self._active_session_for_run(user_id=run.user_id, run_id=run.run_id)
        if session is None:
            return
        self._append_question_event(
            session=session,
            field=field,
            status=PlanningQuestionState.ASKED,
            source_run_id=run.run_id,
            source_message_id=None,
            source_input_revision=run.input_revision,
            fact_id=None,
            reason_code="provider_question",
        )

    def record_reasked_blocked(
        self,
        *,
        run: TutorRunSnapshot,
        field: PlanningFactField,
    ) -> None:
        session = self._active_session_for_run(user_id=run.user_id, run_id=run.run_id)
        if session is None:
            return
        self._append_question_event(
            session=session,
            field=field,
            status="reasked_blocked",
            source_run_id=run.run_id,
            source_message_id=None,
            source_input_revision=run.input_revision,
            fact_id=None,
            reason_code="confirmed_question_reasked",
        )

    def _append_question_event(
        self,
        *,
        session: Mapping[str, object],
        field: PlanningFactField,
        status: PlanningQuestionState | str,
        source_run_id: str | None,
        source_message_id: str | None,
        source_input_revision: int | None,
        fact_id: str | None,
        reason_code: str,
    ) -> None:
        previous = self._conn.execute(
            """
            SELECT events.id
            FROM tutor_planning_question_events AS events
            WHERE events.session_id = %s AND events.field_key = %s
              AND NOT EXISTS (
                SELECT 1
                FROM tutor_planning_question_events AS successor
                WHERE successor.previous_event_id = events.id
              )
            ORDER BY events.created_at DESC, events.id DESC LIMIT 1
            """,
            (session["id"], field.value),
        ).fetchone()
        normalized_status = status.value if isinstance(status, PlanningQuestionState) else str(status)
        event_hash = hashlib.sha256(
            _json(
                {
                    "session_id": str(session["id"]),
                    "field_key": field.value,
                    "status": normalized_status,
                    "source_run_id": source_run_id,
                    "source_message_id": source_message_id,
                    "source_input_revision": source_input_revision,
                    "fact_id": fact_id,
                    "reason_code": reason_code,
                }
            ).encode("utf-8")
        ).hexdigest()
        self._conn.execute(
            """
            INSERT INTO tutor_planning_question_events (
              session_id, user_id, conversation_id, field_key, question_key, status,
              source_run_id, source_message_id, source_input_revision, fact_id,
              previous_event_id, reason_code, event_hash
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id, event_hash) DO NOTHING
            """,
            (
                session["id"],
                session["user_id"],
                session["conversation_id"],
                field.value,
                field.value,
                normalized_status,
                source_run_id,
                source_message_id,
                source_input_revision,
                fact_id,
                str(previous["id"]) if previous is not None else None,
                reason_code,
                event_hash,
            ),
        )

    def _active_session_for_run(self, *, user_id: str, run_id: str) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT sessions.*
            FROM tutor_learning_plan_sessions AS sessions
            JOIN tutor_runs AS runs
              ON runs.conversation_id = sessions.conversation_id AND runs.user_id = sessions.user_id
            JOIN tutor_run_learning_scopes AS scopes
              ON scopes.run_id = runs.id AND scopes.user_id = runs.user_id
            WHERE sessions.user_id = %s AND runs.id = %s
              AND sessions.status IN ('collecting', 'draft_ready')
              AND scopes.scope_kind = 'plan_drafting' AND scopes.task_kind = 'plan_drafting'
            """,
            (user_id, run_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def _active_session_for_input(
        self,
        *,
        user_id: str,
        run_id: str,
        conversation_id: str,
        message_id: str,
        input_revision: int,
        for_update: bool,
    ) -> dict[str, object] | None:
        lock = " FOR UPDATE OF sessions" if for_update else ""
        row = self._conn.execute(
            """
            SELECT sessions.*
            FROM tutor_learning_plan_sessions AS sessions
            JOIN tutor_runs AS runs
              ON runs.conversation_id = sessions.conversation_id AND runs.user_id = sessions.user_id
            JOIN tutor_run_learning_scopes AS scopes
              ON scopes.run_id = runs.id AND scopes.user_id = runs.user_id
            JOIN tutor_run_input_events AS inputs
              ON inputs.run_id = runs.id AND inputs.message_id = %s AND inputs.input_revision = %s
            WHERE sessions.user_id = %s AND sessions.conversation_id = %s
              AND runs.id = %s AND sessions.status IN ('collecting', 'draft_ready')
              AND scopes.scope_kind = 'plan_drafting' AND scopes.task_kind = 'plan_drafting'
            """ + lock,
            (message_id, input_revision, user_id, conversation_id, run_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def _current_fact_row(
        self,
        *,
        session_id: str,
        field: PlanningFactField,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """
            SELECT facts.*
            FROM tutor_planning_intake_facts AS facts
            WHERE facts.session_id = %s AND facts.field_key = %s
              AND NOT EXISTS (
                SELECT 1 FROM tutor_planning_intake_facts AS successor
                WHERE successor.supersedes_fact_id = facts.id
              )
            ORDER BY facts.revision DESC LIMIT 1
            """,
            (session_id, field.value),
        ).fetchone()
        return dict(row) if row is not None else None


class TutorDecisionGate(Protocol):
    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
        context: TutorContextSelection,
    ) -> TutorDecisionGateResult: ...


class PlanningQuestionDecisionGate:
    """Require stable question keys and block confirmed-field re-asks."""

    def __init__(
        self,
        *,
        base: TutorDecisionGate,
        facts: PostgresPlanningFactRepository,
        intent_resolution_enabled: bool = True,
    ) -> None:
        self._base = base
        self._facts = facts
        self._intent_resolution_enabled = intent_resolution_enabled

    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
        context: TutorContextSelection,
    ) -> TutorDecisionGateResult:
        result = self._base.validate(run=run, decision=decision, context=context)
        if result.status is not TutorDecisionGateStatus.APPROVED:
            return result
        if decision.continuation_kind is not TutorContinuationKind.PLANNING_INPUT:
            return result
        session = self._facts._active_session_for_run(user_id=run.user_id, run_id=run.run_id)
        if session is None:
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.DENIED,
                diagnostic_code="planning_session_required",
            )
        if decision.question_key is None:
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.DENIED,
                diagnostic_code="planning_question_key_required",
            )
        try:
            field = PlanningFactField(decision.question_key)
        except ValueError:
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.DENIED,
                diagnostic_code="planning_question_key_invalid",
            )
        if self._facts.question_is_confirmed_for_run(user_id=run.user_id, run_id=run.run_id, field=field):
            self._facts.record_reasked_blocked(run=run, field=field)
            return TutorDecisionGateResult(
                status=TutorDecisionGateStatus.DENIED,
                diagnostic_code="confirmed_question_reasked",
            )
        if field is PlanningFactField.LANGUAGE_ID:
            model_hint = (
                decision.planning_intent_hint.as_mapping()
                if decision.planning_intent_hint is not None
                else None
            )
            language_intent = PlanningIntentResolver(self._facts._conn).resolve_for_run(
                user_id=run.user_id,
                run_id=run.run_id,
                enabled=self._intent_resolution_enabled,
                model_hint=model_hint,
                expected_input_revision=run.input_revision,
            )
            if language_intent.resolution in {
                "auto_confirm",
                "clarification_required",
                "unsupported",
            }:
                diagnostic_code = (
                    "planning_language_hint_invalid"
                    if language_intent.reason_code in {"invalid_model_hint", "stale_input_revision"}
                    else "planning_language_clarification_required"
                )
                return TutorDecisionGateResult(
                    status=TutorDecisionGateStatus.DENIED,
                    diagnostic_code=diagnostic_code,
                )
            if decision.planning_intent_hint is not None and not language_intent.semantic_language_ids:
                return TutorDecisionGateResult(
                    status=TutorDecisionGateStatus.DENIED,
                    diagnostic_code="planning_language_hint_invalid",
                )
        self._facts.record_question_asked(run=run, field=field)
        return result


def normalize_planning_fact(field: PlanningFactField, value: object) -> object:
    if field is PlanningFactField.WEEKLY_MINUTES:
        if isinstance(value, bool):
            raise PlanningFactError("weekly_minutes must be an integer")
        try:
            minutes = _integer(value, label="weekly_minutes")
        except PlanningFactError as exc:
            raise PlanningFactError("weekly_minutes must be an integer") from exc
        if not 15 <= minutes <= 10_080:
            raise PlanningFactError("weekly_minutes is outside the allowed range")
        return minutes
    if field is PlanningFactField.EXPERIENCE_LEVEL:
        normalized = str(value or "").strip().lower()
        if normalized not in _EXPERIENCE_LEVELS:
            raise PlanningFactError("experience_level is unsupported")
        return normalized
    if field is PlanningFactField.TEACHING_PREFERENCES:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise PlanningFactError("teaching_preferences must be a list")
        normalized_preferences = [" ".join(str(item).split()) for item in value]
        if len(normalized_preferences) > 4 or any(
            not item or len(item) > 80 for item in normalized_preferences
        ):
            raise PlanningFactError("teaching_preferences are invalid")
        if len(normalized_preferences) != len(set(normalized_preferences)):
            raise PlanningFactError("teaching_preferences must be unique")
        return normalized_preferences
    maximum = {
        PlanningFactField.LANGUAGE_ID: 80,
        PlanningFactField.GOAL_TEXT: 2_000,
        PlanningFactField.TARGET_LEVEL: 120,
        PlanningFactField.PACE_CONSTRAINTS: 240,
    }[field]
    normalized_text = " ".join(str(value or "").split())
    if field is PlanningFactField.LANGUAGE_ID:
        normalized_text = normalized_text.lower()
    if not normalized_text or len(normalized_text) > maximum:
        raise PlanningFactError(f"{field.value} is invalid")
    return normalized_text


def planning_facts_fingerprint(facts: Sequence[PlanningFact]) -> str:
    payload = [
        {
            "field_key": fact.field_key.value,
            "value_hash": fact.value_hash,
            "revision": fact.revision,
        }
        for fact in sorted(facts, key=lambda item: item.field_key.value)
    ]
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def build_authoritative_context_snapshot(
    *,
    run: TutorRunSnapshot,
    input_revision: int,
    planning_session_id: str | None,
    facts: Sequence[PlanningFact],
    question_states: Mapping[PlanningFactField, PlanningQuestionState],
    action_receipts: Sequence[TutorContextSource] = (),
    confirmed_question_reasked_count: int = 0,
) -> AuthoritativeContextSnapshot:
    ordered_facts = tuple(sorted(facts, key=lambda item: item.field_key.value))
    fingerprint = planning_facts_fingerprint(ordered_facts)
    questions = tuple(
        sorted((field.value, state.value) for field, state in question_states.items())
    )
    bounded_action_receipts = tuple(action_receipts[:8])
    return AuthoritativeContextSnapshot(
        schema_version=PLANNING_SNAPSHOT_SCHEMA_VERSION,
        run_id=run.run_id,
        conversation_id=run.conversation_id,
        input_revision=input_revision,
        planning_session_id=planning_session_id,
        fact_revision=sum(fact.revision for fact in ordered_facts),
        facts_fingerprint=fingerprint,
        required_facts=tuple(fact.as_context_source() for fact in ordered_facts),
        question_states=questions,
        snapshot_hash=_snapshot_hash(
            run.run_id, input_revision, fingerprint, questions, bounded_action_receipts
        ),
        action_receipts=bounded_action_receipts,
        confirmed_question_reasked_count=confirmed_question_reasked_count,
    )


def planning_fact_value_hash(
    field: PlanningFactField,
    value: object,
    *,
    policy_version: str = PLANNING_FACT_POLICY_VERSION,
) -> str:
    return hashlib.sha256(
        _json({"field_key": field.value, "value": value, "policy_version": policy_version}).encode(
            "utf-8"
        )
    ).hexdigest()


def extract_planning_facts(content: str) -> dict[PlanningFactField, object]:
    text = " ".join(str(content or "").split())
    for pattern in (_WEEKLY_ARABIC, _WEEKLY_ARABIC_REVERSED):
        match = pattern.search(text)
        if match is not None:
            minutes = _duration_minutes(float(match.group(1)), match.group(2))
            if 15 <= minutes <= 10_080:
                return {PlanningFactField.WEEKLY_MINUTES: minutes}
    chinese = _WEEKLY_CHINESE.search(text)
    if chinese is not None:
        number = _chinese_number(chinese.group(1))
        if number is not None:
            minutes = _duration_minutes(float(number), chinese.group(2))
            if 15 <= minutes <= 10_080:
                return {PlanningFactField.WEEKLY_MINUTES: minutes}
    return {}


def _duration_minutes(value: float, unit: str) -> int:
    normalized = unit.lower()
    is_hour = normalized in {"小时", "小時", "个小时", "個小時", "hour", "hours", "hr", "hrs", "h"}
    return round(value * 60) if is_hour else round(value)


def _chinese_number(value: str) -> int | None:
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "兩": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if "百" in value:
        head, _, tail = value.partition("百")
        hundreds = digits.get(head, 1)
        remainder = _chinese_number(tail) if tail else 0
        return hundreds * 100 + (remainder or 0)
    if "十" in value:
        head, _, tail = value.partition("十")
        tens = digits.get(head, 1)
        ones = digits.get(tail, 0) if tail else 0
        return tens * 10 + ones
    result = 0
    for character in value:
        if character not in digits:
            return None
        result = result * 10 + digits[character]
    return result


def _fact_from_row(row: Mapping[str, object]) -> PlanningFact:
    return PlanningFact(
        fact_id=str(row["id"]),
        session_id=str(row["session_id"]),
        field_key=PlanningFactField(str(row["field_key"])),
        value=row.get("value_json"),
        value_hash=str(row["value_hash"]),
        revision=_integer(row["revision"], label="fact revision"),
        state=PlanningFactState(str(row["state"])),
        source_message_id=str(row["source_message_id"]),
        source_run_id=str(row["source_run_id"]),
        source_input_revision=_integer(
            row["source_input_revision"],
            label="source input revision",
        ),
        supersedes_fact_id=(str(row["supersedes_fact_id"]) if row.get("supersedes_fact_id") else None),
        policy_version=str(row.get("policy_version") or PLANNING_FACT_POLICY_VERSION),
    )


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise PlanningFactError(f"{label} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, str | bytes | bytearray):
        try:
            return int(value)
        except ValueError as exc:
            raise PlanningFactError(f"{label} must be an integer") from exc
    raise PlanningFactError(f"{label} must be an integer")


def _snapshot_hash(
    run_id: str,
    input_revision: int,
    facts_fingerprint: str,
    question_states: Sequence[tuple[str, str]],
    action_receipts: Sequence[TutorContextSource],
) -> str:
    return hashlib.sha256(
        _json(
            {
                "schema_version": PLANNING_SNAPSHOT_SCHEMA_VERSION,
                "run_id": run_id,
                "input_revision": input_revision,
                "facts_fingerprint": facts_fingerprint,
                "question_states": list(question_states),
                "action_receipts": [
                    {
                        "source_id": source.source_id,
                        "content_hash": hashlib.sha256(_json(source.content).encode("utf-8")).hexdigest(),
                    }
                    for source in action_receipts
                ],
            }
        ).encode("utf-8")
    ).hexdigest()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
