from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.errors import CheckViolation

from app.agents.harness.contracts import (
    TutorDecision,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
)
import app.routes.learning_artifacts as artifact_routes
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.main import app
from app.routes.learning_artifacts import build_learning_artifact_owner_adapters
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCancelAction,
    TutorArtifactOwnerKind,
    TutorArtifactRequestDirectAnswerAction,
    TutorArtifactRequestHintAction,
    TutorArtifactRespondAction,
    TutorArtifactRunAction,
    TutorArtifactSingleSelectResponse,
    TutorArtifactSqlWorkspacePresentationV2,
    TutorArtifactTextResponse,
)
from app.services.learning.artifacts.execution_results import (
    ExecutionResultArtifactProjector,
)
from app.services.learning.artifacts.sql_workspaces import observe_sql_workspace_attempt
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.repository import (
    LearningArtifactEventSinkUnavailable,
    PostgresLearningArtifactRepository,
)
from app.services.learning.artifacts.service import (
    LearningArtifactService,
    LearningArtifactServiceError,
)
from app.services.learning.item_bank.compiler import (
    LearningItemCompiler,
    curated_learning_item_source_root,
)
from app.services.learning.item_bank.contracts import (
    LearningItemSourceV1,
    canonical_hash,
)
from app.services.learning.item_bank.governance_repository import (
    PostgresLearningItemGovernanceRepository,
)
from app.services.learning.item_bank.repository import (
    PostgresLearningItemBankRepository,
)
from app.services.learning.item_bank.review_contracts import (
    REQUIRED_REVIEW_ROLES,
    LearningItemPilotTelemetryV1,
    LearningItemReviewReportV1,
)
from app.services.learning.item_bank.validation import validate_learning_item
from app.services.learning.teaching_artifacts import PostgresTeachingArtifactMaterializer
from app.services.learning.teaching_contracts import (
    TeachingSessionMode,
    TeachingStepDecision,
)
from app.services.learning.teaching_sessions import (
    TeachingSessionRepository,
    TeachingSessionService,
)
from app.services.tutor.continuation import (
    ContinuationIntentState,
    ContinuationSourceKind,
    TutorContinuationDispatcher,
    TutorContinuationIntentProducer,
)
from app.services.tutor.interactive import TutorInteractiveRunDispatcher
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink
from tests.support.teaching_session_support import (
    connection,
    create_teaching_scope,
    database_available,
)


pytestmark = pytest.mark.skipif(
    not database_available(),
    reason="PostgreSQL is not available",
)
_NOW = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
_SQL_NOW = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


