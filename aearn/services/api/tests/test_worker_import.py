import aearn_worker.worker_app as worker_app


celery_app = worker_app.celery_app


def test_worker_registers_health_interactive_and_target_scheduler_tasks() -> None:
    assert celery_app.main == "aearn-worker"
    assert "health.ping" in celery_app.tasks
    assert "review.refresh_due_counts" not in celery_app.tasks
    assert "review.generate_seed_bank" not in celery_app.tasks
    assert "tutor.interactive.dispatch" in celery_app.tasks
    assert "tutor.interactive.reconcile" in celery_app.tasks
    assert "tutor.proactive.scan_due_signals" in celery_app.tasks
    assert "tutor.proactive.drain_candidates" in celery_app.tasks
    assert "tutor.curation.drain" in celery_app.tasks
    assert celery_app.conf.task_routes["tutor.interactive.dispatch"]["queue"] == "tutor-interactive"
    assert celery_app.conf.task_routes["tutor.interactive.reconcile"]["priority"] == 8
    assert celery_app.conf.beat_schedule["tutor-interactive-reconcile"]["schedule"] == 5.0
    assert celery_app.conf.task_routes["tutor.proactive.scan_due_signals"]["queue"] == "tutor-proactive"
    assert celery_app.conf.task_routes["tutor.curation.drain"]["queue"] == "tutor-curation"
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert celery_app.conf.enable_utc is True
