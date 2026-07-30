from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from app.agents.harness.contracts import (
    TutorCapabilityRequest,
    TutorCapabilityResult,
    TutorCapabilityStatus,
    TutorPayloadField,
)

from app.agents.harness.skill_catalog import CatalogSkillReference
from app.services.tutor.persistence import (
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
