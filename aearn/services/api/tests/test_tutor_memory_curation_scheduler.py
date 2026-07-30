from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agents.harness.contracts import (
    TutorCheckpoint,
    TutorCheckpointReason,
    TutorCompactionTrigger,
    TutorRunStatus,
    build_compaction_request,
    empty_checkpoint_metadata,
)
from app.services.tutor.persistence import TutorCurationEnvelope
from app.services.tutor.proactive import (
    CurationProcessOutcome,
    TutorProactivePreference,
    TutorProactiveScheduler,
    TutorProactiveSchedulerConfig,
)
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository


_NOW = datetime(2026, 7, 28, 10, 0, tzinfo=UTC)


def _config(*, hard_paused: bool = False, inferred_memory_enabled: bool = True, curation_budget: int = 3) -> TutorProactiveSchedulerConfig:
    return TutorProactiveSchedulerConfig(
        enabled=True,
        hard_paused=hard_paused,
        cutover_eligible=True,
        inferred_memory_enabled=inferred_memory_enabled,
        proactive_daily_budget=3,
        curation_daily_budget=curation_budget,
        proactive_concurrency_limit=1,
        curation_concurrency_limit=1,
        proactive_cooldown_seconds=1,
        curation_cooldown_seconds=1,
        proactive_circuit_failure_threshold=2,
        curation_circuit_failure_threshold=2,
        circuit_window_seconds=60,
        candidate_lease_seconds=60,
        curation_lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )


def _enable_preference(repository: PostgresTutorProactiveRepository, fixture) -> None:
    repository.upsert_preference(
        preference=TutorProactivePreference(user_id=fixture.user_id, enabled=True),
        now=_NOW,
    )


def _create_outbox_for_run(
    fixture,
    *,
    user_id: str,
    conversation_id: str,
    run_id: str,
) -> str:
    lease = fixture.repository.acquire_lease(
        user_id=user_id,
        run_id=run_id,
        owner_id="curation-scheduler-fixture",
        now=_NOW,
        duration_seconds=60,
    )
    assert lease is not None
    checkpoint = TutorCheckpoint(
        run_id=run_id,
        input_revision=0,
        reason=TutorCheckpointReason.SAFE_PROGRESS,
        status=TutorRunStatus.LEASED,
        metadata=empty_checkpoint_metadata(token_budget=64),
        created_at=_NOW,
    )
    request = build_compaction_request(
        run_id=run_id,
        conversation_id=conversation_id,
        input_revision=0,
        trigger=TutorCompactionTrigger.SAFE_CHECKPOINT,
        metadata=empty_checkpoint_metadata(token_budget=64),
    )
    fixture.repository.persist_safe_checkpoint(
        user_id=user_id,
        lease=lease,
        checkpoint=checkpoint,
        envelope=TutorCurationEnvelope(
            request=request,
            memory_setting_version="memory_settings_v1",
            priority=1,
            retention_until=_NOW + timedelta(days=30),
            stale_after=_NOW + timedelta(days=7),
        ),
    )
    row = fixture.connection.execute(
        "SELECT id::text AS id FROM tutor_memory_curation_outbox WHERE run_id = %s",
        (run_id,),
    ).fetchone()
    assert row is not None
    return str(row["id"])


def _create_outbox(fixture) -> str:
    return _create_outbox_for_run(
        fixture,
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        run_id=fixture.run.run_id,
    )


def _create_other_user_outbox(fixture) -> tuple[str, str]:
    row = fixture.connection.execute(
        "INSERT INTO users (display_name) VALUES ('Tutor Curation Other User') RETURNING id::text AS id"
    ).fetchone()
    assert row is not None
    user_id = str(row["id"])
    conversation_id = fixture.repository.create_conversation(user_id=user_id)
    run = fixture.repository.create_run(
        user_id=user_id,
        conversation_id=conversation_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        origin="interactive",
    )
    return (
        user_id,
        _create_outbox_for_run(
            fixture,
            user_id=user_id,
            conversation_id=conversation_id,
            run_id=run.run_id,
        ),
    )


class _RecordingProcessor:
    def __init__(self, state: str = "completed") -> None:
        self.state = state
        self.calls: list[str] = []

    def process(self, *, job, lease_owner_id: str, now: datetime) -> CurationProcessOutcome:
        del lease_owner_id, now
        self.calls.append(job.job_id)
        return CurationProcessOutcome(state=self.state, code=f"processor_{self.state}")  # type: ignore[arg-type]


