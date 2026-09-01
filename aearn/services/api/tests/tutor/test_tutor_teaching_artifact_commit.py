from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from psycopg import Connection

from app.agents.harness.contracts import (
    TutorDecision,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.routes.learning_artifacts import build_learning_artifact_owner_adapters
from app.services.learning.artifacts.contracts import (
    TutorArtifactActionRequest,
    TutorArtifactCancelAction,
    TutorArtifactOwnerKind,
    TutorArtifactRespondAction,
    TutorArtifactSingleSelectResponse,
)
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
from app.services.learning.teaching_sessions import TeachingSessionService
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


class _ArtifactTeachingProvider:
    def __init__(
        self,
        *,
        artifact_handle: str,
        before_teaching_step: Callable[[str], None] | None = None,
    ) -> None:
        self.artifact_handle = artifact_handle
        self.before_teaching_step = before_teaching_step
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
                        TutorSkillReference("tutor.lesson-teaching", "1.2.0"),
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
                "intent": "structured_answer",
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
) -> tuple[str, str, int, str]:
    suffix = uuid4().hex
    item_key = f"python.variables.atomic.{suffix}"
    required_capability = f"atomic.fixture.{suffix}"
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
                "purpose": "knowledge_check",
                "language_id": "python",
                "difficulty_profile": {
                    "base": "D1",
                    "reasoning_depth": 1,
                    "concept_count": 1,
                    "context_novelty": 1,
                    "transfer_distance": 1,
                    "response_complexity": 1,
                    "scaffolding": 5,
                },
                "prerequisite_keys": [],
                "required_capabilities": [required_capability],
                "runtime_profile_id": None,
                "allowed_interactions": ["respond"],
                "remediation_policy": None,
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
                "purpose": "knowledge_check",
                "title": "Atomic variable check",
                "difficulty": "D1",
                "instruction_markdown": "Choose the value produced by the assignment.",
                "allowed_interactions": ["respond"],
                "hints": [],
                "remediation_item_key": None,
                "source_references": [source_reference],
                "content": {
                    "type": "knowledge_check",
                    "response_kind": "single_choice",
                    "prompt_markdown": "After `value = 42`, which value is bound?",
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
                        response=TutorArtifactSingleSelectResponse(value="forty_two")
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
