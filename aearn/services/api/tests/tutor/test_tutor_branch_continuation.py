from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import Any, cast
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import dict_row

from app.agents.harness.contracts import TutorPolicySnapshot
from app.core.config import Settings, get_settings
from app.db.bootstrap import bootstrap_database
from app.services.learning.artifacts.contracts import (
    TutorArtifactCreate,
    TutorArtifactState,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.owner_adapters import ArtifactMutation
from app.services.learning.artifacts.repository import (
    PostgresLearningArtifactRepository,
)
from app.services.learning.contracts import (
    LearningScope,
    LearningScopeKind,
    LearningTaskKind,
)
from app.services.learning.teaching_contracts import TeachingSessionMode
from app.services.learning.teaching_sessions import TeachingSessionRepository
from app.services.learning.track_repository import PostgresLearningTrackRepository
from app.services.repositories.local_user_data_repository import (
    export_user_data,
    reset_user_data,
)
from app.services.tutor.branch_contracts import (
    BranchAssistanceKind,
    BranchAssistanceReceiptKind,
    BranchControlKind,
    BranchResponseDisposition,
)
from app.services.tutor.branching import (
    PostgresTutorBranchRepository,
    TutorBranchConflict,
    TutorBranchError,
    TutorBranchNotFound,
    TutorClarificationBranchService,
)
from app.services.tutor.continuation import (
    ContinuationIntentNotFound,
    ContinuationIntentStale,
    ContinuationIntentState,
    ContinuationSourceKind,
    PostgresTutorContinuationIntentRepository,
    TutorContinuationDispatcher,
    TutorContinuationIntentProducer,
)
from app.services.tutor.conversation_contracts import TutorConversationEventKind
from app.services.tutor.cutover import HarnessCutoverService
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_api import TutorPublicService
from app.services.tutor.queue_control import PostgresTutorQueueController
from tests.support.teaching_session_support import (
    connection,
    create_teaching_scope,
    database_available,
)

pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)


@dataclass(frozen=True, slots=True)
class _ArtifactScope:
    user_id: str
    conversation_id: str
    track_id: str
    knowledge_key: str
    assignment_id: str
    session_id: str
    session_version: int
    checkpoint_id: str
    artifact_id: str
    artifact_version: int
    hint_receipt_id: str | None = None
    shared_exercise_version_id: str | None = None


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        raise AssertionError("expected integer")
    if isinstance(value, int):
        return value
    return int(str(value))


def _settings() -> Settings:
    return Settings(
        llm_type="disabled",
        tutor_thread_turn_v2_enabled=True,
        tutor_learning_artifacts_enabled=True,
        tutor_artifact_teaching_mode_enabled=True,
    )


def _policy(now: datetime) -> TutorPolicySnapshot:
    return TutorPolicySnapshot(
        deadline=now + timedelta(minutes=5),
        max_iterations=4,
        max_model_calls=3,
        max_capability_calls=2,
        max_effects=2,
        context_token_budget=256,
        lease_duration_seconds=30,
    )


def _artifact_request(
    *,
    scope: dict[str, str | int],
    session: dict[str, object],
    owner_kind: str,
    owner_id: str,
    owner_version: int,
) -> TutorArtifactCreate:
    session_version = _as_int(session["session_version"])
    checkpoint_id = str(session["checkpoint_id"])
    return TutorArtifactCreate.model_validate(
        {
            "user_id": str(scope["user_id"]),
            "conversation_id": str(scope["conversation_id"]),
            "turn_id": None,
            "learning_track_id": str(scope["track_id"]),
            "knowledge_key": str(scope["knowledge_key"]),
            "teaching_session_id": str(session["session_id"]),
            "checkpoint_id": checkpoint_id,
            "track_version": int(scope["track_version"]),
            "progress_version": int(scope["progress_version"]),
            "assignment_version": int(scope["assignment_version"]),
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "owner_version": owner_version,
            "owner_context_version": session_version
            if owner_kind == "teaching_practice"
            else None,
            "artifact_kind": "knowledge_check",
            "purpose": "knowledge_check",
            "state": "active",
            "blocking": True,
            "title": "Branch continuation check",
            "instruction_markdown": "Answer inside the current blocking Artifact.",
            "difficulty": "D1",
            "presentation": {
                "type": "knowledge_check_v1",
                "response_kind": "single_select",
                "prompt_markdown": "After value = 2, what is value?",
                "options": [
                    {"value": "2", "label": "2"},
                    {"value": "3", "label": "3"},
                ],
                "minimum_selections": 1,
                "maximum_selections": 1,
                "maximum_text_length": 2_000,
            },
            "allowed_actions": ["request_hint", "respond"],
            "source_references": [
                {
                    "kind": "teaching_checkpoint",
                    "reference_id": checkpoint_id,
                    "reference_version": session_version,
                    "content_hash": None,
                    "label": "Current teaching checkpoint",
                }
            ],
            "active_attempt": None,
        }
    )


