"""PostgreSQL-authoritative worker flow for interactive Tutor dispatch jobs."""
from __future__ import annotations

import logging
import socket
from time import monotonic
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.safe_diagnostics import log_safe_event
from app.db.connection import connect
from app.services.tutor.continuation import TutorContinuationDispatcher
from app.services.tutor.interactive import TutorRunDispatcher, build_tutor_run_dispatcher
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.queue_control import PostgresTutorQueueController, build_queue_turn_policy
from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService
from app.agents.harness.contracts import TutorTerminalOutcome
from app.agents.harness.skill_catalog import compile_published_skill_catalog


logger = logging.getLogger(__name__)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class TutorInteractiveWorker:
    """Claim one durable job before invoking the existing finite Harness dispatcher."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        dispatcher: TutorRunDispatcher | None = None,
        clock: Clock | None = None,
        owner_id: str | None = None,
        runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
    ) -> None:
        self._settings = settings or get_settings()
        self._runtime_kind = runtime_kind
        if dispatcher is not None:
            self._dispatcher = dispatcher
        elif runtime_kind == "codex_sidecar_v1":
            from app.services.tutor.codex_dispatcher import CodexTutorRunDispatcher

            self._dispatcher = build_tutor_run_dispatcher(
                self._settings,
                codex_dispatcher=CodexTutorRunDispatcher(settings=self._settings),
            )
        else:
            self._dispatcher = build_tutor_run_dispatcher(self._settings)
        self._clock = clock or UtcClock()
        worker_name = "tutor-codex" if runtime_kind == "codex_sidecar_v1" else "tutor-interactive"
        self._owner_id = owner_id or f"{worker_name}:{uuid4().hex}"

    def dispatch_job(self, *, job_id: str | None = None) -> dict[str, object]:
        with connect() as conn:
            try:
                TutorThreadTurnCutoverService(conn).assert_mutation_allowed(settings=self._settings)
            except Exception as exc:
                code = getattr(exc, "code", "TUTOR_THREAD_TURN_V2_UNAVAILABLE")
                return {"status": "blocked_policy", "processed": 0, "job_id": job_id, "code": code}
        claimed_at = self._clock.now()
        with connect() as conn:
            repository = PostgresTutorRepository(conn)
            claims = repository.claim_interactive_dispatch_jobs(
                owner_id=self._owner_id,
                now=claimed_at,
                limit=1,
                job_id=job_id,
                runtime_kind=self._runtime_kind,
            )
        if not claims:
            return {"status": "no_action", "processed": 0, "job_id": job_id}
        claim = claims[0]
        started = monotonic()
        try:
            run_result = self._dispatcher.dispatch(user_id=claim.user_id, run_id=claim.run_id)
        except Exception as exc:  # noqa: BLE001 - boundary maps exceptions to a bounded safe code.
            error_code = _safe_dispatch_error_code(exc)
            log_safe_event(
                logger, "tutor_dispatch_failed", exception=exc, stage="dispatch",
                code=error_code, job_id=claim.job_id, run_id=claim.run_id,
                attempt=claim.attempt_count, lease_generation=claim.lease_generation,
                runtime_kind=self._runtime_kind, duration_ms=(monotonic() - started) * 1000,
            )
            failed_at = self._clock.now()
            with connect() as conn:
                repository = PostgresTutorRepository(conn)
                updated = repository.retry_interactive_dispatch_job(
                    job_id=claim.job_id,
                    owner_id=self._owner_id,
                    lease_generation=claim.lease_generation,
                    error_code=error_code,
                    failed_at=failed_at,
                )
            state = updated.state.value if updated is not None else "stale"
            log_safe_event(
                logger, "tutor_dispatch_deferred", stage="retry_receipt",
                job_id=claim.job_id, run_id=claim.run_id, attempt=claim.attempt_count,
                code=error_code, state=state,
            )
            return {
                "status": state,
                "processed": 1,
                "job_id": claim.job_id,
                "run_id": claim.run_id,
                "attempt": claim.attempt_count,
                "code": error_code,
            }
        completed_at = self._clock.now()
        next_job_id: str | None = None
        next_runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] | None = None
        with connect() as conn:
            repository = PostgresTutorRepository(conn)
            completed = repository.complete_interactive_dispatch_job(
                job_id=claim.job_id,
                owner_id=self._owner_id,
                lease_generation=claim.lease_generation,
                completed_at=completed_at,
            )
            queue = PostgresTutorQueueController(conn)
            if completed and run_result.terminal_outcome is TutorTerminalOutcome.COMPLETED:
                continuation = TutorContinuationDispatcher(
                    conn,
                    settings=self._settings,
                ).dispatch_next(
                    user_id=claim.user_id,
                    conversation_id=claim.conversation_id,
                    claimant_id=f"{self._owner_id}:continuation",
                    now=completed_at,
                )
                if continuation is not None:
                    next_job_id = continuation.dispatch_job_id
                    next_runtime_kind = continuation.runtime_kind
                else:
                    catalog = compile_published_skill_catalog()
                    repository.record_catalog_snapshot(catalog)
                    drained = queue.drain_completed(
                        user_id=claim.user_id, conversation_id=claim.conversation_id,
                        catalog_digest=catalog.digest,
                        policy=build_queue_turn_policy(completed_at, settings=self._settings),
                        occurred_at=completed_at,
                    )
                    next_job_id = (
                        drained.acceptance.dispatch_job_id
                        if drained is not None
                        else None
                    )
                    next_runtime_kind = (
                        drained.run.runtime_kind if drained is not None else None
                    )
            elif completed:
                queue.pause_failed(user_id=claim.user_id, conversation_id=claim.conversation_id)
        if next_job_id is not None:
            enqueue_tutor_interactive_dispatch(next_job_id, runtime_kind=next_runtime_kind)
        return {
            "status": "completed" if completed else "stale",
            "processed": 1,
            "job_id": claim.job_id,
            "run_id": claim.run_id,
            "attempt": claim.attempt_count,
            "next_job_id": next_job_id,
        }

    def reconcile(self, *, limit: int = 10) -> dict[str, object]:
        if limit < 1 or limit > 50:
            raise ValueError("interactive reconcile limit must be within 1..50")
        results: list[dict[str, object]] = []
        for _index in range(limit):
            result = self.dispatch_job()
            if result.get("status") == "no_action":
                break
            results.append(result)
        return {
            "status": "completed",
            "processed": len(results),
            "completed": sum(1 for item in results if item.get("status") == "completed"),
            "deferred": sum(1 for item in results if item.get("status") in {"retry_wait", "dead"}),
        }


def run_tutor_interactive_worker_operation(
    *,
    operation: str,
    job_id: str | None = None,
    limit: int = 10,
    runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] = "harness_v1",
) -> dict[str, object]:
    worker = TutorInteractiveWorker(runtime_kind=runtime_kind)
    if operation == "dispatch":
        return worker.dispatch_job(job_id=job_id)
    if operation == "reconcile":
        return worker.reconcile(limit=limit)
    raise ValueError("unsupported Tutor interactive worker operation")


def enqueue_tutor_interactive_dispatch(
    job_id: str,
    *,
    runtime_kind: Literal["harness_v1", "codex_sidecar_v1"] | None = None,
) -> bool:
    """Best-effort wakeup to the queue that owns the frozen Runtime kind."""

    settings = get_settings()
    broker_url = getattr(settings, "celery_broker_url", None) or "redis://127.0.0.1:6379/0"
    if not _broker_endpoint_reachable(str(broker_url)):
        return False
    selected = runtime_kind or _dispatch_runtime_kind(job_id)
    if selected is None:
        return False
    try:
        if selected == "codex_sidecar_v1":
            from aearn_worker.worker_app import dispatch_codex_run

            dispatch_codex_run.apply_async(args=[job_id], queue="tutor-codex", priority=9, retry=False)
        else:
            from aearn_worker.worker_app import dispatch_interactive_run

            dispatch_interactive_run.apply_async(args=[job_id], queue="tutor-interactive", priority=9, retry=False)
        return True
    except Exception:  # noqa: BLE001 - wakeup loss is recovered from PostgreSQL.
        logger.warning("Tutor interactive Celery wakeup failed job_id=%s code=broker_unavailable", job_id)
        return False


def _dispatch_runtime_kind(
    job_id: str,
) -> Literal["harness_v1", "codex_sidecar_v1"] | None:
    try:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT runs.runtime_kind
                FROM tutor_interactive_dispatch_jobs AS jobs
                JOIN tutor_runs AS runs ON runs.id = jobs.run_id
                WHERE jobs.id = %s
                """,
                (job_id,),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    value = str(row.get("runtime_kind") or "harness_v1")
    return "codex_sidecar_v1" if value == "codex_sidecar_v1" else "harness_v1"


def _safe_dispatch_error_code(exc: Exception) -> str:
    del exc
    return "dispatch_failed"


def _broker_endpoint_reachable(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        return True
    port = parsed.port or 6379
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.05):
            return True
    except OSError:
        return False
