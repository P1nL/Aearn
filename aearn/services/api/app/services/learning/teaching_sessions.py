"""PostgreSQL teaching-session authority, checkpoint CAS, and structured stimuli."""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg import Connection
from pydantic import TypeAdapter, ValidationError

from app.agents.harness.context_budget import build_tutor_context_budget_policy
from app.agents.harness.contracts import TutorPolicySnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings, get_settings
from app.services.learning.teaching_contracts import (
    DomainEventStimulus,
    LearnerMessageStimulus,
    TeachingAuthoritySnapshot,
    TeachingCheckpointState,
    TeachingControlStimulus,
    TeachingPauseReason,
    TeachingSessionMode,
    TeachingSessionStatus,
    TutorTurnStimulus,
    canonical_hash,
    stable,
)
from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
from app.services.tutor.persistence import PostgresTutorRepository

_STIMULUS: TypeAdapter[TutorTurnStimulus] = TypeAdapter(TutorTurnStimulus)
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$")


class TeachingSessionError(ValueError):
    pass


class TeachingSessionNotFound(TeachingSessionError):
    pass


class TeachingSessionConflict(TeachingSessionError):
    pass


class TeachingSessionInvalid(TeachingSessionError):
    pass


@dataclass(frozen=True, slots=True)
class TeachingAuthority:
    user_id: str
    track_id: str
    conversation_id: str
    knowledge_key: str
    node_title: str
    track_version: int
    plan_revision_id: str
    progress_status: str
    progress_version: int
    assignment_id: str
    assignment_version: int
    document_id: str
    document_content_hash: str

    def snapshot(self) -> TeachingAuthoritySnapshot:
        return TeachingAuthoritySnapshot(
            track_version=self.track_version,
            plan_revision_id=self.plan_revision_id,
            progress_version=self.progress_version,
            assignment_id=self.assignment_id,
            assignment_version=self.assignment_version,
            document_id=self.document_id,
            document_content_hash=self.document_content_hash,
        )


