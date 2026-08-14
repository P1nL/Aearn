"""PostgreSQL-authoritative worker flow for interactive Tutor dispatch jobs."""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.db.connection import connect
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
    ) -> None:
        self._settings = settings or get_settings()
        self._dispatcher = dispatcher or build_tutor_run_dispatcher(self._settings)
        self._clock = clock or UtcClock()
        self._owner_id = owner_id or f"tutor-interactive:{uuid4().hex}"

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
            )
        if not claims:
            return {"status": "no_action", "processed": 0, "job_id": job_id}
        claim = claims[0]
        try:
            run_result = self._dispatcher.dispatch(user_id=claim.user_id, run_id=claim.run_id)
        except Exception as exc:  # noqa: BLE001 - boundary maps exceptions to a bounded safe code.
            error_code = _safe_dispatch_error_code(exc)
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
            logger.warning(
                "Tutor interactive dispatch deferred job_id=%s run_id=%s attempt=%s code=%s state=%s",
                claim.job_id,
                claim.run_id,
                claim.attempt_count,
                error_code,
                state,
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
                catalog = compile_published_skill_catalog()
                repository.record_catalog_snapshot(catalog)
                drained = queue.drain_completed(
                    user_id=claim.user_id, conversation_id=claim.conversation_id,
                    catalog_digest=catalog.digest,
                    policy=build_queue_turn_policy(completed_at, settings=self._settings),
                    occurred_at=completed_at,
                )
                next_job_id = drained.acceptance.dispatch_job_id if drained is not None else None
            elif completed:
                queue.pause_failed(user_id=claim.user_id, conversation_id=claim.conversation_id)
        if next_job_id is not None:
            enqueue_tutor_interactive_dispatch(next_job_id)
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
) -> dict[str, object]:
    worker = TutorInteractiveWorker()
    if operation == "dispatch":
        return worker.dispatch_job(job_id=job_id)
    if operation == "reconcile":
        return worker.reconcile(limit=limit)
    raise ValueError("unsupported Tutor interactive worker operation")


def enqueue_tutor_interactive_dispatch(job_id: str) -> bool:
    """Best-effort Celery wakeup; PostgreSQL reconciliation remains authoritative."""

    settings = get_settings()
    broker_url = getattr(settings, "celery_broker_url", None) or "redis://127.0.0.1:6379/0"
    if not _broker_endpoint_reachable(str(broker_url)):
        return False
    try:
        from aearn_worker.worker_app import dispatch_interactive_run

        dispatch_interactive_run.apply_async(args=[job_id], queue="tutor-interactive", priority=9, retry=False)
        return True
    except Exception:  # noqa: BLE001 - wakeup loss is recovered from PostgreSQL.
        logger.warning("Tutor interactive Celery wakeup failed job_id=%s code=broker_unavailable", job_id)
        return False


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
