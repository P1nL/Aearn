from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.agents.harness.contracts import (
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorPolicySnapshot,
    TutorRunSnapshot,
    TutorTerminalOutcome,
)
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.services.learning.item_bank.repository import PublishedLearningItemCandidate
from app.services.learning.teaching_candidates import (
    MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS,
    TeachingArtifactCandidateBuildError,
    TeachingArtifactCandidateBuilder,
    bound_teaching_artifact_candidates,
    project_teaching_provider_context,
)
from app.services.learning.teaching_contracts import (
    TeachingArtifactCandidate,
    TeachingArtifactCandidateScope,
    TeachingArtifactCandidateSet,
    TeachingStepDecision,
)
from app.services.tutor.decision_gate import TeachingTutorDecisionGate
from app.services.tutor.decision_protocol import (
    TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
    TutorDecisionValidationError,
    TutorDecisionValidationIssue,
    build_tutor_replacement_message,
    parse_tutor_provider_items,
    tutor_provider_output_schema,
)
from app.services.tutor.skill_selection import (
    InMemoryTutorSkillSelectionStore,
    TutorSkillSelection,
)


_HANDLE = "li:" + "a" * 64
_OTHER_HANDLE = "li:" + "b" * 64


def _indexed_handle(index: int) -> str:
    return f"li:{index:064x}"


class _CandidateRepository:
    def __init__(self, candidates: tuple[PublishedLearningItemCandidate, ...]) -> None:
        self.candidates = candidates
        self.calls: list[dict[str, object]] = []

    def published_candidates(
        self,
        *,
        knowledge_key: str,
        available_capabilities: tuple[str, ...] | None = None,
        required_handles: tuple[str, ...] = (),
        excluded_purposes: tuple[str, ...] = (),
        limit: int = 8,
    ) -> tuple[PublishedLearningItemCandidate, ...]:
        self.calls.append({
            "knowledge_key": knowledge_key,
            "available_capabilities": available_capabilities,
            "required_handles": required_handles,
            "excluded_purposes": excluded_purposes,
            "limit": limit,
        })
        return self.candidates


class _ApproveGate:
    def validate(
        self,
        *,
        run: TutorRunSnapshot,
        decision: TutorDecision,
    ) -> TutorDecisionGateResult:
        del run, decision
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)


class _TeachingContextRepository:
    def __init__(self, context: dict[str, object]) -> None:
        self.context = context

    def teaching_context(self, *, user_id: str, run_id: str) -> dict[str, object]:
        del user_id, run_id
        return self.context


def _scope(**overrides: object) -> TeachingArtifactCandidateScope:
    values: dict[str, object] = {
        "teaching_session_id": "session-current",
        "checkpoint_id": "checkpoint-current",
        "track_id": "track-current",
        "knowledge_key": "python.variables",
        "session_version": 3,
        "track_version": 5,
        "progress_version": 7,
        "assignment_id": "assignment-current",
        "assignment_version": 2,
    }
    values.update(overrides)
    return TeachingArtifactCandidateScope.model_validate(values)


def _published_candidate(
    *,
    handle: str = _HANDLE,
    knowledge_key: str = "python.variables",
    kind: str = "code",
    purpose: str = "exercise",
    difficulty: str = "D2",
    allowed_interactions: tuple[str, ...] = ("edit", "run"),
) -> PublishedLearningItemCandidate:
    return PublishedLearningItemCandidate(
        handle=handle,
        item_key="private.item.key",
        version="1.0.0",
        kind=kind,
        purpose=purpose,
        knowledge_key=knowledge_key,
        language_id="python",
        difficulty=difficulty,
        title="PRIVATE_REFERENCE_ANSWER_MARKER",
        summary="private hidden tests and rubric must never enter provider context",
        required_capabilities=("python",),
        allowed_interactions=allowed_interactions,
    )


@pytest.mark.parametrize(
    ("learning_artifacts_enabled", "artifact_teaching_enabled"),
    [(False, False), (False, True), (True, False)],
)
def test_candidate_builder_feature_gates_before_repository_lookup(
    learning_artifacts_enabled: bool,
    artifact_teaching_enabled: bool,
) -> None:
    repository = _CandidateRepository((_published_candidate(),))
    result = TeachingArtifactCandidateBuilder(repository).build(
        scope=_scope(),
        available_capabilities=("python",),
        learning_artifacts_enabled=learning_artifacts_enabled,
        artifact_teaching_enabled=artifact_teaching_enabled,
    )

    assert result.feature_enabled is False
    assert result.candidates == ()
    assert repository.calls == []


