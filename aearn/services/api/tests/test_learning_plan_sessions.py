from __future__ import annotations

import json
from datetime import UTC, datetime

import psycopg
import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.capabilities import LearningPlanDraftCapabilityInput
from app.agents.harness.context_builder import TutorContextBuilder
from app.agents.harness.contracts import (
    TutorCheckpointReason,
    TutorContinuationKind,
    TutorDecision,
    TutorDecisionGateResult,
    TutorDecisionGateStatus,
    TutorContextSection,
)
from app.core.config import Settings
from app.db.connection import connect
from app.services.learning.plan_capability import LearningPlanDraftCapabilityHandler
from app.services.learning.planning_facts import (
    PlanningFactField,
    PlanningQuestionDecisionGate,
    PostgresPlanningFactRepository,
)
from app.services.repositories.local_user_data_repository import (
    export_user_data,
    get_user_data_summary,
    reset_user_data,
)
from app.services.tutor.interactive import (
    PostgresTutorContextLoader,
    PostgresTutorLearningContextLoader,
)
from app.services.tutor.learner_state import TutorLearnerStateRepository
from app.services.tutor.persistence import PostgresTutorRepository
from tutor_public_api_support import (
    action_payload,
    assert_error,
    create_tutor_user,
    RecordingTutorDispatcher,
    waiting_dispatcher,
)


pytest_plugins = ("tutor_public_api_support",)


