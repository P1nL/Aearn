from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorContextError,
    TutorContextInput,
    TutorContextSource,
    TutorDecision,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
)
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.main import app
from app.services.learning.artifacts.contracts import (
    TutorArtifactCreate,
    TutorArtifactKind,
    TutorArtifactOwnerKind,
    TutorArtifactPurpose,
    TutorArtifactSourceInspectorPresentationV1,
    TutorArtifactSourceReferenceV1,
    TutorArtifactState,
)
from app.services.learning.artifacts.conversation_events import (
    PostgresTutorArtifactConversationEventSink,
)
from app.services.learning.artifacts.repository import PostgresLearningArtifactRepository
from app.services.learning.lesson_repository import PostgresLessonDocumentRepository
from app.services.learning.source_inspector import (
    PostgresSourceInspectorMaterializer,
    SourceInspectorCommitError,
    parse_source_inspector_candidates,
)
from app.services.learning.teaching_candidates import (
    TeachingArtifactCandidateBuildError,
    project_teaching_provider_context,
)
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.learning.teaching_contracts import TeachingSessionMode, TeachingStepDecision
from app.services.learning.teaching_sessions import TeachingSessionRepository, TeachingSessionService
from app.services.repositories.local_user_data_repository import reset_user_data
from app.services.tutor.interactive import (
    TutorInteractiveRunDispatcher,
    _bind_optional_source_inspection_candidates,
    _source_inspection_context_input,
)
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink
from tests.support.lesson_document_support import sample_lesson_document, sample_source_snapshot
from tests.support.teaching_session_support import connection, create_teaching_scope, database_available