class TeachingSessionRepository:
    def __init__(self, conn: Connection[dict[str, object]]) -> None:
        self._conn = conn

    def resolve_authority(
        self, *, user_id: str, track_id: str, knowledge_key: str,
        conversation_id: str | None = None, for_update: bool = False,
    ) -> TeachingAuthority:
        key = stable(knowledge_key, "knowledge_key")
        extra = " AND conversations.id = %s" if conversation_id is not None else ""
        params: list[object] = [track_id, user_id, key]
        if conversation_id is not None:
            params.append(conversation_id)
        lock = " FOR UPDATE OF tracks, progress, assignments, conversations" if for_update else ""
        rows = self._conn.execute(
            """
            SELECT tracks.id AS track_id, tracks.user_id, tracks.version AS track_version,
                   active.revision_id AS plan_revision_id, nodes.knowledge_key, nodes.title AS node_title,
                   progress.status AS progress_status, progress.version AS progress_version,
                   conversations.id AS conversation_id, assignments.id AS assignment_id,
                   assignments.assignment_version, assignments.document_id,
                   documents.content_hash AS document_content_hash
            FROM tutor_learning_tracks AS tracks
            JOIN tutor_track_active_plans AS active ON (active.track_id,active.user_id)=(tracks.id,tracks.user_id)
            JOIN tutor_track_plan_nodes AS nodes ON (nodes.revision_id,nodes.track_id,nodes.user_id)=(active.revision_id,active.track_id,active.user_id)
            JOIN tutor_track_node_progress AS progress ON (progress.track_id,progress.user_id,progress.knowledge_key)=(nodes.track_id,nodes.user_id,nodes.knowledge_key)
            JOIN tutor_conversation_learning_scopes AS scopes ON scopes.user_id=tracks.user_id AND scopes.learning_track_id=tracks.id AND scopes.scope_kind='learning_track'
            JOIN tutor_conversations AS conversations ON conversations.id=scopes.conversation_id AND conversations.user_id=scopes.user_id
              AND conversations.visibility='learner' AND conversations.kind='interactive' AND conversations.status='active'
            JOIN tutor_lesson_assignments AS assignments ON assignments.user_id=tracks.user_id AND assignments.track_id=tracks.id
              AND assignments.knowledge_key=nodes.knowledge_key AND assignments.status='active'
            JOIN tutor_lesson_documents AS documents ON documents.id=assignments.document_id AND documents.user_id=assignments.user_id
              AND documents.track_id=assignments.track_id AND documents.knowledge_key=assignments.knowledge_key
            WHERE tracks.id=%s AND tracks.user_id=%s AND nodes.knowledge_key=%s
            """ + extra + " ORDER BY conversations.created_at,conversations.id" + lock,
            tuple(params),
        ).fetchall()
        if not rows:
            raise TeachingSessionNotFound("teaching authority was not found")
        if len(rows) != 1:
            raise TeachingSessionConflict("LearningTrack conversation authority is ambiguous")
        row = rows[0]
        if str(row["progress_status"]) == "locked":
            raise TeachingSessionConflict("knowledge point is not available")
        return TeachingAuthority(
            user_id=str(row["user_id"]), track_id=str(row["track_id"]), conversation_id=str(row["conversation_id"]),
            knowledge_key=str(row["knowledge_key"]), node_title=str(row["node_title"]), track_version=_int(row["track_version"]),
            plan_revision_id=str(row["plan_revision_id"]), progress_status=str(row["progress_status"]),
            progress_version=_int(row["progress_version"]), assignment_id=str(row["assignment_id"]),
            assignment_version=_int(row["assignment_version"]), document_id=str(row["document_id"]),
            document_content_hash=str(row["document_content_hash"]),
        )

    def read_current(self, *, user_id: str, track_id: str, knowledge_key: str, for_update: bool = False) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s AND track_id=%s AND knowledge_key=%s "
            "AND status IN ('active','paused','blocked') ORDER BY created_at DESC LIMIT 1" + (" FOR UPDATE" if for_update else ""),
            (user_id, track_id, stable(knowledge_key, "knowledge_key")),
        ).fetchone()
        if row is None:
            raise TeachingSessionNotFound("teaching session was not found")
        return row

    def read_by_id(self, *, user_id: str, track_id: str, session_id: str, for_update: bool = False) -> Mapping[str, object]:
        row = self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE id=%s AND user_id=%s AND track_id=%s" + (" FOR UPDATE" if for_update else ""),
            (session_id, user_id, track_id),
        ).fetchone()
        if row is None:
            raise TeachingSessionNotFound("teaching session was not found")
        return row

    def list_sessions(self, *, user_id: str, track_id: str) -> tuple[Mapping[str, object], ...]:
        return tuple(self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s AND track_id=%s "
            "ORDER BY last_activity_at DESC,created_at DESC,id DESC LIMIT 100",
            (user_id, track_id),
        ).fetchall())

    def open_or_resume(self, *, authority: TeachingAuthority, mode: TeachingSessionMode) -> tuple[Mapping[str, object], bool]:
        existing = self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s AND track_id=%s AND conversation_id=%s "
            "AND knowledge_key=%s AND status IN ('active','paused','blocked') ORDER BY created_at DESC LIMIT 1 FOR UPDATE",
            (authority.user_id, authority.track_id, authority.conversation_id, authority.knowledge_key),
        ).fetchone()
        if existing is not None:
            self._assert_authority(existing, authority)
            return existing, False
        session_id = str(uuid4())
        row = self._conn.execute(
            """INSERT INTO tutor_teaching_sessions (
                 id,user_id,track_id,conversation_id,knowledge_key,track_version,active_plan_revision_id,progress_version,
                 lesson_assignment_id,assignment_version,document_id,document_content_hash,status,mode,version,last_activity_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,1,now()) RETURNING *""",
            (session_id, authority.user_id, authority.track_id, authority.conversation_id, authority.knowledge_key,
             authority.track_version, authority.plan_revision_id, authority.progress_version, authority.assignment_id, authority.assignment_version,
             authority.document_id, authority.document_content_hash, mode.value),
        ).fetchone()
        if row is None:
            raise RuntimeError("teaching session insert failed")
        state = TeachingCheckpointState.model_validate({
            "objective": {"objective_id": f"knowledge:{authority.knowledge_key}", "summary": authority.node_title,
                          "source_handles": [f"knowledge:{authority.knowledge_key}"]},
            "active_focus": {"focus_id": f"knowledge:{authority.knowledge_key}", "focus_kind": "knowledge",
                             "summary": authority.node_title, "source_handles": [f"knowledge:{authority.knowledge_key}"]},
            "pause_reason": "soft_pause", "recommended_action_key": "continue",
        })
        checkpoint = self._insert_checkpoint(
            session=row, predecessor_id=None, session_version=1, state=state,
            authority=authority.snapshot(), source_run_id=None, source_stimulus_id=None,
        )
        updated = self._conn.execute(
            "UPDATE tutor_teaching_sessions SET current_checkpoint_id=%s WHERE id=%s RETURNING *",
            (checkpoint["id"], session_id),
        ).fetchone()
        if updated is None:
            raise RuntimeError("teaching session checkpoint binding failed")
        return updated, True

    def current_checkpoint(self, *, session_id: str, user_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            """SELECT checkpoints.* FROM tutor_teaching_sessions AS sessions
               JOIN tutor_teaching_session_checkpoints AS checkpoints ON checkpoints.id=sessions.current_checkpoint_id
               WHERE sessions.id=%s AND sessions.user_id=%s""",
            (session_id, user_id),
        ).fetchone()
        if row is None:
            raise TeachingSessionConflict("teaching session checkpoint is missing")
        return row

    def mutate(
        self, *, session: Mapping[str, object], authority: TeachingAuthority, expected_session_version: int,
        control: TeachingControlStimulus, target_mode: TeachingSessionMode | None,
    ) -> Mapping[str, object]:
        self._assert_version_and_authority(session, authority, expected_session_version, control)
        checkpoint = self.current_checkpoint(session_id=str(session["id"]), user_id=authority.user_id)
        state = self._checkpoint_state(checkpoint)
        status = TeachingSessionStatus(str(session["status"]))
        mode = TeachingSessionMode(str(session["mode"]))
        paused_at = session.get("paused_at")
        if control.control_key.value == "switch_mode":
            if target_mode is None:
                raise TeachingSessionInvalid("switch_mode requires target mode")
            mode = target_mode
        elif control.control_key.value == "pause":
            status, paused_at = TeachingSessionStatus.PAUSED, datetime.now(UTC)
            state = state.model_copy(update={"pause_reason": TeachingPauseReason.SESSION_PAUSE})
        elif control.control_key.value == "resume":
            status, paused_at = TeachingSessionStatus.ACTIVE, None
            state = state.model_copy(update={"pause_reason": TeachingPauseReason.SOFT_PAUSE})
        next_version = expected_session_version + 1
        next_checkpoint = self._insert_checkpoint(
            session=session, predecessor_id=str(checkpoint["id"]), session_version=next_version, state=state,
            authority=authority.snapshot(), source_run_id=None, source_stimulus_id=None,
        )
        updated = self._conn.execute(
            """UPDATE tutor_teaching_sessions SET status=%s,mode=%s,current_checkpoint_id=%s,version=version+1,
                 paused_at=%s,last_activity_at=now(),last_mutation_key=%s,last_mutation_hash=%s
               WHERE id=%s AND user_id=%s AND version=%s RETURNING *""",
            (status.value, mode.value, next_checkpoint["id"], paused_at, control.client_action_id,
             canonical_hash(control.model_dump(mode="json")), session["id"], authority.user_id, expected_session_version),
        ).fetchone()
        if updated is None:
            raise TeachingSessionConflict("teaching session version changed")
        return updated

    def bind_learner_message_run(
        self, *, user_id: str, run_id: str, conversation_id: str, track_id: str,
        knowledge_key: str, message_id: str, input_revision: int,
    ) -> dict[str, object] | None:
        scope = self._conn.execute(
            """SELECT * FROM tutor_run_learning_scopes WHERE run_id=%s AND user_id=%s AND conversation_id=%s
               AND scope_kind='learning_track' AND task_kind='lesson_teaching' AND learning_track_id=%s AND knowledge_key=%s""",
            (run_id, user_id, conversation_id, track_id, stable(knowledge_key, "knowledge_key")),
        ).fetchone()
        if scope is None:
            return None
        try:
            session = self.read_current(user_id=user_id, track_id=track_id, knowledge_key=knowledge_key, for_update=True)
        except TeachingSessionNotFound:
            return None
        authority = self.resolve_authority(
            user_id=user_id, track_id=track_id, knowledge_key=knowledge_key,
            conversation_id=conversation_id, for_update=True,
        )
        self._assert_authority(session, authority)
        evidence = self._conn.execute(
            "SELECT id FROM tutor_run_input_events WHERE run_id=%s AND conversation_id=%s AND message_id=%s AND input_revision=%s",
            (run_id, conversation_id, message_id, input_revision),
        ).fetchone()
        if evidence is None:
            raise TeachingSessionConflict("learner message stimulus evidence is stale or mismatched")
        stimulus = LearnerMessageStimulus(message_id=message_id, input_revision=input_revision)
        return self._insert_stimulus_scope(run_id=run_id, session=session, authority=authority, stimulus=stimulus)

    def admit_control_run(
        self, *, authority: TeachingAuthority, session: Mapping[str, object], stimulus: TeachingControlStimulus,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        self._assert_version_and_authority(session, authority, stimulus.expected_session_version, stimulus)
        return self._create_stimulus_run(
            authority=authority, session=session, stimulus=stimulus, settings=settings,
        )

    def admit_domain_event_run(
        self, *, authority: TeachingAuthority, session: Mapping[str, object], stimulus: DomainEventStimulus,
        settings: Settings | None = None,
    ) -> dict[str, object]:
        self._assert_authority(session, authority)
        return self._create_stimulus_run(
            authority=authority, session=session, stimulus=stimulus, settings=settings,
        )

    def assert_run_scope_current(self, *, user_id: str, run_id: str) -> Mapping[str, object]:
        row = self._conn.execute(
            """SELECT scopes.*,sessions.current_checkpoint_id,sessions.version AS current_session_version,
                      sessions.status AS session_status
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_teaching_sessions AS sessions ON sessions.id=scopes.teaching_session_id
                 AND sessions.user_id=scopes.user_id AND sessions.conversation_id=scopes.conversation_id
               WHERE scopes.run_id=%s AND scopes.user_id=%s FOR UPDATE OF sessions""",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TeachingSessionNotFound("run teaching scope was not found")
        if str(row["current_checkpoint_id"]) != str(row["checkpoint_id"]):
            raise TeachingSessionConflict("run teaching checkpoint is stale")
        if _int(row["current_session_version"]) != _int(row["session_version"]):
            raise TeachingSessionConflict("run teaching session version is stale")
        if str(row["session_status"]) not in {"active", "paused"}:
            raise TeachingSessionConflict("run teaching session is not current")
        authority = self.resolve_authority(
            user_id=user_id, track_id=str(row["track_id"]), knowledge_key=str(row["knowledge_key"]),
            conversation_id=str(row["conversation_id"]), for_update=True,
        )
        if (authority.track_version, authority.plan_revision_id, authority.progress_version) != (
            _int(row["track_version"]), str(row["active_plan_revision_id"]), _int(row["progress_version"]),
        ):
            raise TeachingSessionConflict("run LearningTrack authority is stale")
        if authority.assignment_id != str(row["lesson_assignment_id"]) or authority.assignment_version != _int(row["assignment_version"]):
            raise TeachingSessionConflict("run lesson assignment authority is stale")
        if authority.document_id != str(row["document_id"]) or authority.document_content_hash != str(row["document_content_hash"]):
            raise TeachingSessionConflict("run LessonDocument authority is stale")
        return row

    def project_session(self, row: Mapping[str, object], *, include_checkpoint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "session_id": str(row["id"]), "track_id": str(row["track_id"]), "track_version": _int(row["track_version"]),
            "conversation_id": str(row["conversation_id"]), "knowledge_key": str(row["knowledge_key"]),
            "status": str(row["status"]), "mode": str(row["mode"]), "session_version": _int(row["version"]),
            "progress_version": _int(row["progress_version"]), "assignment_id": str(row["lesson_assignment_id"]),
            "assignment_version": _int(row["assignment_version"]), "document_id": str(row["document_id"]),
            "checkpoint_id": _optional_str(row.get("current_checkpoint_id")),
            "paused_at": _iso(row.get("paused_at")), "completed_at": _iso(row.get("completed_at")),
            "last_activity_at": _iso(row.get("last_activity_at")), "allowed_actions": [],
        }
        if include_checkpoint and row.get("current_checkpoint_id") is not None:
            checkpoint = self.current_checkpoint(session_id=str(row["id"]), user_id=str(row["user_id"]))
            state = self._checkpoint_state(checkpoint)
            result["checkpoint"] = {
                "checkpoint_id": str(checkpoint["id"]), "session_version": _int(checkpoint["session_version"]),
                "objective": state.objective.model_dump(mode="json"),
                "active_focus": state.active_focus.model_dump(mode="json") if state.active_focus is not None else None,
                "suspended_focuses": [item.model_dump(mode="json") for item in state.suspended_focuses],
                "unresolved_questions": [item.model_dump(mode="json") for item in state.unresolved_questions],
                "covered_concepts": list(state.covered_concepts), "evidence_cursors": [item.model_dump(mode="json") for item in state.evidence_cursors],
                "pause_reason": state.pause_reason.value, "recommended_action_key": state.recommended_action_key,
            }
        return result

    def conversation_projection(self, *, user_id: str, conversation_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s AND conversation_id=%s ORDER BY last_activity_at DESC,id DESC LIMIT 50",
            (user_id, conversation_id),
        ).fetchall()
        return [self.project_session(row, include_checkpoint=False) for row in rows]

    def _insert_checkpoint(
        self, *, session: Mapping[str, object], predecessor_id: str | None, session_version: int,
        state: TeachingCheckpointState, authority: TeachingAuthoritySnapshot,
        source_run_id: str | None, source_stimulus_id: str | None,
    ) -> Mapping[str, object]:
        state_json = state.model_dump(mode="json")
        authority_json = authority.model_dump(mode="json")
        source_hash = canonical_hash({"state": state_json, "authority": authority_json, "session_version": session_version,
                                      "source_run_id": source_run_id, "source_stimulus_id": source_stimulus_id})
        row = self._conn.execute(
            """INSERT INTO tutor_teaching_session_checkpoints (
                 teaching_session_id,user_id,conversation_id,predecessor_checkpoint_id,session_version,state_json,
                 authority_snapshot_json,source_run_id,source_stimulus_id,source_hash
               ) VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s) RETURNING *""",
            (session["id"], session["user_id"], session["conversation_id"], predecessor_id, session_version,
             _json(state_json), _json(authority_json), source_run_id, source_stimulus_id, source_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError("teaching checkpoint insert failed")
        return row

    def _insert_stimulus_scope(
        self, *, run_id: str, session: Mapping[str, object], authority: TeachingAuthority,
        stimulus: TutorTurnStimulus,
    ) -> dict[str, object]:
        parsed = _STIMULUS.validate_python(stimulus)
        existing = self._conn.execute("SELECT * FROM tutor_run_stimulus_events WHERE run_id=%s", (run_id,)).fetchone()
        payload = parsed.model_dump(mode="json")
        if existing is not None:
            if str(existing["payload_hash"]) != canonical_hash(payload):
                raise TeachingSessionConflict("run stimulus is immutable")
            scope = self._conn.execute("SELECT * FROM tutor_run_teaching_scopes WHERE run_id=%s", (run_id,)).fetchone()
            if scope is None:
                raise TeachingSessionConflict("run teaching scope is missing")
            return self._project_admission(existing, scope)
        checkpoint = self.current_checkpoint(session_id=str(session["id"]), user_id=authority.user_id)
        values = _stimulus_columns(parsed)
        stimulus_id = str(uuid4())
        row = self._conn.execute(
            """INSERT INTO tutor_run_stimulus_events (
                 id,run_id,user_id,conversation_id,teaching_session_id,stimulus_kind,message_id,input_revision,
                 control_key,client_action_id,expected_session_version,expected_track_version,
                 expected_progress_version,expected_assignment_version,domain_event_kind,source_id,source_version,
                 safe_payload_json,payload_hash
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING *""",
            (stimulus_id, run_id, authority.user_id, authority.conversation_id, session["id"], parsed.kind,
             *values, _json(_safe_stimulus_payload(parsed)), canonical_hash(payload)),
        ).fetchone()
        if row is None:
            raise RuntimeError("run stimulus insert failed")
        source_hash = canonical_hash({"session_id": str(session["id"]), "checkpoint_id": str(checkpoint["id"]),
                                      "session_version": _int(session["version"]), "stimulus_id": stimulus_id,
                                      "authority": authority.snapshot().model_dump(mode="json")})
        scope = self._conn.execute(
            """INSERT INTO tutor_run_teaching_scopes (
                 run_id,user_id,conversation_id,teaching_session_id,checkpoint_id,stimulus_id,session_version,
                 track_id,knowledge_key,track_version,active_plan_revision_id,progress_version,mode,
                 lesson_assignment_id,assignment_version,document_id,document_content_hash,source_hash
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (run_id, authority.user_id, authority.conversation_id, session["id"], checkpoint["id"], stimulus_id,
             session["version"], authority.track_id, authority.knowledge_key, authority.track_version,
             authority.plan_revision_id, authority.progress_version, session["mode"], authority.assignment_id,
             authority.assignment_version, authority.document_id, authority.document_content_hash, source_hash),
        ).fetchone()
        if scope is None:
            raise RuntimeError("run teaching scope insert failed")
        return self._project_admission(row, scope)

    def _ensure_run_learning_scope(self, *, run_id: str, authority: TeachingAuthority) -> None:
        existing = self._conn.execute("SELECT * FROM tutor_run_learning_scopes WHERE run_id=%s", (run_id,)).fetchone()
        if existing is not None:
            expected = (authority.user_id, authority.conversation_id, authority.track_id, authority.knowledge_key)
            observed = (str(existing["user_id"]), str(existing["conversation_id"]), str(existing["learning_track_id"]), str(existing["knowledge_key"]))
            if observed != expected or str(existing["task_kind"]) != "lesson_teaching":
                raise TeachingSessionConflict("run learning scope is inconsistent")
            return
        conversation_scope = self._conn.execute(
            """SELECT version FROM tutor_conversation_learning_scopes
               WHERE conversation_id=%s AND user_id=%s AND scope_kind='learning_track' AND learning_track_id=%s""",
            (authority.conversation_id, authority.user_id, authority.track_id),
        ).fetchone()
        if conversation_scope is None:
            raise TeachingSessionConflict("conversation LearningTrack scope is stale")
        self._conn.execute(
            """INSERT INTO tutor_run_learning_scopes (
                 run_id,user_id,conversation_id,scope_kind,learning_track_id,task_kind,knowledge_key,scope_version
               ) VALUES (%s,%s,%s,'learning_track',%s,'lesson_teaching',%s,%s)""",
            (run_id, authority.user_id, authority.conversation_id, authority.track_id,
             authority.knowledge_key, conversation_scope["version"]),
        )

    def _create_stimulus_run(
        self, *, authority: TeachingAuthority, session: Mapping[str, object], stimulus: TutorTurnStimulus,
        settings: Settings | None,
    ) -> dict[str, object]:
        active = self._conn.execute(
            """SELECT id FROM tutor_runs WHERE user_id=%s AND conversation_id=%s AND origin='interactive'
               AND terminal_outcome IS NULL AND cancelled_at IS NULL AND superseded_by_run_id IS NULL FOR UPDATE""",
            (authority.user_id, authority.conversation_id),
        ).fetchone()
        if active is not None:
            raise TeachingSessionConflict("conversation already has an active foreground run")
        repository = PostgresTutorRepository(self._conn)
        catalog = compile_published_skill_catalog()
        repository.record_catalog_snapshot(catalog)
        config = settings or get_settings()
        now = datetime.now(UTC)
        policy = TutorPolicySnapshot(
            deadline=now + timedelta(minutes=5), max_iterations=4, max_model_calls=3,
            max_capability_calls=2, max_effects=2, context_token_budget=config.tutor_context_token_budget,
            lease_duration_seconds=30, context_budget_policy=build_tutor_context_budget_policy(config),
        )
        run = repository.create_run(
            user_id=authority.user_id, conversation_id=authority.conversation_id,
            catalog_digest=catalog.digest, policy=policy, origin="interactive",
            policy_version="tutor_teaching_stimulus_policy_v1",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
        )
        self._ensure_run_learning_scope(run_id=run.run_id, authority=authority)
        projection = self._insert_stimulus_scope(run_id=run.run_id, session=session, authority=authority, stimulus=stimulus)
        return {**projection, "run_id": run.run_id, "origin": run.origin, "status": run.status.value}

    def _assert_authority(self, session: Mapping[str, object], authority: TeachingAuthority) -> None:
        expected = (
            authority.user_id, authority.track_id, authority.conversation_id, authority.knowledge_key,
            authority.track_version, authority.plan_revision_id, authority.progress_version, authority.assignment_id,
            authority.assignment_version, authority.document_id, authority.document_content_hash,
        )
        observed = (
            str(session["user_id"]), str(session["track_id"]), str(session["conversation_id"]), str(session["knowledge_key"]),
            _int(session["track_version"]), str(session["active_plan_revision_id"]), _int(session["progress_version"]), str(session["lesson_assignment_id"]),
            _int(session["assignment_version"]), str(session["document_id"]), str(session["document_content_hash"]),
        )
        if observed != expected:
            raise TeachingSessionConflict("teaching session authority is stale")

    def _assert_version_and_authority(
        self, session: Mapping[str, object], authority: TeachingAuthority, expected_session_version: int,
        control: TeachingControlStimulus,
    ) -> None:
        self._assert_authority(session, authority)
        if _int(session["version"]) != expected_session_version or control.expected_session_version != expected_session_version:
            raise TeachingSessionConflict("teaching session version is stale")
        if (control.expected_track_version, control.expected_progress_version, control.expected_assignment_version) != (
            authority.track_version, authority.progress_version, authority.assignment_version,
        ):
            raise TeachingSessionConflict("teaching authority version is stale")
        if str(session["status"]) == "completed":
            raise TeachingSessionConflict("teaching session is completed")

    @staticmethod
    def _checkpoint_state(row: Mapping[str, object]) -> TeachingCheckpointState:
        try:
            return TeachingCheckpointState.model_validate(row["state_json"])
        except ValidationError as exc:
            raise TeachingSessionConflict("stored teaching checkpoint is invalid") from exc

    @staticmethod
    def _project_admission(stimulus: Mapping[str, object], scope: Mapping[str, object]) -> dict[str, object]:
        return {
            "stimulus_id": str(stimulus["id"]), "stimulus_kind": str(stimulus["stimulus_kind"]),
            "session_id": str(scope["teaching_session_id"]), "checkpoint_id": str(scope["checkpoint_id"]),
            "session_version": _int(scope["session_version"]), "track_id": str(scope["track_id"]),
            "knowledge_key": str(scope["knowledge_key"]), "mode": str(scope["mode"]),
        }


class TeachingSessionServiceError(ValueError):
    def __init__(
        self, code: str, message: str, *, status_code: int,
        recoverable: bool = True, details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.recoverable = recoverable
        self.details = dict(details or {})


class TeachingSessionService:
    def __init__(self, conn: Connection[dict[str, object]], *, settings: Settings | None = None) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._repository = TeachingSessionRepository(conn)

    def list_sessions(self, *, user_id: str, track_id: str) -> dict[str, object]:
        user, track = _uuid(user_id, "user_id"), _uuid(track_id, "track_id")
        self._assert_track(user_id=user, track_id=track)
        rows = self._repository.list_sessions(user_id=user, track_id=track)
        return {"items": [self._repository.project_session(row, include_checkpoint=False) for row in rows]}

    def current(self, *, user_id: str, track_id: str, knowledge_key: str) -> dict[str, object]:
        user, track = _uuid(user_id, "user_id"), _uuid(track_id, "track_id")
        try:
            row = self._repository.read_current(user_id=user, track_id=track, knowledge_key=knowledge_key)
        except TeachingSessionNotFound as exc:
            raise self._not_found(track, knowledge_key) from exc
        return self._repository.project_session(row)

    def open(
        self, *, user_id: str, track_id: str, knowledge_key: str, conversation_id: str | None,
        expected_track_version: int, expected_progress_version: int, expected_assignment_version: int,
        mode: TeachingSessionMode, idempotency_key: str,
    ) -> dict[str, object]:
        user, track = _uuid(user_id, "user_id"), _uuid(track_id, "track_id")
        conversation = _uuid(conversation_id, "conversation_id") if conversation_id is not None else None
        request = {
            "track_id": track, "knowledge_key": stable(knowledge_key, "knowledge_key"),
            "conversation_id": conversation, "expected_track_version": expected_track_version,
            "expected_progress_version": expected_progress_version,
            "expected_assignment_version": expected_assignment_version, "mode": mode.value,
        }
        return self._mutate(
            user_id=user, operation=f"teaching.open:{track}:{request['knowledge_key']}",
            idempotency_key=idempotency_key, request_body=request,
            action=lambda: self._open(
                user_id=user, track_id=track, knowledge_key=str(request["knowledge_key"]), conversation_id=conversation,
                expected_track_version=expected_track_version, expected_progress_version=expected_progress_version,
                expected_assignment_version=expected_assignment_version, mode=mode,
            ),
        )

    def action(
        self, *, user_id: str, track_id: str, session_id: str, control: TeachingControlStimulus,
        target_mode: TeachingSessionMode | None, admit_run: bool, idempotency_key: str,
    ) -> dict[str, object]:
        user, track, session = _uuid(user_id, "user_id"), _uuid(track_id, "track_id"), _uuid(session_id, "session_id")
        request = {
            "track_id": track, "session_id": session, "control": control.model_dump(mode="json"),
            "target_mode": target_mode.value if target_mode is not None else None, "admit_run": admit_run,
        }
        return self._mutate(
            user_id=user, operation=f"teaching.action:{session}", idempotency_key=idempotency_key,
            request_body=request,
            action=lambda: self._action(
                user_id=user, track_id=track, session_id=session, control=control,
                target_mode=target_mode, admit_run=admit_run,
            ),
        )

    def _open(
        self, *, user_id: str, track_id: str, knowledge_key: str, conversation_id: str | None,
        expected_track_version: int, expected_progress_version: int, expected_assignment_version: int,
        mode: TeachingSessionMode,
    ) -> dict[str, object]:
        try:
            authority = self._repository.resolve_authority(
                user_id=user_id, track_id=track_id, knowledge_key=knowledge_key,
                conversation_id=conversation_id, for_update=True,
            )
            self._assert_expected(authority, expected_track_version, expected_progress_version, expected_assignment_version)
            row, created = self._repository.open_or_resume(authority=authority, mode=mode)
        except TeachingSessionNotFound as exc:
            raise self._not_found(track_id, knowledge_key) from exc
        except TeachingSessionConflict as exc:
            raise self._conflict(str(exc)) from exc
        return {"teaching_session": self._repository.project_session(row), "created": created}

    def _action(
        self, *, user_id: str, track_id: str, session_id: str, control: TeachingControlStimulus,
        target_mode: TeachingSessionMode | None, admit_run: bool,
    ) -> dict[str, object]:
        if admit_run and control.control_key.value not in {"continue", "return_focus", "enter_next_knowledge"}:
            raise TeachingSessionServiceError(
                "TEACHING_STIMULUS_INVALID", "该教学控制不能创建 Tutor Turn。", status_code=409, recoverable=False,
            )
        try:
            session = self._repository.read_by_id(user_id=user_id, track_id=track_id, session_id=session_id, for_update=True)
            authority = self._repository.resolve_authority(
                user_id=user_id, track_id=track_id, knowledge_key=str(session["knowledge_key"]),
                conversation_id=str(session["conversation_id"]), for_update=True,
            )
            updated = self._repository.mutate(
                session=session, authority=authority, expected_session_version=control.expected_session_version,
                control=control, target_mode=target_mode,
            )
            pending_run = None
            if admit_run:
                admitted_control = control.model_copy(update={"expected_session_version": _int(updated["version"])})
                pending_run = self._repository.admit_control_run(
                    authority=authority, session=updated, stimulus=admitted_control, settings=self._settings,
                )
        except TeachingSessionNotFound as exc:
            raise self._not_found(track_id, session_id) from exc
        except TeachingSessionConflict as exc:
            raise self._conflict(str(exc)) from exc
        except TeachingSessionInvalid as exc:
            raise TeachingSessionServiceError("TEACHING_ACTION_INVALID", str(exc), status_code=400) from exc
        return {"teaching_session": self._repository.project_session(updated), "pending_run": pending_run}

    @staticmethod
    def _assert_expected(authority: TeachingAuthority, track_version: int, progress_version: int, assignment_version: int) -> None:
        if (authority.track_version, authority.progress_version, authority.assignment_version) != (
            track_version, progress_version, assignment_version,
        ):
            raise TeachingSessionConflict("teaching authority version is stale")

    def _mutate(
        self, *, user_id: str, operation: str, idempotency_key: str,
        request_body: Mapping[str, object], action: Callable[[], dict[str, object]],
    ) -> dict[str, object]:
        key = _idempotency_key(idempotency_key)
        request_hash = canonical_hash(request_body)
        with self._conn.transaction():
            self._assert_user(user_id)
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s),hashtext(%s))",
                (user_id, f"{operation}:{key}"),
            )
            existing = self._conn.execute(
                """SELECT request_hash,response_json FROM tutor_api_idempotency_records
                   WHERE user_id=%s AND operation=%s AND idempotency_key=%s FOR UPDATE""",
                (user_id, operation, key),
            ).fetchone()
            if existing is not None:
                if str(existing["request_hash"]) != request_hash:
                    raise TeachingSessionServiceError(
                        "IDEMPOTENCY_CONFLICT", "同一幂等标识不能用于不同的教学请求。",
                        status_code=409, recoverable=False,
                    )
                response = dict(existing["response_json"]) if isinstance(existing["response_json"], Mapping) else {}
                response["idempotent_replayed"] = True
                return response
            response = action()
            response["idempotent_replayed"] = False
            self._conn.execute(
                """INSERT INTO tutor_api_idempotency_records
                   (user_id,operation,idempotency_key,request_hash,response_json)
                   VALUES (%s,%s,%s,%s,%s::jsonb)""",
                (user_id, operation, key, request_hash, _json(response)),
            )
            return response

    def _assert_user(self, user_id: str) -> None:
        if self._conn.execute("SELECT id FROM users WHERE id=%s AND deleted_at IS NULL", (user_id,)).fetchone() is None:
            raise TeachingSessionServiceError("USER_NOT_FOUND", "用户不存在。", status_code=404)

    def _assert_track(self, *, user_id: str, track_id: str) -> None:
        self._assert_user(user_id)
        if self._conn.execute("SELECT id FROM tutor_learning_tracks WHERE id=%s AND user_id=%s", (track_id, user_id)).fetchone() is None:
            raise TeachingSessionServiceError("LEARNING_TRACK_NOT_FOUND", "学习轨道不存在。", status_code=404)

    @staticmethod
    def _not_found(track_id: str, key: str) -> TeachingSessionServiceError:
        return TeachingSessionServiceError(
            "TEACHING_SESSION_NOT_FOUND", "教学会话不存在或当前知识点尚未具备权威课程。",
            status_code=404, details={"track_id": track_id, "knowledge_key": key},
        )

    @staticmethod
    def _conflict(reason: str) -> TeachingSessionServiceError:
        return TeachingSessionServiceError(
            "TEACHING_AUTHORITY_CONFLICT", "教学会话 authority 已过期或范围不一致。",
            status_code=409, details={"reason": reason},
        )


def _stimulus_columns(stimulus: TutorTurnStimulus) -> tuple[object, ...]:
    if isinstance(stimulus, LearnerMessageStimulus):
        return (stimulus.message_id, stimulus.input_revision, None, None, None, None, None, None, None, None, None)
    if isinstance(stimulus, TeachingControlStimulus):
        return (
            None, None, stimulus.control_key.value, stimulus.client_action_id,
            stimulus.expected_session_version, stimulus.expected_track_version,
            stimulus.expected_progress_version, stimulus.expected_assignment_version,
            None, None, None,
        )
    if isinstance(stimulus, DomainEventStimulus):
        return (None, None, None, None, None, None, None, None, stimulus.event_kind.value, stimulus.source_id, stimulus.source_version)
    raise TypeError("unsupported TutorTurnStimulus")


def _safe_stimulus_payload(stimulus: TutorTurnStimulus) -> dict[str, object]:
    if isinstance(stimulus, TeachingControlStimulus):
        return dict(stimulus.safe_payload)
    if isinstance(stimulus, DomainEventStimulus):
        return {"safe_handles": list(stimulus.safe_handles)}
    return {}


def _idempotency_key(value: str) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY.fullmatch(normalized):
        raise TeachingSessionServiceError("VALIDATION_ERROR", "幂等标识不合法。", status_code=400)
    return normalized


def _uuid(value: object, label: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise TeachingSessionServiceError("VALIDATION_ERROR", f"{label} 不合法。", status_code=400) from exc


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _int(value: object) -> int:
    if isinstance(value, bool):
        raise TeachingSessionConflict("stored integer is invalid")
    return int(str(value))


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
