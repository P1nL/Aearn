from __future__ import annotations

from datetime import timedelta

import psycopg
import pytest

from app.agents.harness.contracts import TutorEffectProposal, TutorEffectStatus, payload_fields_from_mapping
from app.agents.harness.capabilities import TUTOR_PLAN_ACTIVATE_EFFECT_TYPE, TUTOR_PLAN_ROLLBACK_EFFECT_TYPE
from tutor_learner_state_support import learner_state_effect_repository, select_learner_state_skill


_HASH_A = "a" * 64
_HASH_B = "b" * 64


def _activate_proposal(*, effect_id: str, revision: int, title: str, before: str, after: str) -> TutorEffectProposal:
    return TutorEffectProposal(
        effect_id=effect_id,
        effect_type=TUTOR_PLAN_ACTIVATE_EFFECT_TYPE,
        expected_input_revision=revision,
        payload=payload_fields_from_mapping(
            {
                "title": title,
                "outline": ["Practice one focused concept", after],
                "change_reason": "The learner asked for a smaller verified next step.",
                "diff": [{"field": "focus", "before": before, "after": after}],
                "evidence_ids": ["evt-plan-1"],
                "evidence_hashes": [_HASH_A],
                "policy_version": "tutor_policy_v1",
            }
        ),
    )


def _rollback_proposal(*, effect_id: str, revision: int) -> TutorEffectProposal:
    return TutorEffectProposal(
        effect_id=effect_id,
        effect_type=TUTOR_PLAN_ROLLBACK_EFFECT_TYPE,
        expected_input_revision=revision,
        payload=payload_fields_from_mapping(
            {
                "reason": "The learner can return to the immediately previous verified plan.",
                "evidence_ids": ["evt-plan-rollback"],
                "evidence_hashes": [_HASH_B],
                "policy_version": "tutor_policy_v1",
            }
        ),
    )


def test_plan_revisions_are_immutable_activate_idempotently_and_rollback_to_predecessor(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="plan-input",
        content="Please make the plan more focused.",
    )
    select_learner_state_skill(fixture, input_revision=accepted.input_revision)
    repository, learner_state = learner_state_effect_repository(fixture)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="plan-revision-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None
    legacy_before = {
        "plans": fixture.connection.execute(
            "SELECT count(*) AS count FROM learning_plans WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
        "reviews": fixture.connection.execute(
            "SELECT count(*) AS count FROM review_states WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
        "attempts": fixture.connection.execute(
            "SELECT count(*) AS count FROM attempts WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
    }

    first_proposal = _activate_proposal(
        effect_id="plan-activate-1",
        revision=accepted.input_revision,
        title="Loop foundations",
        before="broad practice",
        after="loop invariants",
    )
    first = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=first_proposal,
        idempotency_key="plan-activate-1-key",
        now=now,
    )
    replayed = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=first_proposal,
        idempotency_key="plan-activate-1-key",
        now=now,
    )
    second = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=_activate_proposal(
            effect_id="plan-activate-2",
            revision=accepted.input_revision,
            title="Loop debugging",
            before="loop invariants",
            after="trace one failing branch",
        ),
        idempotency_key="plan-activate-2-key",
        now=now,
    )
    rollback = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=_rollback_proposal(effect_id="plan-rollback-1", revision=accepted.input_revision),
        idempotency_key="plan-rollback-1-key",
        now=now,
    )

    assert first.result.status is TutorEffectStatus.COMMITTED
    assert first.committer_invoked is True
    assert replayed.replayed is True
    assert replayed.result.commit_id == first.result.commit_id
    assert second.result.status is TutorEffectStatus.COMMITTED
    assert rollback.result.status is TutorEffectStatus.COMMITTED
    assert first.result.commit_id is not None
    assert second.result.commit_id is not None
    assert rollback.result.commit_id == first.result.commit_id
    assert learner_state.active_plan_for_user(user_id=fixture.user_id).revision_id == first.result.commit_id  # type: ignore[union-attr]

    revisions = fixture.connection.execute(
        """
        SELECT id::text AS id, predecessor_revision_id::text AS predecessor_revision_id, title, diff_json
        FROM tutor_plan_revisions
        WHERE user_id = %s
        ORDER BY created_at ASC, id ASC
        """,
        (fixture.user_id,),
    ).fetchall()
    actions = fixture.connection.execute(
        """
        SELECT action, current_revision_id::text AS current_revision_id,
               target_revision_id::text AS target_revision_id,
               predecessor_revision_id::text AS predecessor_revision_id
        FROM tutor_plan_revision_actions
        WHERE user_id = %s
        ORDER BY created_at ASC, id ASC
        """,
        (fixture.user_id,),
    ).fetchall()
    legacy_after = {
        "plans": fixture.connection.execute(
            "SELECT count(*) AS count FROM learning_plans WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
        "reviews": fixture.connection.execute(
            "SELECT count(*) AS count FROM review_states WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
        "attempts": fixture.connection.execute(
            "SELECT count(*) AS count FROM attempts WHERE user_id = %s", (fixture.user_id,)
        ).fetchone(),
    }

    assert [(row["id"], row["predecessor_revision_id"], row["title"]) for row in revisions] == [
        (first.result.commit_id, None, "Loop foundations"),
        (second.result.commit_id, first.result.commit_id, "Loop debugging"),
    ]
    assert revisions[0]["diff_json"] == [{"after": "loop invariants", "before": "broad practice", "field": "focus"}]
    assert [(row["action"], row["current_revision_id"], row["target_revision_id"]) for row in actions] == [
        ("activate", None, first.result.commit_id),
        ("activate", first.result.commit_id, second.result.commit_id),
        ("rollback", second.result.commit_id, first.result.commit_id),
    ]
    assert legacy_after == legacy_before

    with pytest.raises(psycopg.errors.CheckViolation):
        with fixture.connection.transaction():
            fixture.connection.execute(
                "UPDATE tutor_plan_revisions SET title = 'mutated' WHERE id = %s",
                (first.result.commit_id,),
            )


def test_plan_effect_invalid_descriptor_payload_is_denied_before_any_plan_write(tutor_persistence) -> None:
    fixture = tutor_persistence
    now = fixture.run.policy.deadline - timedelta(days=1)
    accepted = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="invalid-plan-input",
        content="Try a compact plan.",
    )
    select_learner_state_skill(fixture, input_revision=accepted.input_revision)
    repository, _ = learner_state_effect_repository(fixture)
    lease = fixture.repository.acquire_lease(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        owner_id="invalid-plan-worker",
        now=now,
        duration_seconds=60,
    )
    assert lease is not None

    receipt = repository.commit_effect_if_current(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        lease=lease,
        proposal=TutorEffectProposal(
            effect_id="invalid-plan-effect",
            effect_type=TUTOR_PLAN_ACTIVATE_EFFECT_TYPE,
            expected_input_revision=accepted.input_revision,
            payload=payload_fields_from_mapping({"title": "Missing required evidence"}),
        ),
        idempotency_key="invalid-plan-key",
        now=now,
    )

    assert receipt.result.status is TutorEffectStatus.DENIED
    assert receipt.committer_invoked is False
    assert fixture.connection.execute(
        "SELECT count(*) AS count FROM tutor_plan_revisions WHERE user_id = %s", (fixture.user_id,)
    ).fetchone() == {"count": 0}