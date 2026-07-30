"""API-side, verified-only composition for bounded proactive Tutor work."""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from app.agents.harness.capabilities import TUTOR_ACTIVITY_RECORD_EFFECT_TYPE
from app.agents.harness.catalog_context import CatalogContextLoader
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorEffectProposal,
    TutorEffectResult,
    TutorEffectStatus,
    TutorPolicySnapshot,
    TutorProviderResult,
    TutorRunSnapshot,
    TutorContextSelection,
)
from app.agents.harness.skill_catalog import SkillCatalogSnapshot, compile_published_skill_catalog
from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.services.tutor.capability_policy import CapabilityPolicyContext, InMemoryCapabilityPolicyResolver
from app.services.tutor.curation import build_curation_proposal_processor
from app.services.tutor.decision_gate import CatalogTutorDecisionGate
from app.services.tutor.interactive import PostgresTutorContextLoader, UtcClock
from app.services.tutor.learner_state import TutorLearnerStateRepository, build_learner_state_effect_handlers
from app.services.tutor.persistence import (
    PostgresTutorLifecycle,
    PostgresTutorRepository,
    PostgresTutorSkillSelectionStore,
)
from app.services.tutor.ports import (
    Clock,
    DefaultDenyCapabilityGateway,
    NoopTutorCompactionPublisher,
    TutorProviderGateway,
)
from app.services.tutor.proactive import (
    ProactiveRunComposition,
    TutorProactiveScheduler,
    TutorProactiveSchedulerConfig,
    TutorRunLoopProactiveExecutor,
)
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository
from app.services.tutor.provider_gateway import PrimaryTutorProviderGateway
from app.services.tutor.run_loop import TutorRunLoop


SchedulerOperation = Literal["scan_due_signals", "drain_candidates", "drain_curation"]
ProactiveProviderFactory = Callable[[Settings], TutorProviderGateway]

_PROACTIVE_SKILL_KEY = "tutor.learner-state@1.0.0"
_PROACTIVE_POLICY_VERSION = "tutor_proactive_policy_v1"


class ProactiveDeliveryProviderGateway:
    """Keep model text out of background chat while preserving typed effects only."""

    def __init__(self, delegate: TutorProviderGateway) -> None:
        self._delegate = delegate

    def decide(self, *, run: TutorRunSnapshot, context: TutorContextSelection) -> TutorProviderResult:
        result = self._delegate.decide(run=run, context=context)
        if result.decision is None or result.decision.public_message is None:
            return result
        return replace(result, decision=replace(result.decision, public_message=None))


class PostgresProactiveEffectCommitter:
    """Use the normal durable CAS effect boundary with a run-scoped idempotency key."""

    def __init__(self, *, repository: PostgresTutorRepository) -> None:
        self._repository = repository

    def commit(self, *, run: TutorRunSnapshot, proposal: TutorEffectProposal) -> TutorEffectResult:
        if run.lease is None:
            return TutorEffectResult(effect_id=proposal.effect_id, status=TutorEffectStatus.DENIED)
        identity = "|".join((run.run_id, proposal.effect_id, str(proposal.expected_input_revision)))
        receipt = self._repository.commit_effect_if_current(
            user_id=run.user_id,
            run_id=run.run_id,
            lease=run.lease,
            proposal=proposal,
            idempotency_key=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        )
        return receipt.result


class PostgresProactiveLoopFactory:
    """Compose the finite loop with one reviewed Skill and no executable capability."""

    def __init__(
        self,
        *,
        conn: Any,
        settings: Settings,
        catalog: SkillCatalogSnapshot,
        clock: Clock,
        provider_factory: ProactiveProviderFactory,
    ) -> None:
        self._conn = conn
        self._settings = settings
        self._catalog = catalog
        self._clock = clock
        self._provider_factory = provider_factory

    def build(
        self,
        *,
        run_id: str,
        user_id: str,
        candidate_kind: str,
        allowed_capability_ids: tuple[str, ...],
        allowed_effect_types: tuple[str, ...],
    ) -> TutorRunLoop:
        learner_skill = self._catalog.resolve_skill("tutor.learner-state", "1.0.0")
        if learner_skill is None or learner_skill.reference.key != _PROACTIVE_SKILL_KEY:
            raise RuntimeError("reviewed proactive learner-state Skill is unavailable")
        repository = PostgresTutorRepository(
            self._conn,
            effect_handlers=build_learner_state_effect_handlers(TutorLearnerStateRepository(self._conn)),
        )
        selection_store = PostgresTutorSkillSelectionStore(repository=repository, user_id=user_id)
        resolver = InMemoryCapabilityPolicyResolver(
            [
                CapabilityPolicyContext(
                    run_id=run_id,
                    user_id=user_id,
                    origin="proactive",
                    input_revision=0,
                    catalog_digest=self._catalog.digest,
                    eligible_skill_references=(learner_skill.reference,),
                    eligible_capability_ids=allowed_capability_ids,
                    eligible_effect_types=allowed_effect_types,
                    granted_policy_tags=("learner-state",),
                    allowed_origins=("proactive",),
                    consent_granted=True,
                    runtime_available_capability_ids=(),
                    remaining_capability_budget=0,
                )
            ]
        )
        base_loader = PostgresTutorContextLoader(
            conn=self._conn,
            learner_state=TutorLearnerStateRepository(self._conn),
            proactive_candidate_kind=candidate_kind,
        )
        return TutorRunLoop(
            store=repository.as_run_store(user_id=user_id),
            context_loader=CatalogContextLoader(
                base_loader=base_loader,
                catalog=self._catalog,
                policy_resolver=resolver,
                selection_store=selection_store,
            ),
            context_builder=TutorContextBuilder(),
            provider=ProactiveDeliveryProviderGateway(self._provider_factory(self._settings)),
            capability_gateway=DefaultDenyCapabilityGateway(),
            effect_committer=PostgresProactiveEffectCommitter(repository=repository),
            clock=self._clock,
            compaction_publisher=NoopTutorCompactionPublisher(),
            decision_gate=CatalogTutorDecisionGate(
                catalog=self._catalog,
                policy_resolver=resolver,
                selection_store=selection_store,
            ),
            lifecycle=PostgresTutorLifecycle(repository=repository),
        )


