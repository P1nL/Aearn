from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

import app.routes.tutor as tutor_route
from app.agents.harness.contracts import TutorContinuationKind, TutorPlanningIntentHint
from app.core.config import Settings
from app.db.bootstrap import bootstrap_database
from app.db.connection import connect
from app.services.learning.planning_questions import (
    PLANNING_QUESTION_CATALOG_VERSION,
    PlanningQuestionCatalogError,
    build_planning_question_presentation,
    format_planning_question_value,
    validate_planning_question_value,
)
from app.services.tutor.interaction_authority import TutorInteractionAuthorityService
from app.services.tutor.persistence import TutorInteractionRequestConflict
from tests.support.tutor_public_api_support import action_payload, create_tutor_user, waiting_dispatcher


pytest_plugins = ("tests.support.tutor_public_api_support",)



def test_typed_request_schema_bootstraps_twice_with_scoped_constraints() -> None:
    bootstrap_database()
    bootstrap_database()
    with connect() as conn:
        columns = {
            str(row["column_name"])
            for row in conn.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'tutor_interaction_requests'
                """
            ).fetchall()
        }
        constraints = {
            str(row["conname"])
            for row in conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'tutor_interaction_requests'::regclass"
            ).fetchall()
        }
        indexes = {
            str(row["indexname"])
            for row in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'tutor_interaction_requests'"
            ).fetchall()
        }
    assert {
        "item_id", "source_turn_id", "kind", "actor", "schema_version",
        "catalog_version", "question_key", "descriptor_json", "presentation_json",
        "state", "version", "response_hash", "receipt_hash", "answer_turn_id",
        "answer_message_id", "resolved_at",
    }.issubset(columns)
    assert {
        "fk_tutor_interaction_request_source_turn_scope",
        "fk_tutor_interaction_request_answer_turn_scope",
        "chk_tutor_interaction_request_actor_kind",
        "chk_tutor_interaction_request_resolution",
    }.issubset(constraints)
    assert "uq_tutor_interaction_requests_pending_conversation" in indexes
    assert "uq_tutor_interaction_requests_source_turn" in indexes


@pytest.mark.parametrize(
    ("question_key", "value", "presentation_type"),
    [
        ("language_id", "python", "single_select"),
        ("goal_text", "构建可靠自动化工具", "text"),
        ("target_level", "intermediate", "single_select"),
        ("weekly_minutes", 240, "integer"),
        ("experience_level", "beginner", "single_select"),
        ("teaching_preferences", ["examples_first", "practice_heavy"], "multi_select"),
        ("pace_constraints", "工作日每次不超过四十分钟", "text"),
    ],
)
def test_all_planning_question_catalog_fields_are_typed_and_validate(
    tutor_persistence,
    question_key: str,
    value: object,
    presentation_type: str,
) -> None:
    presentation = build_planning_question_presentation(
        tutor_persistence.connection,
        question_key=question_key,
    )
    assert presentation["type"] == presentation_type
    assert validate_planning_question_value(
        tutor_persistence.connection,
        question_key=question_key,
        catalog_version=PLANNING_QUESTION_CATALOG_VERSION,
        value=value,
    ) == value
    with pytest.raises(PlanningQuestionCatalogError):
        validate_planning_question_value(
            tutor_persistence.connection,
            question_key=question_key,
            catalog_version="stale_catalog",
            value=value,
        )

def test_planning_question_display_uses_natural_option_label(tutor_persistence) -> None:
    presentation = build_planning_question_presentation(
        tutor_persistence.connection,
        question_key="experience_level",
    )
    assert format_planning_question_value(
        presentation=presentation,
        value="new",
    ) == "完全没有经验"


def _snapshot(client: TestClient, *, user_id: str, conversation_id: str) -> dict[str, object]:
    response = client.get(
        f"/api/tutor/conversations/{conversation_id}/snapshot?user_id={user_id}"
    )
    assert response.status_code == 200
    return response.json()


def _create_plan_session(
    client: TestClient,
    *,
    user_id: str,
    preferred_language_id: str | None = "python",
) -> dict[str, object]:
    response = client.post(
        "/api/learning-plan-sessions",
        json={
            "user_id": user_id,
            "client_action_id": "typed-plan-session",
            "preferred_language_id": preferred_language_id,
        },
    )
    assert response.status_code in {200, 201}
    return response.json()["session"]


def test_planning_request_uses_server_catalog_and_records_exact_fact(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="你每周准备投入多少分钟？",
        continuation_kind=TutorContinuationKind.PLANNING_INPUT,
        question_key="weekly_minutes",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_plan_session(tutor_client, user_id=user_id)
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "typed-plan-source",
            content="请帮我制定学习计划。",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    source_turn_id = str(accepted.json()["run_id"])
    source_snapshot = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    pending = source_snapshot["pending_requests"]
    assert isinstance(pending, list) and len(pending) == 1
    source_messages = [
        item
        for item in source_snapshot["timeline"]
        if item["kind"] == "message"
        and item["role"] == "tutor"
        and item["content"] == "你每周准备投入多少分钟？"
    ]
    assert len(source_messages) == 1
    chronological_timeline = list(reversed(source_snapshot["timeline"]))
    tutor_message_index = next(
        index
        for index, item in enumerate(chronological_timeline)
        if item["kind"] == "message"
        and item["role"] == "tutor"
        and item["content"] == "你每周准备投入多少分钟？"
    )
    request_index = next(
        index
        for index, item in enumerate(chronological_timeline)
        if item["kind"] == "elicitation" and item["turn_id"] == source_turn_id
    )
    assert tutor_message_index < request_index
    request = pending[0]
    assert request["request_kind"] == "planning_input"
    assert request["presentation"] == {
        "type": "integer",
        "field_key": "weekly_minutes",
        "minimum": 15,
        "maximum": 10_080,
        "step": 15,
        "recommended": 300,
        "unit": "minutes_per_week",
    }

    invalid = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "typed-plan-invalid",
            "expected_request_version": 1,
            "response": {
                "kind": "planning_input",
                "question_key": "weekly_minutes",
                "catalog_version": "tutor_planning_questions_v1",
                "value": 1,
            },
        },
    )
    assert invalid.status_code == 409

    response = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "typed-plan-valid",
            "expected_request_version": 1,
            "response": {
                "kind": "planning_input",
                "question_key": "weekly_minutes",
                "catalog_version": "tutor_planning_questions_v1",
                "value": 240,
            },
        },
    )
    assert response.status_code == 202
    answer_turn_id = str(response.json()["run_id"])
    assert answer_turn_id != source_turn_id
    assert provider.calls == [(source_turn_id, 1), (answer_turn_id, 1)]
    answered_snapshot = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    response_messages = [
        item
        for item in answered_snapshot["timeline"]
        if item["kind"] == "message"
        and item["role"] == "learner"
        and item["in_reply_to_item_id"] == request["id"]
    ]
    assert len(response_messages) == 1
    assert response_messages[0]["content"] == "每周 240 分钟"
    assert "weekly_minutes" not in response_messages[0]["content"]

    with connect() as conn:
        fact = conn.execute(
            """
            SELECT field_key, value_json, state, source_run_id::text AS source_run_id
            FROM tutor_planning_intake_facts
            WHERE user_id = %s AND conversation_id = %s AND field_key = 'weekly_minutes'
            ORDER BY revision DESC LIMIT 1
            """,
            (user_id, conversation_id),
        ).fetchone()
    assert fact is not None
    assert fact["field_key"] == "weekly_minutes"
    assert fact["value_json"] == 240
    assert fact["state"] == "confirmed"
    assert fact["source_run_id"] == answer_turn_id


@pytest.mark.parametrize(
    ("learner_text", "candidate", "excluded_language", "source_key"),
    [
        ("我想做langchain架构的agent", "python", "java", "semantic-langchain-source"),
        ("我想用 LangChain4j 做 Agent", "java", "python", "semantic-langchain4j-source"),
    ],
)
def test_semantic_language_request_persists_only_validated_candidate_without_default_or_fact(
    learner_text: str,
    candidate: str,
    excluded_language: str,
    source_key: str,
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="你想学习哪门编程语言？",
        continuation_kind=TutorContinuationKind.PLANNING_INPUT,
        question_key="language_id",
        planning_intent_hint=TutorPlanningIntentHint(
            schema_version="planning-intent-hint-v2",
            candidate_language_ids=(candidate,),
            confidence="high",
            reason_code="technology_ecosystem_match",
        ),
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_plan_session(
        tutor_client,
        user_id=user_id,
        preferred_language_id=None,
    )
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            source_key,
            content=learner_text,
            planning_facts={
                "goal_text": "构建可靠的 Agent",
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
    first_snapshot = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    second_snapshot = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    request = first_snapshot["pending_requests"][0]
    assert second_snapshot["pending_requests"][0] == request
    assert request["presentation"] == {
        "type": "single_select",
        "field_key": "language_id",
        "options": [
            {"value": candidate, "label": request["presentation"]["options"][0]["label"]}
        ],
        "recommended": None,
        "selection_scope": "intent_shortlist",
        "selection_reason_code": "semantic_technology_ecosystem_match",
        "intent_policy_version": "planning-language-intent-v2",
    }
    assert excluded_language not in {
        option["value"] for option in request["presentation"]["options"]
    }
    public_json = json.dumps(first_snapshot, ensure_ascii=False)
    for protected in (
        "confidence",
        "candidate_language_ids",
        "planning_intent_hint",
        "rationale",
    ):
        assert protected not in public_json
    with connect() as conn:
        course = conn.execute(
            """
            SELECT id::text AS id
            FROM language_courses
            WHERE language = %s AND archived_at IS NULL
            ORDER BY level, title, id
            LIMIT 1
            """,
            (candidate,),
        ).fetchone()
        fact = conn.execute(
            """
            SELECT value_json FROM tutor_planning_intake_facts
            WHERE user_id = %s AND conversation_id = %s AND field_key = 'language_id'
            """,
            (user_id, conversation_id),
        ).fetchone()
    assert course is not None
    assert str(course["id"]) not in public_json
    assert fact is None


def test_feature_off_persists_named_legacy_full_catalog_without_rewriting_on_replay(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    rollback_settings = tutor_api_settings.model_copy(
        update={"tutor_planning_intent_enabled": False}
    )
    dispatcher, _provider = waiting_dispatcher(
        settings=rollback_settings,
        message="你想学习哪门编程语言？",
        continuation_kind=TutorContinuationKind.PLANNING_INPUT,
        question_key="language_id",
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_plan_session(
        tutor_client,
        user_id=user_id,
        preferred_language_id=None,
    )
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "feature-off-language-source",
            content="我想做一个 Agent",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    first = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    second = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    presentation = first["pending_requests"][0]["presentation"]
    assert second["pending_requests"][0]["presentation"] == presentation
    assert presentation["selection_scope"] == "full_catalog"
    assert presentation["selection_reason_code"] == "feature_off_rollback"
    assert presentation["intent_policy_version"] == "planning-language-intent-v2"
    assert presentation["recommended"] is None
    assert len(presentation["options"]) > 3


def test_generic_agent_uses_clarification_and_clarification_response_writes_no_language_fact(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, _provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="你更倾向使用哪种实现语言，或者目标框架需要哪种运行环境？",
        continuation_kind=TutorContinuationKind.CLARIFICATION,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    session = _create_plan_session(tutor_client, user_id=user_id)
    conversation_id = str(session["conversation_id"])

    accepted = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(
            user_id,
            "generic-agent-source",
            content="我想做一个 Agent",
            learning_scope={"scope_kind": "plan_drafting", "task_kind": "plan_drafting"},
        ),
    )
    assert accepted.status_code == 202
    request = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)["pending_requests"][0]
    assert request["request_kind"] == "clarification"
    assert request["presentation"]["type"] == "text"
    assert request["presentation"]["field_key"] is None

    response = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "generic-agent-clarification-answer",
            "expected_request_version": request["version"],
            "response": {
                "kind": "clarification",
                "answer_text": "我指的是服务端框架变体，还没决定实现语言。",
            },
        },
    )
    assert response.status_code == 202
    with connect() as conn:
        fact = conn.execute(
            """
            SELECT value_json FROM tutor_planning_intake_facts
            WHERE user_id = %s AND conversation_id = %s AND field_key = 'language_id'
            """,
            (user_id, conversation_id),
        ).fetchone()
    assert fact is None


def test_approval_requires_exact_proposal_identity_and_creates_fresh_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="是否批准 Tutor 继续执行该受控操作？",
        continuation_kind=TutorContinuationKind.APPROVAL,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "typed-approval-conversation"),
    )
    conversation_id = str(conversation.json()["conversation_id"])
    source = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "typed-approval-source", content="请执行受控操作。"),
    )
    assert source.status_code == 202
    source_turn_id = str(source.json()["run_id"])
    request = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)["pending_requests"][0]
    assert request["kind"] == "approval"
    proposal_identity = request["presentation"]["proposal_id"]

    ordinary_text = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "typed-approval-plain-text", content="我批准。"),
    )
    assert ordinary_text.status_code == 202
    assert ordinary_text.json()["queued"] is True
    pending_after_queue = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)
    assert pending_after_queue["pending_requests"][0]["id"] == request["id"]
    assert pending_after_queue["queue"][0]["content"] == "我批准。"

    mismatch = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "typed-approval-mismatch",
            "expected_request_version": 1,
            "response": {
                "kind": "approval",
                "proposal_identity": "proposal:wrong",
                "decision": "approve",
                "reason": None,
            },
        },
    )
    assert mismatch.status_code == 409

    approved = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "typed-approval-valid",
            "expected_request_version": 1,
            "response": {
                "kind": "approval",
                "proposal_identity": proposal_identity,
                "decision": "approve",
                "reason": "范围与风险已确认",
            },
        },
    )
    assert approved.status_code == 202
    answer_turn_id = str(approved.json()["run_id"])
    assert answer_turn_id != source_turn_id
    assert approved.json()["request"]["state"] == "answered"
    assert provider.calls == [(source_turn_id, 1), (answer_turn_id, 1)]


def test_authority_receipt_is_internal_scoped_idempotent_and_fresh_turn(
    monkeypatch: pytest.MonkeyPatch,
    tutor_client: TestClient,
    tutor_api_settings: Settings,
) -> None:
    dispatcher, provider = waiting_dispatcher(
        settings=tutor_api_settings,
        message="正在等待受信能力结果。",
        continuation_kind=TutorContinuationKind.CAPABILITY_RESULT,
    )
    monkeypatch.setattr(tutor_route, "build_tutor_run_dispatcher", lambda _settings: dispatcher)
    user_id = str(create_tutor_user(tutor_client)["id"])
    conversation = tutor_client.post(
        "/api/tutor/conversations",
        json=action_payload(user_id, "typed-authority-conversation"),
    )
    conversation_id = str(conversation.json()["conversation_id"])
    source = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/inputs",
        json=action_payload(user_id, "typed-authority-source", content="请查询受信结果。"),
    )
    assert source.status_code == 202
    source_turn_id = str(source.json()["run_id"])
    request = _snapshot(tutor_client, user_id=user_id, conversation_id=conversation_id)["pending_requests"][0]
    assert request["actor"] == "authority"
    assert request["allowed_actions"] == []
    assert "authority_request_hash" not in json.dumps(request)

    learner_forgery = tutor_client.post(
        f"/api/tutor/conversations/{conversation_id}/requests/{request['id']}/responses",
        json={
            "user_id": user_id,
            "client_action_id": "typed-authority-forgery",
            "expected_request_version": 1,
            "response": {"kind": "capability_result", "result_hash": "0" * 64},
        },
    )
    assert learner_forgery.status_code == 400

    with connect() as conn:
        internal = conn.execute(
            """
            SELECT id::text AS id, authority_scope_json, authority_request_hash
            FROM tutor_interaction_requests WHERE item_id = %s
            """,
            (request["id"],),
        ).fetchone()
        assert internal is not None
        service = TutorInteractionAuthorityService(conn, settings=tutor_api_settings)
        with pytest.raises(TutorInteractionRequestConflict):
            service.accept_receipt(
                user_id=user_id,
                conversation_id=conversation_id,
                item_id=request["id"],
                expected_request_version=1,
                issuer="catalog-capability-gateway",
                subject=internal["id"],
                scope={**internal["authority_scope_json"], "kind": "external_result"},
                request_hash=internal["authority_request_hash"],
                result_hash="0" * 64,
                verification_result="verified",
                receipt_identity="receipt:wrong-scope",
                received_at=datetime.now(UTC),
            )
        ambiguous = service.accept_receipt(
            user_id=user_id,
            conversation_id=conversation_id,
            item_id=request["id"],
            expected_request_version=1,
            issuer="catalog-capability-gateway",
            subject=internal["id"],
            scope=internal["authority_scope_json"],
            request_hash=internal["authority_request_hash"],
            result_hash="1" * 64,
            verification_result="ambiguous",
            receipt_identity="receipt:capability:1",
            received_at=datetime.now(UTC),
        )
        assert ambiguous.turn is None
        assert ambiguous.request.state.value == "pending"
        verified = service.accept_receipt(
            user_id=user_id,
            conversation_id=conversation_id,
            item_id=request["id"],
            expected_request_version=2,
            issuer="catalog-capability-gateway",
            subject=internal["id"],
            scope=internal["authority_scope_json"],
            request_hash=internal["authority_request_hash"],
            result_hash="2" * 64,
            verification_result="verified",
            receipt_identity="receipt:capability:2",
            received_at=datetime.now(UTC),
        )
        assert verified.turn is not None
        answer_turn_id = verified.turn.run.run_id
        replay = service.accept_receipt(
            user_id=user_id,
            conversation_id=conversation_id,
            item_id=request["id"],
            expected_request_version=2,
            issuer="catalog-capability-gateway",
            subject=internal["id"],
            scope=internal["authority_scope_json"],
            request_hash=internal["authority_request_hash"],
            result_hash="2" * 64,
            verification_result="verified",
            receipt_identity="receipt:capability:2",
            received_at=datetime.now(UTC),
        )
        assert replay.replayed is True
        assert replay.turn is not None and replay.turn.run.run_id == answer_turn_id
        with pytest.raises(TutorInteractionRequestConflict):
            service.accept_receipt(
                user_id=user_id,
                conversation_id=conversation_id,
                item_id=request["id"],
                expected_request_version=2,
                issuer="catalog-capability-gateway",
                subject=internal["id"],
                scope=internal["authority_scope_json"],
                request_hash=internal["authority_request_hash"],
                result_hash="3" * 64,
                verification_result="verified",
                receipt_identity="receipt:capability:2",
                received_at=datetime.now(UTC),
            )
        rows = conn.execute(
            """
            SELECT runs.response_to_request_id::text AS response_to_request_id,
                   messages.role, jobs.state
            FROM tutor_runs AS runs
            JOIN tutor_run_input_events AS inputs ON inputs.run_id = runs.id
            JOIN tutor_messages AS messages ON messages.id = inputs.message_id
            JOIN tutor_interactive_dispatch_jobs AS jobs ON jobs.run_id = runs.id
            WHERE runs.id = %s
            """,
            (answer_turn_id,),
        ).fetchone()
        conn.commit()
    assert rows is not None
    assert rows["response_to_request_id"] == internal["id"]
    assert rows["role"] == "tutor"
    assert rows["state"] == "pending"
    assert provider.calls == [(source_turn_id, 1)]
