from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.runtime import LearningPlanRuntimeToolRegistry, RuntimeToolCall
from app.db.connection import connect
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.learning.plan_tools import (
    LEARNING_PLAN_DRAFT_TOOL_NAME,
    PLANNING_CONTEXT_TOOL_NAME,
)
from app.services.tutor.persistence import PostgresTutorRepository
from tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    create_tutor_user,
)

pytest_plugins = ("tutor_public_api_support",)


def _call(tool_name: str, arguments: dict[str, object], *, call_id: str) -> RuntimeToolCall:
    return RuntimeToolCall(
        thread_id="thread-safe",
        turn_id="turn-safe",
        call_id=call_id,
        tool_name=tool_name,
        arguments=arguments,
    )


def _modules() -> list[dict[str, object]]:
    return [
        {
            "stable_key": "foundations",
            "title": "Foundations",
            "nodes": [
                {
                    "stable_key": "python.variables",
                    "title": "Variables",
                    "required_capabilities": ["python"],
                }
            ],
        },
        {
            "stable_key": "automation",
            "title": "Automation",
            "nodes": [
                {
                    "stable_key": "python.files",
                    "title": "Files",
                    "prerequisites": ["python.variables"],
                    "required_capabilities": ["python"],
                }
            ],
        },
    ]


@pytest.mark.asyncio
async def test_postgres_typed_tools_build_server_profile_append_once_and_fence_generation(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: object,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    created = tutor_client.post(
        "/api/learning-plan-sessions",
        json={
            "user_id": user_id,
            "client_action_id": "codex-tool-session",
            "preferred_language_id": "python",
        },
    )
    assert created.status_code in {200, 201}
    session = created.json()["session"]
    conversation_id = str(session["conversation_id"])
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "codex-tool-input",
            content="请基于我确认的偏好生成计划。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
            planning_facts={
                "language_id": "python",
                "goal_text": "Build reliable automation tools",
                "target_level": "intermediate",
                "weekly_minutes": 240,
                "experience_level": "beginner",
                "teaching_preferences": ["examples", "practice"],
                "pace_constraints": "Four focused sessions each week.",
            },
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    generation = 3
    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        lease = repository.acquire_lease(
            user_id=user_id,
            run_id=run_id,
            owner_id="codex-tool-worker",
            now=datetime.now(UTC),
            duration_seconds=60,
        )
        assert lease is not None
        run = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None and run.lease is not None
        registry = LearningPlanRuntimeToolRegistry.from_postgres(
            conn,
            run=run,
            runtime_generation=generation,
            runtime_generation_reader=lambda: generation,
        )
        context = await registry.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="context"))
        first = await registry.invoke(
            _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _modules()}, call_id="draft-1")
        )
        replay = await registry.invoke(
            _call(LEARNING_PLAN_DRAFT_TOOL_NAME, {"modules": _modules()}, call_id="draft-2")
        )
        conn.commit()

        context_payload = json.loads(context.content)
        first_payload = json.loads(first.content)
        replay_payload = json.loads(replay.content)
        assert context_payload["status"] == "completed"
        assert context_payload["data"]["missing_facts"] == []
        assert first_payload["status"] == "completed"
        assert replay_payload["status"] == "completed"
        assert replay_payload["replayed"] is True
        assert first_payload["data"] == replay_payload["data"]

        stored = conn.execute(
            """
            SELECT count(*)::int AS count, min(profile_json->>'goal_text') AS goal_text,
                   min(profile_json->>'pace_summary') AS pace_summary,
                   min(profile_json->>'title') AS title
            FROM tutor_learning_plan_drafts
            WHERE user_id = %s AND source_run_id = %s
            """,
            (user_id, run_id),
        ).fetchone()
        assert stored == {
            "count": 1,
            "goal_text": "Build reliable automation tools",
            "pace_summary": "Four focused sessions each week.",
            "title": "python intermediate 学习计划",
        }

        runtime_registry = LearningPlanRuntimeToolRegistry.from_postgres(
            conn,
            run=run,
            runtime_generation=3,
            runtime_generation_reader=lambda: generation,
        )
        generation = 4
        stale = await runtime_registry.invoke(
            _call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="stale")
        )
        assert json.loads(stale.content)["code"] == "tool_runtime_generation_stale"

        generation = 3
        source_message = conn.execute(
            "SELECT message_id AS id FROM tutor_run_input_events WHERE run_id = %s AND input_revision = %s",
            (run_id, run.input_revision),
        ).fetchone()
        assert source_message is not None
        PostgresPlanningFactRepository(conn).record_input(
            user_id=user_id,
            run_id=run_id,
            conversation_id=conversation_id,
            message_id=str(source_message["id"]),
            input_revision=run.input_revision,
            content="每周五小时。",
            explicit_facts={"weekly_minutes": 300},
        )
        facts_stale = await registry.invoke(
            _call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="facts-stale")
        )
        assert json.loads(facts_stale.content)["code"] == "planning_facts_stale"

        current_run = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert current_run is not None
        blocked = LearningPlanRuntimeToolRegistry.from_postgres(
            conn,
            run=current_run,
            runtime_generation=3,
            runtime_generation_reader=lambda: 3,
            policy_allowed=lambda: False,
        )
        denied = await blocked.invoke(_call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="denied"))
        assert denied.success is False
        assert json.loads(denied.content)["status"] == "policy_blocked"


@pytest.mark.asyncio
async def test_postgres_context_reports_awaiting_user_for_missing_authoritative_facts(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: object,
) -> None:
    del tutor_api_settings
    dispatcher = RecordingTutorDispatcher()
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    created = tutor_client.post(
        "/api/learning-plan-sessions",
        json={
            "user_id": user_id,
            "client_action_id": "codex-tool-missing-session",
            "preferred_language_id": "python",
        },
    )
    session = created.json()["session"]
    conversation_id = str(session["conversation_id"])
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "codex-tool-missing-input",
            content="我想学习 Python。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
            planning_facts={"language_id": "python"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        assert repository.acquire_lease(
            user_id=user_id,
            run_id=run_id,
            owner_id="codex-tool-missing-worker",
            now=datetime.now(UTC),
            duration_seconds=60,
        ) is not None
        run = repository.load_snapshot(user_id=user_id, run_id=run_id)
        assert run is not None and run.lease is not None
        registry = LearningPlanRuntimeToolRegistry.from_postgres(
            conn,
            run=run,
            runtime_generation=1,
            runtime_generation_reader=lambda: 1,
        )
        result = await registry.invoke(
            _call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="missing-context")
        )
        payload = json.loads(result.content)
        assert result.success is True
        assert payload["status"] == "awaiting_user"
        assert payload["code"] == "planning_facts_missing"
        assert "goal_text" in payload["data"]["missing_facts"]
        assert payload["data"]["next_missing_fact"] == {
            "field_key": "experience_level",
            "meaning": "学习者此前与编程相关的经验等级。",
            "exact_question": "你目前有多少相关编程经验？",
            "wording_policy": (
                "可先简短确认已知事实，然后必须逐字使用 exact_question 作为唯一问题；"
                "不得改写字段含义、补充括号示例、添加选项或提出第二个问题。"
            ),
            "response_authority": "aearn_typed_request",
        }
        encoded = json.dumps(payload, ensure_ascii=False)
        assert user_id not in encoded
        assert conversation_id not in encoded
        assert run_id not in encoded