def _seed_hint_owner(
    conn: Connection[dict[str, object]],
    *,
    scope: dict[str, str | int],
) -> tuple[str, str, str]:
    suffix = uuid4().hex
    gate_key = f"branch.hint.{suffix[:12]}"
    slot = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_slots (
          document_id, user_id, track_id, knowledge_key, block_id, gate_key,
          gate_kind, assessment_contract_version, required_capabilities_json,
          learner_prompt_hash, learner_prompt
        ) VALUES (
          %s, %s, %s, %s, %s, %s,
          'knowledge_check', 'branch_hint_v1', '["python.variables"]'::jsonb,
          %s, 'Choose the value produced by the assignment.'
        ) RETURNING id
        """,
        (
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            gate_key,
            gate_key,
            _digest(f"prompt:{suffix}"),
        ),
    ).fetchone()
    assert slot is not None
    exercise = conn.execute(
        """
        INSERT INTO tutor_exercise_versions (
          language_id, exercise_key, exercise_type, version, source_kind, title,
          learner_prompt_json, starter_artifact_json, required_capabilities_json,
          runtime_profile_key, execution_required, public_feedback_policy_version,
          validation_status, content_hash, published_at
        ) VALUES (
          'python', %s, 'static_code_reasoning', 'v1', 'curated_fixture',
          'Branch hint fixture', '{"text":"Choose 2"}'::jsonb, '{"content":""}'::jsonb,
          '["python.variables"]'::jsonb, NULL, false, 'branch_hint_feedback_v1',
          'ready', %s, %s
        ) RETURNING id
        """,
        (
            f"python.variables.branch_hint.{suffix}",
            _digest(f"exercise:{suffix}"),
            datetime.now(UTC),
        ),
    ).fetchone()
    assert exercise is not None
    binding = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_bindings (
          slot_id, document_id, user_id, track_id, knowledge_key, gate_key,
          exercise_version_id, requirement_kind, pass_policy_version, pass_threshold,
          execution_requirement, slot_contract_hash, binding_contract_hash, published_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s,
          %s, 'required', 'branch_hint_pass_v1', 1,
          'forbidden', %s, %s, %s
        ) RETURNING id
        """,
        (
            slot["id"],
            scope["document_id"],
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            gate_key,
            exercise["id"],
            _digest(f"slot:{suffix}"),
            _digest(f"binding:{suffix}"),
            datetime.now(UTC),
        ),
    ).fetchone()
    assert binding is not None
    state = conn.execute(
        """
        INSERT INTO tutor_lesson_gate_states (
          user_id, track_id, knowledge_key, lesson_assignment_id,
          document_id, gate_binding_id, state
        ) VALUES (%s, %s, %s, %s, %s, %s, 'available')
        RETURNING id, version
        """,
        (
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            scope["assignment_id"],
            scope["document_id"],
            binding["id"],
        ),
    ).fetchone()
    assert state is not None and _as_int(state["version"]) == 1
    hint = conn.execute(
        """
        INSERT INTO tutor_exercise_hint_receipts (
          user_id, track_id, knowledge_key, lesson_assignment_id,
          gate_binding_id, hint_level, hint_policy_version, safe_hint_json,
          idempotency_key, request_hash
        ) VALUES (
          %s, %s, %s, %s,
          %s, 1, 'branch_hint_policy_v1',
          '{"summary":"Trace the latest assignment."}'::jsonb,
          %s, %s
        ) RETURNING id
        """,
        (
            scope["user_id"],
            scope["track_id"],
            scope["knowledge_key"],
            scope["assignment_id"],
            binding["id"],
            f"branch-hint:{suffix}",
            _digest(f"hint:{suffix}"),
        ),
    ).fetchone()
    assert hint is not None
    return str(state["id"]), str(hint["id"]), str(exercise["id"])