class _ArtifactTeachingProvider:
    def __init__(
        self,
        *,
        artifact_handle: str,
        before_teaching_step: Callable[[str], None] | None = None,
        interaction_intent: str = "structured_answer",
    ) -> None:
        self.artifact_handle = artifact_handle
        self.before_teaching_step = before_teaching_step
        self.interaction_intent = interaction_intent
        self.calls = 0
        self.selected_handle: str | None = None

    def decide(
        self,
        *,
        run,  # type: ignore[no-untyped-def]
        context,  # type: ignore[no-untyped-def]
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult:
        del run
        self.calls += 1
        advertised_handles = _advertised_artifact_handles(context.as_prompt_context())
        assert advertised_handles
        selected_handle = (
            self.artifact_handle
            if self.artifact_handle in advertised_handles
            else advertised_handles[0]
        )
        if self.selected_handle is None:
            self.selected_handle = selected_handle
        else:
            assert self.selected_handle == selected_handle
        if self.calls == 1:
            assert any(
                item["section"] == "teaching_session"
                for item in context.as_prompt_context()
            )
            return TutorProviderResult(
                decision=TutorDecision(
                    skill_references=(
                        TutorSkillReference("tutor.lesson-teaching", "1.2.1"),
                    ),
                )
            )
        if self.before_teaching_step is not None:
            self.before_teaching_step(selected_handle)
        message = "请在结构化检查工件中回答这个变量问题。"
        step = TeachingStepDecision(
            action="recommend_practice",
            objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables",
            source_handles=("knowledge:python.variables",),
            public_message=message,
            focus_resolution="stay",
            pause_kind="evidence_pause",
            teaching_moves=("worked_example", "micro_transfer"),
            interaction={
                "mode": "artifact",
                "intent": self.interaction_intent,
                "artifact_handle": selected_handle,
            },
        )
        thinking = "当前教学单元选择一个已发布且可执行的结构化检查。"
        if thinking_sink is not None:
            thinking_sink.begin_attempt(1)
            thinking_sink.append_text(1, thinking)
            thinking_sink.complete_attempt(1)
        return TutorProviderResult(
            decision=TutorDecision(
                public_message=message,
                public_thinking_text=thinking,
                terminal_outcome=TutorTerminalOutcome.COMPLETED,
                teaching_step=step,
            )
        )


def _advertised_artifact_handles(
    prompt_context: list[dict[str, object]],
) -> list[str]:
    teaching = next(
        item for item in prompt_context if item.get("section") == "teaching_session"
    )
    serialized = str(teaching["content"])
    assert len(serialized) <= 1200
    payload = json.loads(serialized)
    candidates = payload.get("artifact_candidates")
    assert isinstance(candidates, list)
    return [
        str(candidate["handle"])
        for candidate in candidates
        if isinstance(candidate, dict)
    ]


def _artifact_settings() -> Settings:
    return Settings(
        llm_type="disabled",
        tutor_thread_turn_v2_enabled=True,
        tutor_learning_artifacts_enabled=True,
        tutor_artifact_teaching_mode_enabled=True,
    )


def _published_knowledge_item(
    conn: Connection[dict[str, object]],
    *,
    hints: tuple[dict[str, object], ...] = (),
    item_key: str | None = None,
    purpose: str = "knowledge_check",
    difficulty: str = "D1",
    required_capability: str | None = None,
    remediation_item_key: str | None = None,
    remediation_policy: dict[str, object] | None = None,
    prompt_markdown: str = "After `value = 42`, which value is bound?",
) -> tuple[str, str, int, str]:
    suffix = uuid4().hex
    item_key = item_key or f"python.variables.atomic.{suffix}"
    required_capability = required_capability or f"atomic.fixture.{suffix}"
    difficulty_level = int(difficulty[1:])
    source_reference = {
        "source_id": "python.tutorial",
        "source_version": "3.12",
        "locator": "variables.atomic-artifact",
        "content_hash": canonical_hash({"source": suffix}),
    }
    source = LearningItemSourceV1.model_validate(
        {
            "schema_version": "learning_item_source_v1",
            "blueprint": {
                "schema_version": "learning_item_blueprint_v1",
                "blueprint_key": f"blueprint.{item_key}",
                "version": "v1",
                "knowledge_key": "python.variables",
                "item_kind": "knowledge_check",
                "purpose": purpose,
                "language_id": "python",
                "difficulty_profile": {
                    "base": difficulty,
                    "reasoning_depth": difficulty_level,
                    "concept_count": difficulty_level,
                    "context_novelty": difficulty_level,
                    "transfer_distance": difficulty_level,
                    "response_complexity": difficulty_level,
                    "scaffolding": 6 - difficulty_level,
                },
                "prerequisite_keys": [],
                "required_capabilities": [required_capability],
                "runtime_profile_id": None,
                "allowed_interactions": ["respond"],
                "remediation_policy": remediation_policy,
                "publication_policy": {
                    "risk_tier": "low",
                    "required_review_roles": [
                        role.value for role in REQUIRED_REVIEW_ROLES
                    ],
                    "agent_review_required": True,
                    "pilot_required": True,
                    "human_approval_required": False,
                },
                "source_references": [source_reference],
            },
            "public": {
                "schema_version": "learning_item_public_v1",
                "item_key": item_key,
                "version": "v1",
                "kind": "knowledge_check",
                "purpose": purpose,
                "title": f"Atomic variable {purpose.replace('_', ' ')}",
                "difficulty": difficulty,
                "instruction_markdown": "Choose the value produced by the assignment.",
                "allowed_interactions": ["respond"],
                "hints": list(hints),
                "remediation_item_key": remediation_item_key,
                "source_references": [source_reference],
                "content": {
                    "type": "knowledge_check",
                    "response_kind": "single_choice",
                    "prompt_markdown": prompt_markdown,
                    "options": [
                        {"option_id": "forty_two", "label": "42"},
                        {"option_id": "forty_one", "label": "41"},
                    ],
                },
            },
            "private": {
                "schema_version": "learning_item_private_v1",
                "item_key": item_key,
                "version": "v1",
                "kind": "knowledge_check",
                "content": {
                    "type": "knowledge_check",
                    "accepted_answers": ["forty_two"],
                    "answer_explanation_markdown": "The assignment binds 42.",
                    "tests": [
                        {
                            "id": "visible.correct",
                            "case_type": "visible",
                            "input_json": {"answer": "forty_two"},
                            "expected_output_json": {"accepted": True},
                            "weight": 1,
                            "is_critical": True,
                            "order_index": 0,
                        },
                        {
                            "id": "hidden.wrong",
                            "case_type": "hidden",
                            "input_json": {"answer": "forty_one"},
                            "expected_output_json": {"accepted": False},
                            "weight": 1,
                            "is_critical": False,
                            "order_index": 1,
                        },
                    ],
                    "score_policy": {
                        "kind": "static_exact",
                        "policy_version": "static_exact_v1",
                        "threshold": 1,
                    },
                },
            },
        }
    )
    validation = validate_learning_item(source)
    imported = PostgresLearningItemBankRepository(conn).import_validated_source(
        source=source,
        validation=validation,
        import_key=f"atomic-import:{suffix}",
        source_path=f"tests/atomic-{suffix}.learning-item.json",
        source_file_hash=canonical_hash({"source_hash": source.source_hash}),
        imported_at=_NOW,
    )
    governance = PostgresLearningItemGovernanceRepository(conn)
    subject = governance.load_review_subject(handle=imported.handle)
    reports = tuple(
        LearningItemReviewReportV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            review_input_hash=subject.blind_input(role).review_input_hash,
            role=role,
            reviewer_identity=f"reviewer.{role.value}.{suffix[:8]}",
            verdict="approved",
        )
        for role in REQUIRED_REVIEW_ROLES
    )
    review = governance.record_review_bundle(
        subject=subject,
        reports=reports,
        bundle_key=f"atomic-review:{suffix}",
        occurred_at=_NOW,
    )
    assert review.publication is not None
    pilot = governance.start_pilot(
        handle=imported.handle,
        transition_key=f"atomic-pilot:{suffix}",
        occurred_at=_NOW,
    )
    assert pilot.state == "pilot"
    publication = governance.record_pilot_telemetry(
        handle=imported.handle,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            observation_window_hash=canonical_hash({"pilot": suffix}),
            sample_count=1,
            completed_count=1,
            cohort_complete=True,
        ),
        expected_pilot_sequence=0,
        telemetry_key=f"atomic-telemetry:{suffix}",
        occurred_at=_NOW,
    ).publication
    assert publication is not None and publication.state == "published"
    return (
        imported.handle,
        imported.version_id,
        publication.state_version,
        required_capability,
    )


