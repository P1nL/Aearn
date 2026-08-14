from __future__ import annotations

from datetime import timedelta

from app.agents.harness.capabilities import TUTOR_ACTIVITY_RECORD_EFFECT_TYPE
from app.agents.harness.contracts import (
    TutorEffectProposal,
    TutorEffectStatus,
    TutorLease,
    payload_fields_from_mapping,
)
from app.agents.harness.skill_catalog import CatalogSkillReference
from app.services.tutor.conversation_contracts import TutorInteractionProtocolVersion
from app.services.tutor.persistence import PostgresTutorRepository
from app.services.tutor.skill_selection import TutorSkillSelection
from tutor_learner_state_support import learner_state_effect_repository, select_learner_state_skill


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



def test_retry_lineage_reuses_committed_logical_effect_without_second_domain_write(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="logical-effect-source-input",
        content="Record one safe activity once.",
    )
    select_learner_state_skill(fixture, input_revision=accepted.input_revision)
    repository, learner_state = learner_state_effect_repository(fixture)
    source_lease = repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="logical-effect-source-worker",
        now=now,
        duration_seconds=60,
    )
    assert source_lease is not None
    payload = payload_fields_from_mapping(
        {
            "category": "retry-dedupe",
            "reason": "The same logical retry action must have one durable effect.",
            "evidence_ids": ["logical-effect-evidence"],
            "evidence_hashes": ["d" * 64],
            "inbox_message": None,
            "policy_version": "tutor_policy_v1",
        }
    )
    source_receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=source_lease,
        proposal=TutorEffectProposal(
            effect_id="logical-effect-source",
            effect_type=TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload,
        ),
        idempotency_key="logical-effect-source-key",
        now=now,
    )
    assert source_receipt.result.status is TutorEffectStatus.COMMITTED

    fixture.connection.execute(
        """
        UPDATE tutor_runs
        SET status = 'failed', terminal_outcome = 'failed', terminal_diagnostic_code = 'retryable_fixture',
            terminal_at = %s, active_lease_owner_id = NULL, active_lease_expires_at = NULL
        WHERE id = %s
        """,
        (now, fixture.run.run_id),
    )
    retry_run = fixture.repository.create_run(
        user_id=fixture.user_id,
        conversation_id=fixture.conversation_id,
        catalog_digest=fixture.catalog.digest,
        policy=fixture.run.policy,
        origin="interactive",
        policy_version="tutor_retry_policy_v1",
        interaction_protocol_version=TutorInteractionProtocolVersion.THREAD_TURN_V2,
        retry_of_turn_id=fixture.run.run_id,
        retry_root_turn_id=fixture.run.run_id,
    )
    retry_input = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=retry_run.run_id,
        idempotency_key="logical-effect-retry-input",
        content="Record one safe activity once.",
        source="retry",
    )
    skill = next(skill for skill in fixture.catalog.skills if skill.reference.key == "tutor.learner-state@1.0.0")
    fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=retry_run.run_id,
        input_revision=retry_input.input_revision,
        selection=TutorSkillSelection(
            reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )
    retry_lease = repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=retry_run.run_id,
        owner_id="logical-effect-retry-worker",
        now=now,
        duration_seconds=60,
    )
    assert retry_lease is not None
    replay = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=retry_run.run_id,
        lease=retry_lease,
        proposal=TutorEffectProposal(
            effect_id="logical-effect-retry",
            effect_type=TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
            expected_input_revision=retry_input.input_revision,
            payload=payload,
        ),
        idempotency_key="logical-effect-retry-key",
        now=now,
    )

    assert replay.result.status is TutorEffectStatus.COMMITTED
    assert replay.result.commit_id == source_receipt.result.commit_id
    assert replay.replayed is True
    assert replay.committer_invoked is False
    assert len(learner_state.list_activity_records(user_id=fixture.user_id)) == 1
