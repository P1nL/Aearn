from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from app.services.tutor.proactive import (
    TutorProactivePreference,
    TutorProactiveScheduler,
    TutorProactiveSchedulerConfig,
    TutorProactiveSignal,
)
from app.services.tutor.proactive_repository import PostgresTutorProactiveRepository


_NOW = datetime(2026, 7, 28, 9, 0, tzinfo=UTC)


def _config(
    *,
    hard_paused: bool = False,
    daily_budget: int = 3,
    concurrency_limit: int = 1,
    retry_backoff_seconds: int = 5,
) -> TutorProactiveSchedulerConfig:
    return TutorProactiveSchedulerConfig(
        enabled=True,
        hard_paused=hard_paused,
        cutover_eligible=True,
        inferred_memory_enabled=True,
        proactive_daily_budget=daily_budget,
        curation_daily_budget=3,
        proactive_concurrency_limit=concurrency_limit,
        curation_concurrency_limit=1,
        proactive_cooldown_seconds=1,
        curation_cooldown_seconds=1,
        proactive_circuit_failure_threshold=2,
        curation_circuit_failure_threshold=2,
        circuit_window_seconds=60,
        candidate_lease_seconds=60,
        curation_lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def _signal(*, source_id: str, dedupe_key: str) -> TutorProactiveSignal:
    return TutorProactiveSignal(
        user_id="placeholder",
        signal_kind="review_due",
        source_type="time_scan",
        source_id=source_id,
        source_hash=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
        occurred_at=_NOW,
        dedupe_key=dedupe_key,
        dedupe_window_seconds=3_600,
        source_reference={"source_event_id": source_id},
    )


def _fixture_signal(fixture, *, source_id: str, dedupe_key: str) -> TutorProactiveSignal:
    signal = _signal(source_id=source_id, dedupe_key=dedupe_key)
    return TutorProactiveSignal(
        user_id=fixture.user_id,
        signal_kind=signal.signal_kind,
        source_type=signal.source_type,
        source_id=signal.source_id,
        source_hash=signal.source_hash,
        occurred_at=signal.occurred_at,
        dedupe_key=signal.dedupe_key,
        dedupe_window_seconds=signal.dedupe_window_seconds,
        source_reference=signal.source_reference,
    )


def _enable_preference(repository: PostgresTutorProactiveRepository, fixture) -> None:
    repository.upsert_preference(
        preference=TutorProactivePreference(user_id=fixture.user_id, enabled=True),
        now=_NOW,
    )


def test_signals_dedupe_to_one_eligible_candidate_and_audit_the_suppressed_repeat(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    scheduler = TutorProactiveScheduler(store=repository, config=_config())

    first = scheduler.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-001", dedupe_key="review-due-window"),
        now=_NOW,
    )
    repeated = scheduler.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-002", dedupe_key="review-due-window"),
        now=_NOW + timedelta(minutes=1),
    )

    counts = fixture.connection.execute(
        """
        SELECT
          (SELECT count(*) FROM tutor_proactive_signals WHERE user_id = %s) AS signals,
          (SELECT count(*) FROM tutor_proactive_candidates WHERE user_id = %s) AS candidates,
          (SELECT count(*) FROM tutor_scheduler_audit WHERE candidate_id = %s AND code = 'dedupe_window') AS dedupe_audits
        """,
        (fixture.user_id, fixture.user_id, first.candidate_id),
    ).fetchone()
    suppressed = fixture.connection.execute(
        """
        SELECT disposition, disposition_code
        FROM tutor_proactive_signals
        WHERE user_id = %s AND source_id = 'signal-002'
        """,
        (fixture.user_id,),
    ).fetchone()

    assert repeated.candidate_id == first.candidate_id
    assert first.state == "pending"
    assert counts == {"signals": 2, "candidates": 1, "dedupe_audits": 1}
    assert suppressed == {"disposition": "suppressed", "disposition_code": "dedupe_window"}


def test_hard_pause_and_budget_denial_persist_no_action_without_claiming_a_provider_path(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)

    paused = TutorProactiveScheduler(store=repository, config=_config(hard_paused=True))
    paused_candidate = paused.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-paused", dedupe_key="paused-window"),
        now=_NOW,
    )
    paused_result = paused.drain_candidates(worker_id="paused-worker", now=_NOW)

    budget_denied = TutorProactiveScheduler(store=repository, config=_config(daily_budget=0))
    budget_candidate = budget_denied.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-budget", dedupe_key="budget-window"),
        now=_NOW,
    )
    budget_result = budget_denied.drain_candidates(worker_id="budget-worker", now=_NOW)

    assert paused_candidate.state == "no_action"
    assert paused_candidate.no_action_code == "background_hard_paused"
    assert budget_candidate.state == "no_action"
    assert budget_candidate.no_action_code == "proactive_budget_exhausted"
    assert paused_result.claimed == 0
    assert budget_result.claimed == 0


def test_expired_candidate_lease_recovers_once_after_backoff(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    scheduler = TutorProactiveScheduler(store=repository, config=_config())
    candidate = scheduler.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-lease", dedupe_key="lease-window"),
        now=_NOW,
    )

    first = repository.claim_next_candidate(
        worker_id="worker-a",
        now=_NOW,
        lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )
    before_backoff = repository.claim_next_candidate(
        worker_id="worker-b",
        now=_NOW + timedelta(seconds=61),
        lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )
    recovered = repository.claim_next_candidate(
        worker_id="worker-b",
        now=_NOW + timedelta(seconds=66),
        lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )

    assert first is not None and first.candidate_id == candidate.candidate_id
    assert before_backoff is None
    assert recovered is not None
    assert recovered.lease_generation == 2
    assert recovered.attempt_count == 2


def test_proactive_run_reservation_uses_an_internal_background_conversation_and_persists_origin(tutor_persistence) -> None:
    fixture = tutor_persistence
    repository = PostgresTutorProactiveRepository(fixture.connection)
    _enable_preference(repository, fixture)
    scheduler = TutorProactiveScheduler(store=repository, config=_config())
    candidate = scheduler.ingest_committed_signal(
        signal=_fixture_signal(fixture, source_id="signal-background", dedupe_key="background-window"),
        now=_NOW,
    )
    claimed = repository.claim_next_candidate(
        worker_id="background-worker",
        now=_NOW,
        lease_seconds=60,
        max_retry_attempts=2,
        retry_backoff_seconds=5,
    )
    assert claimed is not None and claimed.candidate_id == candidate.candidate_id

    reservation = repository.reserve_proactive_run(
        candidate=claimed,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        policy_version="tutor_proactive_policy_v1",
        policy_fingerprint="b" * 64,
        now=_NOW,
    )
    conversation = fixture.connection.execute(
        "SELECT visibility, kind FROM tutor_conversations WHERE id = %s",
        (reservation.conversation_id,),
    ).fetchone()
    run = fixture.connection.execute(
        "SELECT origin, interaction_protocol_version FROM tutor_runs WHERE id = %s",
        (reservation.run_id,),
    ).fetchone()
    messages = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s",
        (reservation.conversation_id,),
    ).fetchone()
    snapshot = fixture.repository.load_snapshot(user_id=fixture.user_id, run_id=reservation.run_id)

    assert reservation.replayed is False
    assert conversation == {"visibility": "internal", "kind": "proactive"}
    assert run == {"origin": "proactive", "interaction_protocol_version": "legacy_v1"}
    assert messages == {"count": 0}
    assert snapshot is not None and snapshot.origin == "proactive"