def _capability_input() -> LearningPlanDraftCapabilityInput:
    profile = {
        "language_id": "python",
        "goal_text": "Build reliable automation tools",
        "target_level": "intermediate",
        "weekly_minutes": 240,
        "experience_level": "beginner",
        "teaching_preferences": ["examples", "practice"],
        "pace_summary": "Four focused sessions each week.",
        "title": "Python Automation Foundations",
    }
    modules = (
        {
            "module_key": "foundations",
            "title": "Foundations",
            "nodes": [
                {
                    "knowledge_key": "python.variables",
                    "title": "Variables",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "module_key": "automation",
            "title": "Automation",
            "nodes": [
                {
                    "knowledge_key": "python.files",
                    "title": "Files",
                    "prerequisite_keys": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    )
    return LearningPlanDraftCapabilityInput(
        profile_json=json.dumps(profile, separators=(",", ":")),
        module_1=json.dumps(modules[0], separators=(",", ":")),
        module_2=json.dumps(modules[1], separators=(",", ":")),
    )


def _create_session(client: TestClient, user_id: str, action_id: str = "plan-session-create") -> dict[str, object]:
    response = client.post(
        "/api/learning-plan-sessions",
        json={
            "user_id": user_id,
            "client_action_id": action_id,
            "preferred_language_id": "python",
        },
    )
    assert response.status_code in {200, 201}
    session = response.json()["session"]
    assert isinstance(session, dict)
    return session


def test_session_create_resume_cancel_and_cross_user_scope(
    tutor_client: TestClient,
) -> None:
    owner_id = str(create_tutor_user(tutor_client)["id"])
    other_id = str(create_tutor_user(tutor_client)["id"])
    created = _create_session(tutor_client, owner_id)
    resumed = _create_session(tutor_client, owner_id, "plan-session-resume")

    assert resumed["session_id"] == created["session_id"]
    current = tutor_client.get(f"/api/learning-plan-sessions/current?user_id={owner_id}")
    assert current.status_code == 200
    assert current.json()["session"]["conversation_id"] == created["conversation_id"]

    hidden = tutor_client.get(
        f"/api/learning-plan-sessions/{created['session_id']}?user_id={other_id}"
    )
    assert_error(hidden, "LEARNING_PLAN_SESSION_NOT_FOUND", 404)

    cancelled = tutor_client.post(
        f"/api/learning-plan-sessions/{created['session_id']}/cancel",
        json={
            "user_id": owner_id,
            "client_action_id": "plan-session-cancel",
            "expected_session_version": created["version"],
        },
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["session"]["status"] == "cancelled"
    assert tutor_client.get(f"/api/learning-plan-sessions/current?user_id={owner_id}").json()["session"] is None


def test_capability_appends_typed_draft_and_confirm_creates_one_track(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="计划信息已足够。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-confirm-session")
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-draft-input",
            content="我想每周学习四小时，用 Python 做可靠的自动化工具。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        run = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None
        output = LearningPlanDraftCapabilityHandler(conn).generate(
            run=run,
            capability_input=_capability_input(),
        )
        conn.commit()

    current = tutor_client.get(f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}")
    assert current.status_code == 200
    draft_session = current.json()["session"]
    draft = draft_session["current_draft"]
    assert draft["draft_id"] == output.draft_id
    assert draft["draft_version"] == 1
    assert draft["content_hash"] == output.content_hash
    assert draft["sources"][0]["source_id"] == "python-tutorial"
    public_text = json.dumps(draft_session, ensure_ascii=False)
    for protected in ("raw_prompt", "provider_body", "reasoning", "credential", "transport_body"):
        assert protected not in public_text

    with connect() as conn:
        PostgresTutorRepository(conn).request_cancellation(
            user_id=user_id,
            run_id=run_id,
            now=datetime.now(UTC),
        )
        conn.commit()

    confirm_payload = {
        "user_id": user_id,
        "client_action_id": "plan-confirm-draft-1",
        "expected_session_version": draft_session["version"],
        "draft_id": draft["draft_id"],
        "draft_version": draft["draft_version"],
        "content_hash": draft["content_hash"],
    }
    confirmed = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json=confirm_payload,
    )
    replay = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json=confirm_payload,
    )
    assert confirmed.status_code == replay.status_code == 200
    assert replay.json()["idempotent_replayed"] is True
    track_id = str(confirmed.json()["track"]["track_id"])
    assert replay.json()["track"]["track_id"] == track_id

    listing = tutor_client.get(f"/api/learning-tracks?user_id={user_id}")
    assert listing.status_code == 200
    assert [item["track_id"] for item in listing.json()["items"]] == [track_id]
    with connect() as conn:
        scope = conn.execute(
            "SELECT scope_kind, learning_track_id::text FROM tutor_conversation_learning_scopes WHERE conversation_id = %s",
            (conversation_id,),
        ).fetchone()
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*)::int FROM tutor_learning_plan_drafts WHERE user_id = %s) AS drafts,
              (SELECT count(*)::int FROM tutor_learning_tracks WHERE user_id = %s) AS tracks,
              (SELECT count(*)::int FROM tutor_track_plan_revisions WHERE user_id = %s) AS revisions
            """,
            (user_id, user_id, user_id),
        ).fetchone()
    assert scope == {"scope_kind": "learning_track", "learning_track_id": track_id}
    assert counts == {"drafts": 1, "tracks": 1, "revisions": 1}


def test_confirm_rejects_stale_draft_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(settings=tutor_api_settings, message="计划已准备。")
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-stale-session")
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{session['conversation_id']}/inputs",
        json=action_payload(
            user_id,
            "plan-stale-input",
            content="生成 Python 学习计划。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    run_id = str(accepted.json()["run_id"])
    with connect() as conn:
        run = PostgresTutorRepository(conn).load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None
        LearningPlanDraftCapabilityHandler(conn).generate(run=run, capability_input=_capability_input())
        conn.commit()
    current = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    draft = current["current_draft"]
    stale = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json={
            "user_id": user_id,
            "client_action_id": "plan-stale-confirm",
            "expected_session_version": current["version"] - 1,
            "draft_id": draft["draft_id"],
            "draft_version": draft["draft_version"],
            "content_hash": draft["content_hash"],
        },
    )
    assert_error(stale, "LEARNING_PLAN_DRAFT_STALE", 409)
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_tracks WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert count == {"count": 0}

class _OneTokenEstimator:
    def estimate_tokens(self, value: object) -> int:
        del value
        return 1


class _ApprovedDecisionGate:
    def validate(self, *, run, decision) -> TutorDecisionGateResult:  # type: ignore[no-untyped-def]
        del run, decision
        return TutorDecisionGateResult(status=TutorDecisionGateStatus.APPROVED)


def _planning_profile_facts(*, weekly_minutes: int) -> dict[str, object]:
    return {
        "language_id": "python",
        "goal_text": "Build reliable automation tools",
        "target_level": "intermediate",
        "weekly_minutes": weekly_minutes,
        "experience_level": "beginner",
        "teaching_preferences": ["examples", "practice"],
        "pace_constraints": "Four focused sessions each week.",
    }


def test_confirmed_planning_fact_survives_long_history_correction_and_reset(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
) -> None:
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-facts-session")
    conversation_id = str(session["conversation_id"])

    first = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-facts-input-0",
            content="我每周有 30 小时，想系统学习 Python 自动化。",
            planning_facts=_planning_profile_facts(weekly_minutes=1800),
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert first.status_code == 202
    first_replay = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-facts-input-0",
            content="我每周有 30 小时，想系统学习 Python 自动化。",
            planning_facts=_planning_profile_facts(weekly_minutes=1800),
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert first_replay.status_code == 200
    assert first_replay.json()["idempotent_replayed"] is True
    assert first_replay.json()["message_id"] == first.json()["message_id"]
    first_message_id = str(first.json()["message_id"])
    latest = first
    for index in range(1, 7):
        latest = tutor_client.post(
            f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(
                user_id,
                f"plan-facts-input-{index}",
                content=f"继续讨论计划细节 {index}。",
            ),
        )
        assert latest.status_code == 202

    current = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    facts = {item["field_key"]: item for item in current["planning_context"]["facts"]}
    questions = {item["question_key"]: item["status"] for item in current["planning_context"]["questions"]}
    assert facts["weekly_minutes"]["value"] == 1800
    assert facts["weekly_minutes"]["status"] == "confirmed"
    assert questions["weekly_minutes"] == "confirmed"

    latest_run_id = str(latest.json()["run_id"])
    latest_input_revision = int(latest.json()["input_revision"] )
    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        run = repository.load_snapshot(user_id=user_id, run_id=latest_run_id)
        assert run is not None
        context_loader = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(
                conn=conn,
                learner_state=TutorLearnerStateRepository(conn),
            ),
        )
        context_input = context_loader.load_context(
            run,
            input_revision=latest_input_revision,
        )
        replayed_context_input = context_loader.load_context(
            run,
            input_revision=latest_input_revision,
        )
        assert context_input.authoritative_snapshot_hash == replayed_context_input.authoritative_snapshot_hash
        assert context_input.required_facts == replayed_context_input.required_facts
        selection = TutorContextBuilder(estimator=_OneTokenEstimator()).build(
            context_input,
            token_budget=64,
        )

    required_items = [
        item for item in selection.items if item.section is TutorContextSection.REQUIRED_FACTS
    ]
    recent_ids = [
        item.source_id for item in selection.items if item.section is TutorContextSection.RECENT_MESSAGES
    ]
    assert len(required_items) == 7
    assert any('"field_key":"weekly_minutes"' in item.content and '"value":1800' in item.content for item in required_items)
    assert f"message:{first_message_id}" in recent_ids
    assert selection.checkpoint_metadata.required_fact_selected_count == 7
    assert selection.checkpoint_metadata.required_fact_missing_count == 0
    assert selection.checkpoint_metadata.confirmed_question_reasked_count == 0

    corrected = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-facts-correction",
            content="更正：我每周实际安排 10 小时。",
            planning_facts={"weekly_minutes": 600},
            reopen_fact_fields=["weekly_minutes"],
        ),
    )
    assert corrected.status_code == 202
    corrected_run_id = str(corrected.json()["run_id"])

    current = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    corrected_facts = {item["field_key"]: item for item in current["planning_context"]["facts"]}
    corrected_questions = {
        item["question_key"]: item["status"] for item in current["planning_context"]["questions"]
    }
    assert corrected_facts["weekly_minutes"]["value"] == 600
    assert corrected_facts["weekly_minutes"]["revision"] == 2
    assert corrected_questions["weekly_minutes"] == "confirmed"

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, revision, value_json, supersedes_fact_id::text AS supersedes_fact_id
            FROM tutor_planning_intake_facts
            WHERE user_id = %s AND session_id = %s AND field_key = 'weekly_minutes'
            ORDER BY revision
            """,
            (user_id, session["session_id"]),
        ).fetchall()
        assert [row["value_json"] for row in rows] == [1800, 600]
        assert [row["revision"] for row in rows] == [1, 2]
        assert rows[1]["supersedes_fact_id"] == rows[0]["id"]

        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "UPDATE tutor_planning_intake_facts SET value_json = '601'::jsonb WHERE id = %s",
                    (rows[1]["id"],),
                )

        other_user = conn.execute(
            "INSERT INTO users (display_name) VALUES ('Planning fact scope probe') RETURNING id"
        ).fetchone()
        assert other_user is not None
        current_weekly = conn.execute(
            """
            SELECT * FROM tutor_planning_intake_facts
            WHERE id = %s
            """,
            (rows[1]["id"],),
        ).fetchone()
        assert current_weekly is not None
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO tutor_planning_intake_facts (
                      session_id, user_id, conversation_id, field_key, value_json,
                      value_hash, revision, state, source_kind, source_message_id,
                      source_run_id, source_input_revision, supersedes_fact_id, policy_version
                    ) VALUES (
                      %s, %s, %s, 'weekly_minutes', '900'::jsonb, %s, 3,
                      'confirmed', 'explicit_input', %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        current_weekly["session_id"],
                        other_user["id"],
                        current_weekly["conversation_id"],
                        "f" * 64,
                        current_weekly["source_message_id"],
                        current_weekly["source_run_id"],
                        current_weekly["source_input_revision"],
                        current_weekly["id"],
                        current_weekly["policy_version"],
                    ),
                )

        corrected_run = PostgresTutorRepository(conn).load_snapshot(
            user_id=user_id,
            run_id=corrected_run_id,
        )
        assert corrected_run is not None
        facts_repository = PostgresPlanningFactRepository(conn)
        gate = PlanningQuestionDecisionGate(
            base=_ApprovedDecisionGate(),
            facts=facts_repository,
        )
        gate_result = gate.validate(
            run=corrected_run,
            decision=TutorDecision(
                public_message="你每周能投入多少时间？",
                question_key="weekly_minutes",
                checkpoint_reason=TutorCheckpointReason.CAPABILITY_RESULT,
                continuation_kind=TutorContinuationKind.APPROVAL,
            ),
        )
        assert gate_result.status is TutorDecisionGateStatus.DENIED
        assert gate_result.diagnostic_code == "confirmed_question_reasked"
        projected = facts_repository.project_snapshot(
            run=corrected_run,
            input_revision=corrected_run.input_revision,
        )
        assert projected.confirmed_question_reasked_count == 1
        conn.commit()

    with connect() as conn:
        exported = export_user_data(conn, user_id)
        summary = get_user_data_summary(conn, user_id)
        weekly_exports = [
            item for item in exported["planning_intake_facts"] if item["field_key"] == "weekly_minutes"
        ]
        assert [item["value_json"] for item in weekly_exports] == [1800, 600]
        assert all("value_hash" not in item for item in exported["planning_intake_facts"])
        assert all("event_hash" not in item and "reason_code" not in item for item in exported["planning_question_events"])
        assert summary["counts"]["planning_intake_facts"] == 8
        assert summary["counts"]["planning_question_events"] >= 10

        reset = reset_user_data(conn, user_id)
        assert reset["summary"]["counts"]["planning_intake_facts"] == 0
        assert reset["summary"]["counts"]["planning_question_events"] == 0
        remaining = conn.execute(
            """
            SELECT
              (SELECT count(*)::int FROM tutor_planning_intake_facts WHERE user_id = %s) AS facts,
              (SELECT count(*)::int FROM tutor_planning_question_events WHERE user_id = %s) AS questions
            """,
            (user_id, user_id),
        ).fetchone()
        assert remaining == {"facts": 0, "questions": 0}
        conn.commit()


