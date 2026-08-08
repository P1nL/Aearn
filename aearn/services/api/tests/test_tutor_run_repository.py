from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import psycopg
import pytest

from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorPayloadField,
    TutorProviderAttemptOutcome,
    TutorProviderAttemptReceipt,
)
from app.agents.harness.skill_catalog import CatalogSkillReference
from app.services.llm.contracts import LLMUsage
from app.services.tutor.persistence import (
    PostgresTutorRepository,
    TutorCatalogEvidenceError,
    TutorIdempotencyConflict,
    TutorRunNotFound,
    TutorTerminalStateConflict,
)
from app.services.tutor.skill_selection import TutorSkillSelection


def test_accept_input_replays_same_request_and_keeps_raw_text_only_in_messages(tutor_persistence) -> None:
    fixture = tutor_persistence
    raw_learner_text = "Please explain why my closure keeps the old value."

    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="input-001",
        content=raw_learner_text,
    )
    replayed = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="input-001",
        content=raw_learner_text,
    )

    assert accepted.replayed is False
    assert replayed.replayed is True
    assert replayed.message_id == accepted.message_id
    assert replayed.input_revision == 1
    assert fixture.repository.current_input_revision(user_id=fixture.user_id, run_id=fixture.run.run_id) == 1

    message = fixture.connection.execute(
        "SELECT content FROM tutor_messages WHERE id = %s",
        (accepted.message_id,),
    ).fetchone()
    input_event = fixture.connection.execute(
        "SELECT body_hash FROM tutor_run_input_events WHERE run_id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    event = fixture.connection.execute(
        "SELECT payload_json::text AS payload FROM tutor_run_events WHERE id = %s",
        (accepted.event.event_id,),
    ).fetchone()

    assert message is not None and message["content"] == raw_learner_text
    assert input_event is not None
    assert input_event["body_hash"] == hashlib.sha256(raw_learner_text.encode("utf-8")).hexdigest()
    assert event is not None
    assert raw_learner_text not in str(event["payload"])
    assert accepted.event.event_sequence == 1

    with pytest.raises(TutorIdempotencyConflict):
        fixture.repository.accept_input(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            idempotency_key="input-001",
            content="This is a different body for the same request key.",
        )


def test_input_acceptance_checks_user_scope_and_persists_exact_catalog_selection(tutor_persistence) -> None:
    fixture = tutor_persistence
    other_user = fixture.connection.execute(
        "INSERT INTO users (display_name) VALUES ('Tutor Other User') RETURNING id"
    ).fetchone()
    assert other_user is not None

    with pytest.raises(TutorRunNotFound):
        fixture.repository.accept_input(
            user_id=str(other_user["id"]),
            run_id=fixture.run.run_id,
            idempotency_key="input-other-user",
            content="I should not be able to write another user's run.",
        )

    skill = next(
        skill
        for skill in fixture.catalog.skills
        if skill.reference.key == "tutor.registry-grounding@1.0.0"
    )
    selection = TutorSkillSelection(
        reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
        manifest_hash=skill.manifest_hash,
        instruction_hash=skill.instruction_hash,
    )
    evidence = fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        input_revision=0,
        selection=selection,
    )
    replayed = fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        input_revision=0,
        selection=selection,
    )

    assert evidence.replayed is False
    assert replayed.replayed is True
    assert evidence.skill_version == skill.manifest.version
    assert evidence.manifest_hash == skill.manifest_hash
    assert evidence.instruction_hash == skill.instruction_hash
    assert evidence.evaluation_hash == skill.evaluation_hash

    with pytest.raises(TutorCatalogEvidenceError):
        fixture.repository.record_skill_selection(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            input_revision=0,
            selection=TutorSkillSelection(
                reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
                manifest_hash="0" * 64,
                instruction_hash=skill.instruction_hash,
            ),
        )
def test_accept_input_rejects_a_cancelled_run_before_writing_raw_content(tutor_persistence) -> None:
    fixture = tutor_persistence
    fixture.repository.request_cancellation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        now=datetime.now(UTC),
    )

    with pytest.raises(TutorTerminalStateConflict, match="cancelled"):
        fixture.repository.accept_input(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            idempotency_key="cancelled-input",
            content="This must not be stored after cancellation.",
        )

    row = fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_messages WHERE conversation_id = %s",
        (fixture.conversation_id,),
    ).fetchone()
    assert row == {"count": 0}


