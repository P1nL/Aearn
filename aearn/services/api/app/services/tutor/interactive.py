"""Controlled interactive Tutor run composition for the public target adapter.

This module is intentionally narrow: it starts a durable, already-accepted
interactive run after the input transaction commits. It never changes legacy
Graph traffic and its default policy denies Skills, capabilities, and effects.
Only a configured primary provider can produce a bounded public response.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from psycopg import Connection

from app.agents.harness.catalog_context import CatalogContextLoader
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import TutorContextInput, TutorContextSource, TutorRunResult, TutorRunSnapshot
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.db.connection import connect
from app.services.tutor.capability_policy import DefaultDenyCapabilityPolicyResolver
from app.services.tutor.decision_gate import CatalogTutorDecisionGate
from app.services.tutor.learner_state import TutorLearnerStateRepository
from app.services.tutor.persistence import (
    PostgresTutorLifecycle,
    PostgresTutorRepository,
    PostgresTutorSkillSelectionStore,
)
from app.services.tutor.ports import (
    Clock,
    DefaultDenyCapabilityGateway,
    DefaultDenyEffectCommitter,
    NoopTutorCompactionPublisher,
    TutorProviderGateway,
)
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.services.tutor.run_loop import TutorHarnessService, TutorRunLoop


class TutorRunDispatcher(Protocol):
    """Post-commit interactive dispatch boundary used by the public routes."""

    def dispatch(self, *, user_id: str, run_id: str) -> TutorRunResult: ...


class UtcClock:
    """Small production clock adapter; tests inject a deterministic provider instead."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class PostgresTutorContextLoader:
    """Build only bounded, user-scoped context for one persisted Tutor run."""

    def __init__(
        self,
        *,
        conn: Connection[dict[str, object]],
        learner_state: TutorLearnerStateRepository,
        proactive_candidate_kind: str | None = None,
    ) -> None:
        self._conn = conn
        self._learner_state = learner_state
        self._proactive_candidate_kind = proactive_candidate_kind

    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
        recent_messages: tuple[TutorContextSource, ...] = ()
        if self._proactive_candidate_kind is None:
            rows = self._conn.execute(
                """
                SELECT id::text AS id, role, content
                FROM tutor_messages
                WHERE conversation_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 8
                """,
                (snapshot.conversation_id,),
            ).fetchall()
            recent_messages = tuple(
                TutorContextSource(
                    source_id=f"message:{row['id']}",
                    content={
                        "role": "assistant" if str(row.get("role")) == "tutor" else "user",
                        "content": str(row.get("content") or ""),
                    },
                )
                for row in reversed(rows)
            )

        active_plan = self._learner_state.active_plan_for_user(user_id=snapshot.user_id)
        active_plan_sources = (
            (
                TutorContextSource(
                    source_id=f"plan:{active_plan.revision_id}",
                    content={
                        "title": active_plan.title,
                        "outline": list(active_plan.outline),
                        "learner_reason": active_plan.learner_reason,
                        "evidence": list(active_plan.evidence_ids),
                    },
                ),
            )
            if active_plan is not None
            else ()
        )

        memory_sources = tuple(
            TutorContextSource(
                source_id=f"memory:{item.entry_id}",
                content={
                    "kind": item.memory_kind,
                    "category": item.category,
                    "statement": item.statement,
                    "confidence": item.confidence,
                    "provenance": item.provenance_kind,
                    "evidence": list(item.evidence_ids),
                },
            )
            for item in self._learner_state.list_memory_entries(
                user_id=snapshot.user_id,
                include_inactive=False,
                limit=4,
            )
        )
        activity_sources = tuple(
            TutorContextSource(
                source_id=f"activity:{item.activity_id}",
                content={
                    "category": item.category,
                    "reason": item.learner_reason,
                    "evidence": list(item.evidence_ids),
                },
            )
            for item in self._learner_state.list_activity_records(user_id=snapshot.user_id, limit=4)
        )
        return TutorContextInput(
            run_id=snapshot.run_id,
            conversation_id=snapshot.conversation_id,
            input_revision=input_revision,
            system_descriptors=(
                TutorContextSource(
                    source_id=(
                        "tutor:interactive:policy"
                        if self._proactive_candidate_kind is None
                        else "tutor:proactive:policy"
                    ),
                    content=(
                        {
                            "surface": "interactive_tutor",
                            "action_policy": "default_deny",
                            "input_revision": input_revision,
                        }
                        if self._proactive_candidate_kind is None
                        else {
                            "surface": "proactive_tutor",
                            "candidate_kind": self._proactive_candidate_kind,
                            "delivery_scope": "activity_inbox_only",
                            "learner_chat": "forbidden",
                            "runner_execution": "forbidden",
                            "input_revision": input_revision,
                        }
                    ),
                ),
            ),
            active_plan=active_plan_sources,
            recent_messages=recent_messages,
            learner_memory=memory_sources,
            activity_facts=activity_sources,
        )


ProviderFactory = Callable[[Settings], TutorProviderGateway]


class TutorInteractiveRunDispatcher:
    """Execute one persisted interactive run through the finite Harness loop.

    The dispatcher is used only after the public input route's database
    transaction commits. Its production composition is policy-default-deny:
    provider output may produce a public response, while all Skills,
    capabilities, and effects remain behind the existing catalog/policy gates.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        provider_factory: ProviderFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._settings = settings
        self._provider_factory = provider_factory or _primary_provider
        self._clock = clock or UtcClock()

    def dispatch(self, *, user_id: str, run_id: str) -> TutorRunResult:
        with connect() as conn:
            # The provider call must never inherit an implicit PostgreSQL transaction
            # or hold a foreground-run lock. Repository lifecycle methods open their
            # own short atomic transactions around each durable boundary.
            conn.autocommit = True
            repository = PostgresTutorRepository(conn)
            learner_state = TutorLearnerStateRepository(conn)
            catalog = compile_published_skill_catalog()
            policy_resolver = DefaultDenyCapabilityPolicyResolver()
            selection_store = PostgresTutorSkillSelectionStore(repository=repository, user_id=user_id)
            base_loader = PostgresTutorContextLoader(conn=conn, learner_state=learner_state)
            loop = TutorRunLoop(
                store=repository.as_run_store(user_id=user_id),
                context_loader=CatalogContextLoader(
                    base_loader=base_loader,
                    catalog=catalog,
                    policy_resolver=policy_resolver,
                    selection_store=selection_store,
                ),
                context_builder=TutorContextBuilder(),
                provider=self._provider_factory(self._settings),
                capability_gateway=DefaultDenyCapabilityGateway(),
                effect_committer=DefaultDenyEffectCommitter(),
                clock=self._clock,
                compaction_publisher=NoopTutorCompactionPublisher(),
                decision_gate=CatalogTutorDecisionGate(
                    catalog=catalog,
                    policy_resolver=policy_resolver,
                    selection_store=selection_store,
                ),
                lifecycle=PostgresTutorLifecycle(repository=repository),
            )
            result = TutorHarnessService.enabled(loop=loop).run(
                run_id=run_id,
                lease_owner_id=f"tutor-api:{uuid4().hex}",
            )
            conn.commit()
            return result


def build_tutor_run_dispatcher(settings: Settings) -> TutorRunDispatcher:
    """Construct a route-owned dispatcher without caching cross-request state."""

    return TutorInteractiveRunDispatcher(settings=settings)


def _primary_provider(settings: Settings) -> TutorProviderGateway:
    return PrimaryTutorProviderGateway(settings=settings)