def _published_sql_item(
    conn: Connection[dict[str, object]],
) -> tuple[str, str, int, str]:
    compiled = LearningItemCompiler().compile_file(
        curated_learning_item_source_root(),
        "sql-filter-track-v2.yaml",
        require_valid=True,
    )
    payload = compiled.loaded.source.model_dump(mode="json")
    suffix = uuid4().hex
    item_key = f"sql.workspace.atomic.{suffix}"
    capability = f"sql.workspace.{suffix}"
    blueprint = payload["blueprint"]
    public = payload["public"]
    private = payload["private"]
    assert isinstance(blueprint, dict)
    assert isinstance(public, dict)
    assert isinstance(private, dict)
    blueprint.update(
        {
            "blueprint_key": f"blueprint.{item_key}",
            "version": "v1",
            "knowledge_key": "python.variables",
            "required_capabilities": [capability],
        }
    )
    public.update({"item_key": item_key, "version": "v1"})
    private.update({"item_key": item_key, "version": "v1"})
    source = LearningItemSourceV1.model_validate(payload)
    validation = validate_learning_item(source)
    assert validation.passed
    imported = PostgresLearningItemBankRepository(conn).import_validated_source(
        source=source,
        validation=validation,
        import_key=f"sql-atomic-import:{suffix}",
        source_path=f"tests/sql-atomic-{suffix}.learning-item.yaml",
        source_file_hash=canonical_hash({"source_hash": source.source_hash}),
        imported_at=_SQL_NOW,
    )
    governance = PostgresLearningItemGovernanceRepository(conn)
    subject = governance.load_review_subject(handle=imported.handle)
    reports = tuple(
        LearningItemReviewReportV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            review_input_hash=subject.blind_input(role).review_input_hash,
            role=role,
            reviewer_identity=f"sql.reviewer.{role.value}.{suffix[:8]}",
            verdict="approved",
        )
        for role in REQUIRED_REVIEW_ROLES
    )
    review = governance.record_review_bundle(
        subject=subject,
        reports=reports,
        bundle_key=f"sql-atomic-review:{suffix}",
        occurred_at=_SQL_NOW,
    )
    assert review.publication is not None
    pilot = governance.start_pilot(
        handle=imported.handle,
        transition_key=f"sql-atomic-pilot:{suffix}",
        occurred_at=_SQL_NOW,
    )
    assert pilot.state == "pilot"
    publication = governance.record_pilot_telemetry(
        handle=imported.handle,
        telemetry=LearningItemPilotTelemetryV1(
            item_handle=imported.handle,
            content_hash=source.content_hash,
            observation_window_hash=canonical_hash({"sql_pilot": suffix}),
            sample_count=1,
            completed_count=1,
            cohort_complete=True,
        ),
        expected_pilot_sequence=0,
        telemetry_key=f"sql-atomic-telemetry:{suffix}",
        occurred_at=_SQL_NOW,
    ).publication
    assert publication is not None and publication.state == "published"
    return imported.handle, imported.version_id, publication.state_version, capability


def _open_guided(
    conn: Connection[dict[str, object]],
    *,
    settings: Settings,
    required_capability: str,
) -> tuple[dict[str, str | int], str]:
    scope = create_teaching_scope(
        conn,
        required_capabilities=(required_capability,),
    )
    opened = TeachingSessionService(conn, settings=settings).open(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key="python.variables",
        conversation_id=str(scope["conversation_id"]),
        expected_track_version=1,
        expected_progress_version=1,
        expected_assignment_version=1,
        mode=TeachingSessionMode.GUIDED,
        idempotency_key=f"atomic-teaching-open:{uuid4()}",
    )
    pending = opened["pending_run"]
    assert isinstance(pending, dict)
    return scope, str(pending["run_id"])


def _dispatch_artifact(
    *,
    settings: Settings,
    scope: dict[str, str | int],
    run_id: str,
    provider: _ArtifactTeachingProvider,
):  # type: ignore[no-untyped-def]
    return TutorInteractiveRunDispatcher(
        settings=settings,
        provider_factory=lambda _settings: provider,
    ).dispatch(user_id=str(scope["user_id"]), run_id=run_id)


def _artifact_service(
    conn: Connection[dict[str, object]],
) -> LearningArtifactService:
    return LearningArtifactService(
        conn,
        repository=PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        ),
        owner_adapters=build_learning_artifact_owner_adapters(),
        enabled=lambda: True,
        clock=lambda: _NOW,
    )