pytestmark = pytest.mark.skipif(not database_available(), reason="PostgreSQL is not available")
_NOW = datetime(2026, 9, 21, 8, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class TutorSourceScope:
    user_id: str
    track_id: str
    conversation_id: str
    knowledge_key: str
    assignment_id: str
    assignment_version: int
    document_id: str
    document_content_hash: str
    block_id: str
    citation_id: str
    session_id: str
    checkpoint_id: str
    run_id: str


class _TutorSourceProvider:
    def __init__(
        self,
        *,
        choose_source: bool,
        override_handle: str | None = None,
        before_terminal: Callable[[], None] | None = None,
    ) -> None:
        self.choose_source = choose_source
        self.override_handle = override_handle
        self.before_terminal = before_terminal
        self.calls = 0
        self.visible_handles: tuple[str, ...] = ()
        self.required_source_evidence: tuple[dict[str, object], ...] = ()
        self.selected_handle: str | None = None

    def decide(
        self,
        *,
        run,  # type: ignore[no-untyped-def]
        context,  # type: ignore[no-untyped-def]
        thinking_sink: TutorPublicThinkingSink | None = None,
    ) -> TutorProviderResult:
        del run, thinking_sink
        self.calls += 1
        prompt_context = context.as_prompt_context()
        teaching = next(
            item for item in prompt_context if item.get("section") == "teaching_session"
        )
        teaching_payload = json.loads(str(teaching["content"]))
        allowed = teaching_payload.get("allowed_source_handles")
        assert isinstance(allowed, list)
        self.visible_handles = tuple(
            str(handle) for handle in allowed if str(handle).startswith("lesson-source:")
        )
        source_evidence: list[dict[str, object]] = []
        for item in prompt_context:
            if not str(item.get("source_id") or "").startswith(
                "teaching-source-candidate:"
            ):
                continue
            payload = json.loads(str(item["content"]))
            assert isinstance(payload, dict)
            source_evidence.append(payload)
        self.required_source_evidence = tuple(source_evidence)
        if self.calls == 1:
            return TutorProviderResult(
                decision=TutorDecision(
                    skill_references=(
                        TutorSkillReference("tutor.lesson-teaching", "1.2.1"),
                    ),
                )
            )
        selected = self.override_handle
        if selected is None and self.choose_source:
            assert self.visible_handles
            selected = self.visible_handles[0]
        self.selected_handle = selected
        if self.before_terminal is not None:
            self.before_terminal()
        message = "变量绑定会把名称与值关联；这条讲解可以同时展示对应的冻结课程来源。"
        source_handles = ["knowledge:python.variables"]
        if selected is not None:
            source_handles.append(selected)
        return TutorProviderResult(
            decision=TutorDecision(
                public_message=message,
                terminal_outcome=TutorTerminalOutcome.COMPLETED,
                teaching_step=TeachingStepDecision(
                    action="explain_concept",
                    objective_id="knowledge:python.variables",
                    focus_id="knowledge:python.variables",
                    source_handles=tuple(source_handles),
                    public_message=message,
                    focus_resolution="stay",
                    pause_kind="soft_pause",
                    teaching_moves=("targeted_explanation", "worked_example"),
                    interaction={
                        "mode": "none",
                        "intent": "none",
                        "artifact_handle": None,
                    },
                ),
            )
        )


def _settings(
    *,
    learning_artifacts_enabled: bool = True,
    artifact_teaching_enabled: bool = True,
) -> Settings:
    return Settings(
        llm_type="disabled",
        tutor_default_context_window_tokens=16_384,
        tutor_default_output_reserve_tokens=4_096,
        tutor_thread_turn_v2_enabled=True,
        tutor_learning_artifacts_enabled=learning_artifacts_enabled,
        tutor_artifact_teaching_mode_enabled=artifact_teaching_enabled,
    )


@pytest.fixture(scope="module", autouse=True)
def _bootstrap_source_inspector() -> None:
    bootstrap_database()


@pytest.fixture
def source_scope() -> Iterator[TutorSourceScope]:
    settings = _settings()
    with connection() as conn:
        scope = _seed_scope(conn, settings=settings)
        conn.commit()
    try:
        yield scope
    finally:
        with connection() as conn:
            reset_user_data(conn, scope.user_id)
            conn.commit()


def _seed_scope(
    conn,  # type: ignore[no-untyped-def]
    *,
    settings: Settings,
) -> TutorSourceScope:
    base = create_teaching_scope(conn)
    user_id = str(base["user_id"])
    track_id = str(base["track_id"])
    conversation_id = str(base["conversation_id"])
    knowledge_key = str(base["knowledge_key"])
    current = conn.execute(
        """
        SELECT assignments.*,documents.standard_document_id
        FROM tutor_lesson_assignments AS assignments
        JOIN tutor_lesson_documents AS documents ON documents.id=assignments.document_id
        WHERE assignments.id=%s
        """,
        (base["assignment_id"],),
    ).fetchone()
    assert current is not None
    document = sample_lesson_document(personalized=True)
    snapshot = replace(
        sample_source_snapshot(),
        document_content_hash=document.content_hash,
    )
    document_id = PostgresLessonDocumentRepository(conn)._insert_or_reuse_document(
        document_kind="personalized",
        document=document,
        snapshots=(snapshot,),
        user_id=user_id,
        track_id=track_id,
        active_plan_revision_id=str(current["source_plan_revision_id"]),
        standard_document_id=str(current["standard_document_id"]),
        profile_hash=uuid4().hex.ljust(64, "0"),
        generator_version=f"source-sidecar-test-{uuid4()}",
        policy_version="source-sidecar-test-v1",
        source_set_hash=uuid4().hex.ljust(64, "0"),
        change_summary={},
        quality_summary={},
    )
    conn.execute(
        "UPDATE tutor_lesson_assignments SET status='superseded' WHERE id=%s",
        (current["id"],),
    )
    assignment = conn.execute(
        """
        INSERT INTO tutor_lesson_assignments (
          user_id,track_id,knowledge_key,document_id,source_plan_revision_id,
          predecessor_assignment_id,assignment_version,status,impact_json,
          expected_progress_version,content_hash,activated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,2,'active','{}'::jsonb,1,%s,now())
        RETURNING id
        """,
        (
            user_id,
            track_id,
            knowledge_key,
            document_id,
            current["source_plan_revision_id"],
            current["id"],
            document.content_hash,
        ),
    ).fetchone()
    assert assignment is not None
    opened = TeachingSessionService(conn, settings=settings).open(
        user_id=user_id,
        track_id=track_id,
        knowledge_key=knowledge_key,
        conversation_id=conversation_id,
        expected_track_version=1,
        expected_progress_version=1,
        expected_assignment_version=2,
        mode=TeachingSessionMode.GUIDED,
        idempotency_key=f"source-sidecar-open:{uuid4()}",
    )
    session = opened["teaching_session"]
    pending = opened["pending_run"]
    assert isinstance(session, Mapping) and isinstance(pending, Mapping)
    concept = document.blocks[2]
    return TutorSourceScope(
        user_id=user_id,
        track_id=track_id,
        conversation_id=conversation_id,
        knowledge_key=knowledge_key,
        assignment_id=str(assignment["id"]),
        assignment_version=2,
        document_id=document_id,
        document_content_hash=document.content_hash,
        block_id=concept.block_id,
        citation_id=concept.citation_ids[0],
        session_id=str(session["session_id"]),
        checkpoint_id=str(session["checkpoint_id"]),
        run_id=str(pending["run_id"]),
    )


def _dispatch(
    *,
    settings: Settings,
    scope: TutorSourceScope,
    provider: _TutorSourceProvider,
):  # type: ignore[no-untyped-def]
    return TutorInteractiveRunDispatcher(
        settings=settings,
        provider_factory=lambda _settings: provider,
    ).dispatch(user_id=scope.user_id, run_id=scope.run_id)


def test_tutor_selected_source_is_bounded_and_committed_as_atomic_sidecar(
    source_scope: TutorSourceScope,
) -> None:
    provider = _TutorSourceProvider(choose_source=True)
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert 1 <= len(provider.visible_handles) <= 2
    assert len(provider.required_source_evidence) == len(provider.visible_handles)
    assert {str(item["handle"]) for item in provider.required_source_evidence} == set(
        provider.visible_handles
    )
    assert provider.selected_handle in provider.visible_handles
    assert all(set(item) == {"kind", "handle", "title", "excerpt", "recently_displayed"} for item in provider.required_source_evidence)
    assert all(len(str(item["excerpt"])) <= 320 for item in provider.required_source_evidence)

    with connection() as conn:
        artifact = conn.execute(
            """
            SELECT id::text AS id,turn_id::text AS turn_id,checkpoint_id::text AS checkpoint_id,
                   owner_id::text AS owner_id,owner_version,purpose,state,blocking,
                   allowed_actions_json,presentation_json
            FROM tutor_learning_artifacts
            WHERE turn_id=%s AND purpose='source_inspection'
            """,
            (source_scope.run_id,),
        ).fetchone()
        assert artifact is not None
        event = conn.execute(
            "SELECT id::text AS id,event_sequence,event_kind FROM tutor_learning_artifact_events WHERE artifact_id=%s",
            (artifact["id"],),
        ).fetchone()
        receipt = conn.execute(
            """
            SELECT checkpoint_id::text AS checkpoint_id,source_handles_json,
                   learner_response_mode,schema_version,artifact_id
            FROM tutor_teaching_action_receipts WHERE run_id=%s
            """,
            (source_scope.run_id,),
        ).fetchone()
        session = conn.execute(
            "SELECT current_checkpoint_id::text AS checkpoint_id,version FROM tutor_teaching_sessions WHERE id=%s",
            (source_scope.session_id,),
        ).fetchone()
        message_count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
            (source_scope.conversation_id,),
        ).fetchone()
        references = conn.execute(
            """
            SELECT reference_kind,reference_id::text AS reference_id,reference_version,content_hash
            FROM tutor_learning_artifact_references WHERE artifact_id=%s
            """,
            (artifact["id"],),
        ).fetchall()
        attempts = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_exercise_attempts WHERE user_id=%s",
            (source_scope.user_id,),
        ).fetchone()
        continuations = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_continuation_intents WHERE user_id=%s",
            (source_scope.user_id,),
        ).fetchone()
    assert session == {"checkpoint_id": artifact["checkpoint_id"], "version": 2}
    assert artifact["turn_id"] == source_scope.run_id
    assert artifact["owner_id"] == artifact["checkpoint_id"]
    assert artifact["owner_version"] == 2
    assert artifact["state"] == "ready" and artifact["blocking"] is False
    assert artifact["allowed_actions_json"] == []
    assert event == {"id": event["id"], "event_sequence": 1, "event_kind": "created"}
    assert receipt is not None
    assert provider.selected_handle in receipt["source_handles_json"]
    assert receipt["checkpoint_id"] == artifact["checkpoint_id"]
    assert receipt["learner_response_mode"] == "none"
    assert receipt["schema_version"] == "teaching_action_receipt_v2"
    assert receipt["artifact_id"] is None
    assert message_count == {"count": 1}
    assert references == [
        {
            "reference_kind": "lesson_document",
            "reference_id": source_scope.document_id,
            "reference_version": 2,
            "content_hash": source_scope.document_content_hash,
        }
    ]
    assert artifact["presentation_json"]["citation_ids"] == [source_scope.citation_id]
    assert attempts == {"count": 0}
    assert continuations == {"count": 0}


