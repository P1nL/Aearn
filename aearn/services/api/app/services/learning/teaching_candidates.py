"""Server-built, learner-safe Learning Item candidates for teaching decisions."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from app.services.learning.item_bank.repository import (
    PostgresLearningItemBankRepository,
    PublishedLearningItemCandidate,
)
from app.services.learning.teaching_contracts import (
    TeachingArtifactCandidate,
    TeachingArtifactCandidateScope,
    TeachingArtifactCandidateSet,
    TeachingInteractionIntent,
)


MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS = 1200
logger = logging.getLogger(__name__)


class TeachingArtifactCandidateBuildError(ValueError):
    """Published candidate authority could not be represented safely."""


class _PublishedCandidateRepository(Protocol):
    def published_candidates(
        self,
        *,
        knowledge_key: str,
        available_capabilities: Sequence[str] | None = None,
        required_handles: Sequence[str] = (),
        excluded_purposes: Sequence[str] = (),
        limit: int = 8,
    ) -> tuple[PublishedLearningItemCandidate, ...]: ...


class TeachingArtifactCandidateBuilder:
    """Project current published items into a bounded handle-and-intent allowlist."""

    def __init__(self, repository: _PublishedCandidateRepository) -> None:
        self._repository = repository

    @classmethod
    def postgres(cls, repository: PostgresLearningItemBankRepository) -> "TeachingArtifactCandidateBuilder":
        return cls(repository)

    def build(
        self,
        *,
        scope: TeachingArtifactCandidateScope,
        available_capabilities: Sequence[str],
        learning_artifacts_enabled: bool,
        artifact_teaching_enabled: bool,
        required_handles: Sequence[str] = (),
        excluded_purposes: Sequence[str] = ("remediation", "transfer_check"),
        catalog_knowledge_key: str | None = None,
    ) -> TeachingArtifactCandidateSet:
        feature_enabled = learning_artifacts_enabled and artifact_teaching_enabled
        if not feature_enabled:
            return TeachingArtifactCandidateSet(
                scope=scope,
                feature_enabled=False,
            )

        content_knowledge_key = catalog_knowledge_key or scope.knowledge_key
        try:
            published = self._repository.published_candidates(
                knowledge_key=content_knowledge_key,
                available_capabilities=tuple(available_capabilities),
                required_handles=tuple(required_handles),
                excluded_purposes=tuple(excluded_purposes),
                limit=8,
            )
            candidates = tuple(
                _project_candidate(item=item, knowledge_key=content_knowledge_key)
                for item in published
            )
            return TeachingArtifactCandidateSet(
                scope=scope,
                feature_enabled=True,
                candidates=candidates,
            )
        except (TypeError, ValueError) as exc:
            raise TeachingArtifactCandidateBuildError(
                "published teaching artifact candidates are invalid"
            ) from exc


def bound_teaching_artifact_candidates(
    *,
    context: Mapping[str, object],
    candidates: TeachingArtifactCandidateSet,
    max_characters: int = MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS,
    minimum_candidates: int = 0,
) -> TeachingArtifactCandidateSet:
    """Select the exact candidate subset that can be advertised without truncation.

    The returned set remains the decision-gate authority for this context build. This
    prevents a handle omitted from the required provider projection from being accepted
    later merely because it existed elsewhere in the published item pool.
    """

    if max_characters <= 0:
        raise ValueError("teaching provider context bound must be positive")
    if minimum_candidates < 0 or minimum_candidates > len(candidates.candidates):
        raise ValueError("minimum teaching candidate count is invalid")
    if not candidates.feature_enabled or not candidates.candidates:
        if minimum_candidates:
            raise ValueError("required teaching artifact candidate is unavailable")
        return candidates

    base = _provider_teaching_context_base(context)
    selected: list[TeachingArtifactCandidate] = []
    for candidate in candidates.candidates:
        projected = _compact_recent_units(
            {**base, "artifact_candidates": _provider_candidate_projections((*selected, candidate))},
            max_characters=max_characters,
        )
        if _serialized_characters(projected) <= max_characters:
            selected.append(candidate)
    if len(selected) < minimum_candidates:
        raise ValueError("required teaching artifact candidate is unrepresentable")
    return TeachingArtifactCandidateSet(
        scope=candidates.scope,
        feature_enabled=candidates.feature_enabled,
        candidates=tuple(selected),
    )


def project_teaching_provider_context(
    context: Mapping[str, object],
    *,
    max_characters: int = MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS,
) -> dict[str, object]:
    """Build the compact required ``TEACHING_SESSION`` provider projection."""

    try:
        candidates = TeachingArtifactCandidateSet.model_validate(
            context.get("artifact_candidates")
        )
        bounded_candidates = bound_teaching_artifact_candidates(
            context=context,
            candidates=candidates,
            max_characters=max_characters,
            minimum_candidates=_minimum_required_candidate_count(context),
        )
    except (TypeError, ValueError) as exc:
        raise TeachingArtifactCandidateBuildError(
            "teaching artifact candidate context is invalid"
        ) from exc

    bounded = _provider_teaching_context_base(context)
    projections = _provider_candidate_projections(bounded_candidates.candidates)
    if projections:
        bounded["artifact_candidates"] = projections
    bounded = _compact_recent_units(bounded, max_characters=max_characters)
    if _serialized_characters(bounded) > max_characters:
        raise TeachingArtifactCandidateBuildError("required teaching context is unrepresentable")
    return bounded


def _minimum_required_candidate_count(context: Mapping[str, object]) -> int:
    stimulus = context.get("stimulus")
    if not isinstance(stimulus, Mapping):
        return 0
    safe_payload = stimulus.get("safe_payload")
    if not isinstance(safe_payload, Mapping):
        return 0
    if safe_payload.get("reason_code") in {"knowledge_check_evaluation", "model_review_evaluation"}:
        candidates = context.get("artifact_candidates")
        if isinstance(candidates, Mapping):
            projected = candidates.get("candidates")
            if isinstance(projected, list) and projected:
                return 1
    return 0


def _provider_teaching_context_base(
    context: Mapping[str, object],
) -> dict[str, object]:
    session = context.get("session")
    objective = context.get("objective")
    active_focus = context.get("active_focus")
    suspended = context.get("suspended_focuses")
    questions = context.get("unresolved_questions")
    stimulus = context.get("stimulus")
    safe_payload = (
        stimulus.get("safe_payload")
        if isinstance(stimulus, Mapping)
        and isinstance(stimulus.get("safe_payload"), Mapping)
        else None
    )
    artifact_evaluation = (
        isinstance(safe_payload, Mapping)
        and safe_payload.get("reason_code") in {"knowledge_check_evaluation", "model_review_evaluation"}
    )
    bounded: dict[str, object] = {
        "schema_version": context.get("schema_version"),
        "session": (
            {
                key: session.get(key)
                for key in (
                    "session_id",
                    "session_version",
                    "checkpoint_id",
                    "mode",
                    "track_version",
                    "progress_version",
                    "progress_status",
                    "assignment_version",
                )
            }
            if isinstance(session, Mapping)
            else None
        ),
        "stimulus": (
            {
                str(key): value
                for key, value in stimulus.items()
                if value not in (None, (), [], {})
            }
            if isinstance(stimulus, Mapping)
            else stimulus
        ),
        "objective": (
            {"objective_id": objective.get("objective_id")}
            if isinstance(objective, Mapping)
            else None
        ),
        "active_focus": (
            {
                key: active_focus.get(key)
                for key in ("focus_id", "focus_kind")
            }
            if isinstance(active_focus, Mapping)
            else None
        ),
        "pause_kind": context.get("pause_kind"),
        "candidate_focus_id": context.get("candidate_focus_id"),
        "allowed_source_handles": context.get("allowed_source_handles"),
    }
    suspended_projection = (
        [
            {key: item.get(key) for key in ("focus_id", "focus_kind")}
            for item in suspended
            if isinstance(item, Mapping)
        ]
        if isinstance(suspended, list)
        else []
    )
    if suspended_projection:
        bounded["suspended_focuses"] = suspended_projection
    question_projection = (
        [
            {key: item.get(key) for key in ("question_id", "state")}
            for item in questions
            if isinstance(item, Mapping)
        ]
        if isinstance(questions, list)
        else []
    )
    if question_projection:
        bounded["unresolved_questions"] = question_projection
    covered = context.get("covered_concepts")
    if isinstance(covered, list) and covered:
        bounded["covered_concepts"] = covered
    recent_units = context.get("recent_teaching_units")
    if isinstance(recent_units, list) and recent_units and not artifact_evaluation:
        bounded["recent_teaching_units"] = recent_units
    return bounded


def _provider_candidate_projections(
    candidates: Sequence[TeachingArtifactCandidate],
) -> list[dict[str, object]]:
    return [
        {
            "handle": candidate.handle,
            "kind": candidate.kind,
            "intents": [item.value for item in candidate.interaction_intents],
        }
        for candidate in candidates
    ]


def _compact_recent_units(value: Mapping[str, object], *, max_characters: int) -> dict[str, object]:
    """Evict oldest optional units, never current authority or exact candidates."""
    result = dict(value)
    raw = result.get("recent_teaching_units")
    recent = list(raw) if isinstance(raw, (tuple, list)) else []
    before = _serialized_characters(result)
    removed = 0
    while recent and _serialized_characters(result) > max_characters:
        recent.pop(0)
        removed += 1
        if recent:
            result["recent_teaching_units"] = recent
        else:
            result.pop("recent_teaching_units", None)
    if removed:
        logger.debug("teaching_context_compacted before_chars=%d after_chars=%d removed_units=%d limit_chars=%d utf8_bytes=%d",
                     before, _serialized_characters(result), removed, max_characters,
                     len(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")))
    return result


def _serialized_characters(value: object) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _project_candidate(
    *,
    item: PublishedLearningItemCandidate,
    knowledge_key: str,
) -> TeachingArtifactCandidate:
    if item.knowledge_key != knowledge_key:
        raise ValueError("published candidate knowledge scope is stale")
    interactions = frozenset(item.allowed_interactions)
    expected_interactions = {
        "code": frozenset({"edit", "run"}),
        "sql": frozenset({"query", "run"}),
        "demo": frozenset({"observe"}),
        "knowledge_check": frozenset({"respond"}),
        "model_review": frozenset({"review"}),
    }.get(item.kind)
    if expected_interactions is None or interactions != expected_interactions:
        raise ValueError("published candidate interactions are invalid")
    intents = {
        "code": (
            TeachingInteractionIntent.EDIT_CODE,
            TeachingInteractionIntent.RUN_CODE,
        ),
        "sql": (TeachingInteractionIntent.EXECUTE_QUERY,),
        "demo": (TeachingInteractionIntent.INTERACT_WITH_DEMO,),
        "knowledge_check": (TeachingInteractionIntent.STRUCTURED_ANSWER,),
        "model_review": (TeachingInteractionIntent.REVIEW_DIFF,),
    }[item.kind]
    return TeachingArtifactCandidate.model_validate({
        "handle": item.handle,
        "kind": item.kind,
        "purpose": item.purpose,
        "difficulty": item.difficulty,
        "interaction_intents": intents,
    })


__all__ = (
    "MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS",
    "TeachingArtifactCandidateBuildError",
    "TeachingArtifactCandidateBuilder",
    "bound_teaching_artifact_candidates",
    "project_teaching_provider_context",
)