def test_curation_job_seeding_is_idempotent_and_hard_pause_prevents_processor_call(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    outbox_id = _create_outbox(fixture)
    processor = _RecordingProcessor()
    scheduler = TutorProactiveScheduler(
        store=repository,
        config=_config(hard_paused=True),
        curation_processor=processor,
    )

    seeded = scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    replayed_seed = scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    result = scheduler.drain_curation(worker_id="curation-worker", now=_NOW, user_id=fixture.user_id)
    row = fixture.connection.execute(
        "SELECT state, no_action_code, processor_started_at FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert len(seeded) == 1
    assert replayed_seed == ()
    assert result.claimed == 1
    assert result.no_action == 1
    assert processor.calls == []
    assert row == {
        "state": "no_action",
        "no_action_code": "background_hard_paused",
        "processor_started_at": None,
    }


def test_inferred_memory_and_curation_budget_denials_never_invoke_processor(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    outbox_id = _create_outbox(fixture)
    disabled_processor = _RecordingProcessor()
    disabled_scheduler = TutorProactiveScheduler(
        store=repository,
        config=_config(inferred_memory_enabled=False),
        curation_processor=disabled_processor,
    )
    disabled_scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    disabled_scheduler.drain_curation(worker_id="memory-disabled", now=_NOW, user_id=fixture.user_id)
    disabled_row = fixture.connection.execute(
        "SELECT state, no_action_code FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert disabled_processor.calls == []
    assert disabled_row == {"state": "no_action", "no_action_code": "inferred_memory_disabled"}


def test_stale_outbox_source_revision_becomes_stale_without_processor_call(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    outbox_id = _create_outbox(fixture)
    processor = _RecordingProcessor()
    scheduler = TutorProactiveScheduler(store=repository, config=_config(), curation_processor=processor)
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)
    fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="curation-scheduler-newer-input",
        content="A newer input makes the old curation range stale.",
    )

    result = scheduler.drain_curation(worker_id="stale-worker", now=_NOW, user_id=fixture.user_id)
    row = fixture.connection.execute(
        "SELECT state, no_action_code FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert result.claimed == 1
    assert result.no_action == 1
    assert processor.calls == []
    assert row == {"state": "stale", "no_action_code": "outbox_source_revision_stale"}


def test_retryable_curation_processor_uses_backoff_then_reclaims_once(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    _create_outbox(fixture)
    processor = _RecordingProcessor(state="retryable")
    scheduler = TutorProactiveScheduler(store=repository, config=_config(), curation_processor=processor)
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)

    first = scheduler.drain_curation(worker_id="retry-worker", now=_NOW, user_id=fixture.user_id)
    before_backoff = scheduler.drain_curation(
        worker_id="retry-worker", now=_NOW + timedelta(seconds=4), user_id=fixture.user_id
    )
    after_backoff = scheduler.drain_curation(
        worker_id="retry-worker", now=_NOW + timedelta(seconds=5), user_id=fixture.user_id
    )

    assert first.claimed == 1
    assert first.retried == 1
    assert before_backoff.claimed == 0
    assert after_backoff.claimed == 1
    assert processor.calls and len(processor.calls) == 2


def test_curation_budget_denial_never_invokes_processor(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    outbox_id = _create_outbox(fixture)
    processor = _RecordingProcessor()
    scheduler = TutorProactiveScheduler(
        store=repository,
        config=_config(curation_budget=0),
        curation_processor=processor,
    )
    scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id)

    result = scheduler.drain_curation(worker_id="budget-worker", now=_NOW, user_id=fixture.user_id)
    row = fixture.connection.execute(
        "SELECT state, no_action_code FROM tutor_curation_jobs WHERE outbox_id = %s",
        (outbox_id,),
    ).fetchone()

    assert result.claimed == 1
    assert result.no_action == 1
    assert processor.calls == []
    assert row == {"state": "no_action", "no_action_code": "curation_budget_exhausted"}


def test_scoped_curation_queue_drain_never_mutates_another_users_pending_or_expired_job(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    processor = _RecordingProcessor()
    scheduler = TutorProactiveScheduler(store=repository, config=_config(), curation_processor=processor)
    other_user_id, other_outbox_id = _create_other_user_outbox(fixture)

    assert scheduler.seed_curation_jobs(now=_NOW, user_id=fixture.user_id) == ()
    assert fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_curation_jobs WHERE outbox_id = %s",
        (other_outbox_id,),
    ).fetchone() == {"count": 0}

    seeded = scheduler.seed_curation_jobs(now=_NOW, user_id=other_user_id)
    assert len(seeded) == 1
    audit_count = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_scheduler_audit WHERE curation_job_id = %s",
        (seeded[0].job_id,),
    ).fetchone()

    pending_drain = scheduler.drain_curation(
        worker_id="scoped-worker",
        now=_NOW,
        user_id=fixture.user_id,
    )
    pending = fixture.connection.execute(
        """
        SELECT user_id::text AS user_id, state, attempt_count, lease_owner_id,
               lease_generation, lease_expires_at
        FROM tutor_curation_jobs
        WHERE outbox_id = %s
        """,
        (other_outbox_id,),
    ).fetchone()

    assert pending_drain.claimed == 0
    assert pending == {
        "user_id": other_user_id,
        "state": "pending",
        "attempt_count": 0,
        "lease_owner_id": None,
        "lease_generation": 0,
        "lease_expires_at": None,
    }

    fixture.connection.execute(
        """
        UPDATE tutor_curation_jobs
        SET state = 'leased',
            attempt_count = 1,
            lease_owner_id = 'foreign-worker',
            lease_generation = 1,
            lease_expires_at = %s,
            updated_at = %s
        WHERE outbox_id = %s
        """,
        (_NOW - timedelta(seconds=1), _NOW, other_outbox_id),
    )

    expired_drain = scheduler.drain_curation(
        worker_id="scoped-worker",
        now=_NOW,
        user_id=fixture.user_id,
    )
    expired = fixture.connection.execute(
        """
        SELECT user_id::text AS user_id, state, attempt_count, lease_owner_id,
               lease_generation, lease_expires_at, last_error_code
        FROM tutor_curation_jobs
        WHERE outbox_id = %s
        """,
        (other_outbox_id,),
    ).fetchone()
    audit_count_after = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_scheduler_audit WHERE curation_job_id = %s",
        (seeded[0].job_id,),
    ).fetchone()

    assert expired_drain.claimed == 0
    assert expired == {
        "user_id": other_user_id,
        "state": "leased",
        "attempt_count": 1,
        "lease_owner_id": "foreign-worker",
        "lease_generation": 1,
        "lease_expires_at": _NOW - timedelta(seconds=1),
        "last_error_code": None,
    }
    assert audit_count_after == audit_count == {"count": 1}
    assert processor.calls == []