def test_unconfirmed_answer_source_is_pinned_and_blocks_compaction(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
) -> None:
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-unconfirmed-session")
    conversation_id = str(session["conversation_id"])

    asked = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-unconfirmed-asked",
            content="请先帮我梳理学习计划需要的信息。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert asked.status_code == 202
    with connect() as conn:
        run = PostgresTutorRepository(conn).load_snapshot(
            user_id=user_id,
            run_id=str(asked.json()["run_id"]),
        )
        assert run is not None
        PostgresPlanningFactRepository(conn).record_question_asked(
            run=run,
            field=PlanningFactField.WEEKLY_MINUTES,
        )
        conn.commit()

    answered = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-unconfirmed-answer",
            content="工作日晚上和周末都可以安排一些时间。",
        ),
    )
    assert answered.status_code == 202
    answered_message_id = str(answered.json()["message_id"])
    latest = answered
    for index in range(6):
        latest = tutor_client.post(
            f"/api/tutor/conversations/{conversation_id}/inputs",
            json=action_payload(
                user_id,
                f"plan-unconfirmed-followup-{index}",
                content=f"继续讨论其他计划细节 {index}。",
            ),
        )
        assert latest.status_code == 202

    with connect() as conn:
        run = PostgresTutorRepository(conn).load_snapshot(
            user_id=user_id,
            run_id=str(latest.json()["run_id"]),
        )
        assert run is not None
        context_input = PostgresTutorLearningContextLoader(
            conn=conn,
            base_loader=PostgresTutorContextLoader(
                conn=conn,
                learner_state=TutorLearnerStateRepository(conn),
            ),
        ).load_context(run, input_revision=int(latest.json()["input_revision"]))
        selection = TutorContextBuilder(estimator=_OneTokenEstimator()).build(
            context_input,
            token_budget=64,
        )

    assert context_input.compaction_plan is not None
    assert answered_message_id in context_input.compaction_plan.protected_message_ids
    assert context_input.summary_blocked_by_unprojected_fact == 1
    assert f"message:{answered_message_id}" in {
        item.source_id
        for item in selection.items
        if item.section is TutorContextSection.RECENT_MESSAGES
    }
    assert selection.checkpoint_metadata.summary_blocked_by_unprojected_fact == 1