def test_first_turn_rolls_back_every_created_row_after_an_intermediate_failure(tutor_persistence) -> None:
    fixture = tutor_persistence

    def counts() -> dict[str, int]:
        row = fixture.connection.execute(
            """
            SELECT
              (SELECT count(*) FROM tutor_conversations WHERE user_id = %s) AS conversations,
              (SELECT count(*) FROM tutor_runs WHERE user_id = %s) AS runs,
              (
                SELECT count(*)
                FROM tutor_messages AS messages
                JOIN tutor_conversations AS conversations ON conversations.id = messages.conversation_id
                WHERE conversations.user_id = %s
              ) AS messages,
              (
                SELECT count(*)
                FROM tutor_run_public_processes AS processes
                JOIN tutor_runs AS runs ON runs.id = processes.run_id
                WHERE runs.user_id = %s
              ) AS processes
            """,
            (fixture.user_id, fixture.user_id, fixture.user_id, fixture.user_id),
        ).fetchone()
        assert row is not None
        return {key: int(value) for key, value in row.items()}

    before = counts()

    def fail_after_first_input(stage: str) -> None:
        if stage == "after_fresh_turn_input":
            raise RuntimeError("forced first-turn rollback")

    failing_repository = PostgresTutorRepository(fixture.connection, failpoint=fail_after_first_input)
    with pytest.raises(RuntimeError, match="forced first-turn rollback"):
        failing_repository.create_first_interactive_turn(
            user_id=fixture.user_id,
            catalog_digest=fixture.catalog.digest,
            policy=fixture.run.policy,
            idempotency_key="first-turn-forced-rollback",
            content="这条首发消息不能在失败后留下空会话。",
            received_at=datetime.now(UTC),
        )

    assert counts() == before


def test_capability_receipt_requires_exact_selection_and_replays_only_identical_evidence(tutor_persistence) -> None:
    fixture = tutor_persistence
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="capability-worker",
        now=datetime.now(UTC),
        duration_seconds=60,
    )
    assert lease is not None
    run_evidence = fixture.connection.execute(
        "SELECT catalog_digest, policy_fingerprint FROM tutor_runs WHERE id = %s",
        (fixture.run.run_id,),
    ).fetchone()
    assert run_evidence is not None
    request = TutorCapabilityRequest(
        "capability-replay",
        "grounding.retrieve",
        (
            TutorPayloadField("language_id_or_alias", "python"),
            TutorPayloadField("query_text", "closures"),
        ),
    )
    result = TutorCapabilityResult(
        "capability-replay",
        TutorCapabilityStatus.COMPLETED,
        (TutorPayloadField("source_id", "registry-python"),),
    )

    with pytest.raises(TutorCatalogEvidenceError, match="selected Skill"):
        fixture.repository.record_capability_invocation(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            lease=lease,
            input_revision=0,
            request=request,
            result=result,
            capability_version="1.0.0",
            catalog_digest=str(run_evidence["catalog_digest"]),
            policy_fingerprint=str(run_evidence["policy_fingerprint"]),
        )

    skill = next(skill for skill in fixture.catalog.skills if skill.reference.key == "tutor.registry-grounding@1.0.0")
    fixture.repository.record_skill_selection(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        input_revision=0,
        selection=TutorSkillSelection(
            reference=CatalogSkillReference(skill.manifest.id, skill.manifest.version),
            manifest_hash=skill.manifest_hash,
            instruction_hash=skill.instruction_hash,
        ),
    )
    receipt = fixture.repository.record_capability_invocation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        input_revision=0,
        request=request,
        result=result,
        capability_version="1.0.0",
        catalog_digest=str(run_evidence["catalog_digest"]),
        policy_fingerprint=str(run_evidence["policy_fingerprint"]),
    )
    replayed = fixture.repository.record_capability_invocation(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        input_revision=0,
        request=request,
        result=result,
        capability_version="1.0.0",
        catalog_digest=str(run_evidence["catalog_digest"]),
        policy_fingerprint=str(run_evidence["policy_fingerprint"]),
    )

    assert receipt.replayed is False
    assert replayed.replayed is True
    assert replayed.invocation_id == receipt.invocation_id

    with pytest.raises(TutorIdempotencyConflict, match="capability invocation"):
        fixture.repository.record_capability_invocation(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            lease=lease,
            input_revision=0,
            request=request,
            result=TutorCapabilityResult(
                "capability-replay",
                TutorCapabilityStatus.COMPLETED,
                (TutorPayloadField("source_id", "different-registry-source"),),
            ),
            capability_version="1.0.0",
            catalog_digest=str(run_evidence["catalog_digest"]),
            policy_fingerprint=str(run_evidence["policy_fingerprint"]),
        )

