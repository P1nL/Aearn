"""Build a persisted AuthoritativeContextSnapshot for ReviewSession."""
from __future__ import annotations

from collections.abc import Mapping

from psycopg import Connection

from app.agents.harness.contracts import TutorContextSource
from app.services.learning.planning_facts import AuthoritativeContextSnapshot
from app.services.learning.reviews.contracts import REVIEW_CONTEXT_SCHEMA_VERSION
from app.services.learning.reviews.persistence import as_float, as_int, content_hash, iso, string_list


def build_review_context_snapshot(
    conn: Connection[dict[str, object]],
    *,
    session_id: str,
    user_id: str,
    track_id: str,
    knowledge_key: str,
    scope: Mapping[str, object],
    schedule_row: Mapping[str, object],
) -> AuthoritativeContextSnapshot:
    user = conn.execute(
        """SELECT learning_style, teaching_preference, preferred_time_slots
        FROM users WHERE id = %s AND deleted_at IS NULL""",
        (user_id,),
    ).fetchone()
    if user is None:
        raise ValueError("learner was not found")
    planning = conn.execute(
        """
        SELECT sessions.id AS planning_session_id, sessions.conversation_id,
               drafts.source_run_id, drafts.source_input_revision
        FROM tutor_learning_plan_sessions AS sessions
        LEFT JOIN tutor_learning_plan_drafts AS drafts ON drafts.id = sessions.current_draft_id
        WHERE sessions.user_id = %s AND sessions.confirmed_track_id = %s
          AND sessions.status = 'confirmed'
        ORDER BY sessions.confirmed_at DESC, sessions.id DESC LIMIT 1
        """,
        (user_id, track_id),
    ).fetchone()
    planning_sources: list[TutorContextSource] = []
    planning_session_id: str | None = None
    run_id = session_id
    conversation_id = session_id
    input_revision = 0
    fact_revision = 0
    question_states: tuple[tuple[str, str], ...] = ()
    if planning is not None:
        planning_session_id = str(planning["planning_session_id"])
        conversation_id = str(planning["conversation_id"])
        if planning.get("source_run_id") is not None:
            run_id = str(planning["source_run_id"])
        input_revision = as_int(planning.get("source_input_revision"))
        rows = conn.execute(
            """
            SELECT DISTINCT ON (field_key) id, field_key, value_json, revision, state
            FROM tutor_planning_intake_facts
            WHERE session_id = %s AND user_id = %s AND state = 'confirmed'
            ORDER BY field_key, revision DESC, created_at DESC, id DESC
            """,
            (planning_session_id, user_id),
        ).fetchall()
        planning_sources = [
            TutorContextSource(
                source_id=f"planning-fact:{row['field_key']}:{row['id']}",
                semantic_class="confirmed_fact_source",
                content={
                    "kind": "confirmed_planning_fact",
                    "field_key": str(row["field_key"]),
                    "value": row.get("value_json"),
                    "fact_revision": as_int(row["revision"]),
                },
            )
            for row in rows
        ]
        fact_revision += sum(as_int(row["revision"]) for row in rows)
        question_rows = conn.execute(
            """
            SELECT DISTINCT ON (field_key) field_key, status
            FROM tutor_planning_question_events
            WHERE session_id = %s AND user_id = %s AND status <> 'reasked_blocked'
            ORDER BY field_key, created_at DESC, id DESC
            """,
            (planning_session_id, user_id),
        ).fetchall()
        question_states = tuple(sorted((str(row["field_key"]), str(row["status"])) for row in question_rows))
    sources = tuple(
        [
            TutorContextSource(
                source_id=f"review-track:{track_id}",
                semantic_class="confirmed_fact_source",
                content={
                    "kind": "review_track_fact",
                    "language_id": str(scope["language_id"]),
                    "goal_text": str(scope["goal_text"]),
                    "target_level": str(scope["target_level"]),
                    "active_plan_revision_id": str(scope["plan_revision_id"]),
                    "current_knowledge_key": str(scope.get("current_knowledge_key") or ""),
                },
            ),
            TutorContextSource(
                source_id=f"review-preferences:{user_id}",
                semantic_class="confirmed_fact_source",
                content={
                    "kind": "review_preference_fact",
                    "learning_style": _optional(user.get("learning_style")),
                    "teaching_preference": _optional(user.get("teaching_preference")),
                    "preferred_time_slots": string_list(user.get("preferred_time_slots"))[:8],
                },
            ),
            TutorContextSource(
                source_id=f"review-knowledge:{track_id}:{knowledge_key}",
                semantic_class="confirmed_fact_source",
                content={
                    "kind": "review_knowledge_fact",
                    "knowledge_key": knowledge_key,
                    "mastery_level": str(scope.get("mastery_level") or "unseen"),
                    "mastery_confidence": as_float(scope.get("confidence")),
                    "schedule_version": as_int(schedule_row["version"]),
                    "due_at": iso(schedule_row.get("due_at")),
                },
            ),
            *planning_sources,
        ]
    )
    payload = [
        {"source_id": item.source_id, "semantic_class": item.semantic_class, "content": item.content}
        for item in sources
    ]
    fingerprint = content_hash(payload)
    fact_revision += as_int(scope["track_version"]) + as_int(scope.get("mastery_version")) + as_int(schedule_row["version"])
    snapshot_hash = content_hash(
        {
            "schema_version": REVIEW_CONTEXT_SCHEMA_VERSION,
            "session_id": session_id,
            "fact_revision": fact_revision,
            "facts_fingerprint": fingerprint,
            "required_facts": payload,
            "question_states": question_states,
        }
    )
    return AuthoritativeContextSnapshot(
        schema_version=REVIEW_CONTEXT_SCHEMA_VERSION,
        run_id=run_id,
        conversation_id=conversation_id,
        input_revision=input_revision,
        planning_session_id=planning_session_id,
        fact_revision=fact_revision,
        facts_fingerprint=fingerprint,
        required_facts=sources,
        question_states=question_states,
        snapshot_hash=snapshot_hash,
    )


def snapshot_payload(snapshot: AuthoritativeContextSnapshot) -> dict[str, object]:
    return {
        "schema_version": snapshot.schema_version,
        "run_id": snapshot.run_id,
        "conversation_id": snapshot.conversation_id,
        "input_revision": snapshot.input_revision,
        "planning_session_id": snapshot.planning_session_id,
        "fact_revision": snapshot.fact_revision,
        "facts_fingerprint": snapshot.facts_fingerprint,
        "required_facts": [
            {"source_id": item.source_id, "semantic_class": item.semantic_class, "content": item.content}
            for item in snapshot.required_facts
        ],
        "question_states": [list(item) for item in snapshot.question_states],
        "snapshot_hash": snapshot.snapshot_hash,
        "action_receipts": [],
        "confirmed_question_reasked_count": snapshot.confirmed_question_reasked_count,
    }


def _optional(value: object) -> str | None:
    return str(value) if value is not None else None