def _prepare_artifact(
    conn: Connection[dict[str, object]],
    *,
    mode: TeachingSessionMode = TeachingSessionMode.GUIDED,
    hint_owner: bool = False,
) -> _ArtifactScope:
    scope = create_teaching_scope(conn)
    teaching = TeachingSessionRepository(conn)
    with conn.transaction():
        authority = teaching.resolve_authority(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key=str(scope["knowledge_key"]),
            conversation_id=str(scope["conversation_id"]),
            for_update=True,
        )
        session_row, created = teaching.open_or_resume(authority=authority, mode=mode)
    assert created is True
    session = teaching.project_session(session_row)
    owner_kind = "teaching_practice"
    owner_id = str(session["checkpoint_id"])
    owner_version = _as_int(session["session_version"])
    hint_receipt_id: str | None = None
    shared_exercise_version_id: str | None = None
    if hint_owner:
        owner_kind = "lesson_gate"
        owner_id, hint_receipt_id, shared_exercise_version_id = _seed_hint_owner(
            conn, scope=scope
        )
        owner_version = 1
    artifacts = PostgresLearningArtifactRepository(
        conn,
        conversation_events=PostgresTutorArtifactConversationEventSink(conn),
    )
    created_artifact = artifacts.create_artifact(
        _artifact_request(
            scope=scope,
            session=session,
            owner_kind=owner_kind,
            owner_id=owner_id,
            owner_version=owner_version,
        ),
        creation_key=f"branch-artifact:{uuid4().hex}",
        occurred_at=datetime.now(UTC),
    )
    conn.commit()
    return _ArtifactScope(
        user_id=str(scope["user_id"]),
        conversation_id=str(scope["conversation_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key=str(scope["knowledge_key"]),
        assignment_id=str(scope["assignment_id"]),
        session_id=str(session["session_id"]),
        session_version=_as_int(session["session_version"]),
        checkpoint_id=str(session["checkpoint_id"]),
        artifact_id=created_artifact.artifact.id,
        artifact_version=created_artifact.artifact.version,
        hint_receipt_id=hint_receipt_id,
        shared_exercise_version_id=shared_exercise_version_id,
    )


def _create_branch_turn(
    conn: Connection[dict[str, object]],
    fixture: _ArtifactScope,
    *,
    use_service: bool,
    content: str = "Why does this assignment keep the value 2?",
    control_kind: BranchControlKind | None = None,
) -> tuple[str, str, int, str]:
    now = datetime.now(UTC)
    catalog_digest = _digest(f"catalog:{uuid4().hex}")
    conn.execute(
        """
        INSERT INTO tutor_catalog_snapshots (digest, manifest_json, redaction_version)
        VALUES (%s, '{}'::jsonb, 'branch-test-v1')
        """,
        (catalog_digest,),
    )
    accepted = PostgresTutorQueueController(conn).accept_or_queue(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        catalog_digest=catalog_digest,
        policy=_policy(now),
        idempotency_key=f"branch-input:{uuid4().hex}",
        content=content,
        metadata={},
        received_at=now,
    )
    assert accepted.turn is not None and accepted.queued_item is None
    turn = accepted.turn
    PostgresLearningTrackRepository(conn).snapshot_run_scope(
        user_id=fixture.user_id,
        run_id=turn.run.run_id,
        explicit_scope=LearningScope(
            scope_kind=LearningScopeKind.LEARNING_TRACK,
            learning_track_id=fixture.track_id,
            task_kind=LearningTaskKind.LESSON_TEACHING,
            knowledge_key=fixture.knowledge_key,
        ),
    )
    teaching_scope = TeachingSessionRepository(conn).bind_learner_message_run(
        user_id=fixture.user_id,
        run_id=turn.run.run_id,
        conversation_id=fixture.conversation_id,
        track_id=fixture.track_id,
        knowledge_key=fixture.knowledge_key,
        message_id=turn.acceptance.message_id,
        input_revision=turn.acceptance.input_revision,
    )
    assert teaching_scope is not None
    if use_service:
        binding = TutorClarificationBranchService(conn).bind_learner_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            run_id=turn.run.run_id,
            message_id=turn.acceptance.message_id,
            input_revision=turn.acceptance.input_revision,
            control_kind=control_kind,
            occurred_at=now,
        )
    else:
        binding = PostgresTutorBranchRepository(conn).bind_turn(
            user_id=fixture.user_id,
            conversation_id=fixture.conversation_id,
            run_id=turn.run.run_id,
            message_id=turn.acceptance.message_id,
            input_revision=turn.acceptance.input_revision,
            control_kind=control_kind,
            occurred_at=now,
        )
    assert binding is not None
    conn.commit()
    return (
        turn.run.run_id,
        turn.acceptance.message_id,
        turn.acceptance.input_revision,
        binding.branch.branch_id,
    )


def _insert_direct_answer_receipt(
    conn: Connection[dict[str, object]],
    *,
    fixture: _ArtifactScope,
    run_id: str,
) -> str:
    scope = conn.execute(
        """
        SELECT run_id, user_id, conversation_id, teaching_session_id,
               checkpoint_id, stimulus_id, track_id, knowledge_key
        FROM tutor_run_teaching_scopes
        WHERE run_id = %s AND user_id = %s AND conversation_id = %s
        """,
        (run_id, fixture.user_id, fixture.conversation_id),
    ).fetchone()
    assert scope is not None
    assert str(scope["teaching_session_id"]) == fixture.session_id
    assert str(scope["track_id"]) == fixture.track_id
    assert str(scope["knowledge_key"]) == fixture.knowledge_key
    focus_id = f"knowledge:{fixture.knowledge_key}"
    receipt = conn.execute(
        """
        INSERT INTO tutor_teaching_action_receipts (
          run_id, user_id, conversation_id, teaching_session_id,
          checkpoint_id, stimulus_id, action, objective_id, focus_id,
          focus_resolution, pause_kind, source_handles_json,
          public_message_hash, context_source_ids_json,
          context_source_hashes_json, teaching_moves_json,
          learner_response_mode, schema_version, policy_version
        ) VALUES (
          %s, %s, %s, %s,
          %s, %s, 'answer_question', %s, %s,
          'stay', 'soft_pause', %s::jsonb,
          %s, '[]'::jsonb,
          '[]'::jsonb, %s::jsonb,
          'none', 'teaching_action_receipt_v2', 'lesson_teaching_policy_v2'
        ) RETURNING id
        """,
        (
            run_id,
            fixture.user_id,
            fixture.conversation_id,
            fixture.session_id,
            scope["checkpoint_id"],
            scope["stimulus_id"],
            focus_id,
            focus_id,
            json.dumps([focus_id]),
            _digest(f"direct-answer:{run_id}"),
            json.dumps(["targeted_explanation", "learner_feedback"]),
        ),
    ).fetchone()
    assert receipt is not None
    conn.commit()
    return str(receipt["id"])


def _persist_completed_response(
    conn: Connection[dict[str, object]],
    *,
    fixture: _ArtifactScope,
    run_id: str,
    content: str = "The assignment evaluates the right-hand side and binds 2.",
) -> str:
    now = datetime.now(UTC)
    repository = PostgresTutorRepository(conn)
    with conn.transaction():
        run = repository._lock_run(user_id=fixture.user_id, run_id=run_id)
        message = conn.execute(
            """
            INSERT INTO tutor_messages (conversation_id, role, content, created_at)
            VALUES (%s, 'tutor', %s, %s) RETURNING id
            """,
            (fixture.conversation_id, content, now),
        ).fetchone()
        assert message is not None
        message_id = str(message["id"])
        repository._append_item_reference_event_locked(
            run=run,
            event_key=f"item:message:{message_id}:added",
            kind=TutorConversationEventKind.ITEM_ADDED,
            item_id=message_id,
            item_kind="message",
            occurred_at=now,
        )
        updated = conn.execute(
            """
            UPDATE tutor_runs
            SET status = 'completed', terminal_outcome = 'completed',
                terminal_diagnostic_code = 'completed', terminal_at = %s,
                active_lease_owner_id = NULL, active_lease_expires_at = NULL
            WHERE id = %s AND user_id = %s AND terminal_outcome IS NULL
            RETURNING id
            """,
            (now, run_id, fixture.user_id),
        ).fetchone()
        assert updated is not None
        repository._freeze_public_process_locked(
            run=run,
            display_state="completed",
            step_key="learning_reply_generated",
            occurred_at=now,
            tutor_message_id=message_id,
        )
    return message_id


def _resolve_branch(
    conn: Connection[dict[str, object]],
    *,
    fixture: _ArtifactScope,
    run_id: str,
) -> str:
    response_message_id = _persist_completed_response(
        conn, fixture=fixture, run_id=run_id
    )
    resolved = PostgresTutorBranchRepository(conn).complete_turn(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        run_id=run_id,
        response_message_id=response_message_id,
        occurred_at=datetime.now(UTC),
    )
    assert resolved is not None and resolved.state == "resolved"
    conn.commit()
    return response_message_id


def _cleanup_user(
    user_id: str,
    *,
    shared_exercise_version_id: str | None = None,
) -> None:
    # Practice versions are shared immutable authority and intentionally survive
    # local-user cleanup; only the user-owned gate/receipt/Artifact rows are purged.
    del shared_exercise_version_id
    with connection() as conn:
        reset_user_data(conn, user_id)


def test_branch_schema_bootstrap_twice_and_cross_scope_rejection() -> None:
    bootstrap_database()
    bootstrap_database()
    fixture: _ArtifactScope | None = None
    foreign_user_id: str | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            tables = {
                str(row["table_name"])
                for row in conn.execute(
                    """
                    SELECT table_name FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name IN (
                      'tutor_conversation_branches',
                      'tutor_conversation_branch_events',
                      'tutor_run_branch_scopes',
                      'tutor_conversation_branch_items',
                      'tutor_continuation_intents',
                      'tutor_continuation_intent_events'
                    )
                    """
                ).fetchall()
            }
            assert len(tables) == 6
            depth = conn.execute(
                """
                SELECT pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE conname = 'tutor_conversation_branches_depth_check'
                """
            ).fetchone()
            assert depth is not None and "depth = 1" in str(depth["definition"])

            foreign = conn.execute(
                "INSERT INTO users (display_name) VALUES ('Foreign branch learner') RETURNING id"
            ).fetchone()
            assert foreign is not None
            foreign_user_id = str(foreign["id"])
            foreign_conversation_id = PostgresTutorRepository(conn).create_conversation(
                user_id=foreign_user_id
            )
            conn.commit()

            repository = PostgresTutorContinuationIntentRepository(conn)
            with pytest.raises(ContinuationIntentNotFound):
                repository.create_pending(
                    user_id=foreign_user_id,
                    conversation_id=foreign_conversation_id,
                    artifact_id=fixture.artifact_id,
                    source_kind=ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION,
                    source_id=f"foreign:{uuid4().hex}",
                    source_version=1,
                    idempotency_key=f"foreign:{uuid4().hex}",
                )
            with pytest.raises(TutorBranchNotFound):
                PostgresTutorBranchRepository(conn).bind_turn(
                    user_id=foreign_user_id,
                    conversation_id=fixture.conversation_id,
                    run_id=str(uuid4()),
                    message_id=str(uuid4()),
                    input_revision=1,
                )
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_continuation_intents WHERE user_id = %s",
                (foreign_user_id,),
            ).fetchone() == {"count": 0}
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)
        if foreign_user_id is not None:
            _cleanup_user(foreign_user_id)


