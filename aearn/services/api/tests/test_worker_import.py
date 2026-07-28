import aearn_worker.worker_app as worker_app


celery_app = worker_app.celery_app


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


class _WorkerGateResult:
    def __init__(self, row: dict[str, str | None] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, str | None] | None:
        return self._row


class _WorkerGateConnection:
    def __init__(self, row: dict[str, str | None] | None) -> None:
        self._row = row
        self.calls = 0

    def execute(self, _query: str, _params: tuple[str]) -> _WorkerGateResult:
        self.calls += 1
        return _WorkerGateResult(self._row)


def test_legacy_review_worker_gate_blocks_every_rollout_cutover_state(monkeypatch) -> None:
    monkeypatch.setenv("TUTOR_HARNESS_ENABLED", "true")

    expected = {
        None: "CUTOVER_REQUIRED",
        "required": "CUTOVER_REQUIRED",
        "summary_ready": "CUTOVER_REQUIRED",
        "verification_failed": "CUTOVER_VERIFICATION_FAILED",
        "blocked_target_state": "CUTOVER_TARGET_STATE_PRESENT",
        "blocked_checkpoint_scope": "CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED",
        "verified": "CUTOVER_REQUIRED",
    }
    for state, code in expected.items():
        row = None if state is None else {"state": state, "failure_code": None}
        conn = _WorkerGateConnection(row)
        assert worker_app._legacy_worker_gate_code(conn, "00000000-0000-0000-0000-000000000001") == code
        assert conn.calls == 1

    monkeypatch.setenv("TUTOR_HARNESS_ENABLED", "false")
    disabled_conn = _WorkerGateConnection({"state": "verified", "failure_code": None})
    assert worker_app._legacy_worker_gate_code(disabled_conn, "00000000-0000-0000-0000-000000000001") is None
    assert disabled_conn.calls == 0