def _materialized_knowledge_artifact(
    *,
    hints: tuple[dict[str, object], ...] = (),
) -> tuple[Settings, dict[str, str | int], str, str]:
    settings = _artifact_settings()
    with connection() as conn:
        capability = f"atomic.fixture.{uuid4().hex}"
        _transfer_handle, _transfer_version_id, _transfer_publication_version, _ = (
            _published_knowledge_item(
                conn,
                purpose="transfer_check",
                difficulty="D1",
                required_capability=capability,
                prompt_markdown="In a new context, which value is bound after `total = 42`?",
            )
        )
        handle, _version_id, _publication_version, capability = (
            _published_knowledge_item(
                conn,
                hints=hints,
                required_capability=capability,
            )
        )
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )
    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(artifact_handle=handle),
    )
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        artifact = conn.execute(
            "SELECT id::text AS id FROM tutor_learning_artifacts WHERE turn_id=%s",
            (run_id,),
        ).fetchone()
        assert artifact is not None
        session = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
        )
    return settings, scope, str(artifact["id"]), str(session["session_id"])


def _assert_no_teaching_artifact_commit(
    conn: Connection[dict[str, object]],
    *,
    scope: dict[str, str | int],
    run_id: str,
) -> None:
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
        (scope["conversation_id"],),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_teaching_action_receipts WHERE run_id=%s",
        (run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_learning_artifacts WHERE turn_id=%s",
        (run_id,),
    ).fetchone() == {"count": 0}
    session = TeachingSessionService(conn).current(
        user_id=str(scope["user_id"]),
        track_id=str(scope["track_id"]),
        knowledge_key="python.variables",
    )
    assert session["session_version"] == 1


def test_artifact_teaching_commit_is_atomic_and_materializes_exact_learning_item() -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, _version_id, _publication_version, capability = (
            _published_knowledge_item(conn)
        )
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    provider = _ArtifactTeachingProvider(artifact_handle=handle)
    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=provider,
    )
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert provider.calls == 2
    assert provider.selected_handle is not None

    with connection() as conn:
        selected_item = conn.execute(
            """
            SELECT versions.id AS version_id, publication.state_version
            FROM tutor_learning_item_versions AS versions
            JOIN LATERAL (
              SELECT state, state_version
              FROM tutor_learning_item_publication_events
              WHERE version_id=versions.id
              ORDER BY state_version DESC
              LIMIT 1
            ) AS publication ON publication.state='published'
            WHERE versions.handle=%s
            """,
            (provider.selected_handle,),
        ).fetchone()
        assert selected_item is not None
        session = TeachingSessionService(conn).current(
            user_id=str(scope["user_id"]),
            track_id=str(scope["track_id"]),
            knowledge_key="python.variables",
        )
        assert session["session_version"] == 2
        assert session["checkpoint"]["pause_reason"] == "evidence_pause"

        receipt = conn.execute(
            "SELECT * FROM tutor_teaching_action_receipts WHERE run_id=%s",
            (run_id,),
        ).fetchone()
        assert receipt is not None
        assert receipt["schema_version"] == "teaching_action_receipt_v3"
        assert receipt["policy_version"] == "lesson_teaching_policy_v3"
        assert receipt["learner_response_mode"] == "artifact"
        assert receipt["interaction_intent"] == "structured_answer"
        assert receipt["artifact_handle"] == provider.selected_handle
        assert receipt["artifact_event_sequence"] == 1

        artifact = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        ).read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=str(receipt["artifact_id"]),
        )
        assert artifact.turn_id == run_id
        assert artifact.checkpoint_id == session["checkpoint_id"]
        assert artifact.owner_kind is TutorArtifactOwnerKind.LEARNING_ITEM
        assert artifact.owner_id == str(selected_item["version_id"])
        assert artifact.owner_version == int(selected_item["state_version"])
        assert artifact.artifact_kind == "knowledge_check"
        assert artifact.state == "active"
        assert artifact.blocking is True
        assert artifact.presentation.type == "knowledge_check_v1"
        assert artifact.presentation.prompt_markdown.startswith("After `value = 42`")
        assert [item.value for item in artifact.presentation.options] == [
            "forty_two",
            "forty_one",
        ]

        event = conn.execute(
            "SELECT artifact_id,event_sequence,event_kind FROM tutor_learning_artifact_events WHERE id=%s",
            (receipt["artifact_event_id"],),
        ).fetchone()
        assert event == {
            "artifact_id": receipt["artifact_id"],
            "event_sequence": 1,
            "event_kind": "created",
        }
        timeline = conn.execute(
            """
            SELECT event_sequence,item_kind,item_id
            FROM tutor_conversation_events
            WHERE conversation_id=%s AND turn_id=%s AND kind='item_added'
            ORDER BY event_sequence
            """,
            (scope["conversation_id"], run_id),
        ).fetchall()
        assert [row["item_kind"] for row in timeline][-2:] == ["message", "artifact"]
        assert str(timeline[-1]["item_id"]) == artifact.id

        run = PostgresTutorRepository(conn).read_run_state(
            user_id=str(scope["user_id"]),
            run_id=run_id,
        )
        assert run.terminal_outcome is TutorTerminalOutcome.COMPLETED
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}

        service = LearningArtifactService(
            conn,
            repository=PostgresLearningArtifactRepository(
                conn,
                conversation_events=PostgresTutorArtifactConversationEventSink(conn),
            ),
            owner_adapters=build_learning_artifact_owner_adapters(),
            enabled=lambda: True,
            clock=lambda: _NOW,
        )
        with pytest.raises(LearningArtifactServiceError) as unsupported:
            service.act(
                artifact_id=artifact.id,
                conversation_id=str(scope["conversation_id"]),
                request=TutorArtifactActionRequest(
                    user_id=str(scope["user_id"]),
                    learning_track_id=str(scope["track_id"]),
                    teaching_session_id=str(session["session_id"]),
                    client_action_id=f"respond:{uuid4()}",
                    expected_artifact_version=1,
                    action=TutorArtifactRespondAction(
                        response=TutorArtifactTextResponse(kind="short_text", text="42")
                    ),
                ),
            )
        assert unsupported.value.code == "LEARNING_ARTIFACT_ACTION_INVALID"
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}
        cancelled = service.act(
            artifact_id=artifact.id,
            conversation_id=str(scope["conversation_id"]),
            request=TutorArtifactActionRequest(
                user_id=str(scope["user_id"]),
                learning_track_id=str(scope["track_id"]),
                teaching_session_id=str(session["session_id"]),
                client_action_id=f"cancel:{uuid4()}",
                expected_artifact_version=1,
                action=TutorArtifactCancelAction(),
            ),
        )
        assert cancelled.artifact.state == "cancelled"
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}