def test_two_competing_claimants_get_one_claim_and_producer_creates_no_turn() -> None:
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            before = conn.execute(
                "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone()
            assert before == {"count": 0}
            intent = TutorContinuationIntentProducer(conn).record_static_display_timer(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                timer_id=f"timer:{uuid4().hex}",
                timer_version=1,
                not_before=datetime.now(UTC),
            )
            after = conn.execute(
                "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone()
            assert after == before
            assert intent.state is ContinuationIntentState.PENDING
            conn.commit()

        barrier = Barrier(2)

        def claim(claimant: str) -> str | None:
            with psycopg.connect(
                get_settings().database_url, row_factory=dict_row
            ) as claim_conn:
                barrier.wait(timeout=5)
                claimed = PostgresTutorContinuationIntentRepository(
                    claim_conn
                ).claim_next(
                    user_id=fixture.user_id,
                    conversation_id=fixture.conversation_id,
                    claimant_id=claimant,
                    now=datetime.now(UTC),
                )
                return claimed.intent_id if claimed is not None else None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(claim, ("claimant-one", "claimant-two")))
        assert sum(item is not None for item in results) == 1
        assert next(item for item in results if item is not None) == intent.intent_id

        with connection() as conn:
            claimed_rows = conn.execute(
                """
                SELECT id, state, claimed_by, claim_generation
                FROM tutor_continuation_intents
                WHERE user_id = %s AND conversation_id = %s AND state = 'claimed'
                """,
                (fixture.user_id, fixture.conversation_id),
            ).fetchall()
            assert len(claimed_rows) == 1
            assert str(claimed_rows[0]["id"]) == intent.intent_id
            assert str(claimed_rows[0]["claimed_by"]) in {
                "claimant-one",
                "claimant-two",
            }
            assert _as_int(claimed_rows[0]["claim_generation"]) == 1
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)


def test_fixed_priority_preempts_claimed_work_and_then_drains_in_order() -> None:
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            repository = PostgresTutorContinuationIntentRepository(conn)
            producer = TutorContinuationIntentProducer(conn)
            explicit = producer.record_artifact_action(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                artifact_event_id=f"event:{uuid4().hex}",
                artifact_event_sequence=1,
                action_kind="respond",
            )
            expected = producer.record_artifact_action(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                artifact_event_id=f"event:{uuid4().hex}",
                artifact_event_sequence=1,
                action_kind="acknowledge_demo_event",
            )
            timer = producer.record_static_display_timer(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                timer_id=f"timer:{uuid4().hex}",
                timer_version=1,
                not_before=datetime.now(UTC),
            )
            background = producer.record_background_continuation(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                source_id=f"background:{uuid4().hex}",
                source_version=1,
            )
            claimed_explicit = repository.claim_next(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                claimant_id="lower-priority-claimant",
                now=datetime.now(UTC),
            )
            assert claimed_explicit is not None
            assert claimed_explicit.intent_id == explicit.intent_id

            run_id, message_id, input_revision, branch_id = _create_branch_turn(
                conn,
                fixture,
                use_service=False,
            )
            learner = repository.record_learner_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                branch_id=branch_id,
                message_id=message_id,
                input_revision=input_revision,
                run_id=run_id,
            )
            assert learner.source_kind is ContinuationSourceKind.LEARNER_MESSAGE
            assert learner.state is ContinuationIntentState.CONSUMED
            assert learner.consumed_run_id == run_id
            released = repository.read(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                intent_id=explicit.intent_id,
            )
            assert released.state is ContinuationIntentState.PENDING
            release_event = conn.execute(
                """
                SELECT event_kind, reason_code
                FROM tutor_continuation_intent_events
                WHERE intent_id = %s
                ORDER BY intent_version DESC LIMIT 1
                """,
                (explicit.intent_id,),
            ).fetchone()
            assert release_event == {
                "event_kind": "released",
                "reason_code": "higher_priority_learner_message",
            }

            _resolve_branch(conn, fixture=fixture, run_id=run_id)
            observed: list[ContinuationSourceKind] = []
            for expected_kind in (
                ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION,
                ContinuationSourceKind.EXPECTED_INTERACTIVE_EVENT,
                ContinuationSourceKind.STATIC_DISPLAY_TIMER,
                ContinuationSourceKind.BACKGROUND_CONTINUATION,
            ):
                claimed = repository.claim_next(
                    user_id=fixture.user_id,
                    conversation_id=fixture.conversation_id,
                    claimant_id=f"claim:{expected_kind.value}",
                    now=datetime.now(UTC),
                )
                assert claimed is not None
                observed.append(claimed.source_kind)
                repository.cancel(
                    user_id=fixture.user_id,
                    conversation_id=fixture.conversation_id,
                    intent_id=claimed.intent_id,
                    reason_code="priority_test_complete",
                )
            assert observed == [
                ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION,
                ContinuationSourceKind.EXPECTED_INTERACTIVE_EVENT,
                ContinuationSourceKind.STATIC_DISPLAY_TIMER,
                ContinuationSourceKind.BACKGROUND_CONTINUATION,
            ]
            assert {
                explicit.priority,
                expected.priority,
                timer.priority,
                background.priority,
            } == {
                400,
                300,
                200,
                100,
            }
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)


def test_positive_authoritative_hint_receipt_is_recorded_on_branch_response() -> None:
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn, hint_owner=True)
            assert fixture.hint_receipt_id is not None
            run_id, _message_id, _input_revision, branch_id = _create_branch_turn(
                conn,
                fixture,
                use_service=True,
            )
            response_message_id = _persist_completed_response(
                conn,
                fixture=fixture,
                run_id=run_id,
                content="Hint: trace the latest assignment before reading the variable.",
            )
            completed = PostgresTutorBranchRepository(conn).complete_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                run_id=run_id,
                response_message_id=response_message_id,
                assistance_kind=BranchAssistanceKind.HINT,
                assistance_receipt_kind=BranchAssistanceReceiptKind.EXERCISE_HINT,
                assistance_receipt_id=fixture.hint_receipt_id,
            )
            assert completed is not None
            assert completed.state == "resolved"
            assert (
                completed.latest_disposition
                is BranchResponseDisposition.ANSWER_AND_REFOCUS
            )
            event = conn.execute(
                """
                SELECT assistance_kind, assistance_receipt_kind, assistance_receipt_id,
                       disposition
                FROM tutor_conversation_branch_events
                WHERE branch_id = %s AND event_kind = 'response_recorded'
                """,
                (branch_id,),
            ).fetchone()
            assert event is not None
            assert event["assistance_kind"] == "hint"
            assert event["assistance_receipt_kind"] == "exercise_hint"
            assert str(event["assistance_receipt_id"]) == fixture.hint_receipt_id
            assert event["disposition"] == "answer_and_refocus"
    finally:
        if fixture is not None:
            _cleanup_user(
                fixture.user_id,
                shared_exercise_version_id=fixture.shared_exercise_version_id,
            )


