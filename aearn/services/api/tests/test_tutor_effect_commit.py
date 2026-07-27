from __future__ import annotations

from datetime import timedelta

from app.agents.harness.contracts import TutorEffectProposal, TutorEffectStatus, TutorLease
from app.services.tutor.persistence import PostgresTutorRepository


def test_effect_cas_rejects_stale_revision_or_lease_without_invoking_domain_handler(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="effect-worker",
        now=fixture.run.policy.deadline - timedelta(days=1),
        duration_seconds=60,
    )
    assert lease is not None
    fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="effect-newer-input",
        content="A newer learner input must invalidate old effects.",
    )
    calls: list[str] = []

    def handler(conn, run, proposal):
        del conn, run
        calls.append(proposal.effect_id)
        raise AssertionError("stale effect handler must not run")

    repository = PostgresTutorRepository(
        fixture.connection,
        effect_handlers={"future-effect": handler},
    )

    stale = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal("effect-stale-revision", "future-effect", expected_input_revision=0),
        idempotency_key="effect-stale-revision-key",
        now=lease.expires_at - timedelta(seconds=1),
    )
    replayed = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal("effect-stale-revision", "future-effect", expected_input_revision=0),
        idempotency_key="effect-stale-revision-key",
        now=lease.expires_at - timedelta(seconds=1),
    )
    invalid_lease = TutorLease(
        run_id=lease.run_id,
        owner_id=lease.owner_id,
        generation=lease.generation + 1,
        expires_at=lease.expires_at,
    )
    stale_lease = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=invalid_lease,
        proposal=TutorEffectProposal("effect-stale-lease", "future-effect", expected_input_revision=1),
        idempotency_key="effect-stale-lease-key",
        now=lease.expires_at - timedelta(seconds=1),
    )

    assert stale.result.status is TutorEffectStatus.STALE_REJECTED
    assert replayed.replayed is True
    assert replayed.event.event_id == stale.event.event_id
    assert stale_lease.result.status is TutorEffectStatus.STALE_REJECTED
    fixture.repository.request_cancellation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        now=lease.expires_at - timedelta(seconds=1),
    )
    cancelled = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal("effect-cancelled", "future-effect", expected_input_revision=1),
        idempotency_key="effect-cancelled-key",
        now=lease.expires_at - timedelta(seconds=1),
    )
    assert cancelled.result.status is TutorEffectStatus.STALE_REJECTED
    assert calls == []
    effect_rows = fixture.connection.execute(
        "SELECT effect_id, status FROM tutor_effects WHERE run_id = %s ORDER BY effect_id",
        (fixture.run.run_id,),
    ).fetchall()
    assert [(row["effect_id"], row["status"]) for row in effect_rows] == [
        ("effect-cancelled", "stale_rejected"),
        ("effect-stale-lease", "stale_rejected"),
        ("effect-stale-revision", "stale_rejected"),
    ]


def test_unregistered_effect_is_default_denied_and_never_calls_a_handler(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="default-deny-worker",
        now=fixture.run.policy.deadline - timedelta(days=1),
        duration_seconds=60,
    )
    assert lease is not None

    calls: list[str] = []

    def handler(conn, run, proposal):
        del conn, run
        calls.append(proposal.effect_id)
        raise AssertionError("undeclared effect handler must not run")

    repository = PostgresTutorRepository(
        fixture.connection,
        effect_handlers={"future-effect": handler},
    )

    receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal("effect-default-deny", "future-effect", expected_input_revision=0),
        idempotency_key="effect-default-deny-key",
        now=lease.expires_at - timedelta(seconds=1),
    )

    assert receipt.result.status is TutorEffectStatus.DENIED
    assert receipt.committer_invoked is False
    assert calls == []
    assert receipt.event.kind == "effect_result"
