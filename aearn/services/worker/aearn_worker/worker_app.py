import os
import socket
from datetime import UTC, datetime
from pathlib import Path

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import worker_shutdown  # type: ignore[import-untyped]
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[3]
load_dotenv(ROOT_DIR / ".env")

celery_app = Celery(
    "aearn-worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/1"),
)
celery_app.conf.update(timezone="Asia/Shanghai", enable_utc=True)
celery_app.conf.beat_schedule = {
    "tutor-interactive-reconcile": {
        "task": "tutor.interactive.reconcile",
        "schedule": 5.0,
        "args": (10,),
        "options": {"queue": "tutor-interactive", "priority": 8},
    },
    "tutor-codex-runtime-health": {
        "task": "tutor.codex.runtime_health",
        "schedule": 10.0,
        "options": {"queue": "tutor-codex", "priority": 9},
    },
    "tutor-codex-reconcile": {
        "task": "tutor.codex.reconcile",
        "schedule": 5.0,
        "args": (10,),
        "options": {"queue": "tutor-codex", "priority": 8},
    },
}
celery_app.conf.task_routes = {
    "tutor.interactive.dispatch": {"queue": "tutor-interactive", "priority": 9},
    "tutor.interactive.reconcile": {"queue": "tutor-interactive", "priority": 8},
    "tutor.proactive.scan_due_signals": {"queue": "tutor-proactive", "priority": 5},
    "tutor.proactive.drain_candidates": {"queue": "tutor-proactive", "priority": 5},
    "tutor.curation.drain": {"queue": "tutor-curation", "priority": 1},
    "tutor.codex.dispatch": {"queue": "tutor-codex", "priority": 9},
    "tutor.codex.reconcile": {"queue": "tutor-codex", "priority": 8},
    "tutor.codex.runtime_health": {"queue": "tutor-codex", "priority": 9},
    "tutor.codex.runtime_shutdown": {"queue": "tutor-codex", "priority": 9},
}


def _run_tutor_interactive_task(
    operation: str,
    *,
    job_id: str | None = None,
    limit: int = 10,
    runtime_kind: str = "harness_v1",
) -> dict[str, object]:
    """Keep Celery thin: API-side services own dispatch leases and Harness policy."""

    try:
        from app.services.tutor.interactive_worker import run_tutor_interactive_worker_operation
    except ImportError:
        return {
            "status": "blocked_policy",
            "code": "api_interactive_worker_unavailable",
            "processed": 0,
        }
    return run_tutor_interactive_worker_operation(
        operation=operation,
        job_id=job_id,
        limit=limit,
        runtime_kind=(
            "codex_sidecar_v1" if runtime_kind == "codex_sidecar_v1" else "harness_v1"
        ),
    )


def _run_tutor_codex_task(operation: str) -> dict[str, object]:
    """Run one dedicated Codex worker operation and persist bounded readiness."""
    try:
        from app.agents.runtime.worker_host import run_codex_worker_operation
    except ImportError:
        return {"status": "unavailable", "safe_error_code": "api_codex_runtime_unavailable"}
    try:
        result = run_codex_worker_operation(operation)
    except Exception:
        result = {"status": "unavailable", "safe_error_code": "codex_runtime_operation_failed"}
    if operation == "health":
        try:
            from app.db.connection import connect
            from app.services.tutor.runtime_selection import PostgresTutorCodexRuntimeReadinessRepository

            with connect() as conn:
                PostgresTutorCodexRuntimeReadinessRepository(conn).record(
                    worker_id=f"tutor-codex:{socket.gethostname()}",
                    status=str(result.get("status") or "unavailable"),
                    generation=_safe_int(result.get("generation")),
                    runtime_version=_optional_text(result.get("version")),
                    model=_optional_text(result.get("model")),
                    model_provider=_optional_text(result.get("model_provider")),
                    protocol="responses",
                    safe_error_code=_optional_text(result.get("safe_error_code")),
                    observed_at=datetime.now(UTC),
                )
                conn.commit()
        except Exception:
            return {"status": "unavailable", "safe_error_code": "codex_readiness_persist_failed"}
    return result


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_int(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _run_tutor_scheduler_task(operation: str, *, limit: int) -> dict[str, object]:
    """Keep Celery thin: API-side services own PostgreSQL state and policy."""
    try:
        from app.core.config import get_settings
        from app.db.connection import connect
        from app.services.tutor.thread_turn_cutover import TutorThreadTurnCutoverService
        with connect() as conn:
            TutorThreadTurnCutoverService(conn).assert_mutation_allowed(settings=get_settings())
    except Exception as exc:
        return {
            "status": "blocked_policy",
            "code": getattr(exc, "code", "api_scheduler_service_unavailable"),
            "processed": 0,
        }
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


@celery_app.task(name="tutor.interactive.dispatch", queue="tutor-interactive", priority=9)
def dispatch_interactive_run(job_id: str | None = None) -> dict[str, object]:
    return _run_tutor_interactive_task("dispatch", job_id=job_id, limit=1)


@celery_app.task(name="tutor.interactive.reconcile", queue="tutor-interactive", priority=8)
def reconcile_interactive_runs(limit: int = 10) -> dict[str, object]:
    return _run_tutor_interactive_task("reconcile", limit=limit)


@celery_app.task(name="tutor.codex.dispatch", queue="tutor-codex", priority=9)
def dispatch_codex_run(job_id: str | None = None) -> dict[str, object]:
    return _run_tutor_interactive_task(
        "dispatch",
        job_id=job_id,
        limit=1,
        runtime_kind="codex_sidecar_v1",
    )


@celery_app.task(name="tutor.codex.reconcile", queue="tutor-codex", priority=8)
def reconcile_codex_runs(limit: int = 10) -> dict[str, object]:
    return _run_tutor_interactive_task(
        "reconcile",
        limit=limit,
        runtime_kind="codex_sidecar_v1",
    )


@celery_app.task(name="tutor.proactive.scan_due_signals", queue="tutor-proactive", priority=5)
def scan_due_signals(limit: int = 20) -> dict[str, object]:
    return _run_tutor_scheduler_task("scan_due_signals", limit=limit)


@celery_app.task(name="tutor.proactive.drain_candidates", queue="tutor-proactive", priority=5)
def drain_proactive_candidates(limit: int = 10) -> dict[str, object]:
    return _run_tutor_scheduler_task("drain_candidates", limit=limit)


@celery_app.task(name="tutor.curation.drain", queue="tutor-curation", priority=1)
def drain_curation(limit: int = 10) -> dict[str, object]:
    return _run_tutor_scheduler_task("drain_curation", limit=limit)


@celery_app.task(name="tutor.codex.runtime_health", queue="tutor-codex", priority=9)
def codex_runtime_health() -> dict[str, object]:
    return _run_tutor_codex_task("health")


@celery_app.task(name="tutor.codex.runtime_shutdown", queue="tutor-codex", priority=9)
def codex_runtime_shutdown() -> dict[str, object]:
    return _run_tutor_codex_task("shutdown")


@worker_shutdown.connect
def shutdown_codex_runtime_on_worker_exit(**_: object) -> None:
    _run_tutor_codex_task("shutdown")