def test_direct_answer_assistance_requires_exact_same_run_session_teaching_receipt() -> (
    None
):
    fixture: _ArtifactScope | None = None
    foreign: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            repository = PostgresTutorBranchRepository(conn)

            stale_run_id, _message_id, _input_revision, stale_branch_id = (
                _create_branch_turn(
                    conn,
                    fixture,
                    use_service=True,
                    content="Please give me the direct answer for this check.",
                )
            )
            stale_receipt_id = _insert_direct_answer_receipt(
                conn,
                fixture=fixture,
                run_id=stale_run_id,
            )
            stale_response_id = _persist_completed_response(
                conn,
                fixture=fixture,
                run_id=stale_run_id,
                content="The direct answer is 2 because assignment binds that value.",
            )
            stale_completed = repository.complete_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                run_id=stale_run_id,
                response_message_id=stale_response_id,
                assistance_kind=BranchAssistanceKind.DIRECT_ANSWER,
                assistance_receipt_kind=(BranchAssistanceReceiptKind.TEACHING_ACTION),
                assistance_receipt_id=stale_receipt_id,
            )
            assert stale_completed is not None
            assert stale_completed.state == "resolved"
            assert stale_completed.branch_id == stale_branch_id

            current_run_id, _message_id, _input_revision, current_branch_id = (
                _create_branch_turn(
                    conn,
                    fixture,
                    use_service=True,
                    content="Please answer this one directly too.",
                )
            )
            assert current_branch_id != stale_branch_id
            current_response_id = _persist_completed_response(
                conn,
                fixture=fixture,
                run_id=current_run_id,
                content="The direct answer remains 2 for this exact assignment.",
            )
            with pytest.raises(
                ValueError,
                match="branch assistance requires exactly one authoritative receipt",
            ):
                repository.complete_turn(
                    user_id=fixture.user_id,
                    conversation_id=fixture.conversation_id,
                    run_id=current_run_id,
                    response_message_id=current_response_id,
                    assistance_kind=BranchAssistanceKind.DIRECT_ANSWER,
                )

            foreign = _prepare_artifact(conn)
            foreign_run_id, _message_id, _input_revision, _branch_id = (
                _create_branch_turn(
                    conn,
                    foreign,
                    use_service=True,
                    content="Give this other learner a direct answer.",
                )
            )
            foreign_receipt_id = _insert_direct_answer_receipt(
                conn,
                fixture=foreign,
                run_id=foreign_run_id,
            )
            foreign_response_id = _persist_completed_response(
                conn,
                fixture=foreign,
                run_id=foreign_run_id,
                content="This is the other learner's exact direct answer.",
            )
            foreign_completed = repository.complete_turn(
                user_id=foreign.user_id,
                conversation_id=foreign.conversation_id,
                run_id=foreign_run_id,
                response_message_id=foreign_response_id,
                assistance_kind=BranchAssistanceKind.DIRECT_ANSWER,
                assistance_receipt_kind=(BranchAssistanceReceiptKind.TEACHING_ACTION),
                assistance_receipt_id=foreign_receipt_id,
            )
            assert foreign_completed is not None
            assert foreign_completed.state == "resolved"
            assert foreign.user_id != fixture.user_id
            assert foreign.session_id != fixture.session_id

            stale_receipt_scope = conn.execute(
                """
                SELECT run_id, teaching_session_id
                FROM tutor_teaching_action_receipts
                WHERE id = %s
                """,
                (stale_receipt_id,),
            ).fetchone()
            assert stale_receipt_scope is not None
            assert str(stale_receipt_scope["run_id"]) == stale_run_id
            assert str(stale_receipt_scope["teaching_session_id"]) == fixture.session_id

            for rejected_receipt_id in (stale_receipt_id, foreign_receipt_id):
                with pytest.raises(
                    TutorBranchConflict,
                    match="receipt is stale or outside the exact scope",
                ):
                    repository.complete_turn(
                        user_id=fixture.user_id,
                        conversation_id=fixture.conversation_id,
                        run_id=current_run_id,
                        response_message_id=current_response_id,
                        assistance_kind=BranchAssistanceKind.DIRECT_ANSWER,
                        assistance_receipt_kind=(
                            BranchAssistanceReceiptKind.TEACHING_ACTION
                        ),
                        assistance_receipt_id=rejected_receipt_id,
                    )

            assert conn.execute(
                """
                SELECT state, latest_disposition
                FROM tutor_conversation_branches
                WHERE id = %s
                """,
                (current_branch_id,),
            ).fetchone() == {"state": "active", "latest_disposition": None}
            assert conn.execute(
                """
                SELECT count(*)::int AS count
                FROM tutor_conversation_branch_events
                WHERE branch_id = %s AND event_kind = 'response_recorded'
                  AND source_turn_id = %s
                """,
                (current_branch_id, current_run_id),
            ).fetchone() == {"count": 0}

            exact_receipt_id = _insert_direct_answer_receipt(
                conn,
                fixture=fixture,
                run_id=current_run_id,
            )
            exact_receipt_scope = conn.execute(
                """
                SELECT run_id, user_id, conversation_id, teaching_session_id, action
                FROM tutor_teaching_action_receipts
                WHERE id = %s
                """,
                (exact_receipt_id,),
            ).fetchone()
            assert exact_receipt_scope is not None
            assert str(exact_receipt_scope["run_id"]) == current_run_id
            assert str(exact_receipt_scope["user_id"]) == fixture.user_id
            assert (
                str(exact_receipt_scope["conversation_id"]) == fixture.conversation_id
            )
            assert str(exact_receipt_scope["teaching_session_id"]) == fixture.session_id
            assert exact_receipt_scope["action"] == "answer_question"

            completed = repository.complete_turn(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                run_id=current_run_id,
                response_message_id=current_response_id,
                assistance_kind=BranchAssistanceKind.DIRECT_ANSWER,
                assistance_receipt_kind=(BranchAssistanceReceiptKind.TEACHING_ACTION),
                assistance_receipt_id=exact_receipt_id,
            )
            assert completed is not None
            assert completed.state == "resolved"
            assert (
                completed.latest_disposition
                is BranchResponseDisposition.ANSWER_AND_REFOCUS
            )
            event = conn.execute(
                """
                SELECT assistance_kind, assistance_receipt_kind,
                       assistance_receipt_id, disposition, source_turn_id
                FROM tutor_conversation_branch_events
                WHERE branch_id = %s AND event_kind = 'response_recorded'
                  AND source_turn_id = %s
                """,
                (current_branch_id, current_run_id),
            ).fetchone()
            assert event is not None
            assert event["assistance_kind"] == "direct_answer"
            assert event["assistance_receipt_kind"] == "teaching_action"
            assert str(event["assistance_receipt_id"]) == exact_receipt_id
            assert event["disposition"] == "answer_and_refocus"
            assert str(event["source_turn_id"]) == current_run_id
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)
        if foreign is not None:
            _cleanup_user(foreign.user_id)


