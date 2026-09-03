from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.runtime import LearningPlanRuntimeToolRegistry, RuntimeToolCall
from app.db.connection import connect
from app.services.learning.planning_facts import PostgresPlanningFactRepository
from app.services.learning.planning_intent import (
    PLANNING_INTENT_HINT_SCHEMA_VERSION,
    PLANNING_INTENT_HINT_V1_SCHEMA_VERSION,
    PlanningIntentResolver,
    PlanningIntentHintError,
    validate_closed_intent_hint,
    validate_semantic_intent_hint,
)
from app.services.learning.planning_questions import build_planning_question_presentation
from app.services.learning.plan_tools import (
    LEARNING_PLAN_DRAFT_TOOL_NAME,
    PLANNING_CONTEXT_TOOL_NAME,
)
from app.services.tutor.persistence import PostgresTutorRepository
from tests.support.tutor_public_api_support import (
    RecordingTutorDispatcher,
    action_payload,
    create_tutor_user,
)

pytest_plugins = ("tests.support.tutor_public_api_support",)


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
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        language_fact = conn.execute(
            """
            SELECT value_json, source_kind, policy_version
            FROM tutor_planning_intake_facts
            WHERE source_run_id = %s AND field_key = 'language_id'
            """,
            (run_id,),
        ).fetchone()
        assert language_fact == {
            "value_json": "python",
            "source_kind": "deterministic_input",
            "policy_version": "planning-language-intent-v2",
        }
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


