from aearn_worker.worker_app import celery_app


def test_worker_registers_health_and_target_scheduler_tasks_without_replacing_legacy_review_work() -> None:
    assert celery_app.main == "aearn-worker"
    assert "health.ping" in celery_app.tasks
    assert "review.refresh_due_counts" in celery_app.tasks
    assert "review.generate_seed_bank" in celery_app.tasks
    assert "tutor.proactive.scan_due_signals" in celery_app.tasks
    assert "tutor.proactive.drain_candidates" in celery_app.tasks
    assert "tutor.curation.drain" in celery_app.tasks
    assert celery_app.conf.task_routes["tutor.proactive.scan_due_signals"]["queue"] == "tutor-proactive"
    assert celery_app.conf.task_routes["tutor.curation.drain"]["queue"] == "tutor-curation"
    assert celery_app.conf.timezone == "Asia/Shanghai"
    assert celery_app.conf.enable_utc is True