def test_typed_topic_switch_offer_confirm_cancel_and_unoffered_rejection() -> None:
    confirm_fixture: _ArtifactScope | None = None
    cancel_fixture: _ArtifactScope | None = None
    rejected_fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            repository = PostgresTutorBranchRepository(conn)

            confirm_fixture = _prepare_artifact(conn)
            request_run_id, _message_id, _input_revision, confirm_branch_id = (
                _create_branch_turn(
                    conn,
                    confirm_fixture,
                    use_service=True,
                    content="I want to switch from variables to loops.",
                    control_kind=BranchControlKind.REQUEST_TOPIC_SWITCH,
                )
            )
            request_response_id = _persist_completed_response(
                conn,
                fixture=confirm_fixture,
                run_id=request_run_id,
                content="I can pause this Artifact and switch topics if you confirm.",
            )
            offered = repository.complete_turn(
                user_id=confirm_fixture.user_id,
                conversation_id=confirm_fixture.conversation_id,
                run_id=request_run_id,
                response_message_id=request_response_id,
            )
            assert offered is not None
            assert offered.state == "active"
            assert offered.latest_disposition is BranchResponseDisposition.OFFER_SWITCH

            confirm_run_id, _message_id, _input_revision, rebound_branch_id = (
                _create_branch_turn(
                    conn,
                    confirm_fixture,
                    use_service=True,
                    content="Yes, switch topics now.",
                    control_kind=BranchControlKind.CONFIRM_TOPIC_SWITCH,
                )
            )
            assert rebound_branch_id == confirm_branch_id
            confirm_response_id = _persist_completed_response(
                conn,
                fixture=confirm_fixture,
                run_id=confirm_run_id,
                content="Topic switch confirmed; the clarification branch is resolved.",
            )
            confirmed = repository.complete_turn(
                user_id=confirm_fixture.user_id,
                conversation_id=confirm_fixture.conversation_id,
                run_id=confirm_run_id,
                response_message_id=confirm_response_id,
            )
            assert confirmed is not None
            assert confirmed.state == "resolved"
            assert (
                confirmed.latest_disposition
                is BranchResponseDisposition.CONFIRMED_SWITCH
            )
            assert confirmed.round_count == 2
            assert conn.execute(
                """
                SELECT depth, state, round_count, latest_disposition
                FROM tutor_conversation_branches WHERE id = %s
                """,
                (confirm_branch_id,),
            ).fetchone() == {
                "depth": 1,
                "state": "resolved",
                "round_count": 2,
                "latest_disposition": "confirmed_switch",
            }
            confirm_events = conn.execute(
                """
                SELECT branch_version, event_kind, message_classification,
                       control_kind, disposition
                FROM tutor_conversation_branch_events
                WHERE branch_id = %s
                ORDER BY branch_version
                """,
                (confirm_branch_id,),
            ).fetchall()
            assert confirm_events == [
                {
                    "branch_version": 1,
                    "event_kind": "opened",
                    "message_classification": "control",
                    "control_kind": "request_topic_switch",
                    "disposition": None,
                },
                {
                    "branch_version": 2,
                    "event_kind": "response_recorded",
                    "message_classification": "control",
                    "control_kind": "request_topic_switch",
                    "disposition": "offer_switch",
                },
                {
                    "branch_version": 3,
                    "event_kind": "turn_bound",
                    "message_classification": "control",
                    "control_kind": "confirm_topic_switch",
                    "disposition": None,
                },
                {
                    "branch_version": 4,
                    "event_kind": "response_recorded",
                    "message_classification": "control",
                    "control_kind": "confirm_topic_switch",
                    "disposition": "confirmed_switch",
                },
            ]

            cancel_fixture = _prepare_artifact(conn)
            cancel_request_run_id, _message_id, _input_revision, cancel_branch_id = (
                _create_branch_turn(
                    conn,
                    cancel_fixture,
                    use_service=True,
                    content="Offer a switch away from this Artifact.",
                    control_kind=BranchControlKind.REQUEST_TOPIC_SWITCH,
                )
            )
            cancel_offer_response_id = _persist_completed_response(
                conn,
                fixture=cancel_fixture,
                run_id=cancel_request_run_id,
                content="I can switch after you confirm or keep the current task.",
            )
            cancel_offer = repository.complete_turn(
                user_id=cancel_fixture.user_id,
                conversation_id=cancel_fixture.conversation_id,
                run_id=cancel_request_run_id,
                response_message_id=cancel_offer_response_id,
            )
            assert cancel_offer is not None
            assert cancel_offer.state == "active"
            assert (
                cancel_offer.latest_disposition
                is BranchResponseDisposition.OFFER_SWITCH
            )

            cancel_run_id, _message_id, _input_revision, rebound_cancel_branch_id = (
                _create_branch_turn(
                    conn,
                    cancel_fixture,
                    use_service=True,
                    content="Cancel the switch and keep me on this task.",
                    control_kind=BranchControlKind.CANCEL_TOPIC_SWITCH,
                )
            )
            assert rebound_cancel_branch_id == cancel_branch_id
            cancel_response_id = _persist_completed_response(
                conn,
                fixture=cancel_fixture,
                run_id=cancel_run_id,
                content="We will keep the current Artifact and refocus on it.",
            )
            cancelled = repository.complete_turn(
                user_id=cancel_fixture.user_id,
                conversation_id=cancel_fixture.conversation_id,
                run_id=cancel_run_id,
                response_message_id=cancel_response_id,
            )
            assert cancelled is not None
            assert cancelled.state == "resolved"
            assert (
                cancelled.latest_disposition
                is BranchResponseDisposition.ANSWER_AND_REFOCUS
            )
            assert cancelled.round_count == 2
            assert conn.execute(
                """
                SELECT depth, state, round_count, latest_disposition
                FROM tutor_conversation_branches WHERE id = %s
                """,
                (cancel_branch_id,),
            ).fetchone() == {
                "depth": 1,
                "state": "resolved",
                "round_count": 2,
                "latest_disposition": "answer_and_refocus",
            }
            cancel_responses = conn.execute(
                """
                SELECT control_kind, disposition
                FROM tutor_conversation_branch_events
                WHERE branch_id = %s AND event_kind = 'response_recorded'
                ORDER BY branch_version
                """,
                (cancel_branch_id,),
            ).fetchall()
            assert cancel_responses == [
                {
                    "control_kind": "request_topic_switch",
                    "disposition": "offer_switch",
                },
                {
                    "control_kind": "cancel_topic_switch",
                    "disposition": "answer_and_refocus",
                },
            ]

            rejected_fixture = _prepare_artifact(conn)
            with pytest.raises(TutorBranchError):
                _create_branch_turn(
                    conn,
                    rejected_fixture,
                    use_service=True,
                    content="Confirm a topic switch that was never offered.",
                    control_kind=BranchControlKind.CONFIRM_TOPIC_SWITCH,
                )
            assert conn.execute(
                """
                SELECT count(*)::int AS count
                FROM tutor_conversation_branches
                WHERE user_id = %s AND conversation_id = %s
                """,
                (rejected_fixture.user_id, rejected_fixture.conversation_id),
            ).fetchone() == {"count": 0}
            assert conn.execute(
                """
                SELECT count(*)::int AS count
                FROM tutor_run_branch_scopes
                WHERE user_id = %s AND conversation_id = %s
                  AND control_kind = 'confirm_topic_switch'
                """,
                (rejected_fixture.user_id, rejected_fixture.conversation_id),
            ).fetchone() == {"count": 0}
            conn.rollback()
    finally:
        if confirm_fixture is not None:
            _cleanup_user(confirm_fixture.user_id)
        if cancel_fixture is not None:
            _cleanup_user(cancel_fixture.user_id)
        if rejected_fixture is not None:
            _cleanup_user(rejected_fixture.user_id)