def test_artifact_teaching_feature_flag_defaults_off_and_reads_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TUTOR_ARTIFACT_TEACHING_MODE_ENABLED", raising=False)
    assert Settings().tutor_artifact_teaching_mode_enabled is False
    monkeypatch.setenv("TUTOR_ARTIFACT_TEACHING_MODE_ENABLED", "true")
    assert Settings().tutor_artifact_teaching_mode_enabled is True


def test_candidate_builder_forwards_exact_capability_scope_and_projects_safe_handles_only() -> None:
    repository = _CandidateRepository((_published_candidate(),))
    result = TeachingArtifactCandidateBuilder(repository).build(
        scope=_scope(),
        available_capabilities=("python", "python.variables"),
        learning_artifacts_enabled=True,
        artifact_teaching_enabled=True,
    )

    assert repository.calls == [{
        "knowledge_key": "python.variables",
        "available_capabilities": ("python", "python.variables"),
        "required_handles": (),
        "excluded_purposes": ("remediation", "transfer_check"),
        "limit": 8,
    }]
    assert result.feature_enabled is True
    assert result.candidates[0].interaction_intents == ("edit_code", "run_code")
    projection = result.provider_projection()
    assert set(projection[0]) == {
        "handle",
        "kind",
        "purpose",
        "difficulty",
        "interaction_intents",
    }
    serialized = json.dumps(projection, ensure_ascii=False, sort_keys=True)
    assert _HANDLE in serialized
    assert "PRIVATE_REFERENCE_ANSWER_MARKER" not in serialized
    assert "hidden tests" not in serialized
    assert "private.item.key" not in serialized
    assert "required_capabilities" not in serialized


def test_provider_projection_bounds_multiple_candidates_without_truncating_required_context() -> None:
    candidates = tuple(
        TeachingArtifactCandidate(
            handle=_indexed_handle(index),
            kind="knowledge_check",
            purpose="knowledge_check",
            difficulty="D1",
            interaction_intents=("structured_answer",),
        )
        for index in range(1, 9)
    )
    candidate_set = _candidate_set(candidates=candidates)
    context = _rich_context(candidate_set)

    bounded = bound_teaching_artifact_candidates(
        context=context,
        candidates=candidate_set,
    )
    assert 2 <= len(bounded.candidates) < len(candidate_set.candidates)
    context["artifact_candidates"] = bounded.model_dump(mode="json")
    projection = project_teaching_provider_context(context)
    serialized = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    assert len(serialized) <= MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS
    advertised = projection["artifact_candidates"]
    assert isinstance(advertised, list)
    assert [item["handle"] for item in advertised] == [
        item.handle for item in bounded.candidates
    ]
    assert all(set(item) == {"handle", "kind", "intents"} for item in advertised)
    assert "safe_payload" not in serialized
    assert "suspended_focuses" not in projection
    assert "unresolved_questions" not in projection
    assert "recent_teaching_units" not in projection


def test_candidate_builder_rejects_cross_knowledge_or_malformed_published_candidate() -> None:
    cross_scope = _CandidateRepository((
        _published_candidate(knowledge_key="python.functions"),
    ))
    with pytest.raises(TeachingArtifactCandidateBuildError):
        TeachingArtifactCandidateBuilder(cross_scope).build(
            scope=_scope(),
            available_capabilities=("python",),
            learning_artifacts_enabled=True,
            artifact_teaching_enabled=True,
        )

    malformed = _CandidateRepository((
        _published_candidate(kind="sql", allowed_interactions=("review",)),
    ))
    with pytest.raises(TeachingArtifactCandidateBuildError):
        TeachingArtifactCandidateBuilder(malformed).build(
            scope=_scope(),
            available_capabilities=("python",),
            learning_artifacts_enabled=True,
            artifact_teaching_enabled=True,
        )


def test_candidate_contract_forbids_private_fields_and_kind_intent_mismatch() -> None:
    with pytest.raises(ValidationError):
        TeachingArtifactCandidate.model_validate({
            "handle": _HANDLE,
            "kind": "code",
            "purpose": "exercise",
            "difficulty": "D2",
            "interaction_intents": ["edit_code"],
            "private_rubric": "forbidden",
        })
    with pytest.raises(ValidationError):
        TeachingArtifactCandidate(
            handle=_HANDLE,
            kind="sql",
            purpose="sql_exploration",
            difficulty="D2",
            interaction_intents=("review_diff",),
        )


