"""Explicit server-only D composition; ordinary interactive factory remains unchanged.

No API route or environment variable can supply a material scope policy here. The
caller must inject an approved immutable-node requirement resolver and the
same-connection C-backed EvidenceSelection factory.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from psycopg import Connection

from app.core.config import Settings
from app.services.grounding.evidence_binding_v2 import EvidenceSelection
from app.services.grounding.material_binding_repository import MaterialBindingStale
from app.services.grounding.material_contracts_v2 import (
    CurrentMaterialAuthorizationReceipt, DraftScope, EvidenceBindingV2, MaterialSelectionResult, NodeMaterialRequirement,
)
from app.services.learning.material_selection import (
    MaterialPlanningAuthority, PostgresMaterialPlanningConsumer, RequirementResolver,
)
from app.services.learning.material_semantics import MaterialSemanticReviewer, PrimaryMaterialSemanticReviewer
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.services.tutor.ports import TutorProviderGateway
from app.agents.harness.contracts import TutorProviderResult, TutorRunSnapshot, TutorContextSelection
from app.services.tutor.public_thinking_stream import TutorPublicThinkingSink
from app.services.tutor.interactive import (
    ProviderFactory, TutorInteractiveRunDispatcher,
)


class _BoundMaterialAuthority(MaterialPlanningAuthority):
    def __init__(self, conn: Connection[Any], evidence: EvidenceSelection) -> None:
        self._conn = conn
        self._evidence = evidence

    def resolve_evidence(self, draft: DraftScope,
                         requirements: tuple[NodeMaterialRequirement, ...]) -> MaterialSelectionResult:
        return self._evidence.resolve_evidence(draft, requirements)

    def authorize_selection(self, conn: Connection[Any],
                            selection: MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt:
        return self._evidence.authorize_selection(conn, selection)

    def authorize_binding(self, conn: Connection[Any], binding: EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt:
        if conn is not self._conn:
            raise MaterialBindingStale("wrong current authority connection")
        # The C-backed adapter re-reads the exact persisted selection; do not
        # substitute an in-memory selection supplied by the caller.
        return self._evidence.authorize_binding(conn, binding)


class _ReviewedDeterministicProvider:
    """Test transport fallback: enforce review, but only primary owns repair loop."""

    def __init__(self, delegate: TutorProviderGateway,
                 consumer: PostgresMaterialPlanningConsumer) -> None:
        self._delegate = delegate
        self._consumer = consumer

    def decide(self, *, run: TutorRunSnapshot, context: TutorContextSelection,
               thinking_sink: TutorPublicThinkingSink | None = None) -> TutorProviderResult:
        result = self._delegate.decide(run=run, context=context, thinking_sink=thinking_sink)
        if result.decision is None:
            return result
        issue = self._consumer.review_decision(run, result.decision, 1)
        if issue is not None:
            return TutorProviderResult.model_unavailable(
                safe_code="TUTOR_MATERIAL_SEMANTIC_REVIEW_DENIED", attempts=result.attempts)
        return result

def build_internal_material_planning_dispatcher(
    settings: Settings, *, server_opt_in: bool = False,
    requirements: RequirementResolver | None = None,
    evidence_factory: Callable[[Connection[Any]], EvidenceSelection] | None = None,
    provider_factory: ProviderFactory | None = None,
    semantic_reviewer: MaterialSemanticReviewer | None = None,
) -> TutorInteractiveRunDispatcher:
    """Only explicit dual-gate internal construction injects D into the real loop.

    The factory must build C governance with this exact connection and its own
    current-policy actor context. Missing injections do not query D tables.
    """
    if not (server_opt_in and settings.rag_evidence_consumer_enabled
            and requirements is not None and evidence_factory is not None):
        return TutorInteractiveRunDispatcher(settings=settings, provider_factory=provider_factory)

    reviewer = semantic_reviewer or PrimaryMaterialSemanticReviewer(settings)

    def make_consumer(conn: Connection[dict[str, object]]) -> PostgresMaterialPlanningConsumer:
        evidence = evidence_factory(conn)
        if (evidence.conn is not conn or not evidence.enabled
                or evidence.selections is None or evidence.selections.conn is not conn):
            raise MaterialBindingStale("D evidence authority is not bound to current connection")
        return PostgresMaterialPlanningConsumer(
            conn, authority=_BoundMaterialAuthority(conn, evidence), requirements=requirements,
            semantic_reviewer=reviewer,
        )

    def bind_provider(provider: TutorProviderGateway,
                      consumer: PostgresMaterialPlanningConsumer) -> TutorProviderGateway:
        if isinstance(provider, PrimaryTutorProviderGateway):
            return provider.with_decision_validator(
                lambda run, _context, decision, attempt: consumer.review_decision(
                    run, decision, attempt))
        return _ReviewedDeterministicProvider(provider, consumer)

    return TutorInteractiveRunDispatcher(
        settings=settings, provider_factory=provider_factory,
        material_consumer_factory=make_consumer, material_provider_binder=bind_provider,
    )