def test_reconnect_snapshot_recovers_active_then_resolved_branch_membership() -> None:
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            run_id, message_id, _input_revision, branch_id = _create_branch_turn(
                conn,
                fixture,
                use_service=True,
            )

        with connection() as reconnect:
            active = TutorPublicService(reconnect).read_conversation_snapshot(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                limit=40,
                cursor=None,
            )
            assert active["snapshot_version"] == "tutor_conversation_snapshot_v5"
            active_branches = cast(list[dict[str, Any]], active["branches"])
            assert len(active_branches) == 1
            active_branch = active_branches[0]
            assert active_branch["branch_id"] == branch_id
            assert active_branch["anchor_artifact_id"] == fixture.artifact_id
            assert active_branch["state"] == "active"
            assert active_branch["collapsed"] is False
            assert active_branch["item_count"] == 2
            assert [item["item_role"] for item in active_branch["items"]] == [
                "learner",
                "process",
            ]
            assert active_branch["items"][0]["item_id"] == message_id

        with connection() as conn:
            response_message_id = _resolve_branch(conn, fixture=fixture, run_id=run_id)

        with connection() as reconnect:
            resolved = TutorPublicService(reconnect).read_conversation_snapshot(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                limit=40,
                cursor=None,
            )
            resolved_branches = cast(list[dict[str, Any]], resolved["branches"])
            resolved_branch = resolved_branches[0]
            assert resolved_branch["branch_id"] == branch_id
            assert resolved_branch["state"] == "resolved"
            assert resolved_branch["collapsed"] is True
            assert resolved_branch["disposition"] == "answer_and_refocus"
            assert resolved_branch["item_count"] == 3
            assert [item["item_role"] for item in resolved_branch["items"]] == [
                "learner",
                "process",
                "tutor",
            ]
            assert resolved_branch["items"][-1]["item_id"] == response_message_id
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)


def test_artifact_result_continuation_returns_to_mainline_after_branch_resolution() -> (
    None
):
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            run_id, _message_id, _input_revision, branch_id = _create_branch_turn(
                conn,
                fixture,
                use_service=True,
            )
            _resolve_branch(conn, fixture=fixture, run_id=run_id)
            artifacts = PostgresLearningArtifactRepository(
                conn,
                conversation_events=PostgresTutorArtifactConversationEventSink(conn),
            )
            current = artifacts.read_artifact(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
            )
            terminal = artifacts.apply_owner_update(
                artifact_id=fixture.artifact_id,
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                learning_track_id=fixture.track_id,
                teaching_session_id=fixture.session_id,
                expected_artifact_version=current.version,
                event_key=f"branch-result:{uuid4().hex}",
                event_kind="terminal",
                mutation=ArtifactMutation(
                    state=TutorArtifactState.COMPLETED,
                    owner_version=current.owner_version,
                    owner_context_version=fixture.session_version,
                    presentation=current.presentation,
                    allowed_actions=(),
                    active_attempt=None,
                    safe_event_payload={"outcome": "completed"},
                ),
                occurred_at=datetime.now(UTC),
            )
            run_count_before = conn.execute(
                "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                (fixture.user_id,),
            ).fetchone()
            intent = TutorContinuationIntentProducer(conn).record_artifact_action(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                artifact_event_id=terminal.artifact_event_id,
                artifact_event_sequence=terminal.artifact_event_sequence,
                action_kind="respond",
            )
            assert intent.state is ContinuationIntentState.PENDING
            assert (
                conn.execute(
                    "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                    (fixture.user_id,),
                ).fetchone()
                == run_count_before
            )

            dispatched = TutorContinuationDispatcher(
                conn, settings=_settings()
            ).dispatch_next(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                claimant_id="result-continuation",
                now=datetime.now(UTC),
            )
            assert dispatched is not None
            assert dispatched.intent.intent_id == intent.intent_id
            assert dispatched.intent.state is ContinuationIntentState.CONSUMED
            assert dispatched.run_id != run_id
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_run_branch_scopes WHERE run_id = %s",
                (dispatched.run_id,),
            ).fetchone() == {"count": 0}
            mainline_scope = conn.execute(
                """
                SELECT teaching_session_id, checkpoint_id, stimulus_id
                FROM tutor_run_teaching_scopes WHERE run_id = %s
                """,
                (dispatched.run_id,),
            ).fetchone()
            assert mainline_scope is not None
            assert str(mainline_scope["teaching_session_id"]) == fixture.session_id
            assert conn.execute(
                "SELECT state FROM tutor_conversation_branches WHERE id = %s",
                (branch_id,),
            ).fetchone() == {"state": "resolved"}
            foreground = conn.execute(
                """
                SELECT id FROM tutor_runs
                WHERE user_id = %s AND conversation_id = %s AND origin = 'interactive'
                  AND terminal_outcome IS NULL AND cancelled_at IS NULL
                  AND superseded_by_run_id IS NULL
                """,
                (fixture.user_id, fixture.conversation_id),
            ).fetchall()
            assert [str(row["id"]) for row in foreground] == [dispatched.run_id]
            assert (
                TutorContinuationDispatcher(conn, settings=_settings()).dispatch_next(
                    user_id=fixture.user_id,
                    conversation_id=fixture.conversation_id,
                    claimant_id="duplicate-result-continuation",
                    now=datetime.now(UTC),
                )
                is None
            )
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)