def test_optional_source_is_pruned_at_required_fact_limit_and_gate_cannot_reauthorize_hidden_handle(
    source_scope: TutorSourceScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with connection() as conn:
        raw_context = TeachingSessionRepository(conn, settings=_settings()).teaching_context(
            user_id=source_scope.user_id,
            run_id=source_scope.run_id,
        )
    assert raw_context is not None
    raw_candidates = parse_source_inspector_candidates(raw_context)
    assert raw_candidates
    hidden_handle = raw_candidates[0].handle

    original_project_snapshot = PostgresPlanningFactRepository.project_snapshot

    def saturated_project_snapshot(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        snapshot = original_project_snapshot(self, *args, **kwargs)
        saturated = tuple(
            TutorContextSource(
                source_id=f"source-budget-fact:{index}",
                content={"fact": index},
                semantic_class="confirmed_fact_source",
            )
            for index in range(8)
        )
        return replace(snapshot, required_facts=saturated)

    monkeypatch.setattr(
        PostgresPlanningFactRepository,
        "project_snapshot",
        saturated_project_snapshot,
    )
    provider = _TutorSourceProvider(
        choose_source=True,
        override_handle=hidden_handle,
    )
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert provider.visible_handles == ()
    assert provider.required_source_evidence == ()
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    assert result.diagnostic_code == "teaching_source_handle_invalid"
    with connection() as conn:
        _assert_no_source_commit(conn, source_scope)


def test_optional_source_is_pruned_when_teaching_projection_has_no_character_room(
    source_scope: TutorSourceScope,
) -> None:
    snapshot, teaching_context = _source_budget_inputs(source_scope)
    candidates = parse_source_inspector_candidates(teaching_context)
    assert candidates
    teaching_context["recent_teaching_units"] = []
    ordinary = list(teaching_context["allowed_source_handles"])
    padded_context: dict[str, object] | None = None
    for length in range(1200):
        trial = dict(teaching_context)
        trial["allowed_source_handles"] = [*ordinary, f"padding:{'x' * length}"]
        try:
            projection = project_teaching_provider_context(trial)
        except TeachingArtifactCandidateBuildError:
            break
        if len(json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= 1200:
            padded_context = trial
    assert padded_context is not None
    context_input = _source_budget_context_input(
        snapshot=snapshot,
        teaching_context=padded_context,
        teaching_session_id=source_scope.session_id,
    )
    with pytest.raises(TutorContextError, match="TUTOR_TEACHING_SESSION_STALE"):
        _source_inspection_context_input(
            context_input=context_input,
            teaching_context=padded_context,
            teaching_session_id=source_scope.session_id,
            candidates=(candidates[0],),
            run_id=source_scope.run_id,
        )
    bounded = _bind_optional_source_inspection_candidates(
        snapshot=snapshot,
        context_input=context_input,
        teaching_context=padded_context,
        teaching_session_id=source_scope.session_id,
    )
    _assert_source_budget_sync(bounded, expected_handles=())


def test_optional_source_never_displaces_interaction_candidate_or_grounding(
    source_scope: TutorSourceScope,
) -> None:
    snapshot, teaching_context = _source_budget_inputs(source_scope)
    source_candidates = parse_source_inspector_candidates(teaching_context)
    assert source_candidates
    raw_candidate_set = teaching_context.get("artifact_candidates")
    assert isinstance(raw_candidate_set, Mapping)
    candidate_set = dict(raw_candidate_set)
    interaction_handle = f"li:{'a' * 64}"
    candidate_set["feature_enabled"] = True
    candidate_set["candidates"] = [
        {
            "handle": interaction_handle,
            "kind": "code",
            "purpose": "exercise",
            "difficulty": "D1",
            "interaction_intents": ["edit_code", "run_code"],
        }
    ]
    teaching_context["artifact_candidates"] = candidate_set
    teaching_context["recent_teaching_units"] = []
    ordinary = list(teaching_context["allowed_source_handles"])
    padded_context: dict[str, object] | None = None
    base_projection: dict[str, object] | None = None
    for length in range(1200):
        trial = dict(teaching_context)
        trial["allowed_source_handles"] = [*ordinary, f"padding:{'x' * length}"]
        try:
            projection = project_teaching_provider_context(trial)
        except TeachingArtifactCandidateBuildError:
            break
        projected_candidates = projection.get("artifact_candidates")
        if isinstance(projected_candidates, list) and projected_candidates:
            padded_context = trial
            base_projection = projection
    assert padded_context is not None and base_projection is not None
    visible_trial = dict(padded_context)
    visible_trial["allowed_source_handles"] = [
        *visible_trial["allowed_source_handles"],
        source_candidates[0].handle,
    ]
    source_projection = project_teaching_provider_context(visible_trial)
    assert source_projection.get("artifact_candidates") != base_projection.get(
        "artifact_candidates"
    )

    grounding = TutorContextSource(
        source_id=f"teaching-artifact-evidence:{source_scope.run_id}:0",
        content={"source_handle": interaction_handle, "grounding": "required"},
        semantic_class="confirmed_fact_source",
    )
    context_input = replace(
        _source_budget_context_input(
            snapshot=snapshot,
            teaching_context=padded_context,
            teaching_session_id=source_scope.session_id,
        ),
        required_facts=(grounding,),
    )
    bounded = _bind_optional_source_inspection_candidates(
        snapshot=snapshot,
        context_input=context_input,
        teaching_context=padded_context,
        teaching_session_id=source_scope.session_id,
    )
    _assert_source_budget_sync(bounded, expected_handles=())
    assert bounded.required_facts == (grounding,)
    projected = bounded.teaching_session[0].content
    assert isinstance(projected, Mapping)
    assert projected.get("artifact_candidates") == base_projection.get(
        "artifact_candidates"
    )


def test_optional_source_is_pruned_when_only_base_context_fits_token_budget(
    source_scope: TutorSourceScope,
) -> None:
    snapshot, teaching_context = _source_budget_inputs(source_scope)
    candidates = parse_source_inspector_candidates(teaching_context)
    assert candidates
    context_input = _source_budget_context_input(
        snapshot=snapshot,
        teaching_context=teaching_context,
        teaching_session_id=source_scope.session_id,
    )
    builder = TutorContextBuilder()
    base_selection = builder.build(context_input, token_budget=100_000)
    base_budget = base_selection.checkpoint_metadata.consumed_tokens
    tight_snapshot = replace(
        snapshot,
        policy=replace(
            snapshot.policy,
            context_token_budget=base_budget,
            context_budget_policy=None,
        ),
    )
    builder.build(context_input, token_budget=base_budget)
    source_input = _source_inspection_context_input(
        context_input=context_input,
        teaching_context=teaching_context,
        teaching_session_id=source_scope.session_id,
        candidates=(candidates[0],),
        run_id=source_scope.run_id,
    )
    with pytest.raises(TutorContextError):
        builder.build(source_input, token_budget=base_budget)
    bounded = _bind_optional_source_inspection_candidates(
        snapshot=tight_snapshot,
        context_input=context_input,
        teaching_context=teaching_context,
        teaching_session_id=source_scope.session_id,
    )
    _assert_source_budget_sync(bounded, expected_handles=())


def test_no_selected_source_handle_creates_no_source_artifact(
    source_scope: TutorSourceScope,
) -> None:
    provider = _TutorSourceProvider(choose_source=False)
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.COMPLETED
    assert provider.visible_handles
    with connection() as conn:
        assert conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_artifacts WHERE turn_id=%s",
            (source_scope.run_id,),
        ).fetchone() == {"count": 0}
        receipt = conn.execute(
            "SELECT source_handles_json,learner_response_mode FROM tutor_teaching_action_receipts WHERE run_id=%s",
            (source_scope.run_id,),
        ).fetchone()
    assert receipt == {
        "source_handles_json": ["knowledge:python.variables"],
        "learner_response_mode": "none",
    }


def test_forged_or_stale_source_handle_is_rejected_without_commit(
    source_scope: TutorSourceScope,
) -> None:
    with connection() as conn:
        context = TeachingSessionRepository(conn, settings=_settings()).teaching_context(
            user_id=source_scope.user_id,
            run_id=source_scope.run_id,
        )
    assert context is not None
    candidates = context["source_inspection_candidates"]
    assert isinstance(candidates, list) and candidates
    valid = str(candidates[0]["handle"])
    forged = f"{valid[:-1]}{'0' if valid[-1] != '0' else '1'}"
    provider = _TutorSourceProvider(choose_source=True, override_handle=forged)
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    assert result.diagnostic_code == "teaching_source_handle_invalid"
    with connection() as conn:
        _assert_no_source_commit(conn, source_scope)


def test_cross_scope_source_handle_is_rejected(
    source_scope: TutorSourceScope,
) -> None:
    with connection() as conn:
        first_context = TeachingSessionRepository(
            conn,
            settings=_settings(),
        ).teaching_context(
            user_id=source_scope.user_id,
            run_id=source_scope.run_id,
        )
        assert first_context is not None
        first_candidates = first_context["source_inspection_candidates"]
        assert isinstance(first_candidates, list) and first_candidates
        foreign_handle = str(first_candidates[0]["handle"])
        other = _seed_scope(conn, settings=_settings())
        conn.commit()
    try:
        provider = _TutorSourceProvider(
            choose_source=True,
            override_handle=foreign_handle,
        )
        result = _dispatch(settings=_settings(), scope=other, provider=provider)
        assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
        assert result.diagnostic_code == "teaching_source_handle_invalid"
        with connection() as conn:
            _assert_no_source_commit(conn, other)
    finally:
        with connection() as conn:
            reset_user_data(conn, other.user_id)
            conn.commit()


def test_completed_progress_exposes_no_source_candidate_and_rejects_source_selection(
    source_scope: TutorSourceScope,
) -> None:
    with connection() as conn:
        conn.execute(
            """
            UPDATE tutor_track_node_progress
            SET status='completed',started_at=COALESCE(started_at,now()),completed_at=now()
            WHERE track_id=%s AND user_id=%s AND knowledge_key=%s
            """,
            (source_scope.track_id, source_scope.user_id, source_scope.knowledge_key),
        )
        context = TeachingSessionRepository(
            conn,
            settings=_settings(),
        ).teaching_context(
            user_id=source_scope.user_id,
            run_id=source_scope.run_id,
        )
        conn.commit()
    assert context is not None
    assert context["session"]["progress_status"] == "completed"
    assert context["source_inspection_candidates"] == []
    assert not any(
        str(handle).startswith("lesson-source:")
        for handle in context["allowed_source_handles"]
    )
    provider = _TutorSourceProvider(
        choose_source=True,
        override_handle=f"lesson-source:{'b' * 64}",
    )
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    assert result.diagnostic_code == "teaching_source_handle_invalid"
    with connection() as conn:
        _assert_no_source_commit(conn, source_scope)


def test_flag_off_exposes_no_candidate_and_cannot_create(
    source_scope: TutorSourceScope,
) -> None:
    settings = _settings(artifact_teaching_enabled=False)
    with connection() as conn:
        context = TeachingSessionRepository(conn, settings=settings).teaching_context(
            user_id=source_scope.user_id,
            run_id=source_scope.run_id,
        )
    assert context is not None
    assert context["source_inspection_candidates"] == []
    assert not any(
        str(handle).startswith("lesson-source:")
        for handle in context["allowed_source_handles"]
    )
    provider = _TutorSourceProvider(
        choose_source=True,
        override_handle=f"lesson-source:{'a' * 64}",
    )
    result = _dispatch(settings=settings, scope=source_scope, provider=provider)
    assert result.terminal_outcome is TutorTerminalOutcome.BLOCKED_POLICY
    assert result.diagnostic_code == "teaching_source_handle_invalid"
    with connection() as conn:
        _assert_no_source_commit(conn, source_scope)


def test_late_source_creation_failure_rolls_back_message_checkpoint_receipt_and_artifact(
    source_scope: TutorSourceScope,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _TutorSourceProvider(choose_source=True)

    def fail_create(
        _self: PostgresSourceInspectorMaterializer,
        _prepared,  # type: ignore[no-untyped-def]
        *,
        occurred_at: datetime,
    ):  # type: ignore[no-untyped-def]
        del occurred_at
        raise SourceInspectorCommitError("injected late source failure")

    monkeypatch.setattr(PostgresSourceInspectorMaterializer, "create", fail_create)
    result = _dispatch(settings=_settings(), scope=source_scope, provider=provider)
    assert result.terminal_outcome is not TutorTerminalOutcome.COMPLETED
    with connection() as conn:
        _assert_no_source_commit(conn, source_scope)


def test_legacy_source_inspector_remains_readable_and_manual_post_is_absent(
    source_scope: TutorSourceScope,
) -> None:
    with connection() as conn:
        legacy = PostgresLearningArtifactRepository(
            conn,
            conversation_events=PostgresTutorArtifactConversationEventSink(conn),
        ).create_artifact(
            TutorArtifactCreate(
                user_id=source_scope.user_id,
                conversation_id=source_scope.conversation_id,
                learning_track_id=source_scope.track_id,
                knowledge_key=source_scope.knowledge_key,
                teaching_session_id=source_scope.session_id,
                checkpoint_id=source_scope.checkpoint_id,
                track_version=1,
                progress_version=1,
                assignment_version=2,
                owner_kind=TutorArtifactOwnerKind.TEACHING_PRACTICE,
                owner_id=source_scope.checkpoint_id,
                owner_version=1,
                owner_context_version=1,
                artifact_kind=TutorArtifactKind.SOURCE_INSPECTOR,
                purpose=TutorArtifactPurpose.REMEDIATION,
                state=TutorArtifactState.ACTIVE,
                blocking=False,
                title="历史来源定位",
                instruction_markdown="兼容历史只读来源工件。",
                presentation=TutorArtifactSourceInspectorPresentationV1(
                    document_id=source_scope.document_id,
                    document_content_hash=source_scope.document_content_hash,
                    block_id=source_scope.block_id,
                    excerpt="变量绑定",
                    citation_ids=(source_scope.citation_id,),
                ),
                source_references=(
                    TutorArtifactSourceReferenceV1(
                        kind="lesson_document",
                        reference_id=source_scope.document_id,
                        reference_version=2,
                        content_hash=source_scope.document_content_hash,
                        label="历史课程文档",
                    ),
                ),
            ),
            creation_key=f"legacy-source-inspector:{uuid4()}",
            occurred_at=_NOW,
        ).artifact
        conn.commit()
    with connection() as conn:
        projected = PostgresLearningArtifactRepository(conn).read_artifact(
            user_id=source_scope.user_id,
            conversation_id=source_scope.conversation_id,
            artifact_id=legacy.id,
        )
    assert projected.purpose is TutorArtifactPurpose.REMEDIATION
    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert (
        "POST",
        "/api/learning-tracks/{track_id}/lesson-references/{conversation_id}/artifacts",
    ) not in routes


def _source_budget_inputs(
    scope: TutorSourceScope,
):  # type: ignore[no-untyped-def]
    with connection() as conn:
        snapshot = PostgresTutorRepository(conn, settings=_settings()).load_snapshot(
            user_id=scope.user_id,
            run_id=scope.run_id,
        )
        teaching_context = TeachingSessionRepository(
            conn,
            settings=_settings(),
        ).teaching_context(
            user_id=scope.user_id,
            run_id=scope.run_id,
        )
    assert snapshot is not None
    assert teaching_context is not None
    return snapshot, teaching_context


def _source_budget_context_input(
    *,
    snapshot,  # type: ignore[no-untyped-def]
    teaching_context: Mapping[str, object],
    teaching_session_id: str,
) -> TutorContextInput:
    return TutorContextInput(
        run_id=snapshot.run_id,
        conversation_id=snapshot.conversation_id,
        input_revision=snapshot.input_revision,
        current_input_required=False,
        teaching_session=(
            TutorContextSource(
                source_id=f"teaching-session:{teaching_session_id}",
                content=project_teaching_provider_context(teaching_context),
            ),
        ),
    )


def _assert_source_budget_sync(
    context_input: TutorContextInput,
    *,
    expected_handles: tuple[str, ...],
) -> None:
    assert len(context_input.teaching_session) == 1
    teaching_payload = context_input.teaching_session[0].content
    assert isinstance(teaching_payload, Mapping)
    allowed = teaching_payload.get("allowed_source_handles")
    assert isinstance(allowed, list)
    provider_handles = tuple(
        str(handle) for handle in allowed if str(handle).startswith("lesson-source:")
    )
    evidence_handles = tuple(
        str(source.content["handle"])
        for source in context_input.required_facts
        if source.source_id.startswith("teaching-source-candidate:")
        and isinstance(source.content, Mapping)
    )
    assert provider_handles == expected_handles
    assert evidence_handles == expected_handles


def _assert_no_source_commit(conn, scope: TutorSourceScope) -> None:  # type: ignore[no-untyped-def]
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_learning_artifacts WHERE turn_id=%s",
        (scope.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_teaching_action_receipts WHERE run_id=%s",
        (scope.run_id,),
    ).fetchone() == {"count": 0}
    assert conn.execute(
        "SELECT count(*)::int AS count FROM tutor_messages WHERE conversation_id=%s AND role='tutor'",
        (scope.conversation_id,),
    ).fetchone() == {"count": 0}
    session = conn.execute(
        "SELECT current_checkpoint_id::text AS checkpoint_id,version FROM tutor_teaching_sessions WHERE id=%s",
        (scope.session_id,),
    ).fetchone()
    assert session == {"checkpoint_id": scope.checkpoint_id, "version": 1}

