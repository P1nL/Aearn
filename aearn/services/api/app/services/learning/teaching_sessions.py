"""PostgreSQL teaching-session authority, checkpoint CAS, and structured stimuli."""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from psycopg import Connection
from pydantic import TypeAdapter, ValidationError

from app.agents.harness.contracts import TutorPolicySnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings, get_settings
from app.core.teaching_safety import sanitize_summary_text
from app.services.learning.artifacts.contracts import assert_public_artifact_safe
from app.services.learning.item_bank.repository import PostgresLearningItemBankRepository
from app.services.learning.teaching_candidates import (
    TeachingArtifactCandidateBuildError,
    TeachingArtifactCandidateBuilder,
    bound_teaching_artifact_candidates,
)
from app.services.learning.teaching_loop import build_teaching_action_shelf
from app.services.learning.teaching_contracts import (
    DomainEventStimulus,
    LearnerMessageStimulus,
    TeachingArtifactCandidateScope,
    TeachingAuthoritySnapshot,
    TeachingCheckpointState,
    TeachingControlKey,
    TeachingControlStimulus,
    TeachingPauseReason,
    TeachingSessionMode,
    TeachingSessionStatus,
    TeachingSessionSummaryV1,
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
    def __init__(
        self,
        conn: Connection[dict[str, object]],
        *,
        settings: Settings | None = None,
        artifact_candidate_builder: TeachingArtifactCandidateBuilder | None = None,
    ) -> None:
        self._conn = conn
        self._settings = settings or get_settings()
        self._artifact_candidate_builder = artifact_candidate_builder or TeachingArtifactCandidateBuilder(
            PostgresLearningItemBankRepository(conn)
        )

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
            "ORDER BY CASE WHEN status IN ('active','paused') THEN 0 WHEN status='completed' THEN 1 ELSE 2 END, "
            "created_at DESC,id DESC LIMIT 1" + (" FOR UPDATE" if for_update else ""),
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
            "AND knowledge_key=%s AND status IN ('active','paused','completed') "
            "ORDER BY CASE WHEN status IN ('active','paused') THEN 0 ELSE 1 END, created_at DESC,id DESC "
            "LIMIT 1 FOR UPDATE",
            (authority.user_id, authority.track_id, authority.conversation_id, authority.knowledge_key),
        ).fetchone()
        predecessor_session_id: str | None = None
        if existing is not None:
            try:
                self._assert_authority(existing, authority)
            except TeachingSessionConflict:
                predecessor_session_id = self._block_stale_session(existing)
            else:
                return existing, False
        session_id = str(uuid4())
        row = self._conn.execute(
            """INSERT INTO tutor_teaching_sessions (
                 id,user_id,track_id,conversation_id,knowledge_key,track_version,active_plan_revision_id,progress_version,
                 lesson_assignment_id,assignment_version,document_id,document_content_hash,predecessor_session_id,
                 status,mode,version,last_activity_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,1,now()) RETURNING *""",
            (session_id, authority.user_id, authority.track_id, authority.conversation_id, authority.knowledge_key,
             authority.track_version, authority.plan_revision_id, authority.progress_version, authority.assignment_id,
             authority.assignment_version, authority.document_id, authority.document_content_hash,
             predecessor_session_id, mode.value),
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

    def _block_stale_session(self, session: Mapping[str, object]) -> str:
        active_run = self._conn.execute(
            """SELECT runs.id FROM tutor_runs AS runs
               JOIN tutor_run_teaching_scopes AS scopes ON scopes.run_id=runs.id
               WHERE scopes.teaching_session_id=%s AND runs.user_id=%s
                 AND runs.terminal_outcome IS NULL AND runs.cancelled_at IS NULL
                 AND runs.superseded_by_run_id IS NULL
               LIMIT 1 FOR UPDATE OF runs""",
            (session["id"], session["user_id"]),
        ).fetchone()
        if active_run is not None:
            raise TeachingSessionConflict("stale teaching session still has an active run")
        checkpoint = self.current_checkpoint(
            session_id=str(session["id"]), user_id=str(session["user_id"]),
        )
        state = self._checkpoint_state(checkpoint).model_copy(update={
            "pause_reason": TeachingPauseReason.AUTHORITY_PAUSE,
            "recommended_action_key": "refresh_session",
        })
        authority = TeachingAuthoritySnapshot(
            track_version=_int(session["track_version"]),
            plan_revision_id=str(session["active_plan_revision_id"]),
            progress_version=_int(session["progress_version"]),
            assignment_id=str(session["lesson_assignment_id"]),
            assignment_version=_int(session["assignment_version"]),
            document_id=str(session["document_id"]),
            document_content_hash=str(session["document_content_hash"]),
        )
        next_version = _int(session["version"]) + 1
        next_checkpoint = self._insert_checkpoint(
            session=session, predecessor_id=str(checkpoint["id"]), session_version=next_version,
            state=state, authority=authority, source_run_id=None, source_stimulus_id=None,
        )
        updated = self._conn.execute(
            """UPDATE tutor_teaching_sessions SET status='blocked',current_checkpoint_id=%s,
                 version=version+1,paused_at=NULL,last_activity_at=now(),
                 last_mutation_key='authority-refresh',last_mutation_hash=%s
               WHERE id=%s AND user_id=%s AND version=%s RETURNING id""",
            (next_checkpoint["id"], canonical_hash({"session_id": str(session["id"]), "reason": "authority_stale"}),
             session["id"], session["user_id"], session["version"]),
        ).fetchone()
        if updated is None:
            raise TeachingSessionConflict("stale teaching session changed before refresh")
        return str(session["id"])

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
        elif control.control_key.value == "escalate_guided":
            mode = TeachingSessionMode.GUIDED
            status, paused_at = TeachingSessionStatus.ACTIVE, None
        elif control.control_key.value == "return_focus":
            suspended = list(state.suspended_focuses)
            if not suspended:
                raise TeachingSessionConflict("no suspended teaching focus is available")
            resolved = state.active_focus.focus_id if state.active_focus is not None else None
            state = state.model_copy(update={
                "active_focus": suspended.pop(),
                "suspended_focuses": tuple(suspended),
                "unresolved_questions": tuple(
                    item for item in state.unresolved_questions if item.question_id != resolved
                ),
                "recommended_action_key": "continue",
            })
        elif control.control_key.value == "change_example":
            state = state.model_copy(update={"recommended_action_key": "continue"})
        elif control.control_key.value == "pause":
            status, paused_at = TeachingSessionStatus.PAUSED, datetime.now(UTC)
            state = state.model_copy(update={"pause_reason": TeachingPauseReason.SESSION_PAUSE})
        elif control.control_key.value == "resume":
            status, paused_at = TeachingSessionStatus.ACTIVE, None
            state = state.model_copy(update={"pause_reason": TeachingPauseReason.SOFT_PAUSE})
        elif control.control_key.value == "continue":
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

    def find_domain_event_admission(
        self, *, user_id: str, track_id: str, knowledge_key: str, stimulus: DomainEventStimulus,
    ) -> dict[str, object] | None:
        row = self._conn.execute(
            """SELECT stimuli.id AS stimulus_id, scopes.teaching_session_id, scopes.checkpoint_id,
                      scopes.session_version, scopes.track_id, scopes.knowledge_key, scopes.mode,
                      runs.id AS run_id, runs.origin, runs.status, jobs.id AS dispatch_job_id
               FROM tutor_run_stimulus_events AS stimuli
               JOIN tutor_run_teaching_scopes AS scopes ON scopes.stimulus_id=stimuli.id
               JOIN tutor_runs AS runs ON runs.id=stimuli.run_id AND runs.user_id=stimuli.user_id
               LEFT JOIN tutor_interactive_dispatch_jobs AS jobs ON jobs.run_id=runs.id
               WHERE stimuli.user_id=%s AND scopes.track_id=%s AND scopes.knowledge_key=%s
                 AND stimuli.stimulus_kind='domain_event' AND stimuli.domain_event_kind=%s
                 AND stimuli.source_id=%s AND stimuli.source_version=%s""",
            (user_id, track_id, stable(knowledge_key, "knowledge_key"), stimulus.event_kind.value,
             stimulus.source_id, stimulus.source_version),
        ).fetchone()
        if row is None:
            return None
        return {
            "stimulus_id": str(row["stimulus_id"]), "stimulus_kind": "domain_event",
            "session_id": str(row["teaching_session_id"]), "checkpoint_id": str(row["checkpoint_id"]),
            "session_version": _int(row["session_version"]), "track_id": str(row["track_id"]),
            "knowledge_key": str(row["knowledge_key"]), "mode": str(row["mode"]),
            "run_id": str(row["run_id"]), "origin": str(row["origin"]),
            "status": str(row["status"]),
            "dispatch_job_id": _optional_str(row.get("dispatch_job_id")),
        }

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

    def structured_summary(
        self, *, session: Mapping[str, object], checkpoint: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        selected = checkpoint or self.current_checkpoint(
            session_id=str(session["id"]), user_id=str(session["user_id"]),
        )
        if (
            str(selected["teaching_session_id"]) != str(session["id"])
            or str(selected["user_id"]) != str(session["user_id"])
            or str(selected["conversation_id"]) != str(session["conversation_id"])
            or str(session.get("current_checkpoint_id") or "") != str(selected["id"])
            or _int(selected["session_version"]) != _int(session["version"])
        ):
            raise TeachingSessionConflict("teaching summary checkpoint is stale")
        state = self._checkpoint_state(selected)
        try:
            authority = TeachingAuthoritySnapshot.model_validate(selected["authority_snapshot_json"])
        except ValidationError as exc:
            raise TeachingSessionConflict("stored teaching summary authority is invalid") from exc
        expected_authority = (
            _int(session["track_version"]), str(session["active_plan_revision_id"]),
            _int(session["progress_version"]), str(session["lesson_assignment_id"]),
            _int(session["assignment_version"]), str(session["document_id"]),
            str(session["document_content_hash"]),
        )
        observed_authority = (
            authority.track_version, authority.plan_revision_id, authority.progress_version,
            authority.assignment_id, authority.assignment_version, authority.document_id,
            authority.document_content_hash,
        )
        if observed_authority != expected_authority:
            raise TeachingSessionConflict("teaching summary authority is stale")
        state_json = state.model_dump(mode="json")
        authority_json = authority.model_dump(mode="json")
        source_run_id = _optional_str(selected.get("source_run_id"))
        source_stimulus_id = _optional_str(selected.get("source_stimulus_id"))
        expected_hash = canonical_hash({
            "state": state_json, "authority": authority_json,
            "session_version": _int(selected["session_version"]),
            "source_run_id": source_run_id, "source_stimulus_id": source_stimulus_id,
        })
        if expected_hash != str(selected["source_hash"]):
            raise TeachingSessionConflict("teaching summary source hash is stale")
        summary = TeachingSessionSummaryV1(
            teaching_session_id=str(session["id"]), knowledge_key=str(session["knowledge_key"]),
            session_version=_int(session["version"]), status=TeachingSessionStatus(str(session["status"])),
            mode=TeachingSessionMode(str(session["mode"])), objective=state.objective,
            active_focus=state.active_focus, suspended_focuses=state.suspended_focuses,
            unresolved_questions=state.unresolved_questions, covered_concepts=state.covered_concepts,
            evidence_cursors=state.evidence_cursors, pause_reason=state.pause_reason,
            recommended_action_key=state.recommended_action_key, source_checkpoint_id=str(selected["id"]),
            predecessor_checkpoint_id=_optional_str(selected.get("predecessor_checkpoint_id")),
            source_checkpoint_hash=expected_hash, authority_snapshot_hash=canonical_hash(authority_json),
        )
        return summary.model_dump(mode="json")

    def teaching_message_semantics(
        self, *, user_id: str, run_id: str,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        scope = self._conn.execute(
            "SELECT teaching_session_id FROM tutor_run_teaching_scopes WHERE run_id=%s AND user_id=%s",
            (run_id, user_id),
        ).fetchone()
        if scope is None:
            return (), ()
        session_id = str(scope["teaching_session_id"])
        checkpoint = self.current_checkpoint(session_id=session_id, user_id=user_id)
        state = self._checkpoint_state(checkpoint)
        unresolved = tuple(
            dict.fromkeys(
                item.source_message_id for item in state.unresolved_questions
                if item.source_message_id is not None
            )
        )
        handle_ids: list[str] = []
        focus_items = (state.objective, *(state.suspended_focuses), *(() if state.active_focus is None else (state.active_focus,)))
        for item in focus_items:
            handle_ids.extend(
                handle.removeprefix("message:")
                for handle in item.source_handles if handle.startswith("message:")
            )
        latest = self._conn.execute(
            """SELECT inputs.message_id::text AS message_id
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_run_input_events AS inputs ON inputs.run_id=scopes.run_id
               JOIN tutor_messages AS messages ON messages.id=inputs.message_id
               WHERE scopes.teaching_session_id=%s AND scopes.user_id=%s
               ORDER BY messages.created_at DESC,messages.id DESC LIMIT 1""",
            (session_id, user_id),
        ).fetchone()
        corrections = tuple(dict.fromkeys((*handle_ids, *(() if latest is None else (str(latest["message_id"]),)))))
        return corrections, unresolved

    def teaching_context(self, *, user_id: str, run_id: str) -> dict[str, object] | None:
        scope_exists = self._conn.execute(
            "SELECT 1 FROM tutor_run_teaching_scopes WHERE run_id=%s AND user_id=%s", (run_id, user_id),
        ).fetchone()
        if scope_exists is None:
            return None
        self.assert_run_scope_current(user_id=user_id, run_id=run_id)
        row = self._conn.execute(
            """SELECT scopes.*, sessions.status AS session_status, sessions.current_checkpoint_id,
                      checkpoints.state_json, stimuli.stimulus_kind, stimuli.message_id, stimuli.input_revision,
                      stimuli.control_key, stimuli.client_action_id, stimuli.domain_event_kind, stimuli.source_id,
                      stimuli.source_version, stimuli.safe_payload_json,
                      progress.status AS progress_status,
                      nodes.required_capabilities_json AS available_capabilities_json
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_teaching_sessions AS sessions ON sessions.id=scopes.teaching_session_id
                 AND sessions.user_id=scopes.user_id AND sessions.conversation_id=scopes.conversation_id
               JOIN tutor_teaching_session_checkpoints AS checkpoints ON checkpoints.id=scopes.checkpoint_id
                 AND checkpoints.teaching_session_id=scopes.teaching_session_id
               JOIN tutor_run_stimulus_events AS stimuli ON stimuli.id=scopes.stimulus_id AND stimuli.run_id=scopes.run_id
               JOIN tutor_track_node_progress AS progress ON progress.track_id=scopes.track_id
                 AND progress.user_id=scopes.user_id AND progress.knowledge_key=scopes.knowledge_key
               JOIN tutor_track_plan_nodes AS nodes ON nodes.revision_id=scopes.active_plan_revision_id
                 AND nodes.track_id=scopes.track_id AND nodes.user_id=scopes.user_id
                 AND nodes.knowledge_key=scopes.knowledge_key
               WHERE scopes.run_id=%s AND scopes.user_id=%s""",
            (run_id, user_id),
        ).fetchone()
        if row is None:
            raise TeachingSessionConflict("teaching context authority is missing")
        if str(row["current_checkpoint_id"]) != str(row["checkpoint_id"]):
            raise TeachingSessionConflict("teaching context checkpoint is stale")
        state = self._checkpoint_state(row)
        handles: set[str] = {
            f"knowledge:{row['knowledge_key']}", f"stimulus:{row['stimulus_id']}",
            *state.objective.source_handles,
        }
        if state.active_focus is not None:
            handles.update(state.active_focus.source_handles)
        for focus in state.suspended_focuses:
            handles.update(focus.source_handles)
        for evidence in state.evidence_cursors:
            handles.add(f"{evidence.evidence_kind}:{evidence.source_id}")
        references = self._conn.execute(
            "SELECT id FROM tutor_message_context_references WHERE run_id=%s AND user_id=%s ORDER BY reference_index",
            (run_id, user_id),
        ).fetchall()
        handles.update(f"context-reference:{item['id']}" for item in references)
        stimulus_kind = str(row["stimulus_kind"])
        raw_safe_payload = row.get("safe_payload_json")
        safe_payload = (
            {str(key): value for key, value in raw_safe_payload.items()}
            if isinstance(raw_safe_payload, Mapping)
            else {}
        )
        result_evaluation_summary = self._result_evaluation_summary(
            row=row,
            safe_payload=safe_payload,
        )
        knowledge_check_evaluation = self._knowledge_check_evaluation(
            row=row,
            safe_payload=safe_payload,
        )
        model_review_evaluation = self._model_review_evaluation(
            row=row,
            safe_payload=safe_payload,
        )
        if result_evaluation_summary is not None:
            source_handle = str(safe_payload["source_handle"])
            safe_payload = {
                "reason_code": "result_evaluation",
                "source_handle": source_handle,
                "result_summary": result_evaluation_summary,
            }
            handles.add(source_handle)
        elif knowledge_check_evaluation is not None:
            source_handle = str(safe_payload["source_handle"])
            evaluation_summary, successor_handle = knowledge_check_evaluation
            safe_payload = {
                "reason_code": "knowledge_check_evaluation",
                "source_handle": source_handle,
                "evaluation_summary": evaluation_summary,
            }
            handles.add(source_handle)
        elif model_review_evaluation is not None:
            source_handle = str(safe_payload["source_handle"])
            evaluation_summary, successor_handle = model_review_evaluation
            safe_payload = {
                "reason_code": "model_review_evaluation",
                "source_handle": source_handle,
                "evaluation_summary": evaluation_summary,
            }
            handles.add(source_handle)
        stimulus: dict[str, object] = {
            "stimulus_id": str(row["stimulus_id"]),
            "kind": stimulus_kind,
            "safe_payload": safe_payload,
        }
        if stimulus_kind == "learner_message":
            stimulus.update(message_id=_optional_str(row.get("message_id")), input_revision=row.get("input_revision"))
        elif stimulus_kind == "teaching_control":
            stimulus["control_key"] = _optional_str(row.get("control_key"))
        elif stimulus_kind == "domain_event":
            stimulus.update(
                event_kind=_optional_str(row.get("domain_event_kind")),
                source_id=_optional_str(row.get("source_id")),
                source_version=row.get("source_version"),
            )
        else:
            raise TeachingSessionConflict("teaching stimulus kind is invalid")
        candidate_focus_id = stable(f"stimulus:{row['stimulus_id']}", "stimulus focus")
        session_row = self.read_by_id(
            user_id=user_id, track_id=str(row["track_id"]), session_id=str(row["teaching_session_id"]),
        )
        checkpoint_row = self.current_checkpoint(
            session_id=str(row["teaching_session_id"]), user_id=user_id,
        )
        structured_summary = self.structured_summary(session=session_row, checkpoint=checkpoint_row)
        recent_receipts = self._conn.execute(
            """SELECT action,focus_id,teaching_moves_json,learner_response_mode,public_message_hash,schema_version
               FROM tutor_teaching_action_receipts
               WHERE teaching_session_id=%s AND user_id=%s
               ORDER BY created_at DESC,id DESC LIMIT 4""",
            (row["teaching_session_id"], user_id),
        ).fetchall()
        recent_teaching_units = [
            {
                "action": str(item["action"]),
                "focus_id": str(item["focus_id"]),
                "teaching_moves": _string_list(item["teaching_moves_json"]),
                "learner_response_mode": str(item["learner_response_mode"]),
                "public_message_hash": str(item["public_message_hash"]),
                "schema_version": str(item["schema_version"]),
            }
            for item in reversed(recent_receipts)
        ]
        historical_summaries: list[dict[str, object]] = []
        predecessor_id = session_row.get("predecessor_session_id")
        if predecessor_id is not None:
            predecessor = self.read_by_id(
                user_id=user_id, track_id=str(row["track_id"]), session_id=str(predecessor_id),
            )
            historical_summaries.append(self.structured_summary(session=predecessor))
        candidate_scope = TeachingArtifactCandidateScope(
            teaching_session_id=str(row["teaching_session_id"]),
            checkpoint_id=str(row["checkpoint_id"]),
            track_id=str(row["track_id"]),
            knowledge_key=str(row["knowledge_key"]),
            session_version=_int(row["session_version"]),
            track_version=_int(row["track_version"]),
            progress_version=_int(row["progress_version"]),
            assignment_id=str(row["lesson_assignment_id"]),
            assignment_version=_int(row["assignment_version"]),
        )
        try:
            artifact_evaluation = knowledge_check_evaluation or model_review_evaluation
            required_successor_handles = (
                (artifact_evaluation[1],)
                if artifact_evaluation is not None and artifact_evaluation[1] is not None
                else ()
            )
            artifact_candidates = self._artifact_candidate_builder.build(
                scope=candidate_scope,
                available_capabilities=_string_list(row.get("available_capabilities_json")),
                learning_artifacts_enabled=self._settings.tutor_learning_artifacts_enabled,
                artifact_teaching_enabled=self._settings.tutor_artifact_teaching_mode_enabled,
                required_handles=required_successor_handles,
                excluded_purposes=() if required_successor_handles else ("remediation", "transfer_check"),
            )
        except TeachingArtifactCandidateBuildError as exc:
            raise TeachingSessionConflict("teaching artifact candidate authority is invalid") from exc
        if result_evaluation_summary is not None:
            artifact_candidates = artifact_candidates.model_copy(
                update={"candidates": ()}
            )
        elif knowledge_check_evaluation is not None or model_review_evaluation is not None:
            artifact_evaluation = knowledge_check_evaluation or model_review_evaluation
            assert artifact_evaluation is not None
            _summary, successor_handle = artifact_evaluation
            candidates = tuple(
                item
                for item in artifact_candidates.candidates
                if successor_handle is not None and item.handle == successor_handle
            )
            if successor_handle is not None and len(candidates) != 1:
                raise TeachingSessionConflict(
                    "Artifact evaluation successor is stale or unavailable"
                )
            artifact_candidates = artifact_candidates.model_copy(
                update={"candidates": candidates}
            )
        else:
            artifact_candidates = artifact_candidates.model_copy(
                update={
                    "candidates": tuple(
                        item
                        for item in artifact_candidates.candidates
                        if item.purpose not in {"remediation", "transfer_check"}
                    )
                }
            )
        context: dict[str, object] = {
            "schema_version": "teaching_session_context_v2",
            "session": {
                "session_id": str(row["teaching_session_id"]), "session_version": _int(row["session_version"]),
                "checkpoint_id": str(row["checkpoint_id"]), "status": str(row["session_status"]),
                "mode": str(row["mode"]), "knowledge_key": str(row["knowledge_key"]),
                "track_id": str(row["track_id"]), "assignment_id": str(row["lesson_assignment_id"]),
                "track_version": _int(row["track_version"]), "progress_version": _int(row["progress_version"]),
                "progress_status": str(row["progress_status"]), "assignment_version": _int(row["assignment_version"]),
            },
            "stimulus": stimulus,
            "objective": state.objective.model_dump(mode="json"),
            "active_focus": state.active_focus.model_dump(mode="json") if state.active_focus is not None else None,
            "suspended_focuses": [item.model_dump(mode="json") for item in state.suspended_focuses],
            "unresolved_questions": [item.model_dump(mode="json") for item in state.unresolved_questions],
            "covered_concepts": list(state.covered_concepts),
            "pause_kind": state.pause_reason.value,
            "recommended_action_key": state.recommended_action_key,
            "candidate_focus_id": candidate_focus_id,
            "structured_summary": structured_summary,
            "related_historical_summaries": historical_summaries,
            "recent_teaching_units": recent_teaching_units,
            "artifact_candidates": artifact_candidates.model_dump(mode="json"),
            "allowed_source_handles": sorted(handles),
            "action_policy": "lesson_teaching_v3",
        }
        try:
            bounded_candidates = bound_teaching_artifact_candidates(
                context=context,
                candidates=artifact_candidates,
                minimum_candidates=1 if required_successor_handles else 0,
            )
        except (TypeError, ValueError) as exc:
            raise TeachingSessionConflict(
                "teaching artifact candidate projection is invalid"
            ) from exc
        context["artifact_candidates"] = bounded_candidates.model_dump(mode="json")
        return context

    def _result_evaluation_summary(
        self,
        *,
        row: Mapping[str, object],
        safe_payload: Mapping[str, object],
    ) -> str | None:
        if safe_payload.get("reason_code") != "result_evaluation":
            return None
        source_handle = str(safe_payload.get("source_handle") or "")
        if not source_handle.startswith("artifact:"):
            raise TeachingSessionConflict(
                "result-evaluation source handle is invalid"
            )
        artifact_id = source_handle.removeprefix("artifact:")
        rows = self._conn.execute(
            """
            SELECT artifacts.instruction_markdown, artifacts.active_attempt_id,
                   artifacts.presentation_json
            FROM tutor_continuation_intents AS intents
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id = intents.artifact_id
             AND artifacts.user_id = intents.user_id
             AND artifacts.conversation_id = intents.conversation_id
             AND artifacts.teaching_session_id = intents.teaching_session_id
             AND artifacts.learning_track_id = intents.learning_track_id
             AND artifacts.knowledge_key = intents.knowledge_key
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id = artifacts.id
             AND events.id::text = intents.source_id
             AND events.event_sequence = intents.source_version
            WHERE intents.consumed_run_id = %s
              AND intents.user_id = %s
              AND intents.conversation_id = %s
              AND intents.teaching_session_id = %s
              AND intents.learning_track_id = %s
              AND intents.knowledge_key = %s
              AND intents.artifact_id = %s
              AND intents.state = 'consumed'
              AND intents.source_kind = 'explicit_artifact_action'
              AND intents.idempotency_key = 'result-evaluation:' || intents.source_id
              AND artifacts.artifact_kind = 'test_result'
              AND artifacts.purpose = 'result'
              AND artifacts.state = 'completed'
              AND NOT artifacts.blocking
              AND artifacts.presentation_kind = 'test_result_v1'
              AND events.event_kind = 'created'
            LIMIT 2
            """,
            (
                row["run_id"],
                row["user_id"],
                row["conversation_id"],
                row["teaching_session_id"],
                row["track_id"],
                row["knowledge_key"],
                artifact_id,
            ),
        ).fetchall()
        if len(rows) != 1:
            raise TeachingSessionConflict(
                "result-evaluation continuation authority is missing or ambiguous"
            )
        result = rows[0]
        presentation = result.get("presentation_json")
        if not isinstance(presentation, Mapping):
            raise TeachingSessionConflict(
                "result-evaluation Artifact presentation is invalid"
            )
        attempt_id = str(result.get("active_attempt_id") or "")
        if not attempt_id or str(presentation.get("attempt_id") or "") != attempt_id:
            raise TeachingSessionConflict(
                "result-evaluation Attempt identity is invalid"
            )
        summary = sanitize_summary_text(
            str(presentation.get("summary_markdown") or result["instruction_markdown"]),
            max_length=320,
        )
        if not summary:
            raise TeachingSessionConflict(
                "result-evaluation summary is empty"
            )
        try:
            assert_public_artifact_safe(
                {
                    "source_handle": source_handle,
                    "result_summary": summary,
                }
            )
        except ValueError as exc:
            raise TeachingSessionConflict(
                "result-evaluation summary is protected"
            ) from exc
        return summary

    def _knowledge_check_evaluation(
        self,
        *,
        row: Mapping[str, object],
        safe_payload: Mapping[str, object],
    ) -> tuple[str, str | None] | None:
        if safe_payload.get("reason_code") != "knowledge_check_evaluation":
            return None
        source_handle = str(safe_payload.get("source_handle") or "")
        if not source_handle.startswith("artifact:"):
            raise TeachingSessionConflict(
                "knowledge-check evaluation source handle is invalid"
            )
        artifact_id = source_handle.removeprefix("artifact:")
        rows = self._conn.execute(
            """
            SELECT artifacts.presentation_json,receipts.id::text AS receipt_id,
                   receipts.outcome,receipts.assistance_kind,receipts.result_hash
            FROM tutor_continuation_intents AS intents
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id=intents.artifact_id
             AND artifacts.user_id=intents.user_id
             AND artifacts.conversation_id=intents.conversation_id
             AND artifacts.teaching_session_id=intents.teaching_session_id
             AND artifacts.learning_track_id=intents.learning_track_id
             AND artifacts.knowledge_key=intents.knowledge_key
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id=artifacts.id
             AND events.id::text=intents.source_id
             AND events.event_sequence=intents.source_version
            JOIN tutor_knowledge_check_response_receipts AS receipts
              ON receipts.artifact_id=artifacts.id
             AND receipts.user_id=artifacts.user_id
             AND receipts.conversation_id=artifacts.conversation_id
             AND receipts.teaching_session_id=artifacts.teaching_session_id
             AND receipts.learning_track_id=artifacts.learning_track_id
            WHERE intents.consumed_run_id=%s AND intents.user_id=%s
              AND intents.conversation_id=%s AND intents.teaching_session_id=%s
              AND intents.learning_track_id=%s AND intents.knowledge_key=%s
              AND intents.artifact_id=%s AND intents.state='consumed'
              AND intents.source_kind='explicit_artifact_action'
              AND intents.idempotency_key='knowledge-check-evaluation:' || intents.source_id
              AND artifacts.artifact_kind='knowledge_check'
              AND artifacts.state='completed' AND artifacts.presentation_kind='knowledge_check_v1'
              AND artifacts.presentation_json->>'response_receipt_id'=receipts.id::text
              AND events.event_kind='action'
              AND events.action_kind IN ('respond','request_direct_answer')
              AND events.safe_payload_json->'owner_result'->>'response_receipt_id'=receipts.id::text
              AND events.safe_payload_json->'owner_result'->>'result_hash'=receipts.result_hash
            LIMIT 2
            """,
            (
                row["run_id"],
                row["user_id"],
                row["conversation_id"],
                row["teaching_session_id"],
                row["track_id"],
                row["knowledge_key"],
                artifact_id,
            ),
        ).fetchall()
        if len(rows) != 1:
            raise TeachingSessionConflict(
                "knowledge-check evaluation continuation authority is missing or ambiguous"
            )
        result = rows[0]
        presentation = result.get("presentation_json")
        if not isinstance(presentation, Mapping):
            raise TeachingSessionConflict(
                "knowledge-check evaluation presentation is invalid"
            )
        summary = sanitize_summary_text(
            str(presentation.get("evaluation_markdown") or ""),
            max_length=320,
        )
        if not summary:
            raise TeachingSessionConflict(
                "knowledge-check evaluation summary is empty"
            )
        remediation_handle = presentation.get("remediation_handle")
        transfer_handle = presentation.get("transfer_handle")
        successors = tuple(
            value
            for value in (remediation_handle, transfer_handle)
            if isinstance(value, str) and value
        )
        if len(successors) > 1 or any(
            re.fullmatch(r"li:[0-9a-f]{64}", value) is None for value in successors
        ):
            raise TeachingSessionConflict(
                "knowledge-check evaluation successor identity is invalid"
            )
        successor_handle = successors[0] if successors else None
        try:
            assert_public_artifact_safe(
                {
                    "source_handle": source_handle,
                    "evaluation_summary": summary,
                    "successor_handle": successor_handle,
                    "outcome": str(result["outcome"]),
                    "assistance_kind": str(result["assistance_kind"]),
                }
            )
        except ValueError as exc:
            raise TeachingSessionConflict(
                "knowledge-check evaluation summary is protected"
            ) from exc
        return summary, successor_handle

    def _model_review_evaluation(
        self,
        *,
        row: Mapping[str, object],
        safe_payload: Mapping[str, object],
    ) -> tuple[str, str | None] | None:
        if safe_payload.get("reason_code") != "model_review_evaluation":
            return None
        source_handle = str(safe_payload.get("source_handle") or "")
        if not source_handle.startswith("artifact:"):
            raise TeachingSessionConflict("model review evaluation source handle is invalid")
        artifact_id = source_handle.removeprefix("artifact:")
        rows = self._conn.execute(
            """
            SELECT artifacts.presentation_json,receipts.id::text AS receipt_id,
                   receipts.outcome,receipts.assistance_kind,receipts.result_hash
            FROM tutor_continuation_intents AS intents
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id=intents.artifact_id AND artifacts.user_id=intents.user_id
             AND artifacts.conversation_id=intents.conversation_id
             AND artifacts.teaching_session_id=intents.teaching_session_id
             AND artifacts.learning_track_id=intents.learning_track_id
             AND artifacts.knowledge_key=intents.knowledge_key
            JOIN tutor_learning_artifact_events AS events
              ON events.artifact_id=artifacts.id AND events.id::text=intents.source_id
             AND events.event_sequence=intents.source_version
            JOIN tutor_model_review_artifact_receipts AS receipts
              ON receipts.artifact_id=artifacts.id AND receipts.user_id=artifacts.user_id
             AND receipts.conversation_id=artifacts.conversation_id
             AND receipts.teaching_session_id=artifacts.teaching_session_id
             AND receipts.learning_track_id=artifacts.learning_track_id
            WHERE intents.consumed_run_id=%s AND intents.user_id=%s
              AND intents.conversation_id=%s AND intents.teaching_session_id=%s
              AND intents.learning_track_id=%s AND intents.knowledge_key=%s
              AND intents.artifact_id=%s AND intents.state='consumed'
              AND intents.source_kind='explicit_artifact_action'
              AND intents.idempotency_key='model-review-evaluation:' || intents.source_id
              AND artifacts.artifact_kind='model_code_review' AND artifacts.state='completed'
              AND artifacts.presentation_kind='model_code_review_v2'
              AND artifacts.presentation_json->>'review_receipt_id'=receipts.id::text
              AND artifacts.presentation_json->>'result_hash'=receipts.result_hash
              AND events.event_kind='action' AND events.action_kind='complete_review'
              AND events.safe_payload_json->'owner_result'->>'review_receipt_id'=receipts.id::text
              AND events.safe_payload_json->'owner_result'->>'result_hash'=receipts.result_hash
            LIMIT 2
            """,
            (
                row["run_id"],row["user_id"],row["conversation_id"],
                row["teaching_session_id"],row["track_id"],row["knowledge_key"],artifact_id,
            ),
        ).fetchall()
        if len(rows) != 1:
            raise TeachingSessionConflict(
                "model review evaluation continuation authority is missing or ambiguous"
            )
        result = rows[0]
        presentation = result.get("presentation_json")
        if not isinstance(presentation, Mapping):
            raise TeachingSessionConflict("model review evaluation presentation is invalid")
        summary = sanitize_summary_text(
            str(presentation.get("evaluation_markdown") or ""),
            max_length=320,
        )
        if not summary:
            raise TeachingSessionConflict("model review evaluation summary is empty")
        successor = presentation.get("remediation_handle")
        if successor is not None and (
            not isinstance(successor, str)
            or re.fullmatch(r"li:[0-9a-f]{64}", successor) is None
        ):
            raise TeachingSessionConflict("model review remediation identity is invalid")
        if (str(result["outcome"]) == "failed") != (successor is not None):
            raise TeachingSessionConflict("model review remediation outcome is inconsistent")
        try:
            assert_public_artifact_safe(
                {
                    "source_handle": source_handle,
                    "evaluation_summary": summary,
                    "successor_handle": successor,
                    "outcome": str(result["outcome"]),
                    "assistance_kind": str(result["assistance_kind"]),
                }
            )
        except ValueError as exc:
            raise TeachingSessionConflict("model review evaluation summary is protected") from exc
        return summary, successor if isinstance(successor, str) else None


    def next_available_knowledge_key(
        self, *, user_id: str, track_id: str, current_knowledge_key: str,
        for_update: bool = False,
    ) -> str | None:
        lock = " FOR UPDATE OF progress" if for_update else ""
        row = self._conn.execute(
            """SELECT nodes.knowledge_key FROM tutor_track_active_plans AS active
               JOIN tutor_track_plan_nodes AS nodes ON nodes.revision_id=active.revision_id
                 AND nodes.track_id=active.track_id AND nodes.user_id=active.user_id
               JOIN tutor_track_plan_modules AS modules ON modules.id=nodes.module_id
               JOIN tutor_track_node_progress AS progress ON progress.track_id=nodes.track_id
                 AND progress.user_id=nodes.user_id AND progress.knowledge_key=nodes.knowledge_key
               WHERE active.track_id=%s AND active.user_id=%s AND progress.status='available'
                 AND nodes.knowledge_key<>%s
               ORDER BY modules.order_index,nodes.order_index,nodes.knowledge_key LIMIT 1""" + lock,
            (track_id, user_id, stable(current_knowledge_key, "current_knowledge_key")),
        ).fetchone()
        return str(row["knowledge_key"]) if row is not None else None

    def project_session(self, row: Mapping[str, object], *, include_checkpoint: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "session_id": str(row["id"]), "track_id": str(row["track_id"]), "track_version": _int(row["track_version"]),
            "conversation_id": str(row["conversation_id"]), "knowledge_key": str(row["knowledge_key"]),
            "status": str(row["status"]), "mode": str(row["mode"]), "session_version": _int(row["version"]),
            "progress_version": _int(row["progress_version"]), "assignment_id": str(row["lesson_assignment_id"]),
            "assignment_version": _int(row["assignment_version"]), "document_id": str(row["document_id"]),
            "checkpoint_id": _optional_str(row.get("current_checkpoint_id")),
            "paused_at": _iso(row.get("paused_at")), "completed_at": _iso(row.get("completed_at")),
            "last_activity_at": _iso(row.get("last_activity_at")),
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
            live = self._conn.execute(
                """SELECT progress.status AS progress_status, progress.version AS live_progress_version,
                          tracks.version AS live_track_version, assignments.assignment_version AS live_assignment_version,
                          EXISTS (SELECT 1 FROM tutor_runs AS runs JOIN tutor_run_teaching_scopes AS scopes ON scopes.run_id=runs.id
                            WHERE scopes.teaching_session_id=%s AND runs.user_id=%s AND runs.terminal_outcome IS NULL
                              AND runs.cancelled_at IS NULL AND runs.superseded_by_run_id IS NULL) AS runtime_active,
                          EXISTS (SELECT 1 FROM tutor_interaction_requests AS requests
                            WHERE requests.user_id=%s AND requests.conversation_id=%s AND requests.state='pending') AS blocking_request
                   FROM tutor_track_node_progress AS progress
                   JOIN tutor_learning_tracks AS tracks ON tracks.id=progress.track_id AND tracks.user_id=progress.user_id
                   JOIN tutor_lesson_assignments AS assignments ON assignments.track_id=progress.track_id
                     AND assignments.user_id=progress.user_id AND assignments.knowledge_key=progress.knowledge_key
                     AND assignments.status='active'
                   WHERE progress.track_id=%s AND progress.user_id=%s AND progress.knowledge_key=%s""",
                (row["id"], row["user_id"], row["user_id"], row["conversation_id"],
                 row["track_id"], row["user_id"], row["knowledge_key"]),
            ).fetchone()
            next_knowledge_key = self.next_available_knowledge_key(
                user_id=str(row["user_id"]), track_id=str(row["track_id"]),
                current_knowledge_key=str(row["knowledge_key"]),
            )
            shelf = build_teaching_action_shelf(
                session_id=str(row["id"]), session_version=_int(row["version"]),
                checkpoint_id=str(checkpoint["id"]), mode=TeachingSessionMode(str(row["mode"])),
                state=state, track_version=_int(live["live_track_version"] if live else row["track_version"]),
                progress_version=_int(live["live_progress_version"] if live else row["progress_version"]),
                assignment_version=_int(live["live_assignment_version"] if live else row["assignment_version"]),
                runtime_active=bool(live and live.get("runtime_active")),
                blocking_request=bool(live and live.get("blocking_request")),
                progress_status=str(live.get("progress_status") if live else ""),
                next_knowledge_key=next_knowledge_key,
            )
            shelf_payload: dict[str, object] = shelf.model_dump(mode="json")
            result["action_shelf"] = shelf_payload
            primary = shelf_payload.get("primary_action")
            secondary = shelf_payload.get("secondary_actions")
            overflow = shelf_payload.get("overflow_actions")
            candidates = (
                ([primary] if isinstance(primary, dict) else [])
                + (list(secondary) if isinstance(secondary, list) else [])
                + (list(overflow) if isinstance(overflow, list) else [])
            )
            result["allowed_actions"] = [str(item["key"]) for item in candidates if isinstance(item, dict)]
        else:
            result["action_shelf"] = None
            result["allowed_actions"] = []
        return result

    def conversation_projection(self, *, user_id: str, conversation_id: str) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT * FROM tutor_teaching_sessions WHERE user_id=%s AND conversation_id=%s ORDER BY last_activity_at DESC,id DESC LIMIT 50",
            (user_id, conversation_id),
        ).fetchall()
        turn_rows = self._conn.execute(
            """SELECT scopes.teaching_session_id,scopes.run_id
               FROM tutor_run_teaching_scopes AS scopes
               JOIN tutor_teaching_sessions AS sessions ON sessions.id=scopes.teaching_session_id
               WHERE sessions.user_id=%s AND sessions.conversation_id=%s
               ORDER BY scopes.created_at,scopes.run_id""",
            (user_id, conversation_id),
        ).fetchall()
        turn_ids: dict[str, list[str]] = {}
        for turn in turn_rows:
            turn_ids.setdefault(str(turn["teaching_session_id"]), []).append(str(turn["run_id"]))
        result: list[dict[str, object]] = []
        for row in rows:
            projected = self.project_session(row, include_checkpoint=False)
            projected["turn_ids"] = turn_ids.get(str(row["id"]), [])
            result.append(projected)
        return result

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
        from app.agents.harness.context_budget import build_tutor_context_budget_policy

        policy = TutorPolicySnapshot(
            deadline=now + timedelta(minutes=5), max_iterations=4, max_model_calls=3,
            max_capability_calls=2, max_effects=2, context_token_budget=config.tutor_context_token_budget,
            lease_duration_seconds=30, context_budget_policy=build_tutor_context_budget_policy(config),
        )
        run = repository.create_run(
            user_id=authority.user_id, conversation_id=authority.conversation_id,
            catalog_digest=catalog.digest, policy=policy, origin="interactive",
            policy_version="tutor_teaching_stimulus_policy_v2",
            interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
        )
        self._ensure_run_learning_scope(run_id=run.run_id, authority=authority)
        projection = self._insert_stimulus_scope(run_id=run.run_id, session=session, authority=authority, stimulus=stimulus)
        run_row = repository._lock_run(user_id=authority.user_id, run_id=run.run_id)
        repository._ensure_public_process_locked(run=run_row, occurred_at=now)
        dispatch = repository._ensure_interactive_dispatch_job_locked(run=run_row, available_at=now)
        return {
            **projection, "run_id": run.run_id, "origin": run.origin, "status": run.status.value,
            "dispatch_job_id": dispatch.job_id if dispatch is not None else None,
        }

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
        self._repository = TeachingSessionRepository(conn, settings=self._settings)

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
                client_action_id=idempotency_key,
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
        mode: TeachingSessionMode, client_action_id: str,
    ) -> dict[str, object]:
        try:
            authority = self._repository.resolve_authority(
                user_id=user_id, track_id=track_id, knowledge_key=knowledge_key,
                conversation_id=conversation_id, for_update=True,
            )
            self._assert_expected(authority, expected_track_version, expected_progress_version, expected_assignment_version)
            row, created = self._repository.open_or_resume(authority=authority, mode=mode)
            pending_run = None
            if created and mode is TeachingSessionMode.GUIDED:
                pending_run = self._repository.admit_control_run(
                    authority=authority, session=row,
                    stimulus=TeachingControlStimulus(
                        control_key=TeachingControlKey.OPEN_SESSION, client_action_id=client_action_id,
                        expected_session_version=_int(row["version"]),
                        expected_track_version=authority.track_version,
                        expected_progress_version=authority.progress_version,
                        expected_assignment_version=authority.assignment_version,
                    ),
                    settings=self._settings,
                )
        except TeachingSessionNotFound as exc:
            raise self._not_found(track_id, knowledge_key) from exc
        except TeachingSessionConflict as exc:
            raise self._conflict(str(exc)) from exc
        return {
            "teaching_session": self._repository.project_session(row),
            "created": created, "pending_run": pending_run,
        }

    def _action(
        self, *, user_id: str, track_id: str, session_id: str, control: TeachingControlStimulus,
        target_mode: TeachingSessionMode | None, admit_run: bool,
    ) -> dict[str, object]:
        del admit_run
        control_key = control.control_key
        if control_key is TeachingControlKey.ENTER_NEXT_KNOWLEDGE:
            return self._enter_next_knowledge(
                user_id=user_id, track_id=track_id, session_id=session_id, control=control,
            )
        try:
            session = self._repository.read_by_id(user_id=user_id, track_id=track_id, session_id=session_id, for_update=True)
            session_mode = TeachingSessionMode(str(session["mode"]))
            if session_mode is TeachingSessionMode.FREE_READING and control_key in {
                TeachingControlKey.CONTINUE,
                TeachingControlKey.RETURN_FOCUS,
                TeachingControlKey.CHANGE_EXAMPLE,
            }:
                raise TeachingSessionInvalid("free reading accepts learner input or explicit guided escalation")
            if control_key is TeachingControlKey.ESCALATE_GUIDED and session_mode is not TeachingSessionMode.FREE_READING:
                raise TeachingSessionInvalid("guided escalation requires free-reading mode")
            if (
                control_key is TeachingControlKey.SWITCH_MODE
                and target_mode is TeachingSessionMode.GUIDED
            ):
                raise TeachingSessionInvalid("switching to guided mode requires explicit guided escalation")
            auto_admit = control_key in {
                TeachingControlKey.CONTINUE,
                TeachingControlKey.RETURN_FOCUS,
                TeachingControlKey.CHANGE_EXAMPLE,
                TeachingControlKey.ESCALATE_GUIDED,
            } or (control_key is TeachingControlKey.RESUME and session_mode is TeachingSessionMode.GUIDED)
            authority = self._repository.resolve_authority(
                user_id=user_id, track_id=track_id, knowledge_key=str(session["knowledge_key"]),
                conversation_id=str(session["conversation_id"]), for_update=True,
            )
            updated = self._repository.mutate(
                session=session, authority=authority, expected_session_version=control.expected_session_version,
                control=control, target_mode=target_mode,
            )
            pending_run = None
            if auto_admit:
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

    def _enter_next_knowledge(
        self, *, user_id: str, track_id: str, session_id: str, control: TeachingControlStimulus,
    ) -> dict[str, object]:
        target_key = str(control.safe_payload.get("target_knowledge_key") or "")
        try:
            target_key = stable(target_key, "target_knowledge_key")
        except ValueError as exc:
            raise TeachingSessionServiceError(
                "TEACHING_NEXT_KNOWLEDGE_INVALID", "下一知识点目标不合法。", status_code=400, recoverable=False,
            ) from exc
        source = self._repository.read_by_id(
            user_id=user_id, track_id=track_id, session_id=session_id, for_update=True,
        )
        if _int(source["version"]) != control.expected_session_version:
            raise self._conflict("teaching session version is stale")
        if str(source["status"]) != "completed":
            raise self._conflict("teaching session is not in completion pause")
        live = self._conn.execute(
            """SELECT tracks.version AS track_version, progress.status AS progress_status,
                      progress.version AS progress_version, assignments.assignment_version
               FROM tutor_learning_tracks AS tracks
               JOIN tutor_track_node_progress AS progress ON progress.track_id=tracks.id
                 AND progress.user_id=tracks.user_id AND progress.knowledge_key=%s
               JOIN tutor_lesson_assignments AS assignments ON assignments.track_id=tracks.id
                 AND assignments.user_id=tracks.user_id AND assignments.knowledge_key=progress.knowledge_key
                 AND assignments.status='active'
               WHERE tracks.id=%s AND tracks.user_id=%s FOR UPDATE OF tracks,progress,assignments""",
            (source["knowledge_key"], track_id, user_id),
        ).fetchone()
        if live is None or str(live["progress_status"]) != "completed":
            raise self._conflict("current knowledge point is not completed")
        if (
            _int(live["track_version"]) != control.expected_track_version
            or _int(live["progress_version"]) != control.expected_progress_version
            or _int(live["assignment_version"]) != control.expected_assignment_version
        ):
            raise self._conflict("next-knowledge authority version is stale")
        latest_candidate = self._repository.next_available_knowledge_key(
            user_id=user_id, track_id=track_id,
            current_knowledge_key=str(source["knowledge_key"]), for_update=True,
        )
        if latest_candidate is None or latest_candidate != target_key:
            raise self._conflict("next knowledge candidate changed")
        target = self._repository.resolve_authority(
            user_id=user_id, track_id=track_id, knowledge_key=target_key,
            conversation_id=str(source["conversation_id"]), for_update=True,
        )
        if target.progress_status != "available":
            raise self._conflict("target knowledge point is no longer available")
        updated_track = self._conn.execute(
            """UPDATE tutor_learning_tracks SET current_knowledge_key=%s,version=version+1
               WHERE id=%s AND user_id=%s AND version=%s RETURNING version""",
            (target_key, track_id, user_id, control.expected_track_version),
        ).fetchone()
        if updated_track is None:
            raise self._conflict("LearningTrack version changed")
        target = replace(target, track_version=_int(updated_track["version"]))
        target_session, created = self._repository.open_or_resume(
            authority=target, mode=TeachingSessionMode.GUIDED,
        )
        target_control = TeachingControlStimulus(
            control_key=TeachingControlKey.OPEN_SESSION, client_action_id=control.client_action_id,
            expected_session_version=_int(target_session["version"]),
            expected_track_version=target.track_version, expected_progress_version=target.progress_version,
            expected_assignment_version=target.assignment_version,
            safe_payload={"target_knowledge_key": target_key},
        )
        pending = self._repository.admit_control_run(
            authority=target, session=target_session, stimulus=target_control, settings=self._settings,
        )
        return {
            "teaching_session": self._repository.project_session(source),
            "next_teaching_session": self._repository.project_session(target_session),
            "transitioned": True, "created": created, "pending_run": pending,
        }

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


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _optional_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