def test_automatic_intents_are_guided_only_and_stale_authority_fails_closed() -> None:
    free_reading: _ArtifactScope | None = None
    guided: _ArtifactScope | None = None
    try:
        with connection() as conn:
            free_reading = _prepare_artifact(
                conn, mode=TeachingSessionMode.FREE_READING
            )
            with pytest.raises(ContinuationIntentStale):
                TutorContinuationIntentProducer(conn).record_static_display_timer(
                    user_id=free_reading.user_id,
                    conversation_id=free_reading.conversation_id,
                    artifact_id=free_reading.artifact_id,
                    timer_id=f"free-reading-timer:{uuid4().hex}",
                    timer_version=1,
                    not_before=datetime.now(UTC),
                )
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_continuation_intents WHERE user_id = %s",
                (free_reading.user_id,),
            ).fetchone() == {"count": 0}

        with connection() as conn:
            guided = _prepare_artifact(conn)
            pending = TutorContinuationIntentProducer(
                conn
            ).record_background_continuation(
                user_id=guided.user_id,
                conversation_id=guided.conversation_id,
                artifact_id=guided.artifact_id,
                source_id=f"stale-background:{uuid4().hex}",
                source_version=1,
            )
            artifacts = PostgresLearningArtifactRepository(
                conn,
                conversation_events=PostgresTutorArtifactConversationEventSink(conn),
            )
            current = artifacts.read_artifact(
                user_id=guided.user_id,
                conversation_id=guided.conversation_id,
                artifact_id=guided.artifact_id,
            )
            artifacts.apply_owner_update(
                artifact_id=guided.artifact_id,
                user_id=guided.user_id,
                conversation_id=guided.conversation_id,
                learning_track_id=guided.track_id,
                teaching_session_id=guided.session_id,
                expected_artifact_version=current.version,
                event_key=f"stale-terminal:{uuid4().hex}",
                event_kind="terminal",
                mutation=ArtifactMutation(
                    state=TutorArtifactState.COMPLETED,
                    owner_version=current.owner_version,
                    owner_context_version=guided.session_version,
                    presentation=current.presentation,
                    allowed_actions=(),
                    active_attempt=None,
                    safe_event_payload={"outcome": "completed"},
                ),
                occurred_at=datetime.now(UTC),
            )
            repository = PostgresTutorContinuationIntentRepository(conn)
            assert (
                repository.claim_next(
                    user_id=guided.user_id,
                    conversation_id=guided.conversation_id,
                    claimant_id="stale-authority-claimant",
                    now=datetime.now(UTC),
                )
                is None
            )
            stale = repository.read(
                user_id=guided.user_id,
                conversation_id=guided.conversation_id,
                intent_id=pending.intent_id,
            )
            assert stale.state is ContinuationIntentState.CANCELLED
            assert stale.terminal_reason == "authority_stale"
            assert conn.execute(
                "SELECT count(*)::int AS count FROM tutor_runs WHERE user_id = %s",
                (guided.user_id,),
            ).fetchone() == {"count": 0}
    finally:
        if free_reading is not None:
            _cleanup_user(free_reading.user_id)
        if guided is not None:
            _cleanup_user(guided.user_id)


def test_branch_and_continuation_export_redaction_cutover_and_reset_cleanup() -> None:
    fixture: _ArtifactScope | None = None
    try:
        with connection() as conn:
            fixture = _prepare_artifact(conn)
            run_id, _message_id, _input_revision, _branch_id = _create_branch_turn(
                conn,
                fixture,
                use_service=True,
                content="Learner-visible branch question that must not become branch metadata.",
            )
            _resolve_branch(conn, fixture=fixture, run_id=run_id)
            TutorContinuationIntentProducer(conn).record_background_continuation(
                user_id=fixture.user_id,
                conversation_id=fixture.conversation_id,
                artifact_id=fixture.artifact_id,
                source_id=f"safe-background:{uuid4().hex}",
                source_version=1,
            )

            exported = cast(dict[str, Any], export_user_data(conn, fixture.user_id))
            assert len(exported["clarification_branch_summaries"]) == 1
            assert len(exported["clarification_branch_event_summaries"]) == 2
            assert len(exported["run_branch_scope_summaries"]) == 1
            assert len(exported["clarification_branch_item_summaries"]) == 3
            assert len(exported["continuation_intent_summaries"]) == 2
            branch_export = json.dumps(
                {
                    "branches": exported["clarification_branch_summaries"],
                    "events": exported["clarification_branch_event_summaries"],
                    "scopes": exported["run_branch_scope_summaries"],
                    "items": exported["clarification_branch_item_summaries"],
                    "intents": exported["continuation_intent_summaries"],
                    "intent_events": exported["continuation_intent_event_summaries"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            for protected in (
                "request_hash",
                "idempotency_key",
                "claimed_by",
                "opened_message_id",
                "source_message_id",
                "Learner-visible branch question",
            ):
                assert protected not in branch_export
            assert exported["redaction"]["branch_request_hashes"] == "omitted"
            assert exported["redaction"]["continuation_request_hashes"] == "omitted"
            assert exported["redaction"]["continuation_idempotency_keys"] == "omitted"
            assert exported["redaction"]["continuation_claimant_ids"] == "omitted"

            inventory = HarnessCutoverService(conn)._inventory(fixture.user_id)
            for table in (
                "tutor_conversation_branches",
                "tutor_conversation_branch_events",
                "tutor_run_branch_scopes",
                "tutor_conversation_branch_items",
                "tutor_continuation_intents",
                "tutor_continuation_intent_events",
            ):
                assert inventory.target_counts[table] >= 1

            reset = cast(dict[str, Any], reset_user_data(conn, fixture.user_id))
            for count_key in (
                "clarification_branches",
                "clarification_branch_events",
                "run_branch_scopes",
                "clarification_branch_items",
                "continuation_intents",
                "continuation_intent_events",
            ):
                assert reset["summary"]["counts"][count_key] == 0
            fixture = None
    finally:
        if fixture is not None:
            _cleanup_user(fixture.user_id)