@pytest.mark.asyncio
async def test_postgres_context_exposes_bounded_language_candidates_and_accepts_only_current_hint(
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
            "client_action_id": "codex-language-candidate-session",
            "preferred_language_id": None,
        },
    )
    session = created.json()["session"]
    conversation_id = str(session["conversation_id"])
    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "codex-language-candidate-input",
            content="我想做langchain架构的agent",
            planning_facts={
                "goal_text": "构建 LangChain Agent",
                "target_level": "beginner",
                "weekly_minutes": 240,
                "experience_level": "new",
                "teaching_preferences": [],
                "pace_constraints": "每周四次练习",
            },
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    run_id = str(accepted.json()["run_id"])

    with connect() as conn:
        repository = PostgresTutorRepository(conn)
        assert repository.acquire_lease(
            user_id=user_id,
            run_id=run_id,
            owner_id="codex-language-candidate-worker",
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
        premature = await registry.invoke(
            _call(
                PLANNING_CONTEXT_TOOL_NAME,
                {
                    "planning_intent_hint": {
                        "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                        "candidate_language_ids": ["python"],
                        "confidence": "high",
                        "reason_code": "technology_ecosystem_match",
                    }
                },
                call_id="language-premature-semantic",
            )
        )
        premature_payload = json.loads(premature.content)
        assert premature_payload["status"] == "repairable_invalid"
        assert premature_payload["issues"][0]["code"] == "language_candidates_not_read"
        assert registry.planning_intent_hint is None

        initial = await registry.invoke(
            _call(PLANNING_CONTEXT_TOOL_NAME, {}, call_id="language-context")
        )
        initial_payload = json.loads(initial.content)
        candidates = initial_payload["data"]["language_candidates"]
        assert initial_payload["data"]["next_missing_fact"]["field_key"] == "language_id"
        assert 1 <= len(candidates) <= 24
        assert {candidate["language_id"] for candidate in candidates}.issuperset({"python", "java"})
        assert all(
            set(candidate) == {
                "language_id",
                "course_title",
                "level",
                "capability_state",
                "execution_family",
            }
            for candidate in candidates
        )
        semantic = await registry.invoke(
            _call(
                PLANNING_CONTEXT_TOOL_NAME,
                {
                    "planning_intent_hint": {
                        "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                        "candidate_language_ids": ["python"],
                        "confidence": "high",
                        "reason_code": "technology_ecosystem_match",
                    }
                },
                call_id="language-semantic",
            )
        )
        semantic_payload = json.loads(semantic.content)
        assert semantic_payload["status"] == "awaiting_user"
        assert semantic_payload["data"]["language_resolution"] == {
            "status": "semantic_shortlist",
            "candidate_language_ids": ["python"],
            "reason_code": "semantic_technology_ecosystem_match",
            "policy_version": "planning-language-intent-v2",
        }
        assert registry.planning_intent_hint is not None
        encoded = json.dumps(initial_payload, ensure_ascii=False)
        assert user_id not in encoded
        assert conversation_id not in encoded
        assert run_id not in encoded


def test_planning_intent_resolver_uses_postgres_metadata_and_closed_hints() -> None:
    with connect() as conn:
        resolver = PlanningIntentResolver(conn)
        frontend = resolver.resolve("我想学前端")
        frontend_presentation = build_planning_question_presentation(
            conn,
            question_key="language_id",
            language_intent=frontend,
        )
        assert frontend.resolution == "shortlist"
        assert frontend.intent_tags == ("frontend",)
        assert [item["value"] for item in frontend_presentation["options"]] == [
            "html_css",
            "javascript",
            "typescript",
        ]
        assert frontend_presentation["recommended"] is None
        assert frontend_presentation["selection_scope"] == "intent_shortlist"

        multiple = resolver.resolve("Python 和 Go 哪个适合后端")
        multiple_presentation = build_planning_question_presentation(
            conn,
            question_key="language_id",
            language_intent=multiple,
        )
        assert multiple.resolution == "shortlist"
        assert multiple.explicit_language_ids == ("python", "go")
        assert [item["value"] for item in multiple_presentation["options"]] == ["python", "go"]

        before = resolver.resolve("我想学前端").candidate_course_ids
        conn.execute(
            "UPDATE language_courses SET title = title || ' renamed', description = 'changed' WHERE id = ANY(%s::uuid[])",
            (list(before),),
        )
        after = resolver.resolve("我想学前端").candidate_course_ids
        assert after == before
        conn.rollback()

        hinted = resolver.resolve(
            "请帮我选择方向",
            model_hint={
                "schema_version": PLANNING_INTENT_HINT_V1_SCHEMA_VERSION,
                "intent_tags": ["frontend"],
            },
        )
        assert hinted.intent_tags == ("frontend",)
        ignored = resolver.resolve(
            "请帮我选择方向",
            model_hint={
                "schema_version": PLANNING_INTENT_HINT_V1_SCHEMA_VERSION,
                "intent_tags": ["frontend"],
                "course_id": "forbidden",
            },
        )
        assert ignored.intent_tags == ()
        with pytest.raises(PlanningIntentHintError):
            validate_closed_intent_hint(
                conn,
                {
                    "schema_version": PLANNING_INTENT_HINT_V1_SCHEMA_VERSION,
                    "intent_tags": ["unknown"],
                },
            )

@pytest.mark.parametrize(
    ("learner_text", "candidate", "expected_language"),
    [
        ("我想做langchain架构的agent", "python", "python"),
        ("我想用 LangChain4j 做 Agent", "java", "java"),
    ],
)
def test_semantic_language_hint_creates_only_a_user_confirmed_narrow_candidate(
    learner_text: str,
    candidate: str,
    expected_language: str,
) -> None:
    with connect() as conn:
        resolver = PlanningIntentResolver(conn)
        intent = resolver.resolve(
            learner_text,
            model_hint={
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": [candidate],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
            },
        )
        presentation = build_planning_question_presentation(
            conn,
            question_key="language_id",
            language_intent=intent,
        )

    assert intent.resolution == "shortlist"
    assert intent.auto_confirm_language_id is None
    assert intent.semantic_language_ids == (expected_language,)
    assert presentation["options"] == [
        {
            "value": expected_language,
            "label": presentation["options"][0]["label"],
        }
    ]
    assert presentation["recommended"] is None
    assert presentation["selection_scope"] == "intent_shortlist"
    assert presentation["selection_reason_code"] == "semantic_technology_ecosystem_match"
    assert presentation["intent_policy_version"] == "planning-language-intent-v2"


def test_enabled_ambiguity_and_invalid_semantic_hint_never_expand_to_full_catalog() -> None:
    with connect() as conn:
        resolver = PlanningIntentResolver(conn)
        ambiguous = resolver.resolve("我想做一个 Agent")
        invalid = resolver.resolve(
            "我想做langchain架构的agent",
            model_hint={
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": ["inactive_language"],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
            },
        )
        rollback = resolver.resolve("我想做一个 Agent", enabled=False)

    assert ambiguous.resolution == "clarification_required"
    assert ambiguous.candidate_course_ids == ()
    assert ambiguous.reason_code == "clarification_required_no_intent_signal"
    assert invalid.resolution == "clarification_required"
    assert invalid.candidate_course_ids == ()
    assert invalid.reason_code == "invalid_model_hint"
    assert rollback.resolution == "full_catalog"
    assert rollback.reason_code == "feature_off_rollback"
    assert rollback.candidate_course_ids


def test_semantic_hint_validation_rejects_duplicate_overflow_extra_and_inactive_candidates() -> None:
    with connect() as conn:
        active = tuple(candidate.language_id for candidate in PlanningIntentResolver(conn).language_candidates())
        for payload in (
            {
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": ["python", "python"],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
            },
            {
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": ["python", "java", "go", "sql"],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
            },
            {
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": ["python"],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
                "label": "Python",
            },
            {
                "schema_version": PLANNING_INTENT_HINT_SCHEMA_VERSION,
                "candidate_language_ids": ["inactive_language"],
                "confidence": "high",
                "reason_code": "technology_ecosystem_match",
            },
        ):
            with pytest.raises(PlanningIntentHintError):
                validate_semantic_intent_hint(payload, active_language_ids=active)
