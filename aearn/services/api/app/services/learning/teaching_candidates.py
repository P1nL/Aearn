"""Server-built, learner-safe Learning Item candidates for teaching decisions."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from psycopg import Connection

from app.core.config import Settings
from app.services.learning.item_supply.private_enhancement_contracts import PrivateTeachingDeliveryContext

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

if TYPE_CHECKING:
    from app.services.learning.teaching_artifacts import NativeTeachingPracticeDeliveryContext


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


class NativeTeachingArtifactCandidateBuilder(TeachingArtifactCandidateBuilder):
    """Explicit per-run native advertisement, not public native catalog browsing."""

    def __init__(self, repository: _PublishedCandidateRepository, *,
                 conn: Connection[dict[str, Any]], settings: Settings) -> None:
        super().__init__(repository)
        self.conn, self.settings = conn, settings
        self._runs: dict[str, NativeTeachingPracticeDeliveryContext | PrivateTeachingDeliveryContext] = {}

    def register_delivery(self, *, run_id: str, context: NativeTeachingPracticeDeliveryContext | PrivateTeachingDeliveryContext) -> None:
        from app.services.learning.teaching_artifacts import PostgresTeachingArtifactMaterializer

        if type(run_id) is not str or str(UUID(run_id)) != run_id:
            raise TeachingArtifactCandidateBuildError("native candidate canonical run is required")
        materializer = PostgresTeachingArtifactMaterializer(self.conn, settings=self.settings)
        if isinstance(context, PrivateTeachingDeliveryContext):
            materializer._private_context(context)
            if str(context.run_id) != run_id:
                raise TeachingArtifactCandidateBuildError('private candidate exact run required')
        else:
            materializer._native_context(context)
        if run_id in self._runs and self._runs[run_id] is not context:
            raise TeachingArtifactCandidateBuildError("native candidate run is already bound")
        self._runs[run_id] = context

    def for_run(self, run_id: str) -> TeachingArtifactCandidateBuilder:
        context = self._runs.get(run_id)
        if context is None:
            return TeachingArtifactCandidateBuilder(self._repository)
        return _NativeRunCandidateBuilder(self._repository, parent=self, run_id=run_id, context=context)


class _NativeRunCandidateBuilder(TeachingArtifactCandidateBuilder):
    def __init__(self, repository: _PublishedCandidateRepository, *,
                 parent: NativeTeachingArtifactCandidateBuilder, run_id: str,
                 context: NativeTeachingPracticeDeliveryContext | PrivateTeachingDeliveryContext) -> None:
        super().__init__(repository)
        self.parent, self.run_id, self.context = parent, run_id, context

    def build(self, *, scope: TeachingArtifactCandidateScope,
              available_capabilities: Sequence[str], learning_artifacts_enabled: bool,
              artifact_teaching_enabled: bool, required_handles: Sequence[str] = (),
              excluded_purposes: Sequence[str] = ("remediation", "transfer_check"),
              catalog_knowledge_key: str | None = None) -> TeachingArtifactCandidateSet:
        if not learning_artifacts_enabled or not artifact_teaching_enabled:
            return TeachingArtifactCandidateSet(scope=scope, feature_enabled=False)
        from app.services.learning.item_supply.native_consumer_bridge import _mapped

        context = self.context
        owner: Any = context.exposure_owner
        try:
            self.parent.register_delivery(run_id=self.run_id, context=context)
            owner._lock()
            if isinstance(context, PrivateTeachingDeliveryContext):
                mapping = owner.type_owner.resolve_mapping(context.mapping_receipt_id)
                content = owner.type_owner.query.resolve_content(context.selected_version_id)
                owner.type_owner._candidate(content,mapping)
                if (content.quality.ref.pack_task_id != context.pack_task_id
                        or (mapping.frozen_node.catalog_knowledge_key or mapping.frozen_node.knowledge_key) != (catalog_knowledge_key or scope.knowledge_key)):
                    raise TeachingArtifactCandidateBuildError('private exact task/catalog bridge required')
            else:
                mapping, content, _candidate = _mapped(owner.type_owner, context.mapping_receipt_id,
                    context.selected_version_id, catalog_knowledge_key or scope.knowledge_key)
            node = mapping.frozen_node
            scope_query = (
                "SELECT s.* FROM tutor_run_teaching_scopes s JOIN tutor_teaching_sessions t ON t.id=s.teaching_session_id "
                "AND t.user_id=s.user_id AND t.conversation_id=s.conversation_id "
                "WHERE s.run_id=%s AND s.user_id=%s AND s.track_id=%s AND s.knowledge_key=%s "
                "AND s.teaching_session_id=%s AND s.checkpoint_id=%s AND s.session_version=%s "
                "AND s.track_version=%s AND s.progress_version=%s AND s.lesson_assignment_id=%s "
                "AND s.assignment_version=%s AND s.active_plan_revision_id=%s "
                "AND t.current_checkpoint_id=s.checkpoint_id AND t.version=s.session_version AND t.status IN ('active','paused')")
            scope_parameters = (self.run_id, node.user_id, scope.track_id, scope.knowledge_key, scope.teaching_session_id,
                 scope.checkpoint_id, scope.session_version, scope.track_version, scope.progress_version,
                 scope.assignment_id, scope.assignment_version, node.revision_id)
            row = self.parent.conn.execute(scope_query, scope_parameters).fetchone()
            if row is None or str(node.track_id) != scope.track_id or node.knowledge_key != scope.knowledge_key:
                raise TeachingArtifactCandidateBuildError("native candidate exact original run scope is required")
            if isinstance(context, PrivateTeachingDeliveryContext):
                reserved = self.parent.conn.execute('SELECT payload_json FROM tutor_item_supply_private_native_assessment_reservations WHERE id=%s AND user_id=%s AND epoch=%s AND pack_task_id=%s',
                    (context.reservation_id,owner.user_id,owner.epoch,context.pack_task_id)).fetchone()
                if reserved is None or reserved['payload_json']['mapping_id'] != str(context.mapping_receipt_id):
                    raise TeachingArtifactCandidateBuildError('private exact assessment reservation required')
                refs = reserved['payload_json']
                cap, observation = owner.resolve_reserved_pack(context.reservation_id)
            else:
                reserved = self.parent.conn.execute('SELECT request_json FROM tutor_item_supply_type_exposure_reservations WHERE user_id=%s AND epoch=%s AND operation_key=%s',
                    (owner.user_id,owner.epoch,context.reservation_key)).fetchone()
                if reserved is None or reserved['request_json']['mapping_receipt_id'] != str(context.mapping_receipt_id):
                    raise TeachingArtifactCandidateBuildError('native exact reservation required')
                refs = reserved['request_json']
                observation = owner.snapshot_v2()
                if observation.snapshot_id is None:
                    raise TeachingArtifactCandidateBuildError('native complete exposure required')
                cap = owner.type_owner.resolve_pack(mapping_receipt_id=context.mapping_receipt_id,
                    candidate_version_ids=tuple(UUID(v) for v in refs['candidate_version_ids']),
                    exposure_snapshot_id=observation.snapshot_id,relation_receipt_ids=tuple(UUID(v) for v in refs['relation_receipt_ids']))
            pack = owner.type_owner.require_pack(cap)
            role = "remediation" if type(context) is PrivateTeachingDeliveryContext and context.purpose == "remediation" else "practice"
            selected = next((c for c in pack.selected if c.member.slot == role
                             and c.version_id == context.selected_version_id), None)
            if selected is None or selected.type_evidence.content != content.content or pack.request != mapping.pack_request:
                raise TeachingArtifactCandidateBuildError("native candidate current selected practice is required")
            public = content.quality.source.public if type(context) is PrivateTeachingDeliveryContext else content.source.public
            purpose = context.purpose if type(context) is PrivateTeachingDeliveryContext else public.purpose.value
            successor = type(context) is PrivateTeachingDeliveryContext and context.parent_artifact_id is not None
            if type(context) is PrivateTeachingDeliveryContext and successor:
                checked=self.parent.conn.execute('SELECT item_supply_internal.private_native_successor_delivery_current(%s,%s,%s,%s) AS ok',
                    (context.parent_artifact_id,cap.eligibility_id,context.selected_version_id,purpose)).fetchone()
                if checked is None or checked['ok'] is not True:
                    raise TeachingArtifactCandidateBuildError('private genuine ordinary successor current parent required')
            if (purpose in excluded_purposes and not successor) or required_handles and tuple(required_handles) != (content.content.item_handle,):
                raise TeachingArtifactCandidateBuildError("native candidate purpose or successor scope is mismatched")
            if not set(node.required_capabilities).issubset(available_capabilities):
                raise TeachingArtifactCandidateBuildError("native candidate capabilities are unavailable")
            projected = TeachingArtifactCandidate(handle=content.content.item_handle, kind="knowledge_check",
                purpose=purpose, difficulty=public.difficulty.value,
                interaction_intents=(TeachingInteractionIntent.STRUCTURED_ANSWER,))
            owner.type_owner.require_pack(cap)
            if self.parent.conn.execute(scope_query, scope_parameters).fetchone() is None:
                raise TeachingArtifactCandidateBuildError("native candidate original run scope changed after wait")
            self.parent.register_delivery(run_id=self.run_id, context=context)
            return TeachingArtifactCandidateSet(scope=scope, feature_enabled=True, candidates=(projected,))
        except (TypeError, ValueError, KeyError) as exc:
            raise TeachingArtifactCandidateBuildError("native candidate current authority is unavailable") from exc


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
    "NativeTeachingArtifactCandidateBuilder",
    "MAX_TEACHING_PROVIDER_CONTEXT_CHARACTERS",
    "TeachingArtifactCandidateBuildError",
    "TeachingArtifactCandidateBuilder",
    "bound_teaching_artifact_candidates",
    "project_teaching_provider_context",
)
