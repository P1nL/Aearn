from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from app.agents.harness.contracts import (
    TutorDecision,
    TutorEffectProposal,
    TutorProviderResult,
    TutorSkillReference,
    TutorTerminalOutcome,
    payload_fields_from_mapping,
)
from app.core.config import Settings
from app.services.tutor.ports import FixedClock, SequenceTutorProvider
from app.services.tutor.proactive import TutorProactiveSignal
from app.services.tutor.proactive_worker import build_tutor_proactive_scheduler


_NOW = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(
        tutor_proactive_scheduler_enabled=True,
        tutor_background_hard_paused=False,
        tutor_proactive_cutover_eligible=True,
        tutor_inferred_memory_enabled=False,
        tutor_proactive_daily_budget=1,
        tutor_proactive_concurrency_limit=1,
        tutor_curation_daily_budget=0,
        tutor_curation_concurrency_limit=1,
    )


def _activity_provider() -> SequenceTutorProvider:
    return SequenceTutorProvider(
        [
            TutorProviderResult(
                decision=TutorDecision(
                    skill_references=(TutorSkillReference("tutor.learner-state", "1.0.0"),),
                )
            ),
            TutorProviderResult(
                decision=TutorDecision(
                    # Background delivery must not create a learner chat message;
                    # the production wrapper strips this before terminal persistence.
                    public_message="This must remain out of learner chat.",
                    effect_proposals=(
                        TutorEffectProposal(
                            effect_id="activity-inbox-1",
                            effect_type="tutor.activity.record",
                            expected_input_revision=0,
                            payload=payload_fields_from_mapping(
                                {
                                    "category": "next_step",
                                    "reason": "Continue one short practice step.",
                                    "evidence_ids": ["interactive_terminal"],
                                    "evidence_hashes": ["a" * 64],
                                    "inbox_message": "A short practice suggestion is ready.",
                                    "policy_version": "tutor_proactive_policy_v1",
                                }
                            ),
                        ),
                    ),
                    terminal_outcome=TutorTerminalOutcome.COMPLETED,
                )
            ),
        ]
    )


def _mark_interactive_run_terminal(fixture) -> None:
    fixture.connection.execute(
        """
        UPDATE tutor_runs
        SET status = 'completed',
            terminal_outcome = 'completed',
            terminal_diagnostic_code = 'completed',
            terminal_at = %s,
            updated_at = %s
        WHERE id = %s
        """,
        (_NOW, _NOW, fixture.run.run_id),
    )


def _terminal_signal(user_id: str) -> TutorProactiveSignal:
    source_id = "unverified-terminal"
    return TutorProactiveSignal(
        user_id=user_id,
        signal_kind="interactive_terminal",
        source_type="tutor_run",
        source_id=source_id,
        source_hash=hashlib.sha256(source_id.encode("utf-8")).hexdigest(),
        occurred_at=_NOW,
        dedupe_key="interactive_terminal",
        dedupe_window_seconds=86_400,
        source_reference={"source_event_id": source_id, "policy_tag": "interactive_terminal"},
    )


def test_verified_default_delivery_creates_only_activity_and_inbox_with_durable_skill_evidence(tutor_persistence) -> None:
    fixture = tutor_persistence
    _mark_interactive_run_terminal(fixture)
    provider = _activity_provider()
    scheduler = build_tutor_proactive_scheduler(
        conn=fixture.connection,
        settings=_settings(),
        now=_NOW,
        clock=FixedClock(_NOW),
        provider_factory=lambda _settings: provider,
    )

    candidates = scheduler.scan_due_signals(now=_NOW, limit=5, user_id=fixture.user_id)
    result = scheduler.drain_candidates(worker_id="proactive-fixture", now=_NOW, limit=5)

    assert len(candidates) == 1
    assert candidates[0].state == "pending"
    assert result.claimed == 1
    assert result.completed == 1
    assert len(provider.calls) == 2

    candidate = fixture.connection.execute(
        """
        SELECT state, run_id::text AS run_id
        FROM tutor_proactive_candidates
        WHERE user_id = %s
        """,
        (fixture.user_id,),
    ).fetchone()
    assert candidate is not None
    assert candidate["state"] == "completed"
    assert candidate["run_id"] is not None

    selection = fixture.connection.execute(
        """
        SELECT skill_id, skill_version
        FROM tutor_run_skill_selections
        WHERE run_id = %s
        """,
        (candidate["run_id"],),
    ).fetchone()
    activity = fixture.connection.execute(
        """
        SELECT category, source_run_id::text AS source_run_id
        FROM tutor_activity_records
        WHERE user_id = %s
        """,
        (fixture.user_id,),
    ).fetchone()
    inbox = fixture.connection.execute(
        """
        SELECT message, state
        FROM tutor_inbox_items
        WHERE user_id = %s
        """,
        (fixture.user_id,),
    ).fetchone()
    effects = fixture.connection.execute(
        "SELECT effect_type FROM tutor_effects WHERE run_id = %s",
        (candidate["run_id"],),
    ).fetchall()
    messages = fixture.connection.execute(
        """
        SELECT count(*)::int AS count
        FROM tutor_messages AS messages
        JOIN tutor_runs AS runs ON runs.conversation_id = messages.conversation_id
        WHERE runs.id = %s
        """,
        (candidate["run_id"],),
    ).fetchone()

    assert selection == {"skill_id": "tutor.learner-state", "skill_version": "1.0.0"}
    assert activity == {"category": "next_step", "source_run_id": candidate["run_id"]}
    assert inbox == {"message": "A short practice suggestion is ready.", "state": "unread"}
    assert effects == [{"effect_type": "tutor.activity.record"}]
    assert messages == {"count": 0}


def test_unverified_user_is_denied_before_provider_or_run_creation(tutor_persistence) -> None:
    fixture = tutor_persistence
    fixture.connection.execute("DELETE FROM harness_cutovers WHERE user_id = %s", (fixture.user_id,))
    provider = _activity_provider()
    scheduler = build_tutor_proactive_scheduler(
        conn=fixture.connection,
        settings=_settings(),
        now=_NOW,
        clock=FixedClock(_NOW),
        provider_factory=lambda _settings: provider,
    )

    candidate = scheduler.ingest_committed_signal(signal=_terminal_signal(fixture.user_id), now=_NOW)
    result = scheduler.drain_candidates(worker_id="proactive-fixture", now=_NOW, limit=5)
    runs = fixture.connection.execute(
        "SELECT count(*)::int AS count FROM tutor_runs WHERE origin = 'proactive' AND user_id = %s",
        (fixture.user_id,),
    ).fetchone()

    assert candidate.state == "no_action"
    assert candidate.no_action_code == "cutover_unverified"
    assert result.claimed == 0
    assert provider.calls == []
    assert runs == {"count": 0}
