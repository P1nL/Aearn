from __future__ import annotations

import pytest

from app.services.tutor.persistence import TutorIdempotencyConflict


def test_internal_event_replay_returns_strict_ordered_suffix_and_replays_same_key(tutor_persistence) -> None:
    fixture = tutor_persistence
    first = fixture.repository.accept_input(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        idempotency_key="replay-input",
        content="First durable learner input.",
    ).event
    second = fixture.repository.append_safe_event(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        event_key="safe-progress-1",
        kind="checkpoint_saved",
        input_revision=1,
        payload={
            "kind": "checkpoint_saved",
            "status": "running",
            "run_id": fixture.run.run_id,
            "input_revision": 1,
            "token_budget": 64,
            "consumed_tokens": 8,
        },
    )
    replayed_second = fixture.repository.append_safe_event(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        event_key="safe-progress-1",
        kind="checkpoint_saved",
        input_revision=1,
        payload={
            "kind": "checkpoint_saved",
            "status": "running",
            "run_id": fixture.run.run_id,
            "input_revision": 1,
            "token_budget": 64,
            "consumed_tokens": 8,
        },
    )
    third = fixture.repository.append_safe_event(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        event_key="waiting-1",
        kind="waiting_for_input",
        input_revision=1,
        payload={
            "kind": "waiting_for_input",
            "status": "waiting_for_input",
            "run_id": fixture.run.run_id,
            "input_revision": 1,
        },
    )

    suffix = fixture.repository.events_after(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        after_sequence=first.event_sequence,
        limit=10,
    )

    assert (first.event_sequence, second.event_sequence, third.event_sequence) == (1, 2, 3)
    assert replayed_second.event_id == second.event_id
    assert replayed_second.event_sequence == second.event_sequence
    assert [event.event_sequence for event in suffix] == [2, 3]
    assert [event.kind for event in suffix] == ["checkpoint_saved", "waiting_for_input"]
    assert fixture.repository.events_after(
        user_id=fixture.user_id,
        run_id=fixture.run.run_id,
        after_sequence=third.event_sequence,
        limit=10,
    ) == ()

    with pytest.raises(TutorIdempotencyConflict):
        fixture.repository.append_safe_event(
            user_id=fixture.user_id,
            run_id=fixture.run.run_id,
            event_key="safe-progress-1",
            kind="checkpoint_saved",
            input_revision=1,
            payload={
                "kind": "checkpoint_saved",
                "status": "waiting_for_input",
                "run_id": fixture.run.run_id,
                "input_revision": 1,
            },
        )