def test_provider_attempt_receipts_replay_identically_and_reject_conflicting_facts(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    created_at = datetime.now(UTC)
    attempts = (
        TutorProviderAttemptReceipt(
            attempt_index=1,
            outcome=TutorProviderAttemptOutcome.REPAIRABLE_REJECTED,
            provider_type="deepseek",
            protocol="deepseek_responses",
            model="deepseek-v4-flash",
            usage=LLMUsage(
                input_tokens=175_420,
                cached_input_tokens=170_368,
                output_tokens=20,
                total_tokens=175_440,
                reasoning_tokens=7,
            ),
            diagnostic_code="content_not_json",
        ),
        TutorProviderAttemptReceipt(
            attempt_index=2,
            outcome=TutorProviderAttemptOutcome.ACCEPTED,
            provider_type="deepseek",
            protocol="deepseek_responses",
            model="deepseek-v4-flash",
            usage=LLMUsage(input_tokens=180, output_tokens=40, total_tokens=220),
        ),
    )

    fixture.repository.record_provider_attempts(
        snapshot=fixture.run,
        decision_iteration=1,
        attempts=attempts,
        created_at=created_at,
    )
    fixture.repository.record_provider_attempts(
        snapshot=fixture.run,
        decision_iteration=1,
        attempts=attempts,
        created_at=created_at,
    )
    fixture.repository.record_provider_attempts(
        snapshot=fixture.run,
        decision_iteration=2,
        attempts=(
            TutorProviderAttemptReceipt(
                attempt_index=1,
                outcome=TutorProviderAttemptOutcome.ACCEPTED,
                provider_type="deepseek",
                protocol="deepseek_responses",
                model="deepseek-v4-flash",
            ),
        ),
        created_at=created_at,
    )

    receipts = fixture.repository.list_provider_attempt_receipts(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
    )
    assert len(receipts) == 3
    first_usage = receipts[0].attempt.usage
    assert first_usage is not None
    assert first_usage.input_tokens == 175_420
    assert first_usage.cached_input_tokens == 170_368
    assert first_usage.uncached_input_tokens == 5_052
    assert first_usage.calculated_total_tokens == 175_440
    assert receipts[0].decision_iteration == 1
    assert (
        receipts[0].attempt.outcome is TutorProviderAttemptOutcome.REPAIRABLE_REJECTED
    )
    assert receipts[1].attempt.outcome is TutorProviderAttemptOutcome.ACCEPTED
    assert receipts[2].decision_iteration == 2
    assert receipts[2].attempt.usage is None
    unavailable_usage = fixture.connection.execute(
        """
        SELECT input_tokens, cached_input_tokens, uncached_input_tokens,
               output_tokens, reported_total_tokens, reasoning_tokens, usage_available
        FROM tutor_provider_attempt_receipts
        WHERE run_id = %s AND decision_iteration = 2 AND attempt_index = 1
        """,
        (fixture.run.run_id,),
    ).fetchone()
    assert unavailable_usage == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "uncached_input_tokens": None,
        "output_tokens": None,
        "reported_total_tokens": None,
        "reasoning_tokens": None,
        "usage_available": False,
    }

    conflicting_attempt = TutorProviderAttemptReceipt(
        attempt_index=1,
        outcome=TutorProviderAttemptOutcome.REPAIRABLE_REJECTED,
        provider_type="deepseek",
        protocol="deepseek_responses",
        model="deepseek-v4-flash",
        usage=LLMUsage(
            input_tokens=175_421, cached_input_tokens=170_368, output_tokens=20
        ),
        diagnostic_code="content_not_json",
    )
    with pytest.raises(
        TutorIdempotencyConflict, match="provider attempt receipt identity"
    ):
        fixture.repository.record_provider_attempts(
            snapshot=fixture.run,
            decision_iteration=1,
            attempts=(conflicting_attempt,),
            created_at=created_at,
        )

    other_user = fixture.connection.execute(
        "INSERT INTO users (display_name) VALUES ('Provider Attempt Other User') RETURNING id"
    ).fetchone()
    assert other_user is not None
    other_user_id = str(other_user["id"])
    with pytest.raises(TutorRunNotFound):
        fixture.repository.list_provider_attempt_receipts(
            user_id=other_user_id,
            run_id=fixture.run.run_id,
        )
    with pytest.raises(TutorRunNotFound):
        fixture.repository.record_provider_attempts(
            snapshot=replace(fixture.run, user_id=other_user_id),
            decision_iteration=1,
            attempts=attempts,
            created_at=created_at,
        )


