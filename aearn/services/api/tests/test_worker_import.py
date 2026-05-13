from aearn_worker.worker_app import celery_app


def test_worker_registers_health_task() -> None:
    assert celery_app.main == "aearn-worker"
    assert "health.ping" in celery_app.tasks