def test_confirmed_question_reask_is_blocked_and_checkpoint_metric_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="请再告诉我你的学习目标。",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-reask-session")

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{session['conversation_id']}/inputs",
        json=action_payload(
            user_id,
            "plan-reask-input",
            content="我每周学习四小时，用 Python 做可靠的自动化工具。",
            planning_facts=_planning_profile_facts(weekly_minutes=240),
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        run = conn.execute(
            """
            SELECT status, terminal_outcome, terminal_diagnostic_code
            FROM tutor_runs WHERE id = %s AND user_id = %s
            """,
            (run_id, user_id),
        ).fetchone()
        checkpoint = conn.execute(
            """
            SELECT metadata_json
            FROM tutor_run_checkpoints
            WHERE run_id = %s AND reason = 'terminal'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        blocked_events = conn.execute(
            """
            SELECT count(*)::int AS count
            FROM tutor_planning_question_events
            WHERE user_id = %s AND session_id = %s AND status = 'reasked_blocked'
            """,
            (user_id, session["session_id"]),
        ).fetchone()

    assert run == {
        "status": "blocked_policy",
        "terminal_outcome": "blocked_policy",
        "terminal_diagnostic_code": "confirmed_question_reasked",
    }
    assert checkpoint is not None
    assert checkpoint["metadata_json"]["required_fact_count"] == 7
    assert checkpoint["metadata_json"]["required_fact_selected_count"] == 7
    assert checkpoint["metadata_json"]["confirmed_question_reasked_count"] == 1
    assert blocked_events == {"count": 1}


def test_fact_correction_invalidates_existing_draft_even_with_latest_session_version(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
) -> None:
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_session(tutor_client, user_id, "plan-fact-stale-session")
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-fact-stale-input",
            content="我每周学习四小时，用 Python 做可靠的自动化工具。",
            planning_facts=_planning_profile_facts(weekly_minutes=240),
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])
    with connect() as conn:
        run = PostgresTutorRepository(conn).load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None
        LearningPlanDraftCapabilityHandler(conn).generate(
            run=run,
            capability_input=_capability_input(),
        )
        conn.commit()

    before_correction = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    draft = before_correction["current_draft"]
    corrected = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "plan-fact-stale-correction",
            content="更正：我每周只能学习十小时。",
            planning_facts={"weekly_minutes": 600},
            reopen_fact_fields=["weekly_minutes"],
        ),
    )
    assert corrected.status_code == 202
    latest = tutor_client.get(
        f"/api/learning-plan-sessions/{session['session_id']}?user_id={user_id}"
    ).json()["session"]
    assert latest["current_draft"]["draft_id"] == draft["draft_id"]
    assert latest["planning_context"]["fact_revision"] == 8

    stale = tutor_client.post(
        f"/api/learning-plan-sessions/{session['session_id']}/confirm",
        json={
            "user_id": user_id,
            "client_action_id": "plan-fact-stale-confirm",
            "expected_session_version": latest["version"],
            "draft_id": draft["draft_id"],
            "draft_version": draft["draft_version"],
            "content_hash": draft["content_hash"],
        },
    )
    assert_error(stale, "LEARNING_PLAN_DRAFT_STALE", 409)
    with connect() as conn:
        count = conn.execute(
            "SELECT count(*)::int AS count FROM tutor_learning_tracks WHERE user_id = %s",
            (user_id,),
        ).fetchone()
    assert count == {"count": 0}