def test_bootstrap_twice_preserves_committed_v3_teaching_action_receipt() -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, _version_id, _publication_version, capability = (
            _published_knowledge_item(conn)
        )
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(artifact_handle=handle),
    )
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        receipt = conn.execute(
            """
            SELECT id::text AS id
            FROM tutor_teaching_action_receipts
            WHERE run_id=%s
            """,
            (run_id,),
        ).fetchone()
        assert receipt is not None
        receipt_id = str(receipt["id"])

    bootstrap_database()
    bootstrap_database()

    with connection() as conn:
        persisted = conn.execute(
            """
            SELECT schema_version, policy_version, learner_response_mode,
                   interaction_intent, artifact_handle, artifact_id,
                   artifact_event_id, artifact_event_sequence
            FROM tutor_teaching_action_receipts
            WHERE id=%s
            """,
            (receipt_id,),
        ).fetchone()
        assert persisted is not None
        assert persisted["schema_version"] == "teaching_action_receipt_v3"
        assert persisted["policy_version"] == "lesson_teaching_policy_v3"
        assert persisted["learner_response_mode"] == "artifact"
        assert persisted["interaction_intent"] == "structured_answer"
        assert persisted["artifact_handle"] == handle
        assert persisted["artifact_id"] is not None
        assert persisted["artifact_event_id"] is not None
        assert persisted["artifact_event_sequence"] == 1