def _candidate_set(
    *,
    enabled: bool = True,
    scope: TeachingArtifactCandidateScope | None = None,
    candidates: tuple[TeachingArtifactCandidate, ...] | None = None,
) -> TeachingArtifactCandidateSet:
    return TeachingArtifactCandidateSet(
        scope=scope or _scope(),
        feature_enabled=enabled,
        candidates=(
            candidates
            if candidates is not None
            else (
                TeachingArtifactCandidate(
                    handle=_HANDLE,
                    kind="code",
                    purpose="exercise",
                    difficulty="D2",
                    interaction_intents=("edit_code", "run_code"),
                ),
            )
        ),
    )


def _context(candidates: TeachingArtifactCandidateSet) -> dict[str, object]:
    return {
        "objective": {"objective_id": "knowledge:python.variables"},
        "active_focus": {"focus_id": "knowledge:python.variables"},
        "suspended_focuses": [],
        "session": {
            "session_id": "session-current",
            "checkpoint_id": "checkpoint-current",
            "track_id": "track-current",
            "knowledge_key": "python.variables",
            "assignment_id": "assignment-current",
            "session_version": 3,
            "track_version": 5,
            "progress_version": 7,
            "assignment_version": 2,
            "mode": "guided",
            "progress_status": "in_progress",
        },
        "stimulus": {"kind": "teaching_control", "control_key": "open_session"},
        "candidate_focus_id": "stimulus:current",
        "recent_teaching_units": [],
        "allowed_source_handles": ["knowledge:python.variables"],
        "artifact_candidates": candidates.model_dump(mode="json"),
    }


def _rich_context(candidates: TeachingArtifactCandidateSet) -> dict[str, object]:
    context = _context(candidates)
    context.update(
        {
            "schema_version": "teaching_session_context_v2",
            "session": {
                "session_id": "11111111-1111-4111-8111-111111111111",
                "checkpoint_id": "22222222-2222-4222-8222-222222222222",
                "track_id": "33333333-3333-4333-8333-333333333333",
                "knowledge_key": "python.variables",
                "assignment_id": "44444444-4444-4444-8444-444444444444",
                "session_version": 3,
                "track_version": 5,
                "progress_version": 7,
                "assignment_version": 2,
                "mode": "guided",
                "progress_status": "in_progress",
            },
            "stimulus": {
                "stimulus_id": "55555555-5555-4555-8555-555555555555",
                "kind": "teaching_control",
                "control_key": "open_session",
                "safe_payload": {},
            },
            "candidate_focus_id": "stimulus:55555555-5555-4555-8555-555555555555",
            "covered_concepts": [],
            "pause_kind": "soft_pause",
            "recent_teaching_units": [],
            "allowed_source_handles": [
                "knowledge:python.variables",
                "stimulus:55555555-5555-4555-8555-555555555555",
            ],
        }
    )
    return context


def _run() -> TutorRunSnapshot:
    return TutorRunSnapshot(
        run_id="run-current",
        conversation_id="conversation-current",
        user_id="user-current",
        origin="interactive",
        input_revision=0,
        policy=TutorPolicySnapshot(deadline=datetime(2030, 1, 1, tzinfo=UTC)),
    )


def _decision(*, intent: str, handle: str = _HANDLE, interaction: bool = True) -> TutorDecision:
    return TutorDecision(
        public_message="在当前工件中完成这个有界任务。",
        terminal_outcome=TutorTerminalOutcome.COMPLETED,
        teaching_step=TeachingStepDecision(
            action="recommend_practice",
            objective_id="knowledge:python.variables",
            focus_id="knowledge:python.variables",
            source_handles=("knowledge:python.variables",),
            public_message="在当前工件中完成这个有界任务。",
            focus_resolution="stay",
            pause_kind="evidence_pause",
            teaching_moves=("worked_example", "micro_transfer"),
            learner_response_mode=("none" if not interaction else None),
            interaction=(
                {
                    "mode": "artifact",
                    "intent": intent,
                    "artifact_handle": handle,
                }
                if interaction
                else None
            ),
        ),
    )


