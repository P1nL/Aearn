"""Controlled interactive Tutor run composition for the public target adapter.

This module is intentionally narrow: it starts a durable, already-accepted
interactive run after the input transaction commits. It never changes legacy
Graph traffic and its default policy denies Skills, capabilities, and effects.
Only a configured primary provider can produce a bounded public response.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from psycopg import Connection

from app.agents.harness.catalog_context import CatalogContextLoader
from app.agents.harness.context_budget import TutorContextBudgetPlanner
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES,
    TUTOR_CONTEXT_SUMMARY_POLICY_VERSION,
    TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION,
    TutorContextCompactionCandidate,
    TutorContextCompactionPlan,
    TutorContextError,
    TutorContextInput,
    TutorContextSource,
    TutorRunResult,
    TutorRunSnapshot,
    build_tutor_message_evidence_hash,
)
from app.agents.harness.skill_catalog import compile_published_skill_catalog
from app.core.config import Settings
from app.db.connection import connect
from app.services.learning.context_adapter import TutorLearningContextAdapter
from app.services.learning.context_references import PostgresTutorContextReferenceRepository
from app.services.learning.plan_capability import LearningPlanDraftCapabilityHandler
from app.services.learning.planning_facts import (
    PlanningQuestionDecisionGate,
    PostgresPlanningFactRepository,
)
from app.services.learning.plan_repository import (
    LearningPlanSessionNotFound,
    PostgresLearningPlanSessionRepository,
)
from app.services.tutor.action_adapters import (
    ControlledCapabilityGateway,
    PostgresCapabilityAuthorityVerifier,
    PostgresGroundingActionVerifier,
    PostgresLearningPlanActionVerifier,
)
from app.services.tutor.action_persistence import PostgresActionFence, PostgresActionReceiptStore
from app.services.tutor.action_runtime import ActionVerifier
from app.services.tutor.capability_gateway import CatalogCapabilityGateway
from app.services.learning.plan_policy import InteractiveLearningCapabilityPolicyResolver
from app.services.tutor.decision_gate import CatalogTutorDecisionGate
from app.services.tutor.learner_state import TutorContextSummaryProjection, TutorLearnerStateRepository
from app.services.tutor.persistence import (
    PostgresTutorLifecycle,
    PostgresTutorRepository,
    PostgresTutorSkillSelectionStore,
)
from app.services.tutor.ports import (
    Clock,
    DefaultDenyEffectCommitter,
    NoopTutorCompactionPublisher,
    TutorProviderGateway,
)
from app.services.tutor.grounding_lookup import InMemoryGroundingLookup
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
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._conn = conn
        self._learner_state = learner_state
        self._proactive_candidate_kind = proactive_candidate_kind
        self._now_provider = now_provider or (lambda: datetime.now(UTC))

    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
        current_input: TutorContextSource | None = None
        current_input_required = self._current_input_required(snapshot)
        recent_messages: tuple[TutorContextSource, ...] = ()
        working_summary: tuple[TutorContextSource, ...] = ()
        compaction_plan: TutorContextCompactionPlan | None = None
        if current_input_required:
            current_row = self._load_current_input_row(snapshot, input_revision=input_revision)
            current_message_id = str(current_row["message_id"])
            current_created_at = current_row.get("created_at")
            if not isinstance(current_created_at, datetime):
                raise TutorContextError("TUTOR_CURRENT_INPUT_EVIDENCE_INVALID")
            current_input = TutorContextSource(
                source_id=f"message:{current_message_id}",
                content=str(current_row.get("content") or ""),
            )
            summary = self._learner_state.latest_context_summary_for_conversation(
                user_id=snapshot.user_id,
                conversation_id=snapshot.conversation_id,
                current_message_created_at=current_created_at,
                current_message_id=current_message_id,
                now=self._now_provider(),
            )
            if summary is not None:
                working_summary = (
                    TutorContextSource(
                        source_id=f"summary:{summary.summary_id}",
                        content=summary.summary_json,
                    ),
                )
            rows = self._conn.execute(
                """
                SELECT id::text AS id, role, content, created_at
                FROM tutor_messages
                WHERE conversation_id = %s
                  AND (created_at, id) < (%s, %s::uuid)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (
                    snapshot.conversation_id,
                    current_created_at,
                    current_message_id,
                    MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES,
                ),
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
            compaction_plan = self._load_compaction_plan(
                conversation_id=snapshot.conversation_id,
                current_created_at=current_created_at,
                current_message_id=current_message_id,
                prior_summary=summary,
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
            current_input=current_input,
            current_input_required=current_input_required,
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
            working_summary=working_summary,
            learner_memory=memory_sources,
            activity_facts=activity_sources,
            compaction_plan=compaction_plan,
        )

    def _load_compaction_plan(
        self,
        *,
        conversation_id: str,
        current_created_at: datetime,
        current_message_id: str,
        prior_summary: TutorContextSummaryProjection | None,
    ) -> TutorContextCompactionPlan | None:
        if prior_summary is None:
            rows = self._conn.execute(
                """
                SELECT id::text AS id, role, content, created_at
                FROM tutor_messages
                WHERE conversation_id = %s
                  AND (created_at, id) < (%s, %s::uuid)
                ORDER BY created_at ASC, id ASC
                LIMIT %s
                """,
                (
                    conversation_id,
                    current_created_at,
                    current_message_id,
                    MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES,
                ),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT id::text AS id, role, content, created_at
                FROM tutor_messages
                WHERE conversation_id = %s
                  AND (created_at, id) > (%s, %s::uuid)
                  AND (created_at, id) < (%s, %s::uuid)
                ORDER BY created_at ASC, id ASC
                LIMIT %s
                """,
                (
                    conversation_id,
                    prior_summary.covered_through_created_at,
                    prior_summary.covered_through_message_id,
                    current_created_at,
                    current_message_id,
                    MAX_TUTOR_CONTEXT_COMPACTION_CANDIDATES,
                ),
            ).fetchall()
        if not rows:
            return None
        candidates = tuple(
            TutorContextCompactionCandidate(
                message_id=str(row["id"]),
                content_hash=build_tutor_message_evidence_hash(
                    message_id=str(row["id"]),
                    role=str(row["role"]),
                    content=str(row.get("content") or ""),
                    created_at=_required_datetime(row.get("created_at")),
                ),
                created_at=_required_datetime(row.get("created_at")),
            )
            for row in rows
        )
        return TutorContextCompactionPlan(
            summary_schema_version=TUTOR_CONTEXT_SUMMARY_SCHEMA_VERSION,
            summary_policy_version=TUTOR_CONTEXT_SUMMARY_POLICY_VERSION,
            candidates=candidates,
            prior_summary_id=(prior_summary.summary_id if prior_summary is not None else None),
            prior_summary_hash=(prior_summary.content_hash if prior_summary is not None else None),
        )


    def _current_input_required(self, snapshot: TutorRunSnapshot) -> bool:
        proactive = self._proactive_candidate_kind is not None
        if proactive != (snapshot.origin == "proactive"):
            raise TutorContextError("TUTOR_CONTEXT_ORIGIN_INVALID")
        return not proactive

    def _load_current_input_row(
        self,
        snapshot: TutorRunSnapshot,
        *,
        input_revision: int,
    ) -> dict[str, object]:
        if input_revision != snapshot.input_revision or input_revision < 1:
            raise TutorContextError("TUTOR_CURRENT_INPUT_REVISION_INVALID")
        rows = self._conn.execute(
            """
            SELECT inputs.message_id::text AS message_id, messages.role, messages.content, messages.created_at
            FROM tutor_runs AS runs
            JOIN tutor_run_input_events AS inputs
              ON inputs.run_id = runs.id
             AND inputs.input_revision = %s
            JOIN tutor_messages AS messages
              ON messages.id = inputs.message_id
            WHERE runs.id = %s
              AND runs.user_id = %s
              AND runs.conversation_id = %s
              AND runs.input_revision = %s
              AND inputs.conversation_id = runs.conversation_id
              AND messages.conversation_id = runs.conversation_id
            """,
            (
                input_revision,
                snapshot.run_id,
                snapshot.user_id,
                snapshot.conversation_id,
                input_revision,
            ),
        ).fetchall()
        if len(rows) != 1:
            raise TutorContextError("TUTOR_CURRENT_INPUT_EVIDENCE_INVALID")
        row = rows[0]
        if str(row.get("role")) != "learner":
            raise TutorContextError("TUTOR_CURRENT_INPUT_ROLE_INVALID")
        if not str(row.get("content") or "").strip():
            raise TutorContextError("TUTOR_CURRENT_INPUT_EMPTY")
        return row


class PostgresTutorLearningContextLoader:
    """Append bounded learning authority without changing current-input priority."""

    def __init__(
        self,
        *,
        conn: Connection[dict[str, object]],
        base_loader: PostgresTutorContextLoader,
    ) -> None:
        self._learning = TutorLearningContextAdapter(conn)
        self._context_references = PostgresTutorContextReferenceRepository(conn)
        self._plans = PostgresLearningPlanSessionRepository(conn)
        self._facts = PostgresPlanningFactRepository(conn)
        self._actions = PostgresActionReceiptStore(conn)
        self._base_loader = base_loader

    def load_context(self, snapshot: TutorRunSnapshot, *, input_revision: int) -> TutorContextInput:
        base = self._base_loader.load_context(snapshot, input_revision=input_revision)
        learning = self._learning.load(user_id=snapshot.user_id, run_id=snapshot.run_id)
        descriptors = list(base.system_descriptors)
        descriptors.extend(learning.sources)
        action_receipts = tuple(
            receipt.as_context_source()
            for receipt in self._actions.list_context_receipts(
                user_id=snapshot.user_id,
                run_id=snapshot.run_id,
                input_revision=input_revision,
            )
        )
        authoritative = self._facts.project_snapshot(
            run=snapshot,
            input_revision=input_revision,
            action_receipts=action_receipts,
        )
        reference_items = self._context_references.read_for_input(
            user_id=snapshot.user_id,
            run_id=snapshot.run_id,
            input_revision=input_revision,
        )
        reference_sources = tuple(
            TutorContextSource(
                source_id=f"context-reference:{reference['reference_id']}",
                content={
                    key: value
                    for key, value in reference.items()
                    if key not in {"reference_id", "safe_payload_hash", "created_at"}
                },
                semantic_class="confirmed_fact_source",
            )
            for reference in reference_items
        )
        required_facts = (*authoritative.required_facts, *reference_sources)
        recent_messages = base.recent_messages
        compaction_plan = base.compaction_plan
        summary_blocked = 0
        if learning.scope.scope_kind.value == "plan_drafting":
            try:
                session = self._plans.active_session_for_run(
                    user_id=snapshot.user_id,
                    run_id=snapshot.run_id,
                    input_revision=input_revision,
                )
            except LearningPlanSessionNotFound:
                session = None
            if session is not None:
                descriptors.append(
                    TutorContextSource(
                        source_id=f"learning-plan-session:{session['id']}",
                        content={
                            "status": str(session["status"]),
                            "preferred_language_id": session.get("preferred_language_id"),
                            "session_version": _context_int(session.get("version")),
                            "current_draft_version": _context_int(session.get("draft_version")),
                            "current_draft_hash": session.get("content_hash"),
                            "facts_fingerprint": authoritative.facts_fingerprint,
                            "fact_revision": authoritative.fact_revision,
                            "question_states": dict(authoritative.question_states),
                        },
                    )
                )
                covered_message_ids, protected_message_ids = self._facts.message_semantics_for_session(
                    user_id=snapshot.user_id,
                    session_id=str(session["id"]),
                )
                recent_messages = tuple(
                    replace(
                        source,
                        semantic_class=(
                            "confirmed_fact_source"
                            if source.source_id.removeprefix("message:") in covered_message_ids
                            else (
                                "unresolved_question"
                                if source.source_id.removeprefix("message:") in protected_message_ids
                                else source.semantic_class
                            )
                        ),
                    )
                    for source in base.recent_messages
                )
                if compaction_plan is not None:
                    protected_in_plan = tuple(
                        candidate.message_id
                        for candidate in compaction_plan.candidates
                        if candidate.message_id in protected_message_ids
                    )
                    summary_blocked = int(bool(protected_in_plan))
                    compaction_plan = replace(
                        compaction_plan,
                        protected_message_ids=protected_in_plan,
                    )
                draft = _bounded_current_draft(session)
                if draft is not None:
                    descriptors.append(
                        TutorContextSource(
                            source_id=f"learning-plan-current-draft:{session['current_draft_id']}",
                            content=draft,
                        )
                    )
        return replace(
            base,
            system_descriptors=tuple(descriptors),
            required_facts=required_facts,
            action_receipts=authoritative.action_receipts,
            recent_messages=recent_messages,
            compaction_plan=compaction_plan,
            authoritative_snapshot_schema_version=authoritative.schema_version,
            authoritative_snapshot_hash=authoritative.snapshot_hash,
            fact_revision=authoritative.fact_revision,
            confirmed_question_reasked_count=authoritative.confirmed_question_reasked_count,
            summary_blocked_by_unprojected_fact=summary_blocked,
        )


def _bounded_current_draft(session: Mapping[str, object]) -> dict[str, object] | None:
    plan = session.get("plan_json")
    profile = session.get("profile_json")
    sources = session.get("source_summary_json")
    if not isinstance(plan, Mapping) or not isinstance(profile, Mapping):
        return None
    modules_raw = plan.get("modules")
    modules: list[dict[str, object]] = []
    if isinstance(modules_raw, list):
        for module in modules_raw[:8]:
            if not isinstance(module, Mapping):
                continue
            nodes_raw = module.get("nodes")
            nodes = []
            if isinstance(nodes_raw, list):
                nodes = [
                    {
                        "knowledge_key": node.get("knowledge_key"),
                        "title": node.get("title"),
                    }
                    for node in nodes_raw[:8]
                    if isinstance(node, Mapping)
                ]
            modules.append(
                {
                    "module_key": module.get("module_key"),
                    "title": module.get("title"),
                    "nodes": nodes,
                }
            )
    source_ids = [
        str(item["source_id"])
        for item in sources[:8]
        if isinstance(item, Mapping) and item.get("source_id") is not None
    ] if isinstance(sources, list) else []
    return {
        "profile": {
            "language_id": profile.get("language_id"),
            "goal_text": profile.get("goal_text"),
            "target_level": profile.get("target_level"),
            "weekly_minutes": profile.get("weekly_minutes"),
            "experience_level": profile.get("experience_level"),
            "teaching_preferences": profile.get("teaching_preferences"),
            "pace_summary": profile.get("pace_summary"),
        },
        "modules": modules,
        "source_ids": source_ids,
    }


def _context_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TutorContextError("TUTOR_CONTEXT_TIMELINE_INVALID")
    return value


def _action_policy_fingerprint(
    conn: Connection[dict[str, object]],
    run: TutorRunSnapshot,
) -> str:
    row = conn.execute(
        "SELECT policy_fingerprint FROM tutor_runs WHERE id = %s AND user_id = %s",
        (run.run_id, run.user_id),
    ).fetchone()
    if row is None:
        raise TutorContextError("TUTOR_ACTION_POLICY_EVIDENCE_MISSING")
    return str(row["policy_fingerprint"])


def _action_verifier(
    conn: Connection[dict[str, object]],
    action_id: str,
) -> ActionVerifier:
    if action_id == "learning.plan.draft":
        return PostgresLearningPlanActionVerifier(conn)
    if action_id == "grounding.retrieve":
        return PostgresGroundingActionVerifier(conn)
    return PostgresCapabilityAuthorityVerifier(conn)


ProviderFactory = Callable[[Settings], TutorProviderGateway]


class TutorInteractiveRunDispatcher:
    """Execute one persisted interactive run through the finite Harness loop.

    The dispatcher is used only after the public input route's database
    transaction commits. Its production composition remains default-deny except
    for the exact plan-drafting Skill/capability on an active planning session.
    Effects remain behind the existing deny-by-default gate.
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
            policy_resolver = InteractiveLearningCapabilityPolicyResolver(conn)
            selection_store = PostgresTutorSkillSelectionStore(repository=repository, user_id=user_id)
            planning_facts = PostgresPlanningFactRepository(conn)
            base_loader = PostgresTutorContextLoader(conn=conn, learner_state=learner_state)
            learning_loader = PostgresTutorLearningContextLoader(conn=conn, base_loader=base_loader)
            loop = TutorRunLoop(
                store=repository.as_run_store(user_id=user_id),
                context_loader=CatalogContextLoader(
                    base_loader=learning_loader,
                    catalog=catalog,
                    policy_resolver=policy_resolver,
                    selection_store=selection_store,
                ),
                context_builder=TutorContextBuilder(),
                context_budget_planner=TutorContextBudgetPlanner(),
                provider=self._provider_factory(self._settings),
                capability_gateway=ControlledCapabilityGateway(
                    catalog=catalog,
                    policy_resolver=policy_resolver,
                    selection_store=selection_store,
                    authority_gateway=CatalogCapabilityGateway(
                        catalog=catalog,
                        policy_resolver=policy_resolver,
                        selection_store=selection_store,
                        grounding_lookup=InMemoryGroundingLookup(),
                        learning_plan_handler=LearningPlanDraftCapabilityHandler(conn),
                    ),
                    authority_recorder=repository,
                    receipt_store=PostgresActionReceiptStore(conn),
                    fence=PostgresActionFence(conn),
                    clock=self._clock,
                    policy_fingerprint_loader=lambda run: _action_policy_fingerprint(conn, run),
                    verifier_factory=lambda descriptor: _action_verifier(conn, descriptor.action_id),
                ),
                effect_committer=DefaultDenyEffectCommitter(),
                clock=self._clock,
                compaction_publisher=NoopTutorCompactionPublisher(),
                decision_gate=PlanningQuestionDecisionGate(
                    base=CatalogTutorDecisionGate(
                        catalog=catalog,
                        policy_resolver=policy_resolver,
                        selection_store=selection_store,
                    ),
                    facts=planning_facts,
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