def test_knowledge_check_receipts_replay_and_evaluation_continuation_are_authoritative() -> None:
    settings, scope, artifact_id, session_id = _materialized_knowledge_artifact(
        hints=(
            {"level": 1, "markdown": "Inspect the assignment target."},
            {"level": 2, "markdown": "A name is bound to the right-hand value."},
            {"level": 3, "markdown": "Compare the two numeric options."},
        )
    )
    with connection() as conn:
        service = _artifact_service(conn)
        first_hint_request = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=session_id,
            client_action_id=f"hint:{uuid4()}",
            expected_artifact_version=1,
            action=TutorArtifactRequestHintAction(hint_level=1),
        )
        first_hint = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=first_hint_request,
        )
        assert first_hint.artifact.version == 2
        assert first_hint.artifact.presentation.revealed_hint_levels == (1,)

        replay = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=first_hint_request,
        )
        assert replay.idempotent_replayed is True
        assert replay.artifact_event_id == first_hint.artifact_event_id
        assert replay.artifact.version == 2

        with pytest.raises(LearningArtifactServiceError) as conflict:
            service.act(
                artifact_id=artifact_id,
                conversation_id=str(scope["conversation_id"]),
                request=TutorArtifactActionRequest(
                    user_id=str(scope["user_id"]),
                    learning_track_id=str(scope["track_id"]),
                    teaching_session_id=session_id,
                    client_action_id=first_hint_request.client_action_id,
                    expected_artifact_version=1,
                    action=TutorArtifactRequestHintAction(hint_level=2),
                ),
            )
        assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

        second_hint = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=TutorArtifactActionRequest(
                user_id=str(scope["user_id"]),
                learning_track_id=str(scope["track_id"]),
                teaching_session_id=session_id,
                client_action_id=f"hint:{uuid4()}",
                expected_artifact_version=2,
                action=TutorArtifactRequestHintAction(hint_level=2),
            ),
        )
        third_hint = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=TutorArtifactActionRequest(
                user_id=str(scope["user_id"]),
                learning_track_id=str(scope["track_id"]),
                teaching_session_id=session_id,
                client_action_id=f"hint:{uuid4()}",
                expected_artifact_version=3,
                action=TutorArtifactRequestHintAction(hint_level=3),
            ),
        )
        assert second_hint.artifact.presentation.revealed_hint_levels == (1, 2)
        assert third_hint.artifact.presentation.revealed_hint_levels == (1, 2, 3)

        direct_request = TutorArtifactActionRequest(
            user_id=str(scope["user_id"]),
            learning_track_id=str(scope["track_id"]),
            teaching_session_id=session_id,
            client_action_id=f"direct-answer:{uuid4()}",
            expected_artifact_version=4,
            action=TutorArtifactRequestDirectAnswerAction(),
        )
        answered = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=direct_request,
        )
        assert answered.artifact.version == 5
        assert answered.artifact.state == "completed"
        assert answered.artifact.presentation.assistance_kind == "direct_answer"
        assert answered.artifact.presentation.outcome == "incorrect"
        transfer_handle = answered.artifact.presentation.transfer_handle
        assert transfer_handle is not None
        assert "The assignment binds 42." in answered.artifact.presentation.evaluation_markdown

        answer_replay = service.act(
            artifact_id=artifact_id,
            conversation_id=str(scope["conversation_id"]),
            request=direct_request,
        )
        assert answer_replay.idempotent_replayed is True
        assert answer_replay.artifact_event_id == answered.artifact_event_id

        with pytest.raises(LearningArtifactServiceError) as stale:
            service.act(
                artifact_id=artifact_id,
                conversation_id=str(scope["conversation_id"]),
                request=TutorArtifactActionRequest(
                    user_id=str(scope["user_id"]),
                    learning_track_id=str(scope["track_id"]),
                    teaching_session_id=session_id,
                    client_action_id=f"stale:{uuid4()}",
                    expected_artifact_version=4,
                    action=TutorArtifactRespondAction(
                        response=TutorArtifactSingleSelectResponse(value="forty_two")
                    ),
                ),
            )
        assert stale.value.code == "LEARNING_ARTIFACT_VERSION_CONFLICT"

        assistance = conn.execute(
            """
            SELECT assistance_kind,hint_level
            FROM tutor_knowledge_check_assistance_receipts
            WHERE artifact_id=%s
            ORDER BY created_at,id
            """,
            (artifact_id,),
        ).fetchall()
        assert [(row["assistance_kind"], row["hint_level"]) for row in assistance] == [
            ("hint", 1),
            ("hint", 2),
            ("hint", 3),
            ("direct_answer", None),
        ]
        response = conn.execute(
            """
            SELECT id::text AS id,response_kind,outcome,assistance_kind,
                   independent_mastery_eligible,response_json
            FROM tutor_knowledge_check_response_receipts
            WHERE artifact_id=%s
            """,
            (artifact_id,),
        ).fetchone()
        assert response is not None
        assert response["response_kind"] == "direct_answer"
        assert response["outcome"] == "incorrect"
        assert response["assistance_kind"] == "direct_answer"
        assert response["independent_mastery_eligible"] is False
        assert response["response_json"] == {"kind": "direct_answer"}

        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_knowledge_check_response_receipts SET outcome='correct' WHERE artifact_id=%s",
                    (artifact_id,),
                )
        with pytest.raises(CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_knowledge_check_assistance_receipts SET hint_level=2 WHERE artifact_id=%s AND hint_level=1",
                    (artifact_id,),
                )

        producer = TutorContinuationIntentProducer(conn)
        intent = producer.record_knowledge_check_evaluation(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
            artifact_event_id=answered.artifact_event_id,
            artifact_event_sequence=answered.artifact_event_sequence,
            occurred_at=_NOW,
        )
        intent_replay = producer.record_knowledge_check_evaluation(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
            artifact_event_id=answered.artifact_event_id,
            artifact_event_sequence=answered.artifact_event_sequence,
            occurred_at=_NOW,
        )
        assert intent.state is ContinuationIntentState.PENDING
        assert intent_replay.intent_id == intent.intent_id
        assert intent_replay.replayed is True

        dispatched = TutorContinuationDispatcher(conn, settings=settings).dispatch_next(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            claimant_id="knowledge-check-evaluation-test",
            now=_NOW,
        )
        assert dispatched is not None
        assert dispatched.intent.intent_id == intent.intent_id
        assert dispatched.intent.source_kind is ContinuationSourceKind.EXPLICIT_ARTIFACT_ACTION
        stimulus = conn.execute(
            "SELECT safe_payload_json FROM tutor_run_stimulus_events WHERE run_id=%s",
            (dispatched.run_id,),
        ).fetchone()
        assert stimulus is not None
        assert stimulus["safe_payload_json"] == {
            "reason_code": "knowledge_check_evaluation",
            "source_handle": f"artifact:{artifact_id}",
        }
        context = TeachingSessionRepository(conn, settings=settings).teaching_context(
            user_id=str(scope["user_id"]),
            run_id=dispatched.run_id,
        )
        assert context is not None
        candidates = context["artifact_candidates"]
        assert isinstance(candidates, dict)
        assert [item["handle"] for item in candidates["candidates"]] == [transfer_handle]
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}