def _gate(context: dict[str, object]) -> TeachingTutorDecisionGate:
    catalog = compile_published_skill_catalog()
    skill = catalog.resolve_skill("tutor.lesson-teaching", "1.2.1")
    assert skill is not None
    selections = InMemoryTutorSkillSelectionStore()
    selections.record(
        run_id="run-current",
        input_revision=0,
        selection=TutorSkillSelection(
            reference=skill.reference,
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )
    return TeachingTutorDecisionGate(
        base=_ApproveGate(),
        catalog=catalog,
        selection_store=selections,
        teaching=_TeachingContextRepository(context),
    )


def test_gate_accepts_only_exact_current_candidate_intent_pair() -> None:
    result = _gate(_context(_candidate_set())).validate(
        run=_run(),
        decision=_decision(intent="edit_code"),
    )

    assert result.status is TutorDecisionGateStatus.APPROVED


def test_gate_rejects_handle_not_advertised_by_the_bounded_provider_projection() -> None:
    candidates = tuple(
        TeachingArtifactCandidate(
            handle=_indexed_handle(index),
            kind="knowledge_check",
            purpose="knowledge_check",
            difficulty="D1",
            interaction_intents=("structured_answer",),
        )
        for index in range(1, 9)
    )
    candidate_set = _candidate_set(
        scope=_scope(
            teaching_session_id="11111111-1111-4111-8111-111111111111",
            checkpoint_id="22222222-2222-4222-8222-222222222222",
            track_id="33333333-3333-4333-8333-333333333333",
            assignment_id="44444444-4444-4444-8444-444444444444",
        ),
        candidates=candidates,
    )
    context = _rich_context(candidate_set)
    bounded = bound_teaching_artifact_candidates(
        context=context,
        candidates=candidate_set,
    )
    omitted = next(
        item.handle
        for item in candidate_set.candidates
        if item.handle not in {candidate.handle for candidate in bounded.candidates}
    )

    result = _gate(context).validate(
        run=_run(),
        decision=_decision(intent="structured_answer", handle=omitted),
    )

    assert result.status is TutorDecisionGateStatus.DENIED
    assert result.diagnostic_code == "teaching_artifact_candidate_required"


@pytest.mark.parametrize(
    ("candidate_set", "decision", "diagnostic_code"),
    [
        (
            _candidate_set(enabled=False, candidates=()),
            _decision(intent="edit_code"),
            "teaching_artifact_mode_disabled",
        ),
        (
            _candidate_set(candidates=()),
            _decision(intent="edit_code"),
            "teaching_artifact_candidate_required",
        ),
        (
            _candidate_set(),
            _decision(intent="edit_code", handle=_OTHER_HANDLE),
            "teaching_artifact_candidate_required",
        ),
        (
            _candidate_set(),
            _decision(intent="review_diff"),
            "teaching_artifact_intent_invalid",
        ),
        (
            _candidate_set(scope=_scope(track_version=6)),
            _decision(intent="edit_code"),
            "teaching_artifact_candidate_stale",
        ),
        (
            _candidate_set(),
            _decision(intent="edit_code", interaction=False),
            "teaching_step_v3_required",
        ),
    ],
)
def test_gate_rejects_impossible_artifact_instruction_before_public_authority(
    candidate_set: TeachingArtifactCandidateSet,
    decision: TutorDecision,
    diagnostic_code: str,
) -> None:
    result = _gate(_context(candidate_set)).validate(run=_run(), decision=decision)

    assert result.status is TutorDecisionGateStatus.DENIED
    assert result.diagnostic_code == diagnostic_code


def test_current_provider_schema_requires_v3_interaction_but_parser_keeps_v4_compatibility() -> None:
    payload = {
        "schema_version": TUTOR_PROVIDER_ITEMS_SCHEMA_VERSION,
        "message": {
            "type": "agent_message",
            "public_thinking_text": "只选择当前可执行交互。",
            "text": "回答这个小问题。",
            "conversation_title": None,
        },
        "action": {
            "type": "teaching_step",
            "action": "check_understanding",
            "objective_id": "knowledge:python.variables",
            "focus_id": "knowledge:python.variables",
            "source_handles": ["knowledge:python.variables"],
            "public_message": "回答这个小问题。",
            "focus_resolution": "stay",
            "pause_kind": "soft_pause",
            "escalation_hint": None,
            "teaching_moves": ["guided_derivation", "prediction"],
            "learner_response_mode": "composer",
        },
    }
    with pytest.raises(TutorDecisionValidationError):
        parse_tutor_provider_items(payload, run=_run())

    legacy = {**payload, "schema_version": "tutor_provider_items_v4"}
    decision = parse_tutor_provider_items(legacy, run=_run())
    assert decision.teaching_step is not None
    assert decision.teaching_step.interaction is None
    assert decision.teaching_step.learner_response_mode == "composer"

    teaching_schema = tutor_provider_output_schema()["$defs"]["TutorProviderTeachingStepItem"]
    assert teaching_schema["additionalProperties"] is False
    assert teaching_schema["required"][-1] == "interaction"
    assert "learner_response_mode" not in teaching_schema["properties"]
    assert len(teaching_schema["properties"]["interaction"]["anyOf"]) == 8

    repair = build_tutor_replacement_message(
        (TutorDecisionValidationIssue(path="action.interaction", category="missing"),),
        teaching_policy="current input remains authoritative",
    )
    assert "tutor.lesson-teaching@1.2.1" in repair
    assert "exact handle advertised" in repair
    assert "No candidate or disabled artifact mode" in repair
