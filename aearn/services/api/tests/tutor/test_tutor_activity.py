from __future__ import annotations

from datetime import timedelta

import pytest

from app.agents.harness.capabilities import TUTOR_ACTIVITY_RECORD_EFFECT_TYPE
from app.agents.harness.contracts import TutorEffectProposal, TutorEffectStatus, payload_fields_from_mapping
from app.services.tutor.learner_state import TutorLearnerStateConflict
from tests.support.tutor_learner_state_support import learner_state_effect_repository, select_learner_state_skill


_HASH = "c" * 64


def test_activity_effect_is_user_scoped_and_creates_only_safe_optional_inbox_projection(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="activity-input",
        content="I am ready for a small next action.",
    )
    select_learner_state_skill(fixture, input_revision=accepted.input_revision)
    repository, learner_state = learner_state_effect_repository(fixture)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="activity-effect-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None

    receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal(
            effect_id="activity-effect-1",
            effect_type=TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload_fields_from_mapping(
                {
                    "category": "plan-update",
                    "reason": "A compact plan revision is ready for learner review.",
                    "evidence_ids": ["evt-activity-1"],
                    "evidence_hashes": [_HASH],
                    "inbox_message": "Your next verified step is ready.",
                    "policy_version": "tutor_policy_v1",
                }
            ),
        ),
        idempotency_key="activity-effect-key",
        now=now,
    )

    assert receipt.result.status is TutorEffectStatus.COMMITTED
    assert receipt.result.commit_id is not None
    activities = learner_state.list_activity_records(user_id=fixture.user_id)
    inbox = learner_state.list_inbox_items(user_id=fixture.user_id)
    assert [(item.activity_id, item.category, item.learner_reason) for item in activities] == [
        (
            receipt.result.commit_id,
            "plan-update",
            "A compact plan revision is ready for learner review.",
        )
    ]
    assert [(item.activity_id, item.message, item.state) for item in inbox] == [
        (receipt.result.commit_id, "Your next verified step is ready.", "unread")
    ]
    assert learner_state.list_activity_records(user_id="00000000-0000-0000-0000-000000000000") == ()
    assert "Traceback" not in inbox[0].message

    read = learner_state.mark_inbox_read(user_id=fixture.user_id, inbox_id=inbox[0].inbox_id, now=now)
    assert read.state == "read"
    with pytest.raises(TutorLearnerStateConflict, match="inbox_item_not_unread"):
        learner_state.dismiss_inbox_item(user_id=fixture.user_id, inbox_id=inbox[0].inbox_id, now=now)


def test_activity_descriptor_rejects_provider_diagnostic_payload_before_handler(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="unsafe-activity-input",
        content="I want an update.",
    )
    select_learner_state_skill(fixture, input_revision=accepted.input_revision)
    repository, learner_state = learner_state_effect_repository(fixture)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="unsafe-activity-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None

    receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal(
            effect_id="unsafe-activity-effect",
            effect_type=TUTOR_ACTIVITY_RECORD_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload_fields_from_mapping(
                {
                    "category": "plan-update",
                    "reason": "Traceback from C:\\secret must not become activity.",
                    "evidence_ids": ["evt-activity-unsafe"],
                    "evidence_hashes": [_HASH],
                    "policy_version": "tutor_policy_v1",
                }
            ),
        ),
        idempotency_key="unsafe-activity-key",
        now=now,
    )

    assert receipt.result.status is TutorEffectStatus.DENIED
    assert receipt.committer_invoked is False
    assert learner_state.list_activity_records(user_id=fixture.user_id) == ()