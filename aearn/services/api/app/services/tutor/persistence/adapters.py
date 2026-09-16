"""面向 Tutor runtime ports 的 PostgreSQL adapters。"""
# ruff: noqa: F403, F405
from __future__ import annotations

import logging
from app.core.safe_diagnostics import log_safe_event, safe_diagnostic_identifier

from ._namespace import *
from .repository import PostgresTutorRepository


def _log_teaching_terminal_conflict(error: BaseException, *, run_id: str) -> None:
    """Correlate closed server errors without recording values or tracebacks."""
    seen: set[int] = set()
    cause: BaseException | None = error
    for depth in range(6):
        if cause is None or id(cause) in seen:
            break
        seen.add(id(cause))
        diag = getattr(cause, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        field = constraint if isinstance(constraint, str) and constraint.startswith(("fk_tutor_", "chk_tutor_", "uq_tutor_")) else None
        log_safe_event(
            logging.getLogger(__name__), "tutor_teaching_terminal_conflict",
            run_id=run_id, code="TUTOR_TEACHING_TERMINAL_CONFLICT", stage=f"cause_{depth}",
            action_identifier=safe_diagnostic_identifier(str(cause), trusted=False),
            field_path=field, exception=cause,
        )
        cause = cause.__cause__


class PostgresTutorSkillSelectionStore:
    """Durable exact-Skill evidence adapter shared by catalog gates and effects."""

    def __init__(self, *, repository: PostgresTutorRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def get(self, *, run_id: str, input_revision: int) -> TutorSkillSelection | None:
        return self._repository.load_skill_selection(
            user_id=self._user_id,
            run_id=run_id,
            input_revision=input_revision,
        )

    def record(
        self,
        *,
        run_id: str,
        input_revision: int,
        selection: TutorSkillSelection,
    ) -> None:
        self._repository.record_skill_selection(
            user_id=self._user_id,
            run_id=run_id,
            input_revision=input_revision,
            selection=selection,
        )


class PostgresTutorPublicThinkingSink(TutorPublicThinkingSink):
    """Short-transaction public thinking writer fenced by run lease and revision."""

    def __init__(
        self,
        *,
        repository: PostgresTutorRepository,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        now: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._snapshot = snapshot
        self._lease = lease
        self._decision_iteration = decision_iteration
        self._now = now
        self._generation_counter = 0
        self._generation: int | None = None
        self._attempt_index: int | None = None

    def begin_attempt(self, attempt_index: int) -> None:
        self._start_generation(attempt_index)

    def append_text(self, attempt_index: int, text: str) -> None:
        generation = self._require_current(attempt_index)
        occurred_at = self._renew_lease()
        try:
            self._repository.append_public_thinking_text(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                text=text,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking append lost lifecycle ownership") from exc

    def complete_attempt(self, attempt_index: int) -> None:
        generation = self._require_current(attempt_index)
        occurred_at = self._renew_lease()
        try:
            self._repository.complete_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking completion lost lifecycle ownership") from exc

    def reset_attempt(self, attempt_index: int) -> None:
        self._start_generation(attempt_index)

    def discard_attempt(self, attempt_index: int) -> None:
        generation = self._require_current(attempt_index)
        self._discard(generation=generation, attempt_index=attempt_index)

    def discard_current(self) -> None:
        if self._generation is None or self._attempt_index is None:
            return
        self._discard(generation=self._generation, attempt_index=self._attempt_index)

    def _start_generation(self, attempt_index: int) -> None:
        if attempt_index < 1:
            raise ValueError("provider attempt index must be positive")
        self._generation_counter += 1
        generation = self._decision_iteration * 10_000 + self._generation_counter
        occurred_at = self._renew_lease()
        try:
            self._repository.begin_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                decision_iteration=self._decision_iteration,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking generation lost lifecycle ownership") from exc
        self._generation = generation
        self._attempt_index = attempt_index

    def _discard(self, *, generation: int, attempt_index: int) -> None:
        occurred_at = self._renew_lease()
        try:
            self._repository.discard_public_thinking_stream(
                snapshot=self._snapshot,
                lease=self._lease,
                generation=generation,
                provider_attempt=attempt_index,
                occurred_at=occurred_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("public thinking discard lost lifecycle ownership") from exc

    def _renew_lease(self) -> datetime:
        occurred_at = self._now()
        renewed = self._repository.heartbeat_lease(
            user_id=self._snapshot.user_id,
            lease=self._lease,
            now=occurred_at,
            duration_seconds=self._snapshot.policy.lease_duration_seconds,
        )
        if renewed is None:
            raise TutorLifecycleConflict("public thinking stream lease is unavailable")
        self._lease = renewed
        return occurred_at

    def _require_current(self, attempt_index: int) -> int:
        if self._generation is None or self._attempt_index != attempt_index:
            raise TutorLifecycleConflict("public thinking callback used a stale provider attempt")
        return self._generation


class PostgresTutorLifecycle(TutorLifecyclePersistence):
    """Adapter that gives ``TutorRunLoop`` one atomic persistence boundary."""

    def __init__(
        self,
        *,
        repository: PostgresTutorRepository,
        memory_setting_version: str = _DEFAULT_MEMORY_SETTING_VERSION,
        priority: int = 0,
        intent_resolution_enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._memory_setting_version = memory_setting_version
        self._priority = priority
        self._intent_resolution_enabled = intent_resolution_enabled

    def create_public_thinking_sink(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision_iteration: int,
        now: Callable[[], datetime],
    ) -> TutorPublicThinkingSink:
        return PostgresTutorPublicThinkingSink(
            repository=self._repository,
            snapshot=snapshot,
            lease=lease,
            decision_iteration=decision_iteration,
            now=now,
        )

    def persist_provider_attempts(
        self,
        *,
        snapshot: TutorRunSnapshot,
        decision_iteration: int,
        attempts: tuple[TutorProviderAttemptReceipt, ...],
        created_at: datetime,
    ) -> None:
        try:
            self._repository.record_provider_attempts(
                snapshot=snapshot,
                decision_iteration=decision_iteration,
                attempts=attempts,
                created_at=created_at,
            )
        except TutorPersistenceError as exc:
            raise TutorLifecycleConflict("Tutor provider attempt persistence conflicted") from exc

    def persist_safe_checkpoint(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        compaction_request: TutorCompactionRequest,
    ) -> None:
        try:
            self._repository.persist_safe_checkpoint(
                user_id=snapshot.user_id,
                lease=lease,
                checkpoint=checkpoint,
                envelope=self._envelope(compaction_request, created_at=checkpoint.created_at),
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor checkpoint lifecycle lost ownership") from exc

    def persist_context_high_water(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        request: TutorCompactionRequest,
        created_at: datetime,
    ) -> None:
        try:
            self._repository.persist_context_high_water(
                user_id=snapshot.user_id,
                lease=lease,
                request=request,
                envelope=self._envelope(request, created_at=created_at),
                created_at=created_at,
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor compaction lifecycle lost ownership") from exc

    def persist_terminal(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        checkpoint: TutorCheckpoint,
        result: TutorRunResult,
        compaction_request: TutorCompactionRequest,
    ) -> TutorRunResult:
        try:
            return self._repository.complete_run(
                user_id=snapshot.user_id,
                lease=lease,
                checkpoint=checkpoint,
                result=result,
                envelope=self._envelope(compaction_request, created_at=checkpoint.created_at),
            )
        except TutorTerminalStateConflict as exc:
            teaching = self._repository._conn.execute(
                "SELECT 1 FROM tutor_run_teaching_scopes WHERE run_id=%s AND user_id=%s",
                (snapshot.run_id, snapshot.user_id),
            ).fetchone()
            if teaching is None:
                raise TutorLifecycleConflict("Tutor terminal lifecycle lost ownership") from exc
            _log_teaching_terminal_conflict(exc, run_id=snapshot.run_id)
            self._repository.request_cancellation(
                user_id=snapshot.user_id, run_id=snapshot.run_id, now=checkpoint.created_at,
                diagnostic_code="teaching_authority_stale",
            )
            state = self._repository.read_run_state(user_id=snapshot.user_id, run_id=snapshot.run_id)
            return TutorRunResult(
                run_id=state.snapshot.run_id, status=state.snapshot.status,
                input_revision=state.snapshot.input_revision, iteration_count=state.snapshot.iteration_count,
                model_call_count=state.snapshot.model_call_count,
                capability_call_count=state.snapshot.capability_call_count, effect_count=state.snapshot.effect_count,
                terminal_outcome=state.terminal_outcome, diagnostic_code=state.diagnostic_code,
            )
        except TutorLeaseConflict as exc:
            raise TutorLifecycleConflict("Tutor terminal lifecycle lost ownership") from exc

    def persist_interaction_request(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        decision: "TutorDecision",
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        try:
            return self._repository.record_interaction_request(
                user_id=snapshot.user_id,
                lease=lease,
                decision=decision,
                result=result,
                created_at=created_at,
                intent_resolution_enabled=self._intent_resolution_enabled,
            )
        except (
            TutorInteractionRequestConflict,
            TutorLeaseConflict,
            TutorTerminalStateConflict,
        ) as exc:
            raise TutorLifecycleConflict("Tutor interaction-request lifecycle lost ownership") from exc

    def persist_waiting_result(
        self,
        *,
        snapshot: TutorRunSnapshot,
        lease: TutorLease,
        result: TutorRunResult,
        created_at: datetime,
    ) -> TutorRunResult:
        try:
            return self._repository.record_waiting_result(
                user_id=snapshot.user_id,
                lease=lease,
                result=result,
                created_at=created_at,
            )
        except (TutorLeaseConflict, TutorTerminalStateConflict) as exc:
            raise TutorLifecycleConflict("Tutor waiting lifecycle lost ownership") from exc

    def _envelope(self, request: TutorCompactionRequest, *, created_at: datetime) -> TutorCurationEnvelope:
        return TutorCurationEnvelope(
            request=request,
            memory_setting_version=self._memory_setting_version,
            priority=self._priority,
            retention_until=created_at + timedelta(days=_DEFAULT_RETENTION_DAYS),
            stale_after=created_at + timedelta(days=_DEFAULT_STALE_DAYS),
        )


class PostgresTutorRunStore(TutorRunStore):
    """User-scoped ``TutorRunStore`` adapter; pair it with ``PostgresTutorLifecycle``."""

    def __init__(self, *, repository: PostgresTutorRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def load_snapshot(self, run_id: str) -> TutorRunSnapshot | None:
        return self._repository.load_snapshot(user_id=self._user_id, run_id=run_id)

    def acquire_lease(self, run_id: str, *, owner_id: str, now: datetime, duration_seconds: int) -> TutorLease | None:
        return self._repository.acquire_lease(
            user_id=self._user_id,
            run_id=run_id,
            owner_id=owner_id,
            now=now,
            duration_seconds=duration_seconds,
        )

    def heartbeat_lease(self, lease: TutorLease, *, now: datetime, duration_seconds: int) -> TutorLease | None:
        return self._repository.heartbeat_lease(
            user_id=self._user_id,
            lease=lease,
            now=now,
            duration_seconds=duration_seconds,
        )

    def current_input_revision(self, run_id: str) -> int:
        return self._repository.current_input_revision(user_id=self._user_id, run_id=run_id)

    def is_cancelled(self, run_id: str) -> bool:
        return self._repository.is_cancelled(user_id=self._user_id, run_id=run_id)

    def is_superseded(self, run_id: str) -> bool:
        return self._repository.is_superseded(user_id=self._user_id, run_id=run_id)

    def save_checkpoint(self, checkpoint: TutorCheckpoint) -> None:
        raise RuntimeError("PostgresTutorRunStore requires PostgresTutorLifecycle for checkpoint persistence")

    def record_result(self, result: TutorRunResult) -> None:
        raise RuntimeError("PostgresTutorRunStore requires PostgresTutorLifecycle for result persistence")