def build_tutor_proactive_scheduler(
    *,
    conn: Any,
    settings: Settings,
    now: datetime,
    clock: Clock | None = None,
    provider_factory: ProactiveProviderFactory | None = None,
) -> TutorProactiveScheduler:
    """Build production composition; tests replace only the provider/clock seams."""

    catalog = compile_published_skill_catalog()
    PostgresTutorRepository(conn).record_catalog_snapshot(catalog)
    config = TutorProactiveSchedulerConfig.from_settings(settings)
    composition = ProactiveRunComposition(
        catalog=catalog,
        policy=TutorPolicySnapshot(
            deadline=now + timedelta(seconds=30),
            max_iterations=2,
            max_model_calls=2,
            max_capability_calls=0,
            max_effects=1,
            context_token_budget=256,
            lease_duration_seconds=config.candidate_lease_seconds,
        ),
        policy_version=_PROACTIVE_POLICY_VERSION,
        allowed_effect_types=(TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,),
    )
    scheduler_repository = PostgresTutorProactiveRepository(conn)
    loop_factory = PostgresProactiveLoopFactory(
        conn=conn,
        settings=settings,
        catalog=catalog,
        clock=clock or UtcClock(),
        provider_factory=provider_factory or _primary_provider,
    )
    return TutorProactiveScheduler(
        store=scheduler_repository,
        config=config,
        run_executor=TutorRunLoopProactiveExecutor(
            store=scheduler_repository,
            composition=composition,
            loop_factory=loop_factory,
        ),
        curation_processor=build_curation_proposal_processor(conn=conn, settings=settings),
    )


def run_tutor_scheduler_operation(
    *,
    operation: SchedulerOperation,
    limit: int = 10,
    settings: Settings | None = None,
    now: datetime | None = None,
    clock: Clock | None = None,
    provider_factory: ProactiveProviderFactory | None = None,
) -> dict[str, object]:
    """Run bounded target operations without legacy routes, runners, or chat delivery."""

    if limit <= 0:
        raise ValueError("scheduler task limit must be positive")
    resolved_settings = settings or get_settings()
    config = TutorProactiveSchedulerConfig.from_settings(resolved_settings)
    if not config.enabled:
        return {"status": "blocked_policy", "code": "scheduler_disabled", "processed": 0}
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    with connect() as conn:
        scheduler = build_tutor_proactive_scheduler(
            conn=conn,
            settings=resolved_settings,
            now=current_time,
            clock=clock,
            provider_factory=provider_factory,
        )
        if operation == "scan_due_signals":
            candidates = scheduler.scan_due_signals(now=current_time, limit=limit)
            conn.commit()
            return {
                "status": "ok",
                "processed": len(candidates),
                "eligible": sum(candidate.state == "pending" for candidate in candidates),
            }
        if operation == "drain_candidates":
            result = scheduler.drain_candidates(worker_id="celery-proactive", now=current_time, limit=limit)
            conn.commit()
            return {
                "status": "ok",
                "claimed": result.claimed,
                "completed": result.completed,
                "no_action": result.no_action,
                "retried": result.retried,
            }
        seeded = scheduler.seed_curation_jobs(now=current_time, limit=limit)
        result = scheduler.drain_curation(worker_id="celery-curation", now=current_time, limit=limit)
        conn.commit()
        return {
            "status": "ok",
            "seeded": len(seeded),
            "claimed": result.claimed,
            "completed": result.completed,
            "no_action": result.no_action,
            "retried": result.retried,
        }


def _primary_provider(settings: Settings) -> TutorProviderGateway:
    return PrimaryTutorProviderGateway(settings=settings)
