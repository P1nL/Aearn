import os
from pathlib import Path

from celery import Celery
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

celery_app = Celery(
    "aearn-worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
)
celery_app.conf.update(timezone="Asia/Shanghai", enable_utc=True)
celery_app.conf.task_routes = {
    "tutor.proactive.scan_due_signals": {"queue": "tutor-proactive", "priority": 5},
    "tutor.proactive.drain_candidates": {"queue": "tutor-proactive", "priority": 5},
    "tutor.curation.drain": {"queue": "tutor-curation", "priority": 1},
}


def _run_tutor_scheduler_task(operation: str, *, limit: int) -> dict[str, object]:
    """Keep Celery thin: API-side services own PostgreSQL state and policy."""
    try:
        from app.services.tutor.proactive_worker import run_tutor_scheduler_operation
    except ImportError:
        return {
            "status": "blocked_policy",
            "code": "api_scheduler_service_unavailable",
            "processed": 0,
        }
    return run_tutor_scheduler_operation(operation=operation, limit=limit)  # type: ignore[arg-type]


@celery_app.task(name="health.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="tutor.proactive.scan_due_signals", queue="tutor-proactive", priority=5)
def scan_due_signals(limit: int = 20) -> dict[str, object]:
    return _run_tutor_scheduler_task("scan_due_signals", limit=limit)


@celery_app.task(name="tutor.proactive.drain_candidates", queue="tutor-proactive", priority=5)
def drain_proactive_candidates(limit: int = 10) -> dict[str, object]:
    return _run_tutor_scheduler_task("drain_candidates", limit=limit)


@celery_app.task(name="tutor.curation.drain", queue="tutor-curation", priority=1)
def drain_curation(limit: int = 10) -> dict[str, object]:
    return _run_tutor_scheduler_task("drain_curation", limit=limit)
