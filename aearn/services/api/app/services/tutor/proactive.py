"""Deterministic, feature-disabled proactive Tutor scheduling contracts and service."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from app.agents.harness.contracts import TutorPolicySnapshot, TutorRunResult, TutorRunStatus
from app.agents.harness.skill_catalog import SkillCatalogSnapshot
from app.core.config import Settings
from app.services.tutor.run_loop import TutorRunLoop


SchedulerQueue = Literal["proactive", "curation"]
SchedulerState = Literal["pending", "leased", "completed", "no_action", "failed", "stale"]
ProcessorState = Literal["completed", "no_action", "failed", "retryable"]

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class TutorProactiveSchedulerConfig:
    """Fail-closed policy facts for target-only background work."""

    enabled: bool = False
    hard_paused: bool = True
    cutover_eligible: bool = False
    inferred_memory_enabled: bool = False
    proactive_daily_budget: int = 0
    curation_daily_budget: int = 0
    proactive_concurrency_limit: int = 0
    curation_concurrency_limit: int = 0
    proactive_cooldown_seconds: int = 86_400
    curation_cooldown_seconds: int = 3_600
    proactive_circuit_failure_threshold: int = 1
    curation_circuit_failure_threshold: int = 1
    circuit_window_seconds: int = 3_600
    candidate_lease_seconds: int = 60
    curation_lease_seconds: int = 60
    max_retry_attempts: int = 2
    retry_backoff_seconds: int = 60

    def __post_init__(self) -> None:
        for name in (
            "proactive_daily_budget",
            "curation_daily_budget",
            "proactive_concurrency_limit",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        for name in (
            "curation_concurrency_limit",
            "proactive_cooldown_seconds",
            "curation_cooldown_seconds",
            "circuit_window_seconds",
            "candidate_lease_seconds",
            "curation_lease_seconds",
            "max_retry_attempts",
            "retry_backoff_seconds",
            "proactive_circuit_failure_threshold",
            "curation_circuit_failure_threshold",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")

    @classmethod
    def from_settings(cls, settings: Settings) -> "TutorProactiveSchedulerConfig":
        return cls(
            enabled=settings.tutor_proactive_scheduler_enabled,
            hard_paused=settings.tutor_background_hard_paused,
            cutover_eligible=settings.tutor_proactive_cutover_eligible,
            inferred_memory_enabled=settings.tutor_inferred_memory_enabled,
            proactive_daily_budget=settings.tutor_proactive_daily_budget,
            curation_daily_budget=settings.tutor_curation_daily_budget,
            proactive_concurrency_limit=settings.tutor_proactive_concurrency_limit,
            curation_concurrency_limit=settings.tutor_curation_concurrency_limit,
            proactive_cooldown_seconds=settings.tutor_proactive_cooldown_seconds,
            curation_cooldown_seconds=settings.tutor_curation_cooldown_seconds,
            proactive_circuit_failure_threshold=settings.tutor_proactive_circuit_failure_threshold,
            curation_circuit_failure_threshold=settings.tutor_curation_circuit_failure_threshold,
            circuit_window_seconds=settings.tutor_scheduler_circuit_window_seconds,
            candidate_lease_seconds=settings.tutor_proactive_lease_seconds,
            curation_lease_seconds=settings.tutor_curation_lease_seconds,
            max_retry_attempts=settings.tutor_scheduler_max_retry_attempts,
            retry_backoff_seconds=settings.tutor_scheduler_retry_backoff_seconds,
        )

    def fingerprint(self, *, queue: SchedulerQueue) -> str:
        payload = {
            "queue": queue,
            "enabled": self.enabled,
            "hard_paused": self.hard_paused,
            "cutover_eligible": self.cutover_eligible,
            "inferred_memory_enabled": self.inferred_memory_enabled,
            "daily_budget": self.proactive_daily_budget if queue == "proactive" else self.curation_daily_budget,
            "concurrency_limit": (
                self.proactive_concurrency_limit if queue == "proactive" else self.curation_concurrency_limit
            ),
            "cooldown_seconds": (
                self.proactive_cooldown_seconds if queue == "proactive" else self.curation_cooldown_seconds
            ),
            "circuit_failure_threshold": (
                self.proactive_circuit_failure_threshold
                if queue == "proactive"
                else self.curation_circuit_failure_threshold
            ),
            "circuit_window_seconds": self.circuit_window_seconds,
            "lease_seconds": self.candidate_lease_seconds if queue == "proactive" else self.curation_lease_seconds,
            "max_retry_attempts": self.max_retry_attempts,
            "retry_backoff_seconds": self.retry_backoff_seconds,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TutorProactiveSignal:
    """A committed, safe-reference-only domain or bounded time signal."""

    user_id: str
    signal_kind: str
    source_type: str
    source_id: str
    source_hash: str
    occurred_at: datetime
    dedupe_key: str
    dedupe_window_seconds: int
    policy_version: str = "tutor_proactive_policy_v1"
    source_reference: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("user_id", "signal_kind", "source_type", "source_id", "dedupe_key", "policy_version"):
            _validate_identifier(str(getattr(self, name)), label=name)
        if not _SHA256.fullmatch(self.source_hash):
            raise ValueError("source_hash must be a SHA-256 digest")
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.dedupe_window_seconds <= 0:
            raise ValueError("dedupe_window_seconds must be positive")
        safe_reference = dict(self.source_reference)
        allowed = {"source_event_id", "source_id", "source_hash", "policy_tag"}
        if set(safe_reference) - allowed:
            raise ValueError("source_reference contains an unsafe key")
        for key, value in safe_reference.items():
            _validate_identifier(key, label="source_reference key")
            _validate_identifier(value, label="source_reference value")
        object.__setattr__(self, "source_reference", safe_reference)

    @property
    def dedupe_bucket_at(self) -> datetime:
        timestamp = int(self.occurred_at.astimezone(UTC).timestamp())
        bucket = timestamp - (timestamp % self.dedupe_window_seconds)
        return datetime.fromtimestamp(bucket, tz=UTC)

    @property
    def idempotency_key(self) -> str:
        encoded = "|".join((self.user_id, self.source_type, self.source_id, self.source_hash))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PersistedProactiveSignal:
    signal_id: str
    signal: TutorProactiveSignal
    disposition: str
    disposition_code: str | None
    replayed: bool


@dataclass(frozen=True)
class TutorProactivePreference:
    user_id: str
    enabled: bool = False
    hard_paused: bool = False
    policy_version: str = "tutor_proactive_policy_v1"
    setting_version: str = "tutor_proactive_setting_v1"

    def __post_init__(self) -> None:
        for name in ("user_id", "policy_version", "setting_version"):
            _validate_identifier(str(getattr(self, name)), label=name)


@dataclass(frozen=True)
class SchedulerUsage:
    active_leases: int
    started_today: int
    failed_in_circuit_window: int
    last_completed_at: datetime | None


@dataclass(frozen=True)
class SchedulerDecision:
    allowed: bool
    code: str
    queue: SchedulerQueue

    def __post_init__(self) -> None:
        _validate_identifier(self.code, label="scheduler decision code")


@dataclass(frozen=True)
class TutorProactiveCandidate:
    candidate_id: str
    signal_id: str
    user_id: str
    candidate_kind: str
    dedupe_key: str
    dedupe_bucket_at: datetime
    policy_version: str
    policy_fingerprint: str
    state: SchedulerState
    no_action_code: str | None
    not_before: datetime
    attempt_count: int
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    run_id: str | None
    run_started_at: datetime | None
    terminal_at: datetime | None


@dataclass(frozen=True)
class TutorCurationJob:
    job_id: str
    outbox_id: str
    user_id: str
    policy_version: str
    memory_setting_version: str
    state: SchedulerState
    no_action_code: str | None
    not_before: datetime
    attempt_count: int
    lease_owner_id: str | None
    lease_generation: int
    lease_expires_at: datetime | None
    processor_started_at: datetime | None
    terminal_at: datetime | None


@dataclass(frozen=True)
class ProactiveRunReservation:
    run_id: str
    conversation_id: str
    replayed: bool


@dataclass(frozen=True)
class ProactiveRunOutcome:
    state: ProcessorState
    code: str
    run_id: str | None = None

    def __post_init__(self) -> None:
        _validate_identifier(self.code, label="proactive run outcome code")
        if self.state == "completed" and not self.run_id:
            raise ValueError("a completed proactive run requires a run id")


@dataclass(frozen=True)
class CurationProcessOutcome:
    state: ProcessorState
    code: str

    def __post_init__(self) -> None:
        _validate_identifier(self.code, label="curation process outcome code")


@dataclass(frozen=True)
class SchedulerDrainResult:
    claimed: int = 0
    completed: int = 0
    no_action: int = 0
    retried: int = 0

    def add(self, *, state: ProcessorState | None = None, claimed: bool = False) -> "SchedulerDrainResult":
        return SchedulerDrainResult(
            claimed=self.claimed + int(claimed),
            completed=self.completed + int(state == "completed"),
            no_action=self.no_action + int(state == "no_action"),
            retried=self.retried + int(state in {"failed", "retryable"}),
        )


@dataclass(frozen=True)
class ProactiveRunComposition:
    """Explicit finite-loop composition facts for background Tutor runs."""

    catalog: SkillCatalogSnapshot
    policy: TutorPolicySnapshot
    policy_version: str = "tutor_proactive_policy_v1"
    allowed_capability_ids: tuple[str, ...] = ()
    allowed_effect_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_identifier(self.policy_version, label="policy_version")
        if "runner.execute" in self.allowed_capability_ids:
            raise ValueError("proactive runs must not receive runner.execute")
        if self.allowed_effect_types or self.policy.max_effects != 0:
            raise ValueError("Child 04 proactive runs must not receive domain effect authority")
        for capability_id in self.allowed_capability_ids:
            _validate_identifier(capability_id, label="allowed capability id")

    @property
    def policy_fingerprint(self) -> str:
        payload = {
            "deadline": self.policy.deadline.astimezone(UTC).isoformat(),
            "max_iterations": self.policy.max_iterations,
            "max_model_calls": self.policy.max_model_calls,
            "max_capability_calls": self.policy.max_capability_calls,
            "max_effects": self.policy.max_effects,
            "context_token_budget": self.policy.context_token_budget,
            "lease_duration_seconds": self.policy.lease_duration_seconds,
            "policy_version": self.policy_version,
            "allowed_capability_ids": self.allowed_capability_ids,
        }
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TutorProactiveSchedulerStore(Protocol):
    def preference_for_user(self, *, user_id: str) -> TutorProactivePreference: ...

    def proactive_usage(
        self, *, user_id: str, now: datetime, circuit_window_seconds: int
    ) -> SchedulerUsage: ...

    def curation_usage(self, *, user_id: str, now: datetime, circuit_window_seconds: int) -> SchedulerUsage: ...

    def record_signal(self, *, signal: TutorProactiveSignal, now: datetime) -> PersistedProactiveSignal: ...

    def create_or_replay_candidate(
        self,
        *,
        signal: PersistedProactiveSignal,
        decision: SchedulerDecision,
        policy_fingerprint: str,
        now: datetime,
    ) -> TutorProactiveCandidate: ...

    def claim_next_candidate(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> TutorProactiveCandidate | None: ...

    def mark_candidate_terminal(
        self,
        *,
        candidate: TutorProactiveCandidate,
        state: Literal["completed", "no_action", "failed"],
        code: str,
        now: datetime,
        run_id: str | None = None,
    ) -> None: ...

    def retry_candidate(
        self,
        *,
        candidate: TutorProactiveCandidate,
        code: str,
        now: datetime,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> None: ...

    def reserve_proactive_run(
        self,
        *,
        candidate: TutorProactiveCandidate,
        catalog_digest: str,
        policy: TutorPolicySnapshot,
        policy_version: str,
        policy_fingerprint: str,
        now: datetime,
    ) -> ProactiveRunReservation: ...

    def seed_curation_jobs(self, *, now: datetime, limit: int) -> tuple[TutorCurationJob, ...]: ...

    def claim_next_curation_job(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> TutorCurationJob | None: ...

    def curation_job_current(self, *, job: TutorCurationJob, now: datetime) -> SchedulerDecision: ...

    def mark_curation_processor_started(self, *, job: TutorCurationJob, now: datetime) -> None: ...

    def mark_curation_terminal(
        self,
        *,
        job: TutorCurationJob,
        state: Literal["completed", "no_action", "failed", "stale"],
        code: str,
        now: datetime,
    ) -> None: ...

    def retry_curation_job(
        self,
        *,
        job: TutorCurationJob,
        code: str,
        now: datetime,
        max_retry_attempts: int,
        retry_backoff_seconds: int,
    ) -> None: ...


class ProactiveLoopFactory(Protocol):
    def build(
        self,
        *,
        user_id: str,
        allowed_capability_ids: tuple[str, ...],
        allowed_effect_types: tuple[str, ...],
    ) -> TutorRunLoop: ...


class TutorProactiveRunExecutor(Protocol):
    def execute(
        self, *, candidate: TutorProactiveCandidate, lease_owner_id: str, now: datetime
    ) -> ProactiveRunOutcome: ...


class CurationProposalProcessor(Protocol):
    def process(self, *, job: TutorCurationJob, lease_owner_id: str, now: datetime) -> CurationProcessOutcome: ...


class DefaultDenyProactiveRunExecutor:
    """Feature-off fallback that cannot create a provider or capability request."""

    def execute(
        self, *, candidate: TutorProactiveCandidate, lease_owner_id: str, now: datetime
    ) -> ProactiveRunOutcome:
        del candidate, lease_owner_id, now
        return ProactiveRunOutcome(state="no_action", code="proactive_composition_unavailable")


class DefaultDenyCurationProposalProcessor:
    """Child 04 boundary: no Curator model call or direct domain write exists yet."""

    def process(self, *, job: TutorCurationJob, lease_owner_id: str, now: datetime) -> CurationProcessOutcome:
        del job, lease_owner_id, now
        return CurationProcessOutcome(state="no_action", code="curation_processor_unavailable")


class TutorRunLoopProactiveExecutor:
    """Reserve a durable background run, then invoke only the finite TutorRunLoop."""

    def __init__(
        self,
        *,
        store: TutorProactiveSchedulerStore,
        composition: ProactiveRunComposition,
        loop_factory: ProactiveLoopFactory,
    ) -> None:
        self._store = store
        self._composition = composition
        self._loop_factory = loop_factory

    def execute(
        self, *, candidate: TutorProactiveCandidate, lease_owner_id: str, now: datetime
    ) -> ProactiveRunOutcome:
        reservation = self._store.reserve_proactive_run(
            candidate=candidate,
            catalog_digest=self._composition.catalog.digest,
            policy=self._composition.policy,
            policy_version=self._composition.policy_version,
            policy_fingerprint=self._composition.policy_fingerprint,
            now=now,
        )
        loop = self._loop_factory.build(
            user_id=candidate.user_id,
            allowed_capability_ids=self._composition.allowed_capability_ids,
            allowed_effect_types=self._composition.allowed_effect_types,
        )
        result = loop.run(run_id=reservation.run_id, lease_owner_id=lease_owner_id)
        return _outcome_from_run_result(result, run_id=reservation.run_id)


class TutorProactiveScheduler:
    """Policy-first signal/candidate/curation orchestration with no public delivery path."""

    def __init__(
        self,
        *,
        store: TutorProactiveSchedulerStore,
        config: TutorProactiveSchedulerConfig,
        run_executor: TutorProactiveRunExecutor | None = None,
        curation_processor: CurationProposalProcessor | None = None,
    ) -> None:
        self._store = store
        self._config = config
        self._run_executor = run_executor or DefaultDenyProactiveRunExecutor()
        self._curation_processor = curation_processor or DefaultDenyCurationProposalProcessor()

    def ingest_committed_signal(self, *, signal: TutorProactiveSignal, now: datetime) -> TutorProactiveCandidate:
        persisted = self._store.record_signal(signal=signal, now=now)
        decision = self._proactive_decision(user_id=signal.user_id, now=now, claimed=False)
        return self._store.create_or_replay_candidate(
            signal=persisted,
            decision=decision,
            policy_fingerprint=self._config.fingerprint(queue="proactive"),
            now=now,
        )

    def drain_candidates(self, *, worker_id: str, now: datetime, limit: int = 10) -> SchedulerDrainResult:
        _validate_identifier(worker_id, label="worker_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        result = SchedulerDrainResult()
        for _ in range(limit):
            candidate = self._store.claim_next_candidate(
                worker_id=worker_id,
                now=now,
                lease_seconds=self._config.candidate_lease_seconds,
                max_retry_attempts=self._config.max_retry_attempts,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )
            if candidate is None:
                break
            result = result.add(claimed=True)
            decision = self._proactive_decision(user_id=candidate.user_id, now=now, claimed=True)
            if not decision.allowed:
                self._store.mark_candidate_terminal(
                    candidate=candidate,
                    state="no_action",
                    code=decision.code,
                    now=now,
                )
                result = result.add(state="no_action")
                continue
            outcome = self._run_executor.execute(candidate=candidate, lease_owner_id=worker_id, now=now)
            self._record_candidate_outcome(candidate=candidate, outcome=outcome, now=now)
            result = result.add(state=outcome.state)
        return result

    def seed_curation_jobs(self, *, now: datetime, limit: int = 20) -> tuple[TutorCurationJob, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self._store.seed_curation_jobs(now=now, limit=limit)

    def drain_curation(self, *, worker_id: str, now: datetime, limit: int = 10) -> SchedulerDrainResult:
        _validate_identifier(worker_id, label="worker_id")
        if limit <= 0:
            raise ValueError("limit must be positive")
        result = SchedulerDrainResult()
        for _ in range(limit):
            job = self._store.claim_next_curation_job(
                worker_id=worker_id,
                now=now,
                lease_seconds=self._config.curation_lease_seconds,
                max_retry_attempts=self._config.max_retry_attempts,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )
            if job is None:
                break
            result = result.add(claimed=True)
            source_decision = self._store.curation_job_current(job=job, now=now)
            decision = source_decision if not source_decision.allowed else self._curation_decision(
                user_id=job.user_id,
                now=now,
                claimed=True,
            )
            if not decision.allowed:
                terminal_state: Literal["no_action", "stale"] = "stale" if decision.code.startswith("outbox_") else "no_action"
                self._store.mark_curation_terminal(job=job, state=terminal_state, code=decision.code, now=now)
                result = result.add(state="no_action")
                continue
            self._store.mark_curation_processor_started(job=job, now=now)
            outcome = self._curation_processor.process(job=job, lease_owner_id=worker_id, now=now)
            self._record_curation_outcome(job=job, outcome=outcome, now=now)
            result = result.add(state=outcome.state)
        return result

    def _record_candidate_outcome(
        self, *, candidate: TutorProactiveCandidate, outcome: ProactiveRunOutcome, now: datetime
    ) -> None:
        if outcome.state == "completed":
            self._store.mark_candidate_terminal(
                candidate=candidate,
                state="completed",
                code=outcome.code,
                now=now,
                run_id=outcome.run_id,
            )
        elif outcome.state == "no_action":
            self._store.mark_candidate_terminal(candidate=candidate, state="no_action", code=outcome.code, now=now)
        else:
            self._store.retry_candidate(
                candidate=candidate,
                code=outcome.code,
                now=now,
                max_retry_attempts=self._config.max_retry_attempts,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )

    def _record_curation_outcome(
        self, *, job: TutorCurationJob, outcome: CurationProcessOutcome, now: datetime
    ) -> None:
        if outcome.state == "completed":
            self._store.mark_curation_terminal(job=job, state="completed", code=outcome.code, now=now)
        elif outcome.state == "no_action":
            self._store.mark_curation_terminal(job=job, state="no_action", code=outcome.code, now=now)
        else:
            self._store.retry_curation_job(
                job=job,
                code=outcome.code,
                now=now,
                max_retry_attempts=self._config.max_retry_attempts,
                retry_backoff_seconds=self._config.retry_backoff_seconds,
            )

    def _proactive_decision(self, *, user_id: str, now: datetime, claimed: bool) -> SchedulerDecision:
        if not self._config.enabled:
            return SchedulerDecision(False, "scheduler_disabled", "proactive")
        if self._config.hard_paused:
            return SchedulerDecision(False, "background_hard_paused", "proactive")
        if not self._config.cutover_eligible:
            return SchedulerDecision(False, "cutover_ineligible", "proactive")
        preference = self._store.preference_for_user(user_id=user_id)
        if preference.hard_paused:
            return SchedulerDecision(False, "user_hard_paused", "proactive")
        if not preference.enabled:
            return SchedulerDecision(False, "preference_disabled", "proactive")
        usage = self._store.proactive_usage(
            user_id=user_id,
            now=now,
            circuit_window_seconds=self._config.circuit_window_seconds,
        )
        return self._usage_decision(
            queue="proactive",
            usage=usage,
            now=now,
            claimed=claimed,
            daily_budget=self._config.proactive_daily_budget,
            concurrency_limit=self._config.proactive_concurrency_limit,
            cooldown_seconds=self._config.proactive_cooldown_seconds,
            circuit_threshold=self._config.proactive_circuit_failure_threshold,
        )

    def _curation_decision(self, *, user_id: str, now: datetime, claimed: bool) -> SchedulerDecision:
        if not self._config.enabled:
            return SchedulerDecision(False, "scheduler_disabled", "curation")
        if self._config.hard_paused:
            return SchedulerDecision(False, "background_hard_paused", "curation")
        if not self._config.cutover_eligible:
            return SchedulerDecision(False, "cutover_ineligible", "curation")
        if not self._config.inferred_memory_enabled:
            return SchedulerDecision(False, "inferred_memory_disabled", "curation")
        preference = self._store.preference_for_user(user_id=user_id)
        if preference.hard_paused:
            return SchedulerDecision(False, "user_hard_paused", "curation")
        if not preference.enabled:
            return SchedulerDecision(False, "preference_disabled", "curation")
        usage = self._store.curation_usage(
            user_id=user_id,
            now=now,
            circuit_window_seconds=self._config.circuit_window_seconds,
        )
        return self._usage_decision(
            queue="curation",
            usage=usage,
            now=now,
            claimed=claimed,
            daily_budget=self._config.curation_daily_budget,
            concurrency_limit=self._config.curation_concurrency_limit,
            cooldown_seconds=self._config.curation_cooldown_seconds,
            circuit_threshold=self._config.curation_circuit_failure_threshold,
        )

    @staticmethod
    def _usage_decision(
        *,
        queue: SchedulerQueue,
        usage: SchedulerUsage,
        now: datetime,
        claimed: bool,
        daily_budget: int,
        concurrency_limit: int,
        cooldown_seconds: int,
        circuit_threshold: int,
    ) -> SchedulerDecision:
        if daily_budget <= 0 or usage.started_today >= daily_budget:
            return SchedulerDecision(False, f"{queue}_budget_exhausted", queue)
        if concurrency_limit <= 0 or usage.active_leases > concurrency_limit - int(not claimed):
            return SchedulerDecision(False, f"{queue}_concurrency_exhausted", queue)
        if usage.last_completed_at is not None and (now - usage.last_completed_at).total_seconds() < cooldown_seconds:
            return SchedulerDecision(False, f"{queue}_cooldown_active", queue)
        if usage.failed_in_circuit_window >= circuit_threshold:
            return SchedulerDecision(False, f"{queue}_circuit_open", queue)
        return SchedulerDecision(True, "eligible", queue)


def _outcome_from_run_result(result: TutorRunResult, *, run_id: str) -> ProactiveRunOutcome:
    code = result.diagnostic_code or result.status.value
    if result.status is TutorRunStatus.COMPLETED:
        return ProactiveRunOutcome(state="completed", code=code, run_id=run_id)
    if result.status in {TutorRunStatus.BLOCKED_POLICY, TutorRunStatus.BUDGET_EXHAUSTED, TutorRunStatus.CANCELLED}:
        return ProactiveRunOutcome(state="no_action", code=code, run_id=run_id)
    if result.status in {TutorRunStatus.MODEL_UNAVAILABLE, TutorRunStatus.FAILED}:
        return ProactiveRunOutcome(state="retryable", code=code, run_id=run_id)
    return ProactiveRunOutcome(state="no_action", code="background_waiting_disallowed", run_id=run_id)


def _validate_identifier(value: str, *, label: str) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a bounded stable identifier")
