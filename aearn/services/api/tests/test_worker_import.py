from aearn_worker.worker_app import celery_app


def test_worker_registers_health_task() -> None:
    assert celery_app.main == "aearn-worker"
    assert "health.ping" in celery_app.tasks
    assert "review.refresh_due_counts" in celery_app.tasks
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert celery_app.conf.enable_utc is True