def test_publication_change_after_decision_context_rolls_back_message_checkpoint_and_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, _version_id, _publication_version, capability = (
            _published_knowledge_item(conn)
        )
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    def quarantine(
        conn: Connection[dict[str, object]],
        selected_handle: str,
    ) -> None:
        current = conn.execute(
            """
            SELECT publication.state, publication.state_version
            FROM tutor_learning_item_versions AS versions
            JOIN LATERAL (
              SELECT state, state_version
              FROM tutor_learning_item_publication_events
              WHERE version_id=versions.id
              ORDER BY state_version DESC
              LIMIT 1
            ) AS publication ON true
            WHERE versions.handle=%s
            """,
            (selected_handle,),
        ).fetchone()
        assert current is not None and current["state"] == "published"
        publication = PostgresLearningItemBankRepository(conn).append_publication_state(
            handle=selected_handle,
            expected_state_version=int(current["state_version"]),
            next_state="quarantined",
            transition_key=f"atomic-quarantine:{uuid4()}",
            authority_kind="operator",
            authority_hash=canonical_hash({"quarantine": selected_handle}),
            policy_version="atomic_test_policy_v1",
            reason_code="atomic_test_quarantine",
            occurred_at=_NOW,
        )
        assert publication.state == "quarantined"

    original_prepare = PostgresTeachingArtifactMaterializer.prepare

    def prepare_after_quarantine(
        materializer: PostgresTeachingArtifactMaterializer,
        **kwargs: object,
    ):
        step = kwargs["step"]
        assert isinstance(step, TeachingStepDecision)
        assert step.interaction is not None
        assert step.interaction.artifact_handle is not None
        quarantine(materializer._conn, step.interaction.artifact_handle)
        return original_prepare(materializer, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        PostgresTeachingArtifactMaterializer,
        "prepare",
        prepare_after_quarantine,
    )
    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(artifact_handle=handle),
    )
    assert result.terminal_outcome is TutorTerminalOutcome.CANCELLED
    assert result.diagnostic_code == "teaching_authority_stale"
    with connection() as conn:
        _assert_no_teaching_artifact_commit(conn, scope=scope, run_id=run_id)


def test_artifact_event_failure_after_message_insert_rolls_back_every_public_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, _version_id, _publication_version, capability = (
            _published_knowledge_item(conn)
        )
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    observed_message_counts: list[int] = []

    def fail_after_message(
        repository: PostgresLearningArtifactRepository,
        request,  # type: ignore[no-untyped-def]
        *,
        creation_key: str,
        occurred_at: datetime | None = None,
    ):
        del creation_key, occurred_at
        count = repository._conn.execute(
            "SELECT count(*)::int AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (request.conversation_id,),
        ).fetchone()
        assert count is not None
        observed_message_counts.append(int(count["count"]))
        raise LearningArtifactEventSinkUnavailable(
            "forced Artifact event failure after Tutor message insert"
        )

    monkeypatch.setattr(
        PostgresLearningArtifactRepository,
        "create_artifact",
        fail_after_message,
    )
    result = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(artifact_handle=handle),
    )
    assert observed_message_counts == [1]
    assert result.terminal_outcome is TutorTerminalOutcome.CANCELLED
    assert result.diagnostic_code == "teaching_authority_stale"
    with connection() as conn:
        _assert_no_teaching_artifact_commit(conn, scope=scope, run_id=run_id)


def test_sql_workspace_run_commits_pending_attempt_then_projects_public_grid() -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, version_id, publication_version, capability = _published_sql_item(conn)
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )

    dispatched = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=handle,
            interaction_intent="execute_query",
        ),
    )
    assert dispatched.terminal_outcome is TutorTerminalOutcome.COMPLETED

    with connection() as conn:
        row = conn.execute(
            "SELECT id::text AS id FROM tutor_learning_artifacts WHERE turn_id=%s",
            (run_id,),
        ).fetchone()
        assert row is not None
        artifact_id = str(row["id"])
        service = LearningArtifactService(
            conn,
            repository=PostgresLearningArtifactRepository(
                conn,
                conversation_events=PostgresTutorArtifactConversationEventSink(conn),
            ),
            owner_adapters=build_learning_artifact_owner_adapters(),
            enabled=lambda: True,
            clock=lambda: _SQL_NOW,
        )
        artifact = service.read_artifact(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
        )
        assert artifact.owner_id == version_id
        assert artifact.owner_version == publication_version
        assert isinstance(
            artifact.presentation,
            TutorArtifactSqlWorkspacePresentationV2,
        )
        assert [table.name for table in artifact.presentation.tables] == [
            "mentors",
            "learners",
        ]
        admitted = service.act(
            artifact_id=artifact.id,
            conversation_id=artifact.conversation_id,
            request=TutorArtifactActionRequest(
                user_id=str(scope["user_id"]),
                learning_track_id=str(scope["track_id"]),
                teaching_session_id=artifact.teaching_session_id,
                client_action_id=f"sql-run:{uuid4().hex}",
                expected_artifact_version=artifact.version,
                action=TutorArtifactRunAction(
                    submission=(
                        "SELECT name FROM learners "
                        "WHERE track = 'sql' ORDER BY id;"
                    )
                ),
            ),
        )
        assert admitted.artifact.state == "running"
        assert admitted.artifact.active_attempt is not None
        assert admitted.artifact.active_attempt.status == "pending"
        attempt_id = admitted.artifact.active_attempt.attempt_id
        attempt_row = conn.execute(
            """
            SELECT attempts.gate_binding_id,
                   attempts.learning_item_version_id::text AS learning_item_version_id,
                   results.result_hash
            FROM tutor_exercise_attempts AS attempts
            LEFT JOIN tutor_exercise_attempt_results AS results
              ON results.attempt_id=attempts.id
            WHERE attempts.id=%s
            """,
            (attempt_id,),
        ).fetchone()
        assert attempt_row == {
            "gate_binding_id": None,
            "learning_item_version_id": version_id,
            "result_hash": None,
        }
        conn.commit()

    with connection() as conn:
        observe_sql_workspace_attempt(
            conn,
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
            attempt_id=attempt_id,
        )
        projection = ExecutionResultArtifactProjector(
            conn,
            enabled=lambda: True,
            clock=lambda: _SQL_NOW,
        ).project(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            source_artifact_id=artifact_id,
            attempt_id=attempt_id,
        )
        conn.commit()

    source = projection.source_artifact.artifact
    assert source.state == "completed"
    assert isinstance(source.presentation, TutorArtifactSqlWorkspacePresentationV2)
    assert source.presentation.public_result is not None
    assert source.presentation.public_result.columns == ("name",)
    assert source.presentation.public_result.rows == (("Grace",),)
    assert source.presentation.public_result_attempt_id == attempt_id
    assert source.presentation.public_result_query_hash is not None

    with connection() as conn:
        detail = _artifact_service(conn).read_attempt_detail(
            user_id=str(scope["user_id"]),
            conversation_id=str(scope["conversation_id"]),
            artifact_id=artifact_id,
            attempt_id=attempt_id,
        )
        assert detail.status == "terminal"
        assert detail.result is not None
        assert source.presentation.public_result_query_hash == detail.submission_hash
        assert detail.result.outcome == "passed"
        assert detail.result.execution_result is not None
        serialized = json.dumps(
            detail.result.execution_result.model_dump(mode="json"),
            ensure_ascii=False,
        )
        assert "Barbara" not in serialized
        assert "hidden_sql" not in serialized
        assert detail.result.execution_result.test_feedback[-1].case_id == "non-visible-1"
        assert projection.result_artifact.artifact.presentation.outcome == "passed"
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_mastery_evidence WHERE user_id=%s",
            (scope["user_id"],),
        ).fetchone() == {"count": 0}


