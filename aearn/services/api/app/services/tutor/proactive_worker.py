"""Feature-disabled API-side entry points for narrow Celery scheduler wrappers."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from app.core.config import Settings, get_settings
from app.db.connection import connect
from app.services.tutor.curation import build_curation_proposal_processor
from app.services.tutor.proactive import TutorProactiveScheduler, TutorProactiveSchedulerConfig
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository


SchedulerOperation = Literal["scan_due_signals", "drain_candidates", "drain_curation"]


def run_tutor_scheduler_operation(
    *,
    operation: SchedulerOperation,
    limit: int = 10,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    """Run only bounded target operations; no public delivery or model composition is enabled here."""
    if limit <= 0:
        raise ValueError("scheduler task limit must be positive")
    resolved_settings = settings or get_settings()
    config = TutorProactiveSchedulerConfig.from_settings(resolved_settings)
    if not config.enabled:
        return {"status": "blocked_policy", "code": "scheduler_disabled", "processed": 0}
    current_time = (now or datetime.now(UTC)).astimezone(UTC)
    if operation == "scan_due_signals":
        return {"status": "no_action", "code": "no_due_time_signal_source", "processed": 0}
    with connect() as conn:
        repository = PostgresTutorProactiveRepository(conn)
        scheduler = TutorProactiveScheduler(
            store=repository,
            config=config,
            curation_processor=build_curation_proposal_processor(conn=conn, settings=resolved_settings),
        )
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