def test_provider_attempt_receipt_constraints_enforce_scope_derived_usage_and_append_only(
    tutor_persistence,
) -> None:
    fixture = tutor_persistence
    receipt = TutorProviderAttemptReceipt(
        attempt_index=1,
        outcome=TutorProviderAttemptOutcome.ACCEPTED,
        provider_type="openai",
        protocol="responses",
        model="gpt-test",
        usage=LLMUsage(
            input_tokens=10, cached_input_tokens=4, output_tokens=3, total_tokens=13
        ),
    )
    fixture.repository.record_provider_attempts(
        snapshot=fixture.run,
        decision_iteration=1,
        attempts=(receipt,),
        created_at=datetime.now(UTC),
    )

    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_provider_attempt_receipts SET output_tokens = 4 WHERE run_id = %s",
                (fixture.run.run_id,),
            )
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "DELETE FROM tutor_provider_attempt_receipts WHERE run_id = %s",
                (fixture.run.run_id,),
            )

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                INSERT INTO tutor_provider_attempt_receipts (
                  run_id, user_id, conversation_id, input_revision,
                  decision_iteration, attempt_index, provider_type, protocol,
                  outcome, input_tokens, cached_input_tokens, uncached_input_tokens,
                  usage_available
                )
                VALUES (%s, %s, %s, 0, 1, 2, 'openai', 'responses',
                        'accepted', 10, 11, 0, true)
                """,
                (fixture.run.run_id, fixture.user_id, fixture.conversation_id),
            )

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                INSERT INTO tutor_provider_attempt_receipts (
                  run_id, user_id, conversation_id, input_revision,
                  decision_iteration, attempt_index, provider_type, protocol,
                  outcome, diagnostic_code, input_tokens, uncached_input_tokens,
                  usage_available
                )
                VALUES (%s, %s, %s, 0, 1, 3, 'openai', 'responses',
                        'transport_failed', 'provider_transport_failed', 1, 1, true)
                """,
                (fixture.run.run_id, fixture.user_id, fixture.conversation_id),
            )

    other_user = fixture.connection.execute(
        "INSERT INTO users (display_name) VALUES ('Provider Scope User') RETURNING id"
    ).fetchone()
    assert other_user is not None
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                INSERT INTO tutor_provider_attempt_receipts (
                  run_id, user_id, conversation_id, input_revision,
                  decision_iteration, attempt_index, provider_type, protocol,
                  outcome, usage_available
                )
                VALUES (%s, %s, %s, 0, 1, 5, 'openai', 'responses', 'accepted', false)
                """,
                (fixture.run.run_id, str(other_user["id"]), fixture.conversation_id),
            )

    other_conversation = fixture.repository.create_conversation(user_id=fixture.user_id)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                """
                INSERT INTO tutor_provider_attempt_receipts (
                  run_id, user_id, conversation_id, input_revision,
                  decision_iteration, attempt_index, provider_type, protocol,
                  outcome, usage_available
                )
                VALUES (%s, %s, %s, 0, 1, 4, 'openai', 'responses', 'accepted', false)
                """,
                (fixture.run.run_id, fixture.user_id, other_conversation),
            )