def test_sql_workspace_action_route_executes_only_after_admission_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _artifact_settings()
    with connection() as conn:
        handle, _version_id, _publication_version, capability = _published_sql_item(conn)
        scope, run_id = _open_guided(
            conn,
            settings=settings,
            required_capability=capability,
        )
    dispatched = _dispatch_artifact(
        settings=settings,
        scope=scope,
        run_id=run_id,
        provider=_ArtifactTeachingProvider(
            artifact_handle=handle,
            interaction_intent="execute_query",
        ),
    )
    assert dispatched.terminal_outcome is TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        artifact = conn.execute(
            """
            SELECT id::text AS id,version,teaching_session_id::text AS teaching_session_id
            FROM tutor_learning_artifacts WHERE turn_id=%s
            """,
            (run_id,),
        ).fetchone()
        assert artifact is not None

    monkeypatch.setattr(artifact_routes, "get_settings", lambda: settings)
    monkeypatch.setattr(artifact_routes, "runtime_gate_error", lambda **_kwargs: None)
    monkeypatch.setattr(
        artifact_routes,
        "thread_turn_v2_gate_error",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        artifact_routes,
        "enqueue_tutor_interactive_dispatch",
        lambda *_args, **_kwargs: False,
    )
    response = TestClient(app).post(
        f"/api/tutor/conversations/{scope['conversation_id']}/artifacts/{artifact['id']}/actions",
        json={
            "user_id": str(scope["user_id"]),
            "learning_track_id": str(scope["track_id"]),
            "teaching_session_id": str(artifact["teaching_session_id"]),
            "client_action_id": f"sql-route:{uuid4().hex}",
            "expected_artifact_version": int(artifact["version"]),
            "action": {
                "action": "run",
                "submission": (
                    "SELECT name FROM learners "
                    "WHERE track = 'sql' ORDER BY id;"
                ),
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact"]["state"] == "completed"
    assert body["artifact"]["presentation"]["type"] == "sql_workspace_v2"
    assert body["artifact"]["presentation"]["public_result"] == {
        "kind": "table_result_v1",
        "columns": ["name"],
        "rows": [["Grace"]],
    }
    assert body["artifact_event_sequence"] == body["artifact"]["version"]
    with connection() as conn:
        attempt_id = body["artifact"]["active_attempt"]["attempt_id"]
        assert conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_exercise_attempt_results WHERE attempt_id=%s
            """,
            (attempt_id,),
        ).fetchone() == {"count": 1}
        intent = conn.execute(
            """
            SELECT intents.source_kind,
                   artifacts.active_attempt_id::text AS attempt_id
            FROM tutor_continuation_intents AS intents
            JOIN tutor_learning_artifacts AS artifacts
              ON artifacts.id=intents.artifact_id
            WHERE intents.user_id=%s AND intents.conversation_id=%s
              AND artifacts.active_attempt_id=%s
            """,
            (scope["user_id"], scope["conversation_id"], attempt_id),
        ).fetchone()
        assert intent == {
            "source_kind": "explicit_artifact_action",
            "attempt_id": attempt_id,
        }
